"""Actual registered tool schemas survive provider projections, not an LLM mock claim."""
from types import SimpleNamespace
from AgenticSys import BrachyAgent
from agent_runtime.core import ToolRegistry
from agent_runtime.llm_runtime import LLMRuntimeMixin, _schemas_without_ct
from agent_runtime.semantic_kernel import SemanticDecisionState, semantic_runtime_policy
from agent_runtime.turn_policy import LocalTurnPolicy
from tool_factory.timepoint_inspector import TimepointInspectorTool
from tool_factory.timepoint_controller import TimepointControllerTool
from tool_factory.timepoint_images import TimepointImagesTool
from tool_factory.seed_seg import SeedSegmentationTool
from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool
from tool_factory.viewer_command.query_metrics import QueryMetricsTool
from web.timepoint_chat import ChatTimepointScope


def names(rows):
    return {row['function']['name'] for row in rows}


def test_empty_acquisition_keeps_current_facts_and_timepoint_catalog_capabilities():
    control = SimpleNamespace(config={'_workspace_owner_id':'owner', '_workspace_session_id':'a'*32,
        '_workspace_timepoint_id':'b'*32}, memory=SimpleNamespace(session_id='a'*32))
    registry = ToolRegistry()
    for tool in (TimepointInspectorTool(control), TimepointControllerTool(control),
                 TimepointImagesTool(control), SeedSegmentationTool(), DicomRTExporterTool(), QueryMetricsTool()):
        registry.register(tool)
    # Tool availability needs the authenticated store binding; no store reads
    # are made while exporting descriptors.
    control._workspace_store = object()
    agent = object.__new__(BrachyAgent)
    agent.registry = registry
    agent._active_turn_context={'timepoint_scope':ChatTimepointScope('owner','a'*32,'b'*32,'zh',False)}
    agent._active_turn_policy=semantic_runtime_policy(LocalTurnPolicy('knowledge_query','low',False,False,False))
    raw = registry.to_openai_tools()
    state=SemanticDecisionState('读取当前值；不要修改其他数据')
    empty = LLMRuntimeMixin._provider_schemas_for_turn(agent, _schemas_without_ct(raw), state)
    assert {'timepoint_inspector','timepoint_controller','timepoint_images','query_metrics'} <= names(empty)
    assert 'seed_segmentation' not in names(empty)
    loaded = LLMRuntimeMixin._provider_schemas_for_turn(agent,raw,state)
    assert {'seed_segmentation','timepoint_images','dicom_rt_exporter'} <= names(loaded)
    plan = next(row for row in loaded if row['function']['name']=='record_request_plan')
    fields=plan['function']['parameters']['properties']['goals']['items']['properties']
    assert set(fields['clauses']['items']['enum']) == {row['id'] for row in state.frame['clauses']}
    assert set(fields['tools']['items']['enum']) == names(loaded)-{'record_request_plan'}
    assert 'enum' not in registry.to_openai_tools()[0]['function']['parameters'].get('tools',{})


def test_catalog_title_analysis_word_does_not_erase_explicit_restricted_ui_write():
    from agent_runtime.artifact_analysis import is_analysis_shaped
    message = '请把当前 Table Viewer 的时间点标题重命名为 Natural Language Review。只修改该标题，不要修改其他时间点或任何临床数据。'
    assert not is_analysis_shaped(message)
    assert is_analysis_shaped('请分析当前数据，不要修改标题或执行临床规划。')
    assert is_analysis_shaped('我已修改了标题，现在请分析当前数据。')


def test_provider_catalog_formatter_contains_resolvable_ids_and_titles():
    from agent_runtime.core import ToolResultPipeline
    from tool_factory import ToolResult
    result=ToolResult(True,data={'catalog_revision':3,'default_timepoint_id':'a'*32,
        'timepoints':[{'id':'a'*32,'title':'Fictional A','stage':'preoperative'},
                      {'id':'b'*32,'title':'Fictional B','stage':'intraoperative'}]},message='目录已读取。')
    text=ToolResultPipeline.format('timepoint_inspector',result,'zh')
    assert 'Fictional A' in text and 'Fictional B' in text and 'b'*32 in text
    assert 'catalog_revision' in text


def test_unverified_dose_score_is_not_formatted_as_zero_or_an_error():
    from agent_runtime.core import ToolResultPipeline
    from tool_factory import ToolResult
    result=ToolResult(True,metadata={'v100':.9,'d90':100.,'plan_score':None})
    assert 'UNVERIFIED' in ToolResultPipeline.format('dose_evaluation',result,'en')
    assert '未经验证' in ToolResultPipeline.format('dose_evaluation',result,'zh')


def test_title_only_catalog_authorization_does_not_expand_to_clinical_metadata():
    from agent_runtime.request_parse import mutating_execution_authorized
    message='请把当前 Table Viewer 的时间点标题重命名为 Natural Language Review。只修改该标题，不要修改其他时间点或任何临床数据。'
    params={'action':'update','patch':{'title':'Natural Language Review'},'timepoint_id':'b'*32}
    assert mutating_execution_authorized(message,'timepoint_controller',params=params)
    for unsafe in ({**params,'patch':{'title':'Natural Language Review','stage':'intraoperative'}},
                   {**params,'patch':{'title':'Different title'}},
                   {'action':'delete','timepoint_id':'b'*32}):
        assert not mutating_execution_authorized(message,'timepoint_controller',params=unsafe)
    for read in ('如果我把当前时间点重命名为 Natural Language Review 会怎样？',
                 '不要把当前时间点重命名为 Natural Language Review。',
                 '你之前说重命名时间点为 Natural Language Review。解释一下。'):
        assert not mutating_execution_authorized(read,'timepoint_controller',params=params)


def test_explicit_implant_detection_does_not_implicitly_grant_clinical_review():
    from agent_runtime.request_parse import mutating_execution_authorized
    message='请识别当前术中图像里已经植入的粒子并重建显示。'
    assert mutating_execution_authorized(message,'seed_segmentation',params={'action':'detect'})
    assert mutating_execution_authorized(message,'seed_segmentation',params={'action':'reconstruct'})
    assert not mutating_execution_authorized(message,'seed_segmentation',params={'action':'review_reconstruction'})
    for read in ('如果检测体内粒子，会发生什么？','不要检测体内粒子。','我已检测过粒子，请解释结果。'):
        assert not mutating_execution_authorized(read,'seed_segmentation',params={'action':'detect'})
