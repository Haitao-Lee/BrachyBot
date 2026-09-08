from unittest.mock import patch


def test_opencode_generic_provider_sends_stable_session_header():
    from brain.providers.generic_openai_compat import GenericOpenAICompatLLM

    with patch("openai.OpenAI") as factory:
        provider = GenericOpenAICompatLLM(
            api_key="test-key",
            model="mimo-v2.5",
            base_url="https://opencode.ai/zen/go/v1",
            session_id="workspace/session-123",
        )
        first = provider._get_client()
        second = provider._get_client()

        assert first is second
        assert factory.call_count == 1
        kwargs = factory.call_args.kwargs
        assert kwargs["default_headers"]["user-agent"] == "BrachyBot/1.0"
        assert kwargs["default_headers"]["x-opencode-session"] == "workspace-session-123"


def test_non_opencode_generic_provider_does_not_receive_opencode_header():
    from brain.providers.generic_openai_compat import GenericOpenAICompatLLM

    with patch("openai.OpenAI") as factory:
        provider = GenericOpenAICompatLLM(
            api_key="test-key",
            model="gpt-test",
            base_url="https://api.example.test/v1",
            session_id="workspace-session-123",
        )
        provider._get_client()

        assert factory.call_args.kwargs["default_headers"] is None
