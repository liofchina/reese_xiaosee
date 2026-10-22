"""
EntityExtractor — 从章节内容中提取实体状态变更

每章写完后调用，通过轻量 LLM 调用提取角色状态变化、阵营变化、新伏笔等。
结果用于更新 EntityStore。
"""

import json
import logging
from core.llm_client import LLMClient

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """分析以下网文章节内容，提取实体状态变更信息。

【已知角色】
{known_characters}

【已知阵营】
{known_factions}

【章节内容】
{content}

请严格按以下 JSON 格式输出（只输出 JSON，不要其他内容）：
{{
  "character_updates": [
    {{"name": "角色名", "power_level": "新境界或空字符串", "location": "新位置或空字符串", "alive": true, "event": "本章重要事件简述", "new_goal": "角色新产生的目标（无则空字符串）", "goal_completed": "角色完成的目标（无则空字符串）"}}
  ],
  "faction_updates": [
    {{"name": "阵营名", "status": "active/destroyed/merged", "event": "本章相关事件"}}
  ],
  "new_threads": [
    {{"description": "新引入的伏笔/悬念描述"}}
  ],
  "resolved_threads": [],
  "chapter_hook_registered": {{
    "description": "本章结尾悬念/钩子描述（无则空字符串）",
    "urgency": "high"
  }},
  "timeline_update": {{
    "in_story_time": "本章结束时的故事内时间点（如'第三天·黄昏'）",
    "events": [
      {{"time": "时间描述", "event": "事件简述", "characters": ["参与角色"], "location": "地点"}}
    ]
  }},
  "new_info_gaps": [
    {{"description": "某个角色知道但其他角色不知道的事实", "known_by": ["角色A"], "unknown_to": ["角色B"], "reader_knows": true}}
  ],
  "info_gap_updates": [
    {{"description": "已有信息差的描述", "newly_knows": ["新得知此事的角色"]}}
  ],
  "conflict_updates": [
    {{"description": "冲突描述", "new_level": "personal/organizational/world", "event": "冲突升级事件"}}
  ],
  "relationship_changes": [
    {{"char_a": "角色A", "char_b": "角色B", "change": "关系变化描述", "event": "触发事件"}}
  ],
  "romance_interactions": [
    {{"char_a": "角色A", "char_b": "角色B", "interaction": "互动描述"}}
  ],
  "foreshadowing_hints": [
    {{"hint_text": "伏笔描述", "importance": "low/medium/high"}}
  ],
  "narrative_patterns_used": [],
  "emotion_sequence": []
}}

注意：
- 只提取本章实际发生的变更，没有变化的角色不要列出
- power_level 只在角色确实突破时填写
- event 用一句话概括
- chapter_hook_registered：提取本章最后的悬念/钩子，如果结尾没有明确悬念则 description 为空字符串
- timeline_update：推断本章的故事内时间，如果无法判断则 in_story_time 为空字符串
- new_info_gaps：只提取重要的信息差（某角色获知了其他角色不知道的关键情报）
- conflict_updates：只在冲突升级或新冲突出现时填写
- relationship_changes：只记录关系发生实质变化的角色对
- romance_interactions：只记录感情线角色间的互动（对视、共患难、暧昧等）
- foreshadowing_hints：提取本章新埋设的伏笔/悬念（未在前文出现过的）
- narrative_patterns_used：识别本章使用的叙事套路，从以下选择：underestimate_reveal/last_moment_breakthrough/mysterious_helper/flashback_powerup/tournament_arc/treasure_hunt/betrayal_reveal/power_inheritance
- emotion_sequence：本章读者情绪变化序列（4-6个），从以下选择：好奇/紧张/绝望/燃/震撼/不安/温馨/悲伤/愤怒/释然/恐惧/感动/搞笑/期待/心寒/热血/无奈/惊喜
- 如果某个字段无实质变更，返回空数组/空字符串即可"""


async def extract_entity_changes(
    client: LLMClient,
    chapter_content: str,
    known_characters: list[str],
    known_factions: list[str],
) -> dict:
    """
    从章节内容中提取实体状态变更。
    改进：分段提取（前半段+后半段），合并结果，避免截断丢失关键信息。
    """
    content_len = len(chapter_content)
    if content_len <= 4000:
        segments = [chapter_content]
    else:
        mid = content_len // 2
        overlap = 200
        segments = [
            chapter_content[:mid + overlap],
            chapter_content[mid - overlap:],
        ]

    all_results = []
    for i, segment in enumerate(segments):
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            known_characters="、".join(known_characters) if known_characters else "无",
            known_factions="、".join(known_factions) if known_factions else "无",
            content=segment[:4000],
        )
        try:
            response = await client.complete(
                prompt,
                max_tokens=2000,
                temperature=0.2,
            )
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            all_results.append(json.loads(text))
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"实体变更提取失败（段{i+1}，非致命）: {e}")

    if not all_results:
        return {
            "character_updates": [], "faction_updates": [],
            "new_threads": [], "resolved_threads": [],
            "relationship_changes": [], "romance_interactions": [],
            "foreshadowing_hints": [], "narrative_patterns_used": [],
            "emotion_sequence": [],
        }

    return _merge_extraction_results(all_results)


def _merge_extraction_results(results: list[dict]) -> dict:
    """合并多段提取结果，去重"""
    merged = {
        "character_updates": [],
        "faction_updates": [],
        "new_threads": [],
        "resolved_threads": [],
        "chapter_hook_registered": {"description": "", "urgency": "high"},
        "timeline_update": {"in_story_time": "", "events": []},
        "new_info_gaps": [],
        "info_gap_updates": [],
        "conflict_updates": [],
        "relationship_changes": [],
        "romance_interactions": [],
        "foreshadowing_hints": [],
        "narrative_patterns_used": [],
        "emotion_sequence": [],
    }

    seen_chars = set()
    for r in results:
        for cu in r.get("character_updates", []):
            name = cu.get("name", "")
            if name not in seen_chars:
                merged["character_updates"].append(cu)
                seen_chars.add(name)

        for key in ["faction_updates", "new_threads", "resolved_threads",
                     "new_info_gaps", "info_gap_updates", "conflict_updates",
                     "relationship_changes", "romance_interactions", "foreshadowing_hints"]:
            merged[key].extend(r.get(key, []))

        for p in r.get("narrative_patterns_used", []):
            if p not in merged["narrative_patterns_used"]:
                merged["narrative_patterns_used"].append(p)

        if r.get("emotion_sequence"):
            merged["emotion_sequence"] = r["emotion_sequence"]

        hook = r.get("chapter_hook_registered", {})
        if hook.get("description"):
            merged["chapter_hook_registered"] = hook
        timeline = r.get("timeline_update", {})
        if timeline.get("in_story_time"):
            merged["timeline_update"] = timeline

    return merged
