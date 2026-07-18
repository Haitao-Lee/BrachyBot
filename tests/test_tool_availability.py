"""Regression coverage for dynamic LLM tool availability."""

from __future__ import annotations

from agent_runtime.core import ToolRegistry
from tool_factory.code_executor import CodeExecutorTool
from tool_factory.env_manager import EnvManagerTool
from tool_factory.shell_executor import ShellExecutorTool
from tool_factory.tool_creator import ToolCreatorTool


def _advertised_names(registry: ToolRegistry) -> set[str]:
    return {
        item["function"]["name"]
        for item in registry.to_openai_tools()
    }


def test_disabled_developer_tools_are_not_advertised_to_the_llm(monkeypatch):
    """The model must not waste a turn calling a known-disabled tool."""
    for name in (
        "BRACHYBOT_ENABLE_CODE_EXECUTOR",
        "BRACHYBOT_ENABLE_SHELL_EXECUTOR",
        "BRACHYBOT_ENABLE_ENV_MANAGER",
        "BRACHYBOT_ENABLE_TOOL_CREATOR",
    ):
        monkeypatch.delenv(name, raising=False)

    registry = ToolRegistry()
    for tool in (CodeExecutorTool(), ShellExecutorTool(), EnvManagerTool(), ToolCreatorTool()):
        registry.register(tool)

    assert _advertised_names(registry) == set()
    assert registry.list_tools() == []


def test_explicit_developer_mode_tools_become_advertised(monkeypatch):
    """Explicit opt-in preserves the trusted-local coding workflow."""
    monkeypatch.setenv("BRACHYBOT_ENABLE_CODE_EXECUTOR", "1")
    monkeypatch.setenv("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "true")
    monkeypatch.setenv("BRACHYBOT_ENABLE_ENV_MANAGER", "yes")
    monkeypatch.setenv("BRACHYBOT_ENABLE_TOOL_CREATOR", "on")

    registry = ToolRegistry()
    for tool in (CodeExecutorTool(), ShellExecutorTool(), EnvManagerTool(), ToolCreatorTool()):
        registry.register(tool)

    names = _advertised_names(registry)
    assert names == {"code_executor", "shell_executor", "env_manager", "tool_creator"}
    assert {tool["name"] for tool in registry.list_tools()} == names


def test_direct_ct_analysis_does_not_schedule_a_disabled_executor():
    """The direct keyword shortcut follows the same availability policy."""
    source = ("agent_runtime/response_tools.py")
    with open(source, "r", encoding="utf-8") as handle:
        contents = handle.read()
    assert "action == 'analyze' and ct_path and self.registry.is_available('code_executor')" in contents
