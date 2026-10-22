"""
tests/test_llm_client.py — LLM 客户端错误处理与工厂函数测试
"""

import os
import pytest

from core.llm_client import (
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
