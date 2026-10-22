"""
domain — 领域知识层
学科注入、爽点/节奏系统、Agent 编排器。
"""

from domain.disciplines import get_agent_guidance, resolve_disciplines, rotate_disciplines
from domain.pleasure_system import (
    get_pleasure_guidance_for_writer,
    get_pleasure_guidance_for_outliner,
    get_chapter_pacing_template,
    get_combat_guidance,
    get_combat_tier,
    get_story_phase,
    get_story_phase_guidance,
    WORLD_EXPANSION_RULES,
    STORY_PHASES,
    TITLE_FORMULAS,
    COMBAT_ESCALATION_RULES,
)

__all__ = [
    "get_agent_guidance", "resolve_disciplines", "rotate_disciplines",
    "get_pleasure_guidance_for_writer", "get_pleasure_guidance_for_outliner",
    "get_chapter_pacing_template", "get_combat_guidance", "get_combat_tier",
    "get_story_phase", "get_story_phase_guidance",
    "WORLD_EXPANSION_RULES", "STORY_PHASES", "TITLE_FORMULAS", "COMBAT_ESCALATION_RULES",
]
