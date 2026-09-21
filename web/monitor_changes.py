"""Bounded, server-owned edit evidence. No model inference or dose prediction."""
import copy
import hashlib
import json
import math
from types import SimpleNamespace


def geometry_key(geometry):
    records = {}
    for kind in ('seeds', 'needles'):
        items = []
        for item in geometry.get(kind, []) or []:
            try:
                row = {'id': str(item.get('id')), 'trajectory_id': item.get('trajectory_id') or item.get('needle_id')}
                if kind == 'seeds':
                    row['position'] = [float(v) for v in item['position']]
                    row['direction'] = [float(v) for v in (item.get('direction') or [])]
                else:
                    points = item['points']
                    if len(points) < 2:
                        raise ValueError('needle needs two endpoints')
                    row['points'] = [[float(v) for v in points[0]], [float(v) for v in points[-1]]]
                items.append(row)
            except (KeyError, TypeError, ValueError):
                # Never let one malformed entry drop the whole evidence set;
                # keep the raw item so the key still changes when it changes.
                items.append({'raw': json.dumps(item, sort_keys=True, default=str)})
        records[kind] = sorted(items, key=lambda x: x.get('id', x.get('raw', '')))
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def compact_evidence(evidence):
    """Small LLM facts, not raw plan arrays, images, history or mutation tokens."""
    return {
        'planning_id': evidence['planning_id'], 'version': evidence['after_version'],
        'source': 'server_committed_monitor_edit',
        'changed_objects': [{k: v for k, v in obj.items() if k in ('id', 'kind', 'operation', 'distance_mm')}
                            for obj in evidence.get('changed_objects', [])[:8]],
        'conflicts': evidence.get('conflicts', [])[:4],
        'resolved_conflicts': evidence.get('resolved_conflicts', 0),
        'dose': evidence.get('dose'),
        'interpretation': 'Use these measured deltas, not chat-history numbers. No calibrated model-noise threshold or dose-optimal movement has been established. Score change is not clinical approval.',
    }


def capture(agent, geometry):
    from web import server_support as support
    from web.planning_runs import ACTIVE_PLANNING_ID_KEY, PLANNING_RUN_ID_KEY
    memory = agent.memory
    # Geometry comes from the mutation API's canonical snapshot, including an
    # explicitly empty plan. Never fall back to an old automatic plan here.
    metrics = memory.retrieve('dose_metrics') or memory.retrieve('metrics') or {}
    if isinstance(metrics.get('metrics'), dict):
        metrics = metrics['metrics']
    values = {}
    for key in ('v100', 'v150', 'v200', 'd90', 'd95', 'plan_score', 'ci', 'hi'):
        number = (support._volume_metric_as_fraction(metrics, key)
                  if key.startswith('v') else support._extract_metric_value(metrics, key))
        if number is None and key == 'plan_score':
            number = support._extract_metric_value(metrics, 'score')
        if number is not None and math.isfinite(number):
            values[key] = number * 100 if key.startswith('v') else number
    stale = memory.retrieve('manual_artifact_status') or {}
    versions = getattr(memory, '_planning_versions', {})
    anatomy_keys = ('ct_image', 'ctv_mask', 'oar_mask', 'ctv_array', 'oar_array', 'ctv_label_data', 'oar_label_data')
    organs = {}
    for name, row in list((metrics.get('oar_metrics') or {}).items())[:128]:
        if not isinstance(row, dict):
            continue
        organs[str(name)] = {key: float(row[key]) for key in ('dmax', 'd2cc', 'mean_dose')
                            if isinstance(row.get(key), (int, float)) and math.isfinite(row[key])}
    return {
        'geometry': copy.deepcopy(geometry), 'geometry_key': geometry_key(geometry),
        'planning_id': memory.retrieve(ACTIVE_PLANNING_ID_KEY) or memory.retrieve(PLANNING_RUN_ID_KEY),
        'version': int(memory.retrieve('manual_plan_version') or 0),
        'metrics': values,
        'oar_metrics': organs,
        'score_status': metrics.get('criteria_status') if 'plan_score' not in values else 'available',
        'metrics_current': (memory.retrieve('dose_distribution') is not None or memory.retrieve('dose_distribution_gy') is not None) and not memory.retrieve('manual_geometry_only')
            and not any(stale.get(k) in ('stale', 'outdated') for k in ('dose', 'dvh')),
        'config': copy.deepcopy(memory.retrieve('plan_config') or {}),
        'anatomy_key': [(versions.get(k), id(memory.retrieve(k))) for k in anatomy_keys],
    }


def compare(before, after):
    changed = []
    for kind in ('seeds', 'needles'):
        old = {str(x['id']): x for x in before['geometry'][kind]}
        new = {str(x['id']): x for x in after['geometry'][kind]}
        for object_id in sorted(old.keys() | new.keys()):
            a, b = old.get(object_id), new.get(object_id)
            field = 'position' if kind == 'seeds' else 'points'
            orientation_changed = bool(a and b and kind == 'seeds'
                                       and (a.get('direction') != b.get('direction')
                                            or a.get('trajectory_id') != b.get('trajectory_id')))
            if a and b and a.get(field) == b.get(field) and not orientation_changed:
                continue
            entry = {'id': object_id, 'kind': kind,
                     'operation': 'added' if a is None else 'deleted' if b is None else 'moved'}
            if orientation_changed:
                entry['orientation_or_owner_changed'] = True
            if a and b:
                start, end = a.get(field), b.get(field)
                if kind == 'seeds':
                    entry.update(before=start, after=end, distance_mm=math.dist(start, end))
                    entry['return_vector_mm'] = [x-y for x, y in zip(start, end)]
                else:
                    entry.update(before=start, after=end,
                                 distance_mm=max(math.dist(start[0], end[0]), math.dist(start[-1], end[-1])))
            changed.append(entry)
    ids = {x['id'] for x in changed}
    for snapshot in (before, after):
        changed_tracks = {str(n.get('trajectory_id') or n['id']) for n in snapshot['geometry']['needles'] if str(n['id']) in ids}
        ids.update(str(s['id']) for s in snapshot['geometry']['seeds']
                   if str(s.get('trajectory_id') or s.get('needle_id')) in changed_tracks)
    from web import server_support as support
    for side, snapshot in enumerate((before, after)):
        config = snapshot.get('config', {})
        agent = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda key: config if key == 'plan_config' else None))
        # Filter by edited IDs before the legacy 50-pair presentation cap.
        # Late-numbered seeds must not disappear behind old global violations.
        snapshot = snapshot.copy()
        snapshot['seed_pairs'] = support._seed_interference_report(agent,
            snapshot['geometry']['seeds'], snapshot['geometry']['needles'],
            focus_ids=ids, max_pairs=None)['close_pairs']
        snapshot['needle_pairs'] = []
        needles = snapshot['geometry']['needles']
        minimum = float(config.get('needle_diameter_mm') or 1.2) + float(config.get('needle_clearance_mm') or 1.0)
        for i, left in enumerate(needles):
            for right in needles[i+1:]:
                if not ids.intersection((str(left['id']), str(right['id']))):
                    continue
                distance = support._segment_segment_distance(left['points'][0], left['points'][-1], right['points'][0], right['points'][-1])
                if distance < minimum:
                    snapshot['needle_pairs'].append({'first_id': left['id'], 'second_id': right['id'],
                        'distance_mm': distance, 'minimum_distance_mm': minimum})
        if side == 0:
            before = snapshot
        else:
            after = snapshot
    conflicts = []
    resolved = 0
    for key, distance_key in (('seed_pairs', 'surface_clearance_mm'), ('needle_pairs', 'distance_mm')):
        def pairs(snapshot):
            return {tuple(sorted((str(p['first_id']), str(p['second_id'])))): p
                    for p in snapshot[key] if ids.intersection((str(p['first_id']), str(p['second_id'])))}
        old, new = pairs(before), pairs(after)
        resolved += len(old.keys() - new.keys())
        for pair_id, pair in new.items():
            prior = old.get(pair_id)
            difference = float(pair[distance_key]) - float(prior[distance_key]) if prior else 0
            status = 'new' if prior is None else ('worsened' if difference < -1e-3
                else 'improved' if difference > 1e-3 else 'existing')
            conflicts.append({**pair, 'change': status, 'kind': key,
                              'previous_distance_mm': prior.get(distance_key) if prior else None})
    conflicts.sort(key=lambda p: (p['change'] == 'existing', p.get('surface_clearance_mm', p.get('distance_mm', 0))))
    return {'changed_objects': changed[:64], 'changed_object_count': len(changed),
            'changed_kinds': sorted({obj['kind'] for obj in changed}),
            'conflicts': conflicts[:12], 'resolved_conflicts': resolved,
            'before_version': before['version'], 'after_version': after['version'],
            'planning_id': after['planning_id'], 'geometry_key': after['geometry_key'],
            'dose': dose_comparison(before, after),
            'scope': 'geometry and saved dose deltas; clinical acceptance not evaluated'}


def dose_comparison(before, after):
    comparable = bool(before['metrics_current'] and after['metrics_current']
                      and before.get('anatomy_key') == after.get('anatomy_key')
                      and before.get('config') == after.get('config'))
    organ_changes = []
    if comparable:
        for organ, row in before.get('oar_metrics', {}).items():
            for key, value in row.items():
                current = after.get('oar_metrics', {}).get(organ, {}).get(key)
                if current is not None:
                    organ_changes.append({'organ': organ, 'metric': key, 'before': value,
                                          'after': current, 'delta': current - value})
        organ_changes.sort(key=lambda row: abs(row['delta']), reverse=True)
    return {'comparable': comparable, 'before': before['metrics'] if before['metrics_current'] else {},
            'after': after['metrics'] if after['metrics_current'] else {},
            'score_status': after.get('score_status'),
            'oar_changes': organ_changes[:4], 'oar_metric_comparison_count': len(organ_changes),
            'delta': {k: after['metrics'][k] - v for k, v in before['metrics'].items()
                      if k in after['metrics']} if comparable else {}}


def describe(evidence, language='en'):
    zh = language == 'zh'
    lines = []
    if evidence.get('superseded'):
        lines.append('以下是上一条已记录的编辑证据，当前规划已改变或暂不可核对，不能视作当前规划结论。' if zh
                     else 'This is the last recorded edit evidence. The current plan has changed or cannot be verified; these are not current-plan conclusions.')
    if evidence.get('changed_object_count', 0) > 8:
        lines.append(f"共 {evidence['changed_object_count']} 个对象变化，下面列出前 8 个。" if zh
                     else f"{evidence['changed_object_count']} objects changed; the first 8 are listed below.")
    for obj in evidence.get('changed_objects', [])[:8]:
        if obj['operation'] == 'moved':
            lines.append(f"{obj['id']}：移动 {obj['distance_mm']:.2f} mm。" if zh
                         else f"{obj['id']}: moved {obj['distance_mm']:.2f} mm.")
            if obj.get('orientation_or_owner_changed'):
                lines.append('该粒子的方向或所属针道也已改变。' if zh else 'Its direction or owning needle also changed.')
        else:
            lines.append(f"{obj['id']}：{'新增' if obj['operation'] == 'added' else '删除'}。" if zh
                         else f"{obj['id']}: {obj['operation']}.")
    for pair in evidence.get('conflicts', [])[:4]:
        value = pair.get('surface_clearance_mm', pair.get('distance_mm'))
        status = {'new': '新增违规', 'worsened': '违规加重', 'improved': '间距改善但仍违规', 'existing': '原有违规仍存在'}[pair['change']]
        label = '表面间隙' if pair['kind'] == 'seed_pairs' else '针道距离'
        lines.append(f"{status}：{pair['first_id']} ↔ {pair['second_id']}，{label} {value:.2f} mm。" if zh
                     else f"{pair['change']}: {pair['first_id']} ↔ {pair['second_id']}, {'surface clearance' if pair['kind'] == 'seed_pairs' else 'needle distance'} {value:.2f} mm.")
    if evidence.get('resolved_conflicts'):
        count = evidence['resolved_conflicts']
        lines.append(f"本次消除了 {count} 组已记录的相关间距违规。" if zh else f"Resolved {count} recorded spacing conflicts.")
    dose = evidence.get('dose') or {}
    if dose.get('comparable') and dose.get('edit_count', 0) > 1:
        lines.append(f"剂量差值覆盖自上次有效重算以来的 {dose['edit_count']} 次编辑，不能归因于其中某一步。" if zh
                     else f"Dose deltas cover {dose['edit_count']} edits since the last valid recomputation; they cannot be attributed to just one edit.")
    if dose.get('comparable'):
        for key in ('plan_score', 'v100', 'd90', 'v150', 'v200'):
            if key not in dose['delta']:
                continue
            unit = '百分点' if key.startswith('v') and zh else 'pp' if key.startswith('v') else 'Gy' if key.startswith('d') else '分' if zh else 'points'
            lines.append(f"{key}: {dose['before'][key]:.2f} → {dose['after'][key]:.2f} ({dose['delta'][key]:+.2f} {unit})")
        for row in dose.get('oar_changes', []):
            lines.append(f"OAR {row['organ']} {row['metric']}: {row['before']:.2f} → {row['after']:.2f} ({row['delta']:+.2f} Gy)")
        if not dose.get('oar_changes'):
            lines.append('缺少可比较的 OAR 前后结果。' if zh else 'Comparable before/after OAR results are missing.')
        lines.append('以上是同一监测编辑链的实测变化；覆盖、热点、OAR 和评分须分别看，不能仅凭分数认定整体变好。' if zh
                     else 'Measured changes in this edit sequence. Coverage, hot spots, OAR dose and score must be considered separately; score alone does not establish overall improvement.')
    else:
        lines.append('尚无与本次几何对应的前后剂量结果，暂不能判断剂量优化或劣化；重算后会补充可比差值。' if zh
                     else 'Matching before/after dose results are not available. Dose improvement or deterioration is undetermined; recomputation can supply comparable deltas.')
        score = (dose.get('after') or {}).get('plan_score')
        if score is not None:
            lines.append(f"当前评分 {score:.2f}/100；缺少有效前值。" if zh else f"Current score {score:.2f}/100; valid baseline unavailable.")
    if dose.get('after') and 'plan_score' not in dose['after']:
        lines.append('当前重算结果没有有效评分；不会沿用旧分数或自行补造评分。' if zh
                     else 'The recomputed result has no valid score; an old or invented score is not substituted.')
    if evidence.get('restore_token'):
        code = evidence['restore_token']
        lines.append(f"是否撤销这次编辑？回复“复位 {code}”恢复本次编辑前的几何，或回复“保留 {code}”。复位后剂量仍需重算；原位置不等于已验证的安全位置。" if zh
                     else f"Undo this edit? Reply 'undo {code}' to restore its prior geometry, or 'keep {code}'. Dose must be recomputed afterward; the prior position is not a verified safe position.")
        for obj in evidence.get('changed_objects', [])[:2]:
            if obj.get('return_vector_mm'):
                vector = ', '.join(f'{v:+.2f}' for v in obj['return_vector_mm'])
                lines.append(f"{obj['id']} 返回原位的患者坐标位移为 [{vector}] mm（非屏幕左右方向，也不是剂量最优方向）。" if zh
                             else f"{obj['id']} return displacement in patient coordinates: [{vector}] mm; not screen directions or a dose-optimal direction.")
    return '\n\n'.join(lines)


def screenshot(evidence, event_id):
    ids = []
    for p in evidence.get('conflicts', [])[:2]:
        ids.extend((p['first_id'], p['second_id']))
    ids.extend(x['id'] for x in evidence.get('changed_objects', []) if x['operation'] != 'deleted')
    ids = list(dict.fromkeys(ids))[:8]
    if not ids:
        return None
    return {'target': 'viewer-3d', 'views': ['viewer-3d'], 'object_ids': ids,
            'checkpoint_id': event_id, 'planning_id': evidence['planning_id'],
            'planning_version': evidence['after_version'], 'geometry_key': evidence['geometry_key'],
            'visual_purpose': 'locate', 'annotation_policy': 'required',
            'edit_evidence': {'changed_objects': evidence.get('changed_objects', [])[:8]},
            'question': ' / '.join(ids), 'hide_unrelated': False,
            'focus': {'kind': 'auto', 'padding': 0.5}}
