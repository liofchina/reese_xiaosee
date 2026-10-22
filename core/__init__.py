"""
core — 基础设施层
LLM 客户端、缓存、数据库、安全护栏、可观测性、Prompt 加载器。
"""

from core.llm_client import LLMClient, create_client, ProviderRateLimitError, ProviderUnavailableError
from core.cache import get_cache, LLMCache, NO_CACHE_AGENTS
from core.db import init_db, save_novel, list_novels, delete_novel, get_novel
from core.guardrails import sanitize_input, scan_output, get_guardrail_level
from core.observability import Tracer, LLMCallTrace
from core.prompt_loader import get_prompt_loader

__all__ = [
    "LLMClient", "create_client", "ProviderRateLimitError", "ProviderUnavailableError",
    "get_cache", "LLMCache", "NO_CACHE_AGENTS",
    "init_db", "save_novel", "list_novels", "delete_novel", "get_novel",
    "sanitize_input", "scan_output", "get_guardrail_level",
    "Tracer", "LLMCallTrace",
    "get_prompt_loader",
]
