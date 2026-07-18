"""Regression tests for case-scoped auxiliary agent persistence."""

from __future__ import annotations

from brain.integration.enhanced_agent import EnhancedAgentIntegration


class _Agent:
    pass


def test_enhanced_agent_auxiliary_state_can_be_scoped_to_workspace(tmp_path):
    integration = EnhancedAgentIntegration(
        _Agent(),
        session_id="case-test",
        storage_dir=str(tmp_path / "agent_state"),
    )
    root = str(tmp_path / "agent_state")
    assert integration.layered_memory.base_dir.startswith(root)
    assert integration.reflexion.memory_dir.startswith(root)
    assert integration.user_profile.profile_dir.startswith(root)
    assert integration.skill_crystallizer.skills_dir.startswith(root)
    assert integration.multi_agent_critic._history_path.startswith(root)
