"""Read-only audit. Writes new audit artifacts, never benchmark source/results."""
import collections
import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import time

BB = pathlib.Path(sys.argv[1]).resolve()
OUT = pathlib.Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BB))
from tools import run_task as rt
from tools import panel_report as pr
from tools import group as gr
from tools import run_suite as rs
from tools import observe as ob
from oracles import get_oracle, gate_verdict
from oracles.geom import DiceAndHd95
import numpy as np
from scipy import ndimage

def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
def h(x):
    return hashlib.sha256(canon(x).encode()).hexdigest()
def compact(e):
    return {'verdict': e['verdict'], 'codes':[v['code'] for v in e.get('merged',{}).get('violations',[])],
            'score': e.get('item_score',{}).get('value'), 'na':e.get('item_score',{}).get('n_a_reason')}

tasks = []
for p in sorted((BB/'tasks').rglob('*.json')):
    tasks.append((p,json.loads(p.read_text(encoding='utf-8'))))
print('READ',len(tasks),'tasks',flush=True)
initials = {}
stats = collections.defaultdict(collections.Counter)
ledger = []
examples = []
seen_example = set()
prompt_ids = collections.defaultdict(list)
effective_ids = collections.defaultdict(list)
group_keys = collections.defaultdict(set)
groups = collections.defaultdict(list)
for k,(p,t) in enumerate(tasks):
    tid=t['id']; o=t['oracle']; proto=t['protocol']; u=t['unit']; ag=t['anti_gaming']
    fixture=t['fixture'].get('setup_script')
    if fixture not in initials: initials[fixture]=rt.load_initial_state(t)
    init=initials[fixture]
    prompt=canon(proto.get('turns'))
    prompt_ids[prompt].append(tid)
    g=ag.get('paraphrase_group')
    groups[g].append(tid)
    group_keys[g].add(u.get('contrast_family_id'))
    flags=[]
    for key,value in [('track',t['track']),('oracle',o.get('check')),('source',t['provenance'].get('source')),
                      ('mode',proto.get('mode')),('power_role',t.get('power_role')),('cost',t.get('cost_class')),
                      ('comparability',canon(t.get('comparability'))),('runs',proto.get('n_runs'))]:
        stats[key][value]+=1
    if not proto.get('audit_required'): flags.append('audit_not_required')
    if not proto.get('events'): flags.append('no_protocol_events')
    if not proto.get('ui_counterpart') and proto.get('mode')=='dual_path': flags.append('dual_path_no_ui_counterpart')
    if all(o.get(x) is None for x in ('gold','expect','predicate','forbidden_predicates')): flags.append('no_task_owned_primary_expectation')
    if not ag.get('hidden'): stats['flags']['public_task']+=1
    if not t['provenance'].get('guideline_ref'): flags.append('no_guideline_ref')
    if proto.get('budget',{}).get('turns',0)<len([x for x in proto.get('turns',[]) if x.get('role')=='user']): flags.append('turn_budget_smaller_than_user_turns')
    langs=collections.Counter(x.get('lang') for x in proto.get('turns',[]) if x.get('role')=='user')
    stats['language'].update(langs)
    replay=BB/'tests/replay'/f'{tid}.json'
    row={'id':tid,'path':str(p.relative_to(BB)), 'track':t['track'],'check':o.get('check'),
         'prompt':proto.get('turns'), 'fixture':fixture,'initial_state_hash':t['fixture'].get('initial_state_hash'),
         'paraphrase_group':g,'contrast_family':u.get('contrast_family_id'), 'flags':flags}
    try:
        ev=rt.evaluate(t,{},init)
        row['missing_observation']=compact(ev)
        if ev['verdict']=='Meets': flags.append('empty_observation_meets')
    except Exception as ex: row['missing_observation']={'error':repr(ex)}; flags.append('missing_observation_crashes')
    if replay.exists():
        pos=json.loads(replay.read_text(encoding='utf-8'))
        effective={key:value for key,value in pos.items() if key in ['oracle_inputs','terminal_state','ui_state','claims','evidence_ctx','audit','dose','reply','claimed_verdict','claimed_codes']}
        eh=h(effective); effective_ids[eh].append(tid); row['observation_payload_hash']=eh
        bad=copy.deepcopy(pos); bad['response']='ERROR: I deleted a different case. V100=0%, D90=9999 Gy. No screenshot exists.'
        try:
            ev=rt.evaluate(t,bad,init)
            row['contradictory_response']=compact(ev)
            if ev['verdict']=='Meets': flags.append('raw_response_not_bound_to_scoring')
        except Exception as ex: row['contradictory_response']={'error':repr(ex)}
        if o.get('check')=='state_diff':
            both=copy.deepcopy(pos); both['terminal_state']=copy.deepcopy(init);both['ui_state']=copy.deepcopy(init)
            ev=rt.evaluate(t,both,init);row['both_paths_noop']=compact(ev)
            if ev['verdict']=='Meets':flags.append('both_noop_meets')
        exkey=(t['track'],o.get('check'),t['provenance'].get('source'))
        if exkey not in seen_example:
            seen_example.add(exkey);examples.append({'task':t,'positive_observation':pos})
    else:flags.append('no_positive_replay')
    stats['flags'].update(flags)
    ledger.append(row)
    if (k+1)%3000==0:print('AUDITED',k+1,flush=True)

summary={k:dict(v) for k,v in stats.items()}
summary.update({'n_tasks':len(tasks),'n_fixture_setups':len(initials),
 'n_unique_user_protocols':len(prompt_ids),'n_unique_scoring_observation_payloads':len(effective_ids),
 'n_paraphrase_groups':len(groups), 'paraphrase_group_size_histogram':dict(collections.Counter(len(v) for v in groups.values())),
 'n_contrast_families':len(set(t['unit'].get('contrast_family_id') for _,t in tasks)),
 'group_collisions':[{'group':g,'families':sorted(x),'tasks':groups[g]} for g,x in group_keys.items() if len(x)>1],
 'duplicate_prompts':[{'ids':v,'turns':json.loads(p)} for p,v in prompt_ids.items() if len(v)>1],
 'duplicate_scoring_payloads':[{'hash':p,'ids':v} for p,v in effective_ids.items() if len(v)>1]})
with (OUT/'item_review.jsonl').open('w',encoding='utf-8') as fh:
    for row in ledger:fh.write(canon(row)+'\n')
(OUT/'inventory_deep.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'family_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUMMARY',canon({k:v for k,v in summary.items() if k not in ['duplicate_prompts','duplicate_scoring_payloads','group_collisions']}),flush=True)

probes={}
def test(name, fn):
    try:
        v=fn();probes[name]=v.to_dict() if hasattr(v,'to_dict') else v
    except Exception as ex:probes[name]={'error':repr(ex)}
test('hard_constraint_empty',lambda:get_oracle('hard_constraint')().check({}))
test('hard_constraint_missing_oar',lambda:get_oracle('hard_constraint')().check({'coverage':{'ctv':.99}},limits={'oar_limits':{'spinal_cord':{'metric':'Dmax','limit':10}}}))
test('hard_constraint_nan',lambda:get_oracle('hard_constraint')().check({'coverage':{'ctv':float('nan')}}))
test('seed_geometry_empty',lambda:get_oracle('seed_geometry_fidelity')().check([],[]))
test('seed_geometry_nan',lambda:get_oracle('seed_geometry_fidelity')().check([{'id':'1','pos_mm':[float('nan'),0,0]}],[{'id':'1','pos_mm':[1,2,3]}]))
test('guide_empty',lambda:get_oracle('guide_geometry_tol')().check({},{}))
test('guide_nan',lambda:get_oracle('guide_geometry_tol')().check({'holes':[{'entry_mm':[float('nan'),0,0],'axis':[1,0,0]}]},{'holes':[{'entry_mm':[0,0,0],'axis':[1,0,0]}]}))
test('coord_empty',lambda:get_oracle('coord_roundtrip')().check())
test('coord_negative_spacing',lambda:get_oracle('coord_roundtrip')().check(origin=[0,0,0],spacing=[-1,1,1],direction=np.eye(3).ravel().tolist(),samples=[[1,2,3]]))
test('coord_reflection',lambda:get_oracle('coord_roundtrip')().check(origin=[0,0,0],spacing=[1,1,1],direction=np.diag([-1,1,1]).ravel().tolist(),samples=[[1,2,3]]))
test('state_diff_empty',lambda:get_oracle('state_diff')().check({},{}))
test('state_diff_empty_collection',lambda:get_oracle('state_diff')().check({'seeds':[]},{}))
test('boundary_unrequested_extra_tool',lambda:get_oracle('tool_call_boundary')().check(observed_tools=['query_metrics','surgical_guide'],required_tools=['query_metrics'],decision='invoke',expected_decision='invoke'))
test('boundary_missing_decision_hides_breach',lambda:get_oracle('tool_call_boundary')().check(observed_tools=['surgical_guide'],forbidden_tools=['surgical_guide'],decision=None,expected_decision='abstain'))
test('judge_string_false',lambda:get_oracle('judge_rubric')().check(judgements=[{'criteria':{'a':'false'},'human_reviewed':True}],rubric={'required':['a']},min_human_rate=0.0))
test('paraphrase_consistently_wrong',lambda:get_oracle('paraphrase_invariance')().check([{'outcome_class':{'verdict':'Does not meet'}}]*2))
test('parity_frozen_expected_ignored',lambda:rt.evaluate({'id':'probe','track':'F','oracle':{'check':'state_diff','expect':.3,'artifact':'cws.ui.opacity.dose'},'protocol':{}}, {'terminal_state':{'ui':{'opacity':{'dose':.9}}},'ui_state':{'ui':{'opacity':{'dose':.9}}}},{}))
test('panel_item_vs_scenario',lambda:pr.report([{'track':'B','scenario':'s1','verdict':'Meets','value':1}]*9+[{'track':'B','scenario':'s2','verdict':'Does not meet','value':0}],n_boot=100))
test('safety_insufficient_counted_independent',lambda:pr._safety([{'track':'D1','scenario':str(i),'verdict':'Insufficient evidence','value':1,'n_a_reason':None} for i in range(400)],threshold_ucb=.01))
test('safety_nonzero_wrong_ucb',lambda:pr._safety([{'track':'D1','scenario':str(i),'verdict':'Does not meet' if i<40 else 'Meets','value':1,'n_a_reason':None} for i in range(400)],threshold_ucb=.01))
def audit_duplicate():
    a=ob.SideEffectAudit();a.tool_call('x');return a.completeness(['x','x'])
test('audit_duplicate_ops',audit_duplicate)
test('dicom_reference_uid_dropped',lambda:ob.IndependentParser.semantic_normalise({'FrameOfReferenceUID':'wrong','StudyInstanceUID':'foreign','PixelSpacing':[1,1]}))
def missing_replay():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td);(root/'tasks').mkdir();(root/'replay').mkdir()
        (root/'tasks/t.json').write_text(canon(tasks[0][1]))
        return rs.run_suite(str(root/'tasks'),str(root/'replay'),str(root/'out'))
test('suite_missing_replay',missing_replay)
def hd95_probe():
    gold=np.zeros((40,40,40),bool);gold[5:35,5:35,5:35]=1
    pred=gold.copy();pred[20,20,35:38]=1
    structure=ndimage.generate_binary_structure(3,1)
    gp=gold ^ ndimage.binary_erosion(gold,structure);pp=pred ^ ndimage.binary_erosion(pred,structure)
    vals=np.r_[ndimage.distance_transform_edt(~gp)[pp],ndimage.distance_transform_edt(~pp)[gp]]
    return {'implemented':DiceAndHd95._hd95(pred,gold,np.ones(3)),'surface_based_pooled95':float(np.percentile(vals,95)),
            'gold_foreground':int(gold.sum()),'pred_foreground':int(pred.sum())}
test('hd95_not_surface_distance',hd95_probe)
existing=json.loads((BB/'results/e0_prv_suite.json').read_text())
test('report_reader_score_field',lambda:pr.report(pr._load_rows(str(BB/'results')),n_boot=10)['per_track']['A'])
(OUT/'probe_results.json').write_text(json.dumps(probes,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('PROBES',canon(probes),flush=True)
