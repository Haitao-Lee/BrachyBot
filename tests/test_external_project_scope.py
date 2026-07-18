"""Regression coverage for public-project research scope locking."""

from types import SimpleNamespace

from agent_runtime.response_tools import ResponseToolMixin


def _detector(conversation):
    """Build only the state required by the scope detector."""
    agent = object.__new__(ResponseToolMixin)
    agent.memory = SimpleNamespace(conversation=conversation)
    return agent


def test_external_project_followup_keeps_public_web_scope():
    """A pronoun follow-up retains the named external project, not local code."""
    agent = _detector([
        {"role": "user", "content": "请帮我查询 DeepRare，告知我详细的信息"},
        {"role": "assistant", "content": "我会查询公开资料。"},
    ])

    query = agent._detect_external_project_query("你能查到其代码吗")

    assert query is not None
    assert "DeepRare" in query
    assert "official repository source code" in query


def test_brachybot_request_is_not_misclassified_as_external_project():
    agent = _detector([])

    assert agent._detect_external_project_query("请检查 BrachyBot 当前项目的代码") is None
