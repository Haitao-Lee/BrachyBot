"""Pure-function behavioral probes; no server, clinical mutations, or LLM calls."""
import json
import sys
import types
from dataclasses import asdict
from pathlib import Path

OUT=Path(__file__).parent
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else OUT
pkg=types.ModuleType('agent_runtime'); pkg.__path__=[str(ROOT/'agent_runtime')]
sys.modules['agent_runtime']=pkg
from agent_runtime.ui_operations import resolve_ui_operation_request
from agent_runtime.request_parse import parse_request, mutating_execution_authorized
from agent_runtime.action_plan import ActionPlan, ActionStep
from agent_runtime.answer_coverage import required_metric_aspects, direct_read_decision

state={'ui_operation_catalog':[{'ref':'data-tree:guide_mesh_v1:visibility', 'node_id':'guide_mesh_v1','label':'Puncture guide v1 — Show / hide','aliases':['guide_mesh_v1','surgical_guide','导板','手术导板','穿刺导板','surgical guide'], 'kind':'data-tree-virtual','panel':'viewers','scope':'leaf','visible':True,'object_visible':False,'enabled':True,'available':True,'action':{'target':'tree.visibility','command':'set','value':'guide_mesh_v1,on','semantic_property':'visibility','node_id':'guide_mesh_v1'}}]}
out={'ui_requests':[]}
for q in ['请显示导板','能帮我把导板显示出来吗？','Could you show the surgical guide?','把刚才藏起来的导板恢复一下','让导板重新出现在画面里','请把导板显示出来，肿瘤透明度设为40%','请把CTV和OAR分别设为30%和70%的透明度','请不要显示导板','退出检测','如果导板隐藏了就显示出来','请把轴位放大到150%，其他窗口不动']:
    p=parse_request(q)
    out['ui_requests'].append({'request':q,'resolution':resolve_ui_operation_request(q,state),'subtasks':[asdict(t) for t in p.subtasks]})
out['aggregate_authorization']={q:{t:mutating_execution_authorized(q,t) for t in ['ctv_segmentation','oar_segmentation','planning_pipeline','surgical_guide','report_auto_fill']} for q in ['全部更新','那请你全部更新','全部更新，不含导板']}
plan=ActionPlan(steps=(ActionStep('consumer','report_generator',('dose_recompute#2',)),ActionStep('dose_recompute#2','dose_recompute')))
out['dependency_order']=[s.key for s in plan.ordered_steps()]
out['provider_dependencies']=ActionPlan.from_tool_calls([{'key':'A','tool':'ui_controller','params':{'actions':[]}}, {'key':'B','tool':'ui_screenshot','depends_on':['A'],'params':{}}]).to_dict()
out['coverage']=[{'request':q,'required':list(required_metric_aspects(q)),'decision':str(direct_read_decision(q,[{'covers':['target_dose']}]))} for q in ['各个器官受照剂量是多少','脊髓受到多少辐射','导板在哪里，肿瘤在哪里，分别截图','每根针有多少粒子']]
(OUT/'audit_probes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
