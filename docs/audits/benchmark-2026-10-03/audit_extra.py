import collections, copy, importlib, json, pathlib, sys, types, hashlib
import numpy as np
BB=pathlib.Path(sys.argv[1]).resolve();OUT=pathlib.Path(sys.argv[2]).resolve();sys.path.insert(0,str(BB))
from tools import run_task as rt, splits, live_smoke, group, observe, coverage
from oracles import get_oracle, gate_verdict
from tools.adapters import brachybot
tasks=[json.loads(p.read_text()) for p in sorted((BB/'tasks').rglob('*.json'))]
out={};probes={}
def probe(name,fn):
    try:
        r=fn();probes[name]=r.to_dict() if hasattr(r,'to_dict') else r
    except Exception as ex:probes[name]={'error':repr(ex)}
def check(name,**kwargs):return get_oracle(name)().check(**kwargs)
probe('judge_string_false',lambda:check('judge_rubric',judgments=[{'item_id':'1','criteria_scores':{'a':'false'}}],rubric={'criteria':['a']},human_reviewed={'1':True}))
probe('paraphrase_consistently_wrong_two_ids',lambda:check('paraphrase_invariance',members=[{'instance_id':str(i),'outcome_class':{'verdict':'Does not meet','partial_status':'FAILED_VERIFICATION'}} for i in range(2)]))
probe('roundtrip_missing_independent_payload',lambda:check('roundtrip_fidelity',first={'dims':[1,1,1],'origin':[0,0,0],'spacing':[1,1,1],'direction':[1,0,0,0,1,0,0,0,1],'dtype':'float32'},second={'dims':[1,1,1],'origin':[0,0,0],'spacing':[1,1,1],'direction':[1,0,0,0,1,0,0,0,1],'dtype':'float32'},fmt='nifti',independent={}))
probe('roundtrip_truncated_origin',lambda:check('roundtrip_fidelity',first={'dims':[1,1,1],'origin':[0,0,0],'spacing':[1,1,1],'direction':[1,0,0,0,1,0,0,0,1],'dtype':'float32'},second={'dims':[1,1,1],'origin':[0],'spacing':[1,1,1],'direction':[1,0,0,0,1,0,0,0,1],'dtype':'float32'},fmt='nifti',independent={}))
probe('roundtrip_dose_not_independently_checked',lambda:check('roundtrip_fidelity',first={'dose':[[1,2]]},second={'dose':[[1,2]]},fmt='dose',independent={'dose':[[999,999]]}))
probe('stl_valid_remesh_insufficient',lambda:check('roundtrip_fidelity',first={'n_vertices':8,'volume_mm3':10,'watertight':True,'n_normals':8,'hausdorff_mm':0},second={'n_vertices':16,'volume_mm3':10,'watertight':True,'n_normals':16,'hausdorff_mm':0},fmt='stl',independent={}))
probe('fake_pdf_valid',lambda:check('pdf_parseability',pdf_bytes=b'%PDF-1.7\nnot a PDF /Type /Page \n%%EOF',expected_pages=1))
probe('authz_missing_scope_target',lambda:check('authz_predicate',mutations=[{'op_id':'1','executed':True,'scope_provenance':'named','target':'dose'}]))
probe('interference_far_apart_warn',lambda:check('interference_fp',predictions=[{'id':'far','s':[[0,0,0],[100,0,0]],'t':[[50,-50,100],[50,50,100]],'predicted_risk':'none'}]))
probe('interference_endpoint_physical_overlap',lambda:check('interference_fp',predictions=[{'id':'end','s':[[0,0,0],[10,0,0]],'t':[[10,0,0],[20,0,0]],'predicted_risk':'overlap'}]))
probe('partial_score_discarded',lambda:rt.evaluate({'id':'probe','track':'A','oracle':{'check':'retrieval_at_k'},'protocol':{}},{'oracle_inputs':{'retrieval_at_k':{'queries':[{'relevant':['a','b'],'retrieved':['a']}],'k':2,'recall_min':1}}},{}))
def live_reader_probe():
    stub=types.ModuleType('AgenticSys')
    class Agent:
        def __init__(self,**kwargs):self.calls=0
        def cws_snapshot(self):self.calls+=1;return {'expected_real_snapshot':True}
    stub.BrachyAgent=Agent;sys.modules['AgenticSys']=stub
    agent=live_smoke._agent_factory({'id':'audit-stub'}, {})
    r=agent.observation_state();return {'returned':r,'snapshot_calls':agent.calls}
probe('live_smoke_reader_self_recursion',live_reader_probe)
probe('real_trace_ret_lost',lambda:brachybot.trace_to_observation({'response':'ok','steps':[{'tool':'query_metrics','params':{'metric_type':'all'},'status':'done','metadata':{'dose_metrics':{'v100':90.1}},'result':'V100=90.1%'}]}))

components=splits._connected_groups(tasks)
out['split_connected_component_sizes']=sorted([len(v) for v in components.values()],reverse=True)
splitdoc=splits.build(tasks,seed=20260929)
out['split_rebuild_counts']=splitdoc['counts'];out['split_component_count']=len(components)
out['split_rebuild_task_ids']={k:[tasks[i]['id'] for i in v['task_index']] for k,v in splitdoc['splits'].items()}
out['split_track_counts']={k:dict(collections.Counter(tasks[i]['track'] for i in v['task_index'])) for k,v in splitdoc['splits'].items()}
out['declared_runs_total']=sum(t['protocol']['n_runs'] for t in tasks)
out['track_layer_pairs']={tr:dict(collections.Counter(l for t in tasks if t['track']==tr for l in t['layers'])) for tr in sorted({t['track'] for t in tasks})}
out['zh_tasks']=[t['id'] for t in tasks if any(x.get('lang')=='zh' for x in t['protocol']['turns'])]
out['reviewers']=dict(collections.Counter(tuple(t['provenance'].get('reviewers',[])) for t in tasks)) if False else dict(collections.Counter('|'.join(t['provenance'].get('reviewers',[])) for t in tasks))
out['primary_gold_null']=sum(t['oracle'].get('gold') is None for t in tasks)
out['audited_invariant_without_required']=[t['id'] for t in tasks if t['oracle'].get('constraint_class')=='invariant' and not t['protocol'].get('audit_required')]
out['tool_boundary_indirect_request_abstain']=[]
out['contradictory_prompts']=[]
by_prompt=collections.defaultdict(list)
for t in tasks:
    prompt=json.dumps(t['protocol']['turns'],sort_keys=True)
    obs=json.loads((BB/'tests/replay'/f"{t['id']}.json").read_text())
    oi=obs.get('oracle_inputs',{}).get('tool_call_boundary',{})
    by_prompt[prompt].append((t,obs))
    if oi.get('expected_decision')=='abstain' and any('Can you' in x.get('text','') for x in t['protocol']['turns']):out['tool_boundary_indirect_request_abstain'].append({'id':t['id'],'turns':t['protocol']['turns'],'oracle_inputs':oi})
for prompt,members in by_prompt.items():
    outcomes={json.dumps(m[1].get('oracle_inputs',{}).get('tool_call_boundary',{}),sort_keys=True) for m in members if m[0]['oracle']['check']=='tool_call_boundary'}
    if len(outcomes)>1:out['contradictory_prompts'].append({'turns':json.loads(prompt),'ids':[m[0]['id'] for m in members],'payloads':[json.loads(x) for x in outcomes]})
cov=coverage.compute();out['coverage_structural_summary']={k:v for k,v in cov.items() if k!='rows'}
out['external_answer_leak_sources']={str(p.relative_to(BB.parent)):sum('reference_answer' in x for x in p.read_text().splitlines()) for p in (BB.parent/'external').glob('EXT-*/adapter/adapter.py') if 'reference_answer' in p.read_text()}
out['probes']=probes
(OUT/'audit_extra.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:v for k,v in out.items() if k not in ['split_rebuild_task_ids','zh_tasks','audited_invariant_without_required','contradictory_prompts']},ensure_ascii=False,default=str))
