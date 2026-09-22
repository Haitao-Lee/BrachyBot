"""A final reply must never deny search evidence that the tool chain returned.

Regression (2026-09-22): after three successful web_search calls and one
web_fetch that legitimately 404'd, the final reply claimed "联网检索也没有返回
…可用权威结果" and recycled an unrelated "AI 服务" label from earlier turns. The
honesty prompt must scope failures to the failed step, and a deterministic
guard scrubs a claim that the search returned nothing whenever search hits are
present in the steps.
"""

from agent_runtime.llm_runtime import (
    _FINAL_SYNTHESIS_INSTRUCTION,
    _HONEST_FAILURE_PROMPT,
    _scrub_false_search_absence,
)


_INCIDENT_TEXT = (
    "⚠️ 先如实说明失败点：本轮用于核实「乔布斯病情与治疗」的维基百科页面抓取失败（HTTP 404），"
    "联网检索也没有返回与 AI 服务/该主题相关的可用权威结果。"
    "因此下面的内容主要来自训练数据，属未经本次检索验证的信息，请勿当作已核实的医学事实引用。"
)

_HIT_STEPS = [
    {
        "type": "tool",
        "tool": "web_search",
        "status": "done",
        "result": "## 搜索结果\n- **Pancreatic Neuroendocrine Tumor Stages**\n  来源: https://x.org/1",
    }
]


def test_false_search_absence_claim_is_scrubbed_when_hits_exist():
    out = _scrub_false_search_absence(_INCIDENT_TEXT, _HIT_STEPS)
    assert "HTTP 404" in out
    assert "联网检索也没有返回" not in out
    assert "AI 服务" not in out
    assert "训练数据" in out


def test_honest_absence_claim_survives_without_hits():
    text = "联网检索也没有返回与该主题相关的可用权威结果。"
    out = _scrub_false_search_absence(text, [])
    assert "联网检索也没有返回" in out


def test_nuanced_search_claims_survive():
    text = "联网检索也没有返回2024年后的指南更新，但2023版指南仍然适用。"
    out = _scrub_false_search_absence(text, _HIT_STEPS)
    assert "2024年后的指南更新" in out
    assert "2023版指南仍然适用" in out


def test_false_absence_claim_keeps_honest_tail():
    text = "抓取失败（HTTP 404），联网检索也没有返回可用结果，但维基百科页面有相关内容。"
    out = _scrub_false_search_absence(text, _HIT_STEPS)
    assert "HTTP 404" in out
    assert "联网检索也没有返回可用结果" not in out
    assert "维基百科页面有相关内容" in out


def test_english_false_absence_claim_is_scrubbed():
    text = (
        "The page fetch failed (HTTP 404), and the web search returned no usable "
        "results for this topic. The answer below comes from training data."
    )
    out = _scrub_false_search_absence(text, _HIT_STEPS)
    assert "web search returned no usable" not in out
    assert "HTTP 404" in out
    assert "training data" in out


def test_honest_failure_prompt_pins_search_evidence_rule():
    low = _HONEST_FAILURE_PROMPT.lower()
    assert "never claim that the search returned nothing" in low
    assert "do not import unrelated topics" in low
    assert "never deny" in _FINAL_SYNTHESIS_INSTRUCTION.lower()
