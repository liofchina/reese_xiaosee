"""
LLM 语义缓存 — 对相同请求返回缓存结果，避免重复 LLM 调用。

适用于：开发调试、断点续跑时跳过已完成的 Agent 调用。
不适用于：高 temperature 的创作类调用（如 Writer 流式写作）。

启用方式：设置环境变量 LLM_CACHE_ENABLED=true
"""

import hashlib
import json
import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)


def _hash_request(system: str, prompt: str, tool_name: str = "", model: str = "", content_hash: str = "") -> str:
    """计算请求的内容哈希，content_hash 可用于区分同 prompt 但上下文不同的调用"""
    content = f"{model}|{system}|{prompt}|{tool_name}|{content_hash}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


# 不应缓存的 Agent（评审类/创作类，每次应独立评估）
NO_CACHE_AGENTS = {"quality_critic", "consistency_checker", "writer"}


class LLMCache:
    """
    LLM 调用结果缓存。基于 SQLite 的内容寻址存储。

    使用方式：
        cache = LLMCache()
        if cache.enabled:
            cached = cache.get(system, prompt, tool_name, model)
            if cached:
                return cached
            ...  # 实际调用 LLM
            cache.put(system, prompt, tool_name, model, result)
    """

    def __init__(self, db_path: str = "data/llm_cache.db"):
        self.enabled = os.getenv("LLM_CACHE_ENABLED", "").lower() in ("true", "1", "yes")
        self.db_path = db_path
        if self.enabled:
            self._ensure_db()

    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    hash TEXT PRIMARY KEY,
                    result TEXT NOT NULL,
                    model TEXT,
                    created_at REAL,
                    hit_count INTEGER DEFAULT 0
                )
            """)

    def should_cache(self, agent_name: str = "", temperature: float = 1.0) -> bool:
        """判断是否应缓存此调用：低温度 + 非评审类 Agent"""
        if not self.enabled:
            return False
        if temperature > 0.5:
            return False
        if agent_name in NO_CACHE_AGENTS:
            return False
        return True

    def get(self, system: str, prompt: str, tool_name: str = "", model: str = "") -> dict | None:
        """查询缓存。返回缓存的 dict 结果或 None。"""
        if not self.enabled:
            return None

        key = _hash_request(system, prompt, tool_name, model)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT result FROM cache WHERE hash = ?", (key,)
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE cache SET hit_count = hit_count + 1 WHERE hash = ?", (key,)
                    )
                    logger.debug(f"LLM 缓存命中: {key[:8]}...")
                    return json.loads(row[0])
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
        return None

    def put(
        self,
        system: str,
        prompt: str,
        tool_name: str,
        model: str,
        result: dict,
    ) -> None:
        """写入缓存。"""
        if not self.enabled:
            return

        key = _hash_request(system, prompt, tool_name, model)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (hash, result, model, created_at) VALUES (?, ?, ?, ?)",
                    (key, json.dumps(result, ensure_ascii=False), model, time.time()),
                )
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    def clear(self) -> int:
        """清空缓存，返回删除的条目数。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM cache")
                return cursor.rowcount
        except Exception:
            return 0

    def stats(self) -> dict:
        """缓存统计信息。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                total_hits = conn.execute("SELECT SUM(hit_count) FROM cache").fetchone()[0] or 0
                return {"total_entries": total, "total_hits": total_hits}
        except Exception:
            return {"total_entries": 0, "total_hits": 0}


# ── 全局单例 ────────────────────────────────────────────────────────────────

_global_cache: LLMCache | None = None


def get_cache() -> LLMCache:
    """获取全局缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = LLMCache()
    return _global_cache
