"""A location selector is not permission to mutate a Viewer or sibling scan."""
import pytest
from agent_runtime.request_parse import parse_request, mutating_execution_authorized


@pytest.mark.parametrize('message', [
    '请只重新计算当前 Table Viewer 中体内已经植入粒子的剂量，不要新增或重新规划粒子、针道，不要生成导板或报告，也不要操作其他时间点。',
    '请重算当前 Viewer 里的剂量，不要重新规划。',
    'Please recompute the dose in the current Table Viewer. Do not replan or generate a guide.',
    'Please recompute the dose within the mounted Viewer.',
])
def test_dose_location_retains_only_requested_write(message):
    parsed=parse_request(message)
    assert any(task.target=='dose' and not task.negated for task in parsed.subtasks)
    assert mutating_execution_authorized(message,'dose_recompute',params={'source_set':'implanted'})
    assert not mutating_execution_authorized(message,'surgical_guide',params={'action':'generate'})
    assert not mutating_execution_authorized(message,'planning_pipeline',params={'step':'full'})


@pytest.mark.parametrize('message', [
    '不要重算当前 Table Viewer 中的剂量。',
    '如果重算当前 Table Viewer 中的剂量，会怎样？',
    '解释一下如何重算当前 Table Viewer 中的剂量。',
    '用户说：“请重算当前 Table Viewer 中的剂量”。不要执行。',
    '我已经重算当前 Table Viewer 中的剂量，请解释结果。',
    'Do not recompute the dose in the current Table Viewer.',
])
def test_location_never_grants_negation_condition_question_quote_or_past(message):
    assert not mutating_execution_authorized(message,'dose_recompute',params={'source_set':'implanted'})


def test_actual_viewer_command_is_not_discarded_as_a_location():
    parsed=parse_request('请更新当前 Viewer 的显示设置。')
    assert any(task.target=='viewer' for task in parsed.subtasks)
    parsed=parse_request('请重算当前 Table Viewer 中的剂量，然后清空 Viewer。')
    assert any(task.target=='dose' for task in parsed.subtasks)
    assert any(task.target=='viewer' and task.action=='clear' for task in parsed.subtasks)
