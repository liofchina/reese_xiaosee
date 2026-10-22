"""LLMCache 单元测试"""
import pytest
from unittest.mock import patch
from core.cache import LLMCache, _hash_request, NO_CACHE_AGENTS


class TestShouldCache:
    def _make_cache(self, enabled=True):
        cache = LLMCache.__new__(LLMCache)
        cache.enabled = enabled
        return cache

    def test_disabled_returns_false(self):
        cache = self._make_cache(enabled=False)
        assert cache.should_cache("world_builder", 0.3) is False

    def test_high_temperature_returns_false(self):
        cache = self._make_cache(enabled=True)
        assert cache.should_cache("world_builder", 0.8) is False

    def test_at_temperature_boundary(self):
        cache = self._make_cache(enabled=True)
        # temperature > 0.5 → False
        assert cache.should_cache("world_builder", 0.51) is False
        assert cache.should_cache("world_builder", 0.5) is True

    def test_no_cache_agents(self):
        cache = self._make_cache(enabled=True)
        for agent in NO_CACHE_AGENTS:
            assert cache.should_cache(agent, 0.3) is False

    def test_no_cache_agents_are_expected(self):
        assert "quality_critic" in NO_CACHE_AGENTS
        assert "consistency_checker" in NO_CACHE_AGENTS
        assert "writer" in NO_CACHE_AGENTS

    def test_normal_cacheable(self):
        cache = self._make_cache(enabled=True)
        assert cache.should_cache("world_builder", 0.3) is True
        assert cache.should_cache("character_designer", 0.0) is True

    def test_empty_agent_name_cacheable(self):
        cache = self._make_cache(enabled=True)
        assert cache.should_cache("", 0.3) is True


class TestHashRequest:
    def test_deterministic(self):
        h1 = _hash_request("sys", "prompt", "tool", "model")
        h2 = _hash_request("sys", "prompt", "tool", "model")
        assert h1 == h2

    def test_different_system(self):
        h1 = _hash_request("sys1", "prompt", "tool", "model")
        h2 = _hash_request("sys2", "prompt", "tool", "model")
        assert h1 != h2

    def test_different_prompt(self):
        h1 = _hash_request("sys", "prompt1", "tool", "model")
        h2 = _hash_request("sys", "prompt2", "tool", "model")
        assert h1 != h2

    def test_different_model(self):
        h1 = _hash_request("sys", "prompt", "tool", "model1")
        h2 = _hash_request("sys", "prompt", "tool", "model2")
        assert h1 != h2

    def test_different_content_hash(self):
        h1 = _hash_request("sys", "prompt", "tool", "model", "hash1")
        h2 = _hash_request("sys", "prompt", "tool", "model", "hash2")
        assert h1 != h2

    def test_length_32(self):
        h = _hash_request("s", "p", "t", "m")
        assert len(h) == 32

    def test_hex_characters_only(self):
        h = _hash_request("sys", "prompt", "tool", "model")
        assert all(c in "0123456789abcdef" for c in h)


class TestCacheGetPut:
    """集成测试 — 使用临时数据库"""

    @pytest.fixture
    def cache(self, tmp_path):
        db_path = str(tmp_path / "test_cache.db")
        with patch.dict("os.environ", {"LLM_CACHE_ENABLED": "true"}):
            return LLMCache(db_path=db_path)

    def test_roundtrip(self, cache):
        cache.put("sys", "prompt", "tool", "model", {"key": "value"})
        result = cache.get("sys", "prompt", "tool", "model")
        assert result == {"key": "value"}

    def test_miss_returns_none(self, cache):
        result = cache.get("sys", "nonexistent", "tool", "model")
        assert result is None

    def test_hit_increments_count(self, cache):
        cache.put("sys", "p", "t", "m", {"x": 1})
        cache.get("sys", "p", "t", "m")
        cache.get("sys", "p", "t", "m")
        stats = cache.stats()
        assert stats["total_hits"] == 2

    def test_overwrite_existing(self, cache):
        cache.put("sys", "p", "t", "m", {"v": 1})
        cache.put("sys", "p", "t", "m", {"v": 2})
        result = cache.get("sys", "p", "t", "m")
        assert result == {"v": 2}

    def test_unicode_content(self, cache):
        cache.put("系统", "提示词", "工具", "模型", {"内容": "中文测试"})
        result = cache.get("系统", "提示词", "工具", "模型")
        assert result == {"内容": "中文测试"}


class TestCacheClear:
    @pytest.fixture
    def cache(self, tmp_path):
        db_path = str(tmp_path / "test_cache.db")
        with patch.dict("os.environ", {"LLM_CACHE_ENABLED": "true"}):
            return LLMCache(db_path=db_path)

    def test_clear_returns_count(self, cache):
        cache.put("s1", "p", "t", "m", {"a": 1})
        cache.put("s2", "p", "t", "m", {"b": 2})
        count = cache.clear()
        assert count == 2

    def test_clear_empty_returns_zero(self, cache):
        assert cache.clear() == 0

    def test_get_after_clear_returns_none(self, cache):
        cache.put("sys", "p", "t", "m", {"x": 1})
        cache.clear()
        assert cache.get("sys", "p", "t", "m") is None


class TestCacheStats:
    @pytest.fixture
    def cache(self, tmp_path):
        db_path = str(tmp_path / "test_cache.db")
        with patch.dict("os.environ", {"LLM_CACHE_ENABLED": "true"}):
            return LLMCache(db_path=db_path)

    def test_empty_stats(self, cache):
        stats = cache.stats()
        assert stats == {"total_entries": 0, "total_hits": 0}

    def test_stats_after_puts(self, cache):
        cache.put("s1", "p", "t", "m", {"a": 1})
        cache.put("s2", "p", "t", "m", {"b": 2})
        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["total_hits"] == 0


class TestCacheDisabled:
    def test_get_returns_none_when_disabled(self):
        with patch.dict("os.environ", {"LLM_CACHE_ENABLED": "false"}):
            cache = LLMCache(db_path="irrelevant.db")
        assert cache.get("sys", "prompt", "tool", "model") is None

    def test_put_does_nothing_when_disabled(self):
        with patch.dict("os.environ", {"LLM_CACHE_ENABLED": "false"}):
            cache = LLMCache(db_path="irrelevant.db")
        # Should not raise
        cache.put("sys", "prompt", "tool", "model", {"x": 1})
