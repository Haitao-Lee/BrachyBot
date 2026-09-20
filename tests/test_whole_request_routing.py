"""Adversarial utterances: a lexical noun/verb hit cannot grant execution."""
import pytest
from agent_runtime.turn_policy import classify_local_turn
from agent_runtime.response_tools import ResponseToolMixin


@pytest.mark.parametrize('message', [
    '不要重新执行规划', '为什么要重新执行规划',
    '如果重新执行规划会怎样', '他让我重新执行规划，这是什么意思',
    '日志中写着重新执行规划', '不要在viewer中显示规划结果',
    '为什么viewer显示规划结果很慢', '我昨天生成了手术导板',
    '导板生成失败了', '请解释如何生成手术导板',
    '请不要重新计算当前剂量', '如果隐藏所有OAR会怎样',
    '请把所有OAR隐藏这个功能解释一下',
    '请把OAR设为半透明但是保留CTV不变',
    'Do not rerun planning', 'Why should I replan?',
    'The log says regenerate the surgical guide',
    'Why does the viewer display planning results slowly?',
    'Do not hide all OAR', 'Please explain how to segment CTV',
])
def test_candidate_is_not_permission(message):
    policy = classify_local_turn(message)
    assert not policy.direct_execution, (message, policy)
    assert not policy.execution_grants
    assert not policy.workflow_grants
    assert policy.action_plan is None
    assert ResponseToolMixin()._detect_tool_request(message) is None


def test_rejected_plan_is_not_reintroduced_as_overwrite():
    assert not ResponseToolMixin._force_reexecution_requested('不要重新执行规划')
    assert not ResponseToolMixin._force_reexecution_requested('why rerun planning?')
    assert ResponseToolMixin._force_reexecution_requested(params={'force_reexecution': True})


@pytest.mark.parametrize('message', [
    '请执行放射性粒子植入规划', '请执行CTV分割', '请重新生成手术导板',
    '将结果在viewer中显示出来啊', '帮我将所有OAR在调到半透明',
    '请截图告诉我手术导板在哪里',
])
def test_complete_commands_retain_shortcuts(message):
    policy = classify_local_turn(message)
    assert policy.direct_execution
    assert policy.routing_source == 'whole_request_contract'


def test_abstention_is_auditable_and_does_not_add_router_call():
    policy = classify_local_turn('不要在viewer中显示规划结果')
    assert policy.routing_source == 'primary_semantic'
    assert policy.candidate_intent == 'viewer_display'
    assert policy.routing_reason == 'whole_request_contract_not_satisfied'
    assert not policy.use_router


def test_normalizer_cannot_invent_dose_call_or_replace_unrelated_tool():
    from AgenticSys import BrachyAgent
    message = '可以重新计算DVH相关指标，验证和当前的结果是否一致'
    assert BrachyAgent._normalize_clinical_tool_calls(object(), [], message) == []
    calls = [{'tool': 'query_metrics', 'params': {}}]
    assert BrachyAgent._normalize_clinical_tool_calls(object(), calls, message) == calls


@pytest.mark.parametrize('message', [
    '请重新生成手术报告', '重新生成报告', '生成手术报告',
    '重新生成剂量报告', '生成计划报告', 'regenerate the surgical report',
])
def test_report_object_wins_over_guide_and_dose(message):
    from agent_runtime.turn_policy import (
        is_report_generation_request, is_surgical_guide_generation_request,
    )
    policy = classify_local_turn(message)
    assert is_report_generation_request(message)
    assert not is_surgical_guide_generation_request(message)
    assert policy.intent == 'report_generation'
    assert policy.direct_execution
    assert policy.execution_grants == {'ui_controller'}
    assert 'surgical_guide' not in (policy.allow_tools or set())


@pytest.mark.parametrize('message', [
    '生成手术导板', '请重新生成导板', '请重新生成手术导板',
    'regenerate the surgical guide',
])
def test_guide_object_still_wins_when_guide_noun_present(message):
    policy = classify_local_turn(message)
    assert policy.intent == 'surgical_guide_generation'
    assert policy.direct_execution
    assert policy.execution_grants == {'surgical_guide'}


def test_report_object_never_reaches_surgical_guide_in_normalization():
    class Memory:
        conversation = [{'role': 'user', 'content': '请重新生成手术报告'}]

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    calls = normalizer._normalize_tool_params([{
        'id': 'mis_selected_guide',
        'tool': 'surgical_guide',
        'params': {'action': 'generate'},
    }])
    assert calls == [{
        'id': 'mis_selected_guide',
        'tool': 'ui_controller',
        'params': {'actions': [{'target': 'report.autofill', 'command': 'run'}]},
    }]


def test_rejected_or_compound_report_turn_does_not_force_report_autofill():
    class Memory:
        def __init__(self, content):
            self.conversation = [{'role': 'user', 'content': content}]

        @staticmethod
        def retrieve(_key):
            return None

    for content in ('不要生成报告', '重新生成手术报告并显示截图'):
        normalizer = ResponseToolMixin()
        normalizer.memory = Memory(content)
        calls = [{'id': 'guide', 'tool': 'surgical_guide', 'params': {'action': 'generate'}}]
        assert normalizer._normalize_tool_params(calls) == calls, content


def test_complete_semantic_instructions_are_shared_and_do_not_mutate_input():
    from agent_runtime.llm_runtime import LLMRuntimeMixin
    messages = [{'role': 'system', 'content': 'Trusted system'},
                {'role': 'user', 'content': 'Do not clear the report'}]
    output = LLMRuntimeMixin()._pack_context_for_provider(messages, messages[-1]['content'])
    assert '[Whole-request interpretation]' in output[0]['content']
    assert messages[0]['content'] == 'Trusted system'
    assert output[-1] == messages[-1]


# ---------------------------------------------------------------------------
# Whole-request regression table (negation / question / condition / state)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('message', [
    '报告生成好了吗？', '报告生成好了吗',
    '不要生成报告', '如果报告空了就重新生成',
    '重新生成的报告解读一下', '他让我重新生成报告，这是什么意思',
])
def test_report_semantic_classes_never_take_the_report_fast_path(message):
    from agent_runtime.turn_policy import unambiguous_report_generation_request
    policy = classify_local_turn(message)
    assert not unambiguous_report_generation_request(message), message
    assert not policy.direct_execution, message
    assert not policy.execution_grants, message


@pytest.mark.parametrize('message', [
    '请重新生成手术报告', '生成分析报告', '重新生成剂量报告',
    'regenerate the surgical report', '写一份术后报告',
])
def test_positive_report_commands_keep_the_report_fast_path(message):
    from agent_runtime.turn_policy import unambiguous_report_generation_request
    policy = classify_local_turn(message)
    assert unambiguous_report_generation_request(message), message
    assert policy.intent == 'report_generation', message
    assert policy.execution_grants == {'ui_controller'}, message


def test_compound_guide_and_report_is_ordered_and_stays_semantic():
    message = '重新生成手术导板和报告'
    policy = classify_local_turn(message)
    assert policy.intent == 'semantic_action'
    assert policy.parsed_goals == (
        ('surgical_guide', 'generate'),
        ('report', 'generate'),
    )
    assert policy.action_plan is None


def test_conditional_guide_generation_is_not_an_unconditional_run():
    from agent_runtime.request_parse import mutating_execution_authorized
    message = '如果还没有导板就生成一个'
    policy = classify_local_turn(message)
    assert not policy.direct_execution
    assert not mutating_execution_authorized(message, 'surgical_guide')


def test_generated_guide_location_question_is_not_a_new_generation():
    from agent_runtime.turn_policy import is_surgical_guide_generation_request
    assert not is_surgical_guide_generation_request('生成的手术导板在哪里')
    assert is_surgical_guide_generation_request('请生成手术导板')




def test_guide_generation_status_question_only_calls_read_only_status():
    message = "\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u751f\u6210\u5bfc\u677f\u4e86\u5417"
    policy = classify_local_turn(message)
    assert policy.intent == 'surgical_guide_status_query'
    assert policy.direct_execution
    assert policy.execution_grants == {'surgical_guide'}
    assert policy.action_plan is None
    calls = ResponseToolMixin()._detect_tool_request(message)
    assert calls == [{
        'id': 'tool_direct_surgical_guide_status',
        'tool': 'surgical_guide',
        'params': {'action': 'status'},
    }]


def test_compound_planning_guide_screenshot_and_code_queries_are_all_retained():
    message = (
        "\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u600e\u4e48\u6837\uff0c"
        "\u8bf7\u622a\u56fe\u544a\u8bc9\u6211\u751f\u6210\u7684\u5bfc\u677f\u5728\u54ea\u91cc\uff1f"
        "\u6b64\u5916\u4f60\u53ef\u4ee5\u5199\u4ee3\u7801\u505a\u4e8b\u60c5\u5417"
    )
    policy = classify_local_turn(message)
    assert policy.intent == 'multi_intent_query'
    assert [intent for intent, _ in policy.parsed_subtasks] == [
        'planning_assessment_query', 'session_visual_location_query', 'code_capability_query',
    ]
    calls = ResponseToolMixin()._detect_tool_request(message)
    assert len(calls) == 1 and calls[0]['tool'] == 'ui_screenshot'
    params = calls[0]['params']
    assert params['views'] == ['data-tree', 'viewer-3d']
    assert params['target_refs'] == ['surgical_guide:active']


def test_compound_status_and_location_do_not_turn_status_into_generation():
    message = (
        "\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u751f\u6210\u5bfc\u677f\u4e86\u5417\uff0c"
        "\u5e76\u622a\u56fe\u544a\u8bc9\u6211\u5bfc\u677f\u5728\u54ea\u91cc"
    )
    policy = classify_local_turn(message)
    assert policy.intent == 'multi_intent_query'
    assert [intent for intent, _ in policy.parsed_subtasks] == [
        'surgical_guide_status_query', 'session_visual_location_query',
    ]
    calls = ResponseToolMixin()._detect_tool_request(message)
    assert [call['tool'] for call in calls] == ['surgical_guide', 'ui_screenshot']
    assert calls[0]['params'] == {'action': 'status'}
    assert calls[1]['params']['views'][0] == 'data-tree'


def test_two_visual_location_questions_keep_separate_screenshot_targets():
    message = "这次规划的导板在哪里？肿瘤在哪里，分别截图告知"
    policy = classify_local_turn(message)
    assert policy.intent == 'multi_intent_query'
    assert [intent for intent, _ in policy.parsed_subtasks] == [
        'session_visual_location_query', 'session_visual_location_query',
    ]

    calls = ResponseToolMixin()._detect_tool_request(message)
    assert len(calls) == 2
    assert len({call['id'] for call in calls}) == 2
    assert [call['tool'] for call in calls] == ['ui_screenshot', 'ui_screenshot']
    params = [call['params'] for call in calls]
    assert [item['semantic_target'] for item in params] == ['surgical_guide', 'ctv']
    assert [item['target_refs'] for item in params] == [
        ['surgical_guide:active'], ['structure:ctv:active'],
    ]
    assert all(item['question'] == message for item in params)
    assert all('在哪里' in item['target_query'] for item in params)

    class Memory:
        conversation = [{'role': 'user', 'content': message}]

        @staticmethod
        def get_ui_state():
            return {}

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    normalizer._active_turn_policy = policy
    normalized = normalizer._normalize_tool_params(calls)
    assert len(normalized) == 2
    assert [call['params']['semantic_target'] for call in normalized] == [
        'surgical_guide', 'ctv',
    ]
    assert [call['params']['target_refs'] for call in normalized] == [
        ['surgical_guide:active'], ['structure:ctv:active'],
    ]
    assert all(call['params']['question'] == message for call in normalized)



def test_independent_visual_capture_failure_does_not_cancel_sibling_or_invent_location():
    from types import SimpleNamespace
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from tool_factory import ToolResult

    message = "这次规划的导板在哪里？肿瘤在哪里，分别截图告知"
    policy = classify_local_turn(message)
    calls = ResponseToolMixin()._detect_tool_request(message)
    assert len(calls) == 2
    assert len({call["id"] for call in calls}) == 2

    class Memory:
        user_lang = "zh"

        def __init__(self):
            self.conversation = [{"role": "user", "content": message}]
            self.values = {}

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

        def store(self, key, value):
            self.values[key] = value

    class Harness(ResponseToolMixin):
        def __init__(self):
            self.memory = Memory()
            self._active_turn_policy = policy
            self.executed = []

        def _execute_tool_with_memory(self, tool, params):
            target = params.get("semantic_target")
            self.executed.append((tool, target))
            if target == "surgical_guide":
                return ToolResult(success=False, error="guide capture unavailable")
            return ToolResult(
                success=True, message="CTV screenshot captured",
                data={"attachment_id": "ctv-capture-unique"},
            )

        @staticmethod
        def _build_multi_intent_response(_message, _steps, _policy):
            return "已按独立子任务处理截图。"

    harness = Harness()
    steps = []
    response = harness._execute_direct_tools(calls, steps, [0])
    assert harness.executed == [
        ("ui_screenshot", "surgical_guide"),
        ("ui_screenshot", "ctv"),
    ]
    assert [step["status"] for step in steps] == ["error", "done"]
    assert response == "已按独立子任务处理截图。"

    evidence_steps = []
    for call in calls:
        is_guide = call["params"].get("semantic_target") == "surgical_guide"
        evidence_steps.append({
            "tool": "ui_screenshot",
            "status": "error" if is_guide else "done",
            "result": "guide capture unavailable" if is_guide else "CTV capture ready",
            "params": call["params"],
        })

    class ResponseStub:
        _response_language = ChatWorkflowMixin._response_language
        _code_capability_response = ChatWorkflowMixin._code_capability_response
        _build_multi_intent_response = ChatWorkflowMixin._build_multi_intent_response
        _ui_state_snapshot = staticmethod(lambda: {"viewer": {"ct_loaded": True}})
        memory = SimpleNamespace(user_lang="zh", conversation=[])
        registry = None

    grounded_response = ResponseStub()._build_multi_intent_response(
        message, evidence_steps, policy,
    )
    assert "截图任务执行失败" in grounded_response
    assert "guide capture unavailable" in grounded_response
    assert "左侧" not in grounded_response and "颈部" not in grounded_response


def test_multi_intent_response_keeps_local_answers_and_never_invents_visual_findings():
    from types import SimpleNamespace
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Stub:
        _response_language = ChatWorkflowMixin._response_language
        _code_capability_response = ChatWorkflowMixin._code_capability_response
        _build_multi_intent_response = ChatWorkflowMixin._build_multi_intent_response
        _build_current_planning_assessment_response = staticmethod(
            lambda lang: 'Planning_2 is completed with verified metrics.'
        )
        _ui_state_snapshot = staticmethod(lambda: {"viewer": {"ct_loaded": True}})
        memory = SimpleNamespace(user_lang='zh', conversation=[])
        registry = None

    message = (
        "\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u600e\u4e48\u6837\uff0c"
        "\u8bf7\u622a\u56fe\u544a\u8bc9\u6211\u751f\u6210\u7684\u5bfc\u677f\u5728\u54ea\u91cc\uff1f"
        "\u6b64\u5916\u4f60\u53ef\u4ee5\u5199\u4ee3\u7801\u505a\u4e8b\u60c5\u5417"
    )
    answer = Stub()._build_multi_intent_response(
        message, [], classify_local_turn(message),
    )
    assert 'Planning_2 is completed with verified metrics.' in answer
    assert '\u5f53\u524d\u89c4\u5212\u7ed3\u679c' in answer
    assert '\u4ee3\u7801\u80fd\u529b' in answer
    assert '\u53ef\u4ee5\u534f\u52a9\u7f16\u5199' in answer
    assert 'Viewer' not in answer and '\u9888\u90e8' not in answer
    assert '\\n' not in answer


def test_multi_intent_response_uses_status_tool_result_for_guide_status_clause():
    from types import SimpleNamespace
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Stub:
        _response_language = ChatWorkflowMixin._response_language
        _code_capability_response = ChatWorkflowMixin._code_capability_response
        _build_multi_intent_response = ChatWorkflowMixin._build_multi_intent_response
        _ui_state_snapshot = staticmethod(lambda: {"viewer": {"ct_loaded": True}})
        memory = SimpleNamespace(user_lang='zh', conversation=[])
        registry = None

    message = (
        "\u5f53\u524d\u89c4\u5212\u7ed3\u679c\u751f\u6210\u5bfc\u677f\u4e86\u5417\uff0c"
        "\u5e76\u622a\u56fe\u544a\u8bc9\u6211\u5bfc\u677f\u5728\u54ea\u91cc"
    )
    status = "\u5df2\u6838\u9a8c\uff1a\u5bfc\u677f v2 \u5df2\u751f\u6210\u5e76\u5df2\u52a0\u8f7d\u3002"
    answer = Stub()._build_multi_intent_response(
        message,
        [{'tool': 'surgical_guide', 'status': 'done', 'result': status}],
        classify_local_turn(message),
    )
    assert status in answer
    assert "没有建立与该目标对应的截图任务" in answer
    assert "未据此判断目标位置" not in answer
