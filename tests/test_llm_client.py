"""
tests/test_llm_client.py — LLM 客户端错误处理与工厂函数测试
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm_client import (
    AnthropicClient,
    BudgetExceededError,
    LLMClient,
    OllamaClient,
    OpenAICompatibleClient,
    ProviderRateLimitError,
    ProviderUnavailableError,
    validate_provider_config,
)


class TestValidateProviderConfig:
    def test_anthropic_missing_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            validate_provider_config()

    def test_anthropic_with_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        validate_provider_config()  # should not raise

    def test_openai_compatible_missing_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="LLM_API_KEY"):
            validate_provider_config()

    def test_openai_compatible_missing_base_url(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        with pytest.raises(EnvironmentError, match="LLM_BASE_URL"):
            validate_provider_config()

    def test_openai_compatible_missing_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
        monkeypatch.delenv("MODEL", raising=False)
        with pytest.raises(EnvironmentError, match="MODEL"):
            validate_provider_config()

    def test_ollama_no_validation(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        validate_provider_config()  # should not raise

    def test_unknown_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "unknown_provider")
        with pytest.raises(EnvironmentError, match="未知"):
            validate_provider_config()


class TestProviderExceptions:
    def test_rate_limit_error(self):
        err = ProviderRateLimitError("too many requests")
        assert "too many requests" in str(err)

    def test_unavailable_error_with_code(self):
        err = ProviderUnavailableError(503, "service down")
        assert err.status_code == 503
        assert "service down" in str(err)

    def test_unavailable_error_default_message(self):
        err = ProviderUnavailableError(502)
        assert "502" in str(err)


COMPLETION_CALLS = [
    (
        "tool_call",
        {
            "system": "System",
            "prompt": "Prompt",
            "tool": {"name": "submit_result", "input_schema": {"type": "object"}},
            "tool_name": "submit_result",
        },
    ),
    ("complete", {"prompt": "Prompt"}),
    (
        "multi_turn_tool_call",
        {
            "system": "System",
            "messages": [{"role": "user", "content": "Prompt"}],
            "tools": [],
            "tool_handlers": {},
        },
    ),
]


@pytest.fixture(params=[OpenAICompatibleClient, OllamaClient])
def completion_client(request, monkeypatch):
    monkeypatch.setenv("MAX_COST_PER_RUN", "10")
    monkeypatch.setattr(
        "core.llm_client.get_cache", lambda: SimpleNamespace(enabled=False)
    )
    client = request.param.__new__(request.param)
    LLMClient.__init__(client)
    client.model = "deepseek-chat"
    client.context_window = 32768
    client._chars_per_token = 1.5
    message = MagicMock()
    message.content = "A summary"
    message.tool_calls = [
        SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="submit_result", arguments='{"ok": true}'),
        )
    ]
    message.model_dump.return_value = {"role": "assistant", "content": "A summary"}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=2000),
    )
    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.mark.parametrize(("method", "kwargs"), COMPLETION_CALLS)
async def test_completion_methods_record_usage(completion_client, method, kwargs):
    await getattr(completion_client, method)(**kwargs)

    usage = completion_client.get_cost_summary()
    assert usage["total_calls"] == 1
    assert usage["total_tokens_in"] == 1000
    assert usage["total_tokens_out"] == 2000
    assert usage["total_cost_usd"] == pytest.approx(0.0007)


async def test_completion_stops_when_response_exceeds_budget(completion_client):
    completion_client._max_cost = 0.0001

    with pytest.raises(BudgetExceededError):
        await completion_client.complete("Prompt")

    assert completion_client.get_cost_summary()["total_calls"] == 1
    completion_client.client.chat.completions.create.assert_awaited_once()


async def test_completion_does_not_call_provider_after_budget_is_exhausted(completion_client):
    completion_client._max_cost = 0

    with pytest.raises(BudgetExceededError):
        await completion_client.complete("Prompt")

    completion_client.client.chat.completions.create.assert_not_awaited()


@pytest.mark.parametrize("thinking", [False, True])
async def test_anthropic_multi_turn_and_thinking_record_usage(monkeypatch, thinking):
    monkeypatch.setenv("MAX_COST_PER_RUN", "10")
    client = AnthropicClient.__new__(AnthropicClient)
    LLMClient.__init__(client)
    client.model = "claude-sonnet-4-6"
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", id="call-1", name="submit_result", input={"ok": True})
        ],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=2000),
    )
    client.client = MagicMock()
    client.client.messages.create = AsyncMock(return_value=response)

    if thinking:
        await client.tool_call_with_thinking(
            "System", "Prompt", {"name": "submit_result"}, "submit_result"
        )
    else:
        await client.multi_turn_tool_call(
            "System", [{"role": "user", "content": "Prompt"}], [], {}
        )

    usage = client.get_cost_summary()
    assert usage["total_calls"] == 1
    assert usage["total_tokens_in"] == 1000
    assert usage["total_tokens_out"] == 2000
    assert usage["total_cost_usd"] == pytest.approx(0.033)


@pytest.mark.parametrize("client_class", [AnthropicClient, OpenAICompatibleClient, OllamaClient])
async def test_provider_closes_its_http_client(client_class):
    client = client_class.__new__(client_class)
    client.client = MagicMock()
    client.client.close = AsyncMock()

    await client.close()

    client.client.close.assert_awaited_once()


def test_template_key_does_not_enable_ai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_api_key_here")
    with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
        validate_provider_config()
