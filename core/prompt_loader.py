"""
PromptLoader — Prompt 版本化管理

将系统 prompt 和工具 schema 从代码中解耦，存储为可版本化的 YAML/JSON 文件。
支持 A/B 测试不同 prompt 版本。

环境变量：PROMPT_VERSION=v1（默认）
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "resources" / "prompts"


def _load_json(file_path: Path) -> dict:
    """加载 JSON 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(file_path: Path) -> str:
    """加载文本文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read().strip()


class PromptLoader:
    """
    版本化 Prompt 加载器。

    使用方式：
        loader = PromptLoader()  # 使用环境变量 PROMPT_VERSION 或默认 v1
        system_prompt = loader.get_prompt("world_builder")
        tool_schema = loader.get_tool_schema("world_builder", "submit_result")

    目录结构：
        prompts/
        ├── v1/
        │   ├── world_builder.txt         # 系统 prompt
        │   ├── world_builder_tools.json  # 工具 schema
        │   ├── character_designer.txt
        │   └── ...
        └── v2/
            └── ...
    """

    def __init__(self, version: str | None = None):
        self.version = version or os.getenv("PROMPT_VERSION", "v1")
        self.version_dir = PROMPTS_DIR / self.version
        self._cache: dict[str, Any] = {}

    def has_prompt(self, agent_name: str) -> bool:
        """检查是否存在版本化的 prompt 文件"""
        prompt_file = self.version_dir / f"{agent_name}.txt"
        return prompt_file.exists()

    def get_prompt(self, agent_name: str, fallback: str = "") -> str:
        """
        获取 Agent 的系统 prompt。
        如果版本化文件不存在，返回 fallback（通常是代码中的默认值）。
        """
        cache_key = f"prompt:{agent_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompt_file = self.version_dir / f"{agent_name}.txt"
        if prompt_file.exists():
            result = _load_text(prompt_file)
            self._cache[cache_key] = result
            logger.debug(f"从 {prompt_file} 加载 prompt（版本 {self.version}）")
            return result

        if fallback:
            return fallback

        logger.debug(f"未找到 {prompt_file}，使用代码默认值")
        return ""

    def get_tool_schema(self, agent_name: str, tool_name: str, fallback: dict | None = None) -> dict | None:
        """
        获取工具 schema。
        工具 schema 文件格式为 {agent_name}_tools.json，内容为 {tool_name: schema}。
        """
        cache_key = f"tools:{agent_name}"
        if cache_key not in self._cache:
            tools_file = self.version_dir / f"{agent_name}_tools.json"
            if tools_file.exists():
                self._cache[cache_key] = _load_json(tools_file)
            else:
                self._cache[cache_key] = {}

        tools = self._cache[cache_key]
        return tools.get(tool_name, fallback)

    def list_versions(self) -> list[str]:
        """列出所有可用的 prompt 版本"""
        if not PROMPTS_DIR.exists():
            return []
        return sorted(
            d.name for d in PROMPTS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def clear_cache(self):
        """清除缓存（用于热重载）"""
        self._cache.clear()


# ── 全局单例 ────────────────────────────────────────────────────────────────

_global_loader: PromptLoader | None = None


def get_prompt_loader() -> PromptLoader:
    """获取全局 PromptLoader 实例"""
    global _global_loader
    if _global_loader is None:
        _global_loader = PromptLoader()
    return _global_loader
