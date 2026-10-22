"""
Observability — LLM 调用追踪与指标收集

记录每次 LLM 调用的 token 用量、延迟、成本估算，以及 Agent 级别的执行指标。
支持：
- 结构化 JSON 日志输出
- 按 task_id 查询追踪记录
- 成本估算（基于模型定价）
"""

import json
import time
import logging
import sqlite3
import os
from dataclasses import dataclass, field, asdict
from typing import Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ── 模型定价（每百万 token，美元） ─────────────────────────────────────────────

MODEL_PRICING = {
    # Anthropic
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    # 默认
    "_default": {"input": 3.0, "output": 15.0},
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["_default"])
    return (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000


@dataclass
class LLMCallTrace:
    """单次 LLM 调用记录"""
    task_id: str
    agent_name: str
    method: str               # tool_call / stream / complete / multi_turn / thinking
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    success: bool = True
    error: str = ""
    metadata: dict = field(default_factory=dict)  # iteration, turn 等额外信息
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
        if self.cost_usd == 0.0 and self.tokens_in > 0:
            self.cost_usd = _estimate_cost(self.model, self.tokens_in, self.tokens_out)


@dataclass
class AgentSpan:
    """Agent 级别执行 span"""
    task_id: str
    agent_name: str
    iterations: int = 0
    validation_passed: bool = False
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_latency_ms: int = 0
    total_cost_usd: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0


class Tracer:
    """
    追踪收集器。每个 task 一个 Tracer 实例。

    使用方式：
        tracer = Tracer(task_id="abc123", db_path="data/traces.db")
        tracer.record_llm_call(LLMCallTrace(...))
        summary = tracer.get_summary()
    """

    def __init__(self, task_id: str, db_path: str = "data/traces.db"):
        self.task_id = task_id
        self.db_path = db_path
        self.traces: list[LLMCallTrace] = []
        self.spans: dict[str, AgentSpan] = {}
        self._current_agent: str = ""
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    agent_name TEXT,
                    method TEXT,
                    model TEXT,
                    tokens_in INTEGER,
                    tokens_out INTEGER,
                    latency_ms INTEGER,
                    cost_usd REAL,
                    success INTEGER,
                    error TEXT,
                    metadata TEXT,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_traces_task ON traces(task_id)
            """)

    def record_llm_call(self, trace: LLMCallTrace):
        """记录一次 LLM 调用"""
        trace.task_id = self.task_id
        if not trace.agent_name:
            trace.agent_name = self._current_agent
        self.traces.append(trace)

        # 更新 Agent span
        if trace.agent_name:
            span = self.spans.setdefault(
                trace.agent_name,
                AgentSpan(task_id=self.task_id, agent_name=trace.agent_name, start_time=time.time())
            )
            span.total_tokens_in += trace.tokens_in
            span.total_tokens_out += trace.tokens_out
            span.total_latency_ms += trace.latency_ms
            span.total_cost_usd += trace.cost_usd

        # 持久化
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO traces (task_id, agent_name, method, model, tokens_in, tokens_out, "
                    "latency_ms, cost_usd, success, error, metadata, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trace.task_id, trace.agent_name, trace.method, trace.model,
                        trace.tokens_in, trace.tokens_out, trace.latency_ms,
                        trace.cost_usd, int(trace.success), trace.error,
                        json.dumps(trace.metadata, ensure_ascii=False), trace.timestamp,
                    ),
                )
        except Exception as e:
            logger.warning(f"追踪记录持久化失败: {e}")

    @contextmanager
    def agent_span(self, agent_name: str):
        """Agent 执行 span 上下文管理器"""
        self._current_agent = agent_name
        span = AgentSpan(
            task_id=self.task_id,
            agent_name=agent_name,
            start_time=time.time(),
        )
        self.spans[agent_name] = span
        try:
            yield span
        finally:
            span.end_time = time.time()
            self._current_agent = ""

    def get_summary(self) -> dict:
        """获取追踪摘要"""
        total_tokens_in = sum(t.tokens_in for t in self.traces)
        total_tokens_out = sum(t.tokens_out for t in self.traces)
        total_cost = sum(t.cost_usd for t in self.traces)
        total_calls = len(self.traces)
        failed_calls = sum(1 for t in self.traces if not t.success)

        return {
            "task_id": self.task_id,
            "total_llm_calls": total_calls,
            "failed_calls": failed_calls,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_tokens": total_tokens_in + total_tokens_out,
            "estimated_cost_usd": round(total_cost, 4),
            "agents": {
                name: {
                    "tokens_in": span.total_tokens_in,
                    "tokens_out": span.total_tokens_out,
                    "latency_ms": span.total_latency_ms,
                    "cost_usd": round(span.total_cost_usd, 4),
                }
                for name, span in self.spans.items()
            },
        }

    @staticmethod
    def load_traces(task_id: str, db_path: str = "data/traces.db") -> list[dict]:
        """从数据库加载指定 task 的追踪记录"""
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM traces WHERE task_id = ? ORDER BY timestamp",
                    (task_id,),
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []
