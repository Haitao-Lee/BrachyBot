"""Report producers honor absent current QA and explicit physical units."""
from types import SimpleNamespace
import pytest
from agent_runtime.core import AgentMemory
from tool_factory.output.report_auto_fill import ReportAutoFillTool
from tool_factory.report_generator import ReportGeneratorTool


def test_standalone_autofill_cannot_restore_stale_metrics_from_raw_memory():
    memory = AgentMemory('a'*32)
    memory.store('dose_metrics', {'v100':.99, 'd90':190., 'plan_score':99.})
    memory.store('artifact_status', {'dose':'stale', 'quality_check':'stale'})
    agent = SimpleNamespace(memory=memory, config={})
    tool = ReportAutoFillTool()
    patch, _ = tool._build_patch_from_agent(agent, scope='metrics', language='en')
    assert 'metrics.v100' not in patch and 'metrics.d90' not in patch
    assert not any('score' in key.lower() for key in patch)


@pytest.mark.parametrize('rx', [1., 4., 120.])
def test_full_report_never_rescales_an_explicit_physical_gy_prescription(rx):
    text = ReportGeneratorTool()._generate_full_report({'prescription_gy':rx, 'metrics':{}})
    assert f'{rx:.1f} Gy' in text
    if rx != 120.:
        assert f'{rx*120.:.1f} Gy' not in text


def test_standalone_summary_has_no_fabricated_score_coverage_or_oar_pass():
    text = ReportGeneratorTool()._generate_summary({'metrics':{}})
    assert 'UNVERIFIED' in text and 'Not observed' in text
    assert '0/100' not in text and '0.0%' not in text and 'OAR Violations: 0' not in text
    zero = ReportGeneratorTool()._generate_summary({'metrics':{'plan_score':0.,'v100':0.,'oar_violations':[]}})
    assert '0/100' in zero and '0.0%' in zero and 'OAR Violations: 0' in zero
