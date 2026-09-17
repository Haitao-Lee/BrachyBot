import pytest
from agent_runtime.turn_policy import classify_local_turn, resolve_report_request_action
from agent_runtime.intent_boundary import canonical_resource_read


@pytest.mark.parametrize('message', [
    '你可以清空当前的报告吗', '清空报告', '删除报告', '请导出报告',
    '报告为什么是空的', '不要打开报告', '不要生成报告',
    '请打开报告并删除里面的截图', '请查看剂量然后清空报告',
    'Can you clear the current report?', 'delete the report',
    'Do not regenerate the report', 'Explain how to generate a report',
    'The report was generated yesterday', 'Is the report ready?',
    '查看当前DVH并修改处方剂量', '不要显示当前结构',
])
def test_noncanonical_requests_never_take_resource_or_report_shortcut(message):
    policy = classify_local_turn(message)
    assert policy.intent != 'session_content_query'
    assert not policy.direct_execution
    assert not policy.execution_grants


@pytest.mark.parametrize('message', [
    '你可以清空当前的报告吗', '报告', '删除报告', '导出报告',
    'Can you clear the current report?', 'Do not open the report',
])
def test_resource_noun_is_not_a_read_action(message):
    assert resolve_report_request_action(message) is None


@pytest.mark.parametrize('message', [
    '请查看当前报告', '我想看看当前报告中的截图', '显示当前 CT 影像',
    '查看当前结构和分割结果', '查看当前DVH', 'show the current report',
    'please open the saved report figures',
])
def test_simple_reads_remain_local(message):
    assert canonical_resource_read(message)
    assert classify_local_turn(message).intent == 'session_content_query'


def test_clear_keeps_semantic_capabilities_without_granting_deletion():
    policy = classify_local_turn('你可以清空当前的报告吗')
    assert policy.intent == 'semantic_action'
    assert {'ui_controller', 'ui_inspector'} <= policy.allow_tools
    assert not policy.execution_grants


@pytest.mark.parametrize('message', ['请重新生成报告', 'regenerate the current report'])
def test_explicit_generation_stays_fast(message):
    policy = classify_local_turn(message)
    assert policy.intent == 'report_generation'
    assert policy.direct_execution


def test_clear_tool_normalization_preserves_operation_and_confirmation():
    from agent_runtime.response_tools import ResponseToolMixin
    from tool_factory.ui_controller import UIControllerTool
    calls = ResponseToolMixin()._normalize_tool_params([{
        'tool': 'ui_controller',
        'params': {'actions': [{'target': 'report.clear', 'command': 'run'}]},
    }])
    assert calls[0]['tool'] == 'ui_controller'
    assert calls[0]['params']['actions'][0]['target'] == 'report.clear'
    result = UIControllerTool().execute(**calls[0]['params'])
    assert result.success
    assert result.metadata['actions'][0]['requires_confirm'] is True
    assert result.metadata['has_destructive'] is True
