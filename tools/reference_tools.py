"""
引用/查询工具 — 纯 Python 工具，查询内存中的小说状态。

这些工具供 Agent 在多轮对话中按需调用，而非将所有上下文塞入 prompt。
Claude Code 理念：Agent 应能按需查询，而非依赖预加载的完整上下文。
"""

import re
from typing import Any
from models.novel import (
    WebNovelOutline, CharacterProfile, AntagonistTier,
    ChapterResult, WorldSetting
)
from tools.registry import ToolRegistry

# ── 禁用词表（与 writer.py 保持一致） ─────────────────────────────────────────

BANNED_WORDS = [
    "不禁", "顿时", "忍不住", "猛地", "深深地", "不由得",
    "他心中感到", "她感到一阵", "内心充满了",
]


# ── 工具实现 ────────────────────────────────────────────────────────────────

def make_lookup_character(outline: WebNovelOutline):
    """创建角色查询工具（闭包绑定 outline）"""
    def handler(input_data: dict) -> dict:
        name = input_data.get("name", "")
        # 搜索主角色
        for c in outline.characters:
            if c.name == name or name in c.name:
                return {
                    "found": True,
                    "type": "character",
                    "data": c.model_dump(),
                }
        # 搜索反派
        for a in outline.antagonists:
            if a.name == name or name in a.name:
                return {
                    "found": True,
                    "type": "antagonist",
                    "data": a.model_dump(),
                }
        return {"found": False, "message": f"未找到名为 '{name}' 的角色"}
    return handler


def make_lookup_power_level(outline: WebNovelOutline):
    """创建力量等级查询工具"""
    def handler(input_data: dict) -> dict:
        level_name = input_data.get("level_name", "")
        ps = outline.world.power_system

        for i, lv in enumerate(ps.levels):
            if lv.name == level_name or level_name in lv.name:
                result = {
                    "found": True,
                    "level": lv.model_dump(),
                    "index": i,
                    "total_levels": len(ps.levels),
                }
                if i > 0:
                    result["lower_level"] = ps.levels[i - 1].name
                if i < len(ps.levels) - 1:
                    result["higher_level"] = ps.levels[i + 1].name
                return result

        return {
            "found": False,
            "message": f"未找到 '{level_name}'",
            "available_levels": [lv.name for lv in ps.levels],
        }
    return handler


def make_lookup_faction(outline: WebNovelOutline):
    """创建势力查询工具"""
    def handler(input_data: dict) -> dict:
        faction_name = input_data.get("faction_name", "")
        for f in outline.world.factions:
            if f.name == faction_name or faction_name in f.name:
                return {"found": True, "data": f.model_dump()}
        return {
            "found": False,
            "message": f"未找到 '{faction_name}'",
            "available_factions": [f.name for f in outline.world.factions],
        }
    return handler


def make_search_chapter_summaries(chapters: list[ChapterResult]):
    """创建章节摘要搜索工具"""
    def handler(input_data: dict) -> dict:
        query = input_data.get("query", "")
        n = input_data.get("n", 3)

        results = []
        for ch in chapters:
            # 简单关键词匹配
            score = 0
            for keyword in query.split():
                if keyword in ch.summary:
                    score += 1
                if keyword in ch.title:
                    score += 2
            if score > 0:
                results.append({
                    "chapter_num": ch.chapter_num,
                    "title": ch.title,
                    "summary": ch.summary,
                    "score": score,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return {"results": results[:n], "total_matched": len(results)}
    return handler


def check_banned_words_handler(input_data: dict) -> dict:
    """检查文本中的禁用词"""
    text = input_data.get("text", "")
    found = []
    for word in BANNED_WORDS:
        count = text.count(word)
        if count > 0:
            found.append({"word": word, "count": count})

    # 检查连续三次相同动词
    repeated_verbs = []
    verb_pattern = re.compile(r'(说道|走向|看向|喊道|笑道)')
    matches = verb_pattern.findall(text)
    if matches:
        for i in range(len(matches) - 2):
            if matches[i] == matches[i+1] == matches[i+2]:
                repeated_verbs.append(matches[i])

    return {
        "banned_words_found": found,
        "repeated_verbs": list(set(repeated_verbs)),
        "has_issues": len(found) > 0 or len(repeated_verbs) > 0,
    }


def count_words_handler(input_data: dict) -> dict:
    """统计字数"""
    text = input_data.get("text", "")
    # 中文字符计数
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text)
    return {
        "chinese_chars": chinese_chars,
        "total_chars": total_chars,
    }


# ── 工具 Schema 定义 ────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "lookup_character": {
        "description": "查询角色档案（包括主角、配角、反派）",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "角色名称（支持部分匹配）"},
            },
            "required": ["name"],
        },
    },
    "lookup_power_level": {
        "description": "查询力量等级详情（包含相邻等级信息）",
        "input_schema": {
            "type": "object",
            "properties": {
                "level_name": {"type": "string", "description": "境界名称"},
            },
            "required": ["level_name"],
        },
    },
    "lookup_faction": {
        "description": "查询势力信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "faction_name": {"type": "string", "description": "势力名称"},
            },
            "required": ["faction_name"],
        },
    },
    "search_chapter_summaries": {
        "description": "关键词搜索已写章节摘要",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（空格分隔）"},
                "n": {"type": "integer", "description": "返回结果数量", "default": 3},
            },
            "required": ["query"],
        },
    },
    "check_banned_words": {
        "description": "检查文本中的网文禁用词和重复动词",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要检查的文本"},
            },
            "required": ["text"],
        },
    },
    "count_words": {
        "description": "统计文本字数（中文字符数和总字符数）",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要统计的文本"},
            },
            "required": ["text"],
        },
    },
}


def register_reference_tools(
    registry: ToolRegistry,
    outline: WebNovelOutline | None = None,
    chapters: list[ChapterResult] | None = None,
) -> None:
    """
    注册所有引用/查询工具到注册中心。

    Args:
        registry: 工具注册中心
        outline: 小说大纲（用于角色/力量/势力查询，可为 None）
        chapters: 已写章节列表（用于摘要搜索，可为 None）
    """
    # 始终注册不依赖上下文的工具
    registry.register(
        "check_banned_words",
        TOOL_SCHEMAS["check_banned_words"]["description"],
        TOOL_SCHEMAS["check_banned_words"]["input_schema"],
        check_banned_words_handler,
    )
    registry.register(
        "count_words",
        TOOL_SCHEMAS["count_words"]["description"],
        TOOL_SCHEMAS["count_words"]["input_schema"],
        count_words_handler,
    )

    # 依赖 outline 的工具
    if outline:
        registry.register(
            "lookup_character",
            TOOL_SCHEMAS["lookup_character"]["description"],
            TOOL_SCHEMAS["lookup_character"]["input_schema"],
            make_lookup_character(outline),
        )
        registry.register(
            "lookup_power_level",
            TOOL_SCHEMAS["lookup_power_level"]["description"],
            TOOL_SCHEMAS["lookup_power_level"]["input_schema"],
            make_lookup_power_level(outline),
        )
        registry.register(
            "lookup_faction",
            TOOL_SCHEMAS["lookup_faction"]["description"],
            TOOL_SCHEMAS["lookup_faction"]["input_schema"],
            make_lookup_faction(outline),
        )

    # 依赖 chapters 的工具
    if chapters:
        registry.register(
            "search_chapter_summaries",
            TOOL_SCHEMAS["search_chapter_summaries"]["description"],
            TOOL_SCHEMAS["search_chapter_summaries"]["input_schema"],
            make_search_chapter_summaries(chapters),
        )
