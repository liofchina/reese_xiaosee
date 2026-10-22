"""
CognitiveLoadTracker — 读者认知负荷管理

评估每章的信息密度，防止新读者/回流读者认知过载。
"""

import logging

logger = logging.getLogger(__name__)


# 认知负荷阈值
MAX_ACTIVE_CHARACTERS = 5    # 同一章同时活跃角色上限
MAX_NEW_PROPER_NOUNS = 3     # 每章引入的新专有名词上限
MAX_ACTIVE_THREADS = 3       # 每章涉及的伏笔线上限


def evaluate_chapter_load(
    chapter_outline,
    entity_store=None,
    chapter_num: int = 0,
) -> dict:
    """
    评估章节的认知负荷。

    返回：
        {
            "active_characters": int,
            "active_threads": int,
            "new_nouns_estimate": int,
            "load_level": "low" | "medium" | "high",
            "warnings": list[str],
        }
    """
    warnings = []

    # 统计活跃角色数（从 core_events 和 hook 中提取提到的角色）
    text = " ".join(chapter_outline.core_events or [])
    text += " " + (chapter_outline.hook_start or "")
    text += " " + (chapter_outline.hook_end or "")
    text += " " + (chapter_outline.pleasure_point or "")

    active_chars = 0
    if entity_store:
        for name in entity_store.characters:
            if name in text:
                active_chars += 1
    else:
        # 粗估：core_events 数量 ≈ 活跃角色数
        active_chars = min(len(chapter_outline.core_events or []), 8)

    # 统计伏笔线
    active_threads = 0
    if entity_store:
        for thread in entity_store.plot_threads:
            if thread.status == "open" and thread.description[:10] in text:
                active_threads += 1

    # 新专有名词估计（粗略：core_events 中的首次出现名词）
    new_nouns_estimate = 0
    if entity_store:
        known_names = set(entity_store.characters.keys()) | {
            f.name for f in entity_store.factions.values()
        }
        words = text.replace("，", " ").replace("。", " ").split()
        for w in words:
            if len(w) >= 2 and w not in known_names:
                # 可能是新名词（粗略判断）
                new_nouns_estimate += 1
        new_nouns_estimate = min(new_nouns_estimate, 5)  # 上限

    # 评估负荷等级
    load_score = 0
    if active_chars > MAX_ACTIVE_CHARACTERS:
        load_score += 2
        warnings.append(
            f"角色过多：本章涉及{active_chars}个角色（建议≤{MAX_ACTIVE_CHARACTERS}），"
            f"读者可能混淆"
        )
    if active_threads > MAX_ACTIVE_THREADS:
        load_score += 1
        warnings.append(
            f"伏笔线过多：本章涉及{active_threads}条伏笔线（建议≤{MAX_ACTIVE_THREADS}），"
            f"建议简化焦点"
        )

    load_level = "low" if load_score == 0 else "medium" if load_score <= 2 else "high"

    return {
        "active_characters": active_chars,
        "active_threads": active_threads,
        "new_nouns_estimate": new_nouns_estimate,
        "load_level": load_level,
        "warnings": warnings,
    }


def get_load_context_for_writer(load_data: dict) -> str:
    """生成面向 Writer 的认知负荷控制指令"""
    if load_data["load_level"] == "low":
        return ""

    lines = ["【认知负荷控制】"]
    for w in load_data["warnings"]:
        lines.append(f"  ⚠ {w}")
    lines.append("→ 本章焦点角色最多3人（主角+2个关键角色）")
    lines.append("→ 新引入的概念/名词最多1个")
    lines.append("→ 本章必须自解释，不假设读者记得远期细节")

    return "\n".join(lines)
