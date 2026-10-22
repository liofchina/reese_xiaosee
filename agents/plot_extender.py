"""
Agent 7 — 故事扩展师 PlotExtender（无限模式专用）
在已有故事基础上续写规划，不重建全书框架，只生成后续若干卷。

升级：继承 SingleShotAgent，统一使用 AgentLoop 架构。
"""

import logging
from core.llm_client import LLMClient
from models.novel import (
    WebNovelRequest, WorldSetting, CharacterProfile, AntagonistTier,
    VolumePlan
)
from agents.base import SingleShotAgent
from domain.disciplines import get_agent_guidance
from domain.pleasure_system import get_story_phase, get_story_phase_guidance, WORLD_EXPANSION_RULES

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文续写规划师，擅长在已有故事基础上无缝续写。
你的任务是为正在连载的网文规划接下来几卷的剧情，要求：

1. 严格衔接上卷结尾——新卷开头必须兑现上卷结尾钩子
2. 力量体系连贯——主角境界从上卷结束时的境界继续提升，不能回退
3. 反派梯度递增——新反派要比主角当前境界高2-3个大境界
4. 爽点新鲜感——不要重复前几卷已用过的爽点形式，要有新变化
5. 伏笔延续——之前埋下的伏笔要有所兑现或推进
6. 读者黏性——每卷结尾必须制造更大的危机，让读者停不下来

【故事深化维度（不要只是"反派变强"）】
7. 主题升级：前卷是"如何变强"→新卷是"为什么变强"→更后是"变强后做什么"
8. 世界揭露：新卷至少揭露一个前卷未知的世界真相
9. 人物复杂度：配角不再是简单的"朋友/敌人"，关系开始多面化
10. 读者期望升级：满足当前期望的同时，制造更大的期望（格局要越来越大）

【故事阶段意识】
11. 根据当前故事阶段（origin/rise/crisis/transcendence），调整剧情重心
12. origin阶段聚焦个人成长，rise阶段聚焦势力扩张，crisis阶段聚焦世界级威胁，transcendence聚焦主题升华"""

TOOL = {
    "name": "extend_plot",
    "description": "在已有故事基础上规划接下来几卷，衔接当前剧情状态",
    "input_schema": {
        "type": "object",
        "properties": {
            "extension_volumes": {
                "type": "array",
                "description": "新规划的卷列表，volume_num 从当前最后一卷+1开始",
                "items": {
                    "type": "object",
                    "properties": {
                        "volume_num": {"type": "integer"},
                        "title": {"type": "string"},
                        "theme": {"type": "string"},
                        "antagonist_name": {"type": "string"},
                        "core_pleasure_point": {"type": "string"},
                        "protagonist_power_start": {"type": "string"},
                        "protagonist_power_end": {"type": "string"},
                        "ending_hook": {"type": "string"},
                        "thematic_focus": {"type": "string", "description": "本卷主题聚焦（可选）"},
                        "ethical_dilemma": {"type": "string", "description": "本卷道德困境（可选）"},
                        "story_phase": {"type": "string", "description": "故事阶段：origin/rise/crisis/transcendence（可选）"},
                        "iconic_scene": {"type": "string", "description": "本卷名场面（可选）"},
                    },
                    "required": [
                        "volume_num", "title", "theme", "antagonist_name",
                        "core_pleasure_point", "protagonist_power_start",
                        "protagonist_power_end", "ending_hook",
                    ],
                },
            },
        },
        "required": ["extension_volumes"],
    },
}


class PlotExtenderAgent(SingleShotAgent):
    agent_name = "plot_extender"
    max_iterations = 3
    max_tokens = 4000
    temperature = 0.85

    def build_system_prompt(self, context: dict) -> str:
        base = SYSTEM_PROMPT

        # 故事阶段指导
        existing_volumes = context.get("existing_volumes", [])
        total_vols_estimate = len(existing_volumes) + context.get("extend_by", 3)
        current_vol = len(existing_volumes) + 1
        phase = get_story_phase(current_vol, total_vols_estimate * 2)
        phase_guidance = get_story_phase_guidance(phase)
        if phase_guidance:
            base += f"\n\n【当前故事阶段】\n{phase_guidance}"

        # 世界扩展节奏
        base += f"""

【世界扩展节奏控制】
- 每{WORLD_EXPANSION_RULES['new_region_interval']}卷才可引入1个全新地理区域
- 同时活跃的势力不超过{WORLD_EXPANSION_RULES['max_active_factions']}个
- 同时活跃的区域不超过{WORLD_EXPANSION_RULES['max_active_regions']}个"""

        disciplines = context.get("disciplines", [])
        if disciplines:
            guidance = get_agent_guidance(disciplines, "plot_extender")
            if guidance:
                base += f"\n\n【学科深度要求】\n本书融合以下学科视角，请在续写规划中自然融入：\n\n{guidance}"
        return base

    def get_tool(self) -> tuple[dict, str]:
        return TOOL, "extend_plot"

    def build_prompt(self, context: dict) -> str:
        request: WebNovelRequest = context["request"]
        world: WorldSetting = context["world"]
        characters: list[CharacterProfile] = context["characters"]
        antagonists: list[AntagonistTier] = context["antagonists"]
        existing_volumes: list[VolumePlan] = context["existing_volumes"]
        extend_by: int = context["extend_by"]
        story_so_far: str = context.get("story_so_far", "")
        compressed_state: str = context.get("compressed_state", "")

        last_vol = existing_volumes[-1]
        levels = world.power_system.levels
        level_names = " → ".join(lv.name for lv in levels)

        defeated = [a for a in antagonists if a.defeat_volume <= len(existing_volumes)]
        remaining = [a for a in antagonists if a.defeat_volume > len(existing_volumes)]
        # 扩大查重窗口到最近 10 卷，防止长篇爽点重复
        dedup_window = existing_volumes[-10:] if len(existing_volumes) >= 10 else existing_volumes
        used_pleasures = list({v.core_pleasure_point[:10] for v in dedup_window})

        recent_vols = existing_volumes[-5:]
        recent_summary = "\n".join(
            f"  第{v.volume_num}卷《{v.title}》：{v.theme}，主角{v.protagonist_power_start}→{v.protagonist_power_end}"
            for v in recent_vols
        )

        # 长程上下文：前期 + 中点 + 近期卷摘要
        long_range_context = ""
        if story_so_far:
            long_range_context = f"\n【全局故事脉络】\n{story_so_far}\n"
        if compressed_state:
            long_range_context += f"\n【世界当前状态】\n{compressed_state}\n"

        new_vol_start = last_vol.volume_num + 1
        new_vol_end = new_vol_start + extend_by - 1

        return f"""小说信息：
类型：{request.genre}，核心爽点：{request.core_pleasure}
主角：{request.protagonist_name}

力量体系（从低到高）：{level_names}
{long_range_context}
当前故事状态：
- 已完成：第{last_vol.volume_num}卷，共{sum(1 for _ in existing_volumes)}卷
- 主角当前境界：{last_vol.protagonist_power_end}
- 上卷结尾钩子（必须在新卷开头兑现）：{last_vol.ending_hook}

已解决的反派：{", ".join(a.name for a in defeated) or "无"}
尚未解决的反派：{", ".join(f"{a.name}（{a.current_power}）" for a in remaining) or "无，需要创造新反派"}

最近5卷概况：
{recent_summary}

最近用过的爽点形式（请避免重复）：{", ".join(used_pleasures)}

请为第{new_vol_start}卷到第{new_vol_end}卷规划剧情，严格遵守：
- 共 {extend_by} 卷，volume_num 从 {new_vol_start} 到 {new_vol_end}
- protagonist_power_start 必须等于上卷的 protagonist_power_end："{last_vol.protagonist_power_end}"
- 每卷提升1-2个大境界，境界名必须来自力量体系
- 新反派境界必须比主角当时境界高2-3个大境界
- 最后一卷 ending_hook 要比上卷的更有冲击力
- core_pleasure_point 要具体到场景，不能泛泛而谈"""

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        extend_by: int = context["extend_by"]
        volumes = result.get("extension_volumes", [])
        if len(volumes) != extend_by:
            return False, f"应生成{extend_by}卷，实际{len(volumes)}卷"
        return True, ""

    def parse_result(self, result: dict, context: dict) -> list[VolumePlan]:
        return [
            VolumePlan(**{k: v for k, v in vd.items() if k in VolumePlan.model_fields})
            for vd in result["extension_volumes"]
        ]


# ── 公开接口（保持向后兼容） ─────────────────────────────────────────────────

async def extend_plot(
    client: LLMClient,
    request: WebNovelRequest,
    world: WorldSetting,
    characters: list[CharacterProfile],
    antagonists: list[AntagonistTier],
    existing_volumes: list[VolumePlan],
    extend_by: int = 3,
    story_so_far: str = "",
    compressed_state: str = "",
) -> list[VolumePlan]:
    """返回新增的 VolumePlan 列表"""
    agent = PlotExtenderAgent()
    context = {
        "request": request,
        "world": world,
        "characters": characters,
        "antagonists": antagonists,
        "existing_volumes": existing_volumes,
        "extend_by": extend_by,
        "disciplines": request.disciplines,
        "story_so_far": story_so_far,
        "compressed_state": compressed_state,
    }
    return await agent.run(client, context)
