"""Read-only isolated review probes; JSON observations, not clinical execution."""
import json
from agent_runtime.request_parse import aggregate_scope_targets, mutating_execution_authorized
from agent_runtime.action_plan import ActionPlan, ActionStep
from agent_runtime.ui_operations import values_from_text, resolve_ui_operation_request
from agent_runtime.core import AgentMemory

out = {}
for text in ['全部更新', '全部更新；如果以后需要，重新分割CTV。', '全部更新；他说“重新分割CTV”。', '全部更新，CTV分割了吗？']:
    out[text] = {'scope': sorted(aggregate_scope_targets(text)), 'ctv_authorized': mutating_execution_authorized(text, 'ctv_segmentation')}
for text in ['CTV和OAR分别设为不透明和半透明', 'CTV和OAR分别设为半透明和半透明']:
    out[text] = {'values': values_from_text(text, 'opacity'), 'resolution': resolve_ui_operation_request(text, {})}
base = ActionPlan((ActionStep('A', 'dose_recompute', params={'old': True}),))
incoming = ActionPlan((ActionStep('C', 'report_auto_fill', depends_on=('A',)), ActionStep('A', 'dose_recompute', params={'new': True})))
merged = base.merge(incoming)
out['forward_dependency_merge'] = {'steps': [s.to_dict() for s in merged.steps], 'validation': merged.validate(), 'order': [s.key for s in merged.ordered_steps()]}
memory = AgentMemory('isolated-review')
memory.set_ui_state({'plan': 'new'}, mode='replace', state_seq=1, browser_instance='browser', plan_revision=2)
out['older_plan_newer_sequence'] = memory.set_ui_state({'plan': 'old'}, mode='replace', state_seq=2, browser_instance='browser', plan_revision=1)
out['state_after_older_plan'] = memory.get_ui_state()
# In-memory Flask route, inert store and timer: no disk persistence or server.
from flask import Flask
from types import SimpleNamespace
from unittest.mock import patch
from web.routes import planning_routes as routes
bucket = {'state': {'initial': True}, 'events': [{'type': 'fixture'}], 'training': {}}
cached = [None]
class NoTimer:
    def __init__(self, *args, **kwargs): pass
    def start(self): pass
    def cancel(self): pass
store = SimpleNamespace(get_session=lambda *args: SimpleNamespace(id='review-case'))
with patch.object(routes, 'require_api_key', lambda f: f), patch.object(routes, 'rate_limit', lambda f: f), patch.object(routes, 'current_user', lambda store: {'id': 'review-user'}), patch.object(routes, '_ui_bucket', lambda sid: bucket), patch.object(routes.threading, 'Timer', NoTimer):
    app = Flask('isolated-parity-review')
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *a: None, get_cached_agent=lambda sid: cached[0])
    client = app.test_client()
    def post(seq, state, **kwargs):
        response = client.post('/api/ui/state', headers={'X-BrachyBot-Session': 'review-case'}, json={'state': state, 'state_seq': seq, 'browser_instance': 'review-browser', **kwargs})
        return {'status': response.status_code, 'body': response.get_json()}
    out['cold_state_first'] = post(9, {'value': 'new'})
    out['cold_state_older'] = post(4, {'value': 'old'})
    out['cold_final_state'] = dict(bucket['state'])
    cached[0] = SimpleNamespace(memory=AgentMemory('isolated-warm-review'))
    post(10, {'keep': True, 'deleted': 'old'})
    out['warm_tombstone_response'] = post(11, {}, mode='patch', tombstones=['deleted'])
    out['warm_tombstone_memory'] = cached[0].memory.get_ui_state()
    out['warm_tombstone_bucket'] = dict(bucket['state'])
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
