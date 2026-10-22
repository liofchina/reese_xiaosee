"""
ToolRegistry — 集中式工具注册中心

Claude Code 核心设计理念：工具不应散落在各 Agent 中，而是统一注册、按需获取。
支持内置工具和未来的 MCP 外部工具。
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    集中式工具注册中心。

    使用方式：
        registry = ToolRegistry()
        registry.register("lookup_character", "查询角色档案", schema, handler)

        tools = registry.get_tools(["lookup_character", "lookup_power_level"])
        handlers = registry.get_handlers(["lookup_character", "lookup_power_level"])
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}        # name → Anthropic tool schema
        self._handlers: dict[str, Callable] = {}  # name → handler function
        self._sources: dict[str, str] = {}         # name → source ("builtin" | "mcp:{server}")

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable,
        source: str = "builtin",
    ) -> None:
        """注册一个工具"""
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._handlers[name] = handler
        self._sources[name] = source
        logger.debug(f"工具已注册: {name} (source={source})")

    def unregister(self, name: str) -> None:
        """取消注册"""
        self._tools.pop(name, None)
        self._handlers.pop(name, None)
        self._sources.pop(name, None)

    def get_tool(self, name: str) -> dict:
        """获取单个工具 schema"""
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未注册")
        return self._tools[name]

    def get_tools(self, names: list[str]) -> list[dict]:
        """获取多个工具 schema"""
        return [self.get_tool(n) for n in names]

    def get_handler(self, name: str) -> Callable:
        """获取单个工具 handler"""
        if name not in self._handlers:
            raise KeyError(f"工具 '{name}' 未注册")
        return self._handlers[name]

    def get_handlers(self, names: list[str]) -> dict[str, Callable]:
        """获取多个工具 handler"""
        return {n: self.get_handler(n) for n in names}

    def list_tools(self, source: str | None = None) -> list[str]:
        """列出所有已注册工具名（可按 source 过滤）"""
        if source is None:
            return list(self._tools.keys())
        return [n for n, s in self._sources.items() if s == source]

    def has(self, name: str) -> bool:
        return name in self._tools


# ── 全局单例 ────────────────────────────────────────────────────────────────

_global_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """获取全局工具注册中心"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry
