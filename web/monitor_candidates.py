"""Bounded axial seed-spacing proposals. No dose prediction or live mutation.

These are geometric candidates, not treatment recommendations. Normalization,
spacing and target membership are supplied by the authoritative server helpers.
"""
import copy
import math
import time


def _point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value)):
        raise ValueError('Invalid patient-world point')
    return list(value)


def seed_spacing_candidates(geometry, evidence, object_id, *, normalize, spacing, contains,
                            budget_seconds=1.5):
    """Return at most two non-mutating proposals on an existing needle.

    All affected seed pairs must pass, not just the pair shown on a card. Other
    objects must remain exactly unchanged after authoritative normalization.
    The search is deliberately small; an empty result is not proof of infeasibility.
    """
    seeds, needles = geometry.get('seeds'), geometry.get('needles')
    if not isinstance(seeds, list) or not isinstance(needles, list) or not 1 <= len(seeds) <= 512 or len(needles) > 256:
        return {'candidates': [], 'reason': 'geometry_outside_bounded_search'}
    if (any(not isinstance(s, dict) or not s.get('id') for s in seeds)
            or any(not isinstance(n, dict) for n in needles)
            or len({str(s.get('id')) for s in seeds}) != len(seeds)):
        return {'candidates': [], 'reason': 'ambiguous_object_identity'}
    changed = [s for s in evidence.get('changed_objects', []) if str(s.get('id')) == object_id
               and s.get('kind') == 'seeds' and not s.get('dependent_on_needle')
               and not s.get('derived_from_normalization') and s.get('operation') != 'deleted']
    pairs = [p for p in evidence.get('conflicts', []) if p.get('change') in ('new', 'worsened')
             and object_id in (str(p.get('first_id')), str(p.get('second_id')))]
    if not changed or not pairs:
        return {'candidates': [], 'reason': 'no_related_seed_spacing_issue'}
    selected = next((s for s in seeds if str(s.get('id')) == object_id), None)
    if not selected:
        return {'candidates': [], 'reason': 'object_unavailable'}
    track = str(selected.get('trajectory_id') or selected.get('needle_id') or '')
    owners = [n for n in needles if track and track == str(n.get('trajectory_id') or n.get('id'))]
    if len(owners) != 1:
        return {'candidates': [], 'reason': 'owning_needle_unverified'}
    try:
        origin = _point(selected['position'])
        a, b = (_point(owners[0]['points'][i]) for i in (0, -1))
        axis = [y-x for x, y in zip(a, b)]
        length = math.sqrt(sum(x*x for x in axis))
        if length < .1:
            raise ValueError('Degenerate needle')
        axis = [x/length for x in axis]
    except (KeyError, TypeError, ValueError):
        return {'candidates': [], 'reason': 'geometry_unverified'}
    started = time.monotonic()
    proposals, destinations, evaluations = [], set(), 0
    try:
        baseline = normalize(copy.deepcopy(seeds), needles)
        if len(baseline) != len(seeds):
            return {'candidates': [], 'reason': 'geometry_unverified'}
        original = {str(s['id']): s for s in seeds}
        if any(math.dist(_point(s['position']), _point(original[str(s['id'])]['position'])) > .001 for s in baseline):
            return {'candidates': [], 'reason': 'geometry_requires_normalization'}
        normalized_baseline = {str(s['id']): s for s in baseline}
    except (KeyError, TypeError, ValueError):
        return {'candidates': [], 'reason': 'geometry_unverified'}
    for distance in (.5, 1., 2., 3., 4.):
        for sign in (-1, 1):
            if time.monotonic() - started >= budget_seconds:
                return {'candidates': proposals, 'reason': 'search_budget_exhausted', 'evaluations': evaluations}
            raw = copy.deepcopy(seeds)
            item = next(s for s in raw if str(s.get('id')) == object_id)
            item['position'] = [x+sign*distance*y for x, y in zip(origin, axis)]
            try:
                normalized = normalize(raw, needles)
                if len(normalized) != len(seeds) or {str(s.get('id')) for s in normalized} != {str(s.get('id')) for s in seeds}:
                    continue
                destination = next(s for s in normalized if str(s.get('id')) == object_id)
                point = _point(destination['position'])
                moved = math.dist(point, origin)
                key = tuple(round(x, 6) for x in point)
                if key in destinations or moved < .01 or moved > 4.001:
                    continue
                # A normalization that changes unrelated records is not a local proposal.
                if any(s != normalized_baseline[str(s['id'])] for s in normalized if str(s['id']) != object_id):
                    continue
                if contains(destination) is not True:
                    continue
                evaluations += 1
                report = spacing(normalized, needles, object_id)
                if (not isinstance(report, dict) or report.get('status') != 'clear'
                        or report.get('seed_count') != len(seeds) or report.get('close_pairs')):
                    continue
                destinations.add(key)
                proposals.append({'object_id': object_id, 'position': point, 'direction': destination.get('direction'),
                                  'before': origin, 'displacement_mm': [x-y for x, y in zip(point, origin)],
                                  'distance_mm': moved, 'basis': 'axial_spacing_and_target_membership',
                                  'dose_status': 'not_computed', 'clinical_status': 'not_assessed'})
                if len(proposals) == 2:
                    return {'candidates': proposals, 'reason': 'bounded_candidates', 'evaluations': evaluations}
            except (KeyError, TypeError, ValueError, RuntimeError):
                continue
    return {'candidates': proposals, 'reason': 'bounded_candidates' if proposals else 'no_candidate_in_search_window',
            'evaluations': evaluations}
