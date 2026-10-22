"""
Agent 3 — 剧情规划师 PlotPlanner
根据世界观和人物设定，规划全书里程碑事件和分卷结构。

升级：继承 ThinkingSingleShotAgent，统一使用 AgentLoop 架构 + Extended Thinking。
"""

import logging
from core.llm_client import LLMClient
from models.novel import (
    WebNovelRequest, WorldSetting, CharacterProfile, AntagonistTier,
    PlotFramework, Milestone, VolumePlan
)
from agents.base import ThinkingSingleShotAgent
from domain.disciplines import get_agent_guidance

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文剧情规划师，精通网络小说的卷结构和节奏设计。
你的任务是规划全书的里程碑事件和分卷结构，确保每卷都有独立的爽点高潮。

核心原则：
1. 每卷必须有完整的"压迫→成长→爆发"弧线，读者不会空手而归
2. 里程碑事件要改变主角命运格局，不是小事件
3. 爽点分布要考虑节奏：大爽点之前必须有足够铺垫，读者等得越久爽得越狠
4. 每卷结尾必须有钩子，引出更大的威胁，让读者放不下书
5. 主角成长轨迹要合理：起点低→过程艰辛→结果酣畅

【剧情深度要求】
6. 节奏曲线：每卷遵循"前30%建立冲突→中40%积压压力→后20%爆发释放→尾10%新威胁"的节奏
7. 伏笔系统：每卷至少埋2条伏笔种子，至少兑现1条前卷伏笔（第1卷除外）
8. 转折分类：每个milestone标注转折类型（反转/升级/牺牲/揭露/背叛），不要千篇一律
9. 情感弧线：每卷主角有独立的情感变化（不只是实力变化），写出来

【故事阶段意识】
10. 全书分四大阶段：起源期(origin)→崛起期(rise)→危机期(crisis)→超越期(transcendence)
11. 起源期（前20%）：读者最关心"主角是谁"，聚焦个人成长
12. 崛起期（20-50%）：读者最关心"主角能走多远"，聚焦势力扩张
13. 危机期（50-80%）：读者最关心"主角能否撑过去"，聚焦世界级威胁
14. 超越期（后20%）：读者最关心"这一切意味着什么"，聚焦主题升华

【名场面规划】
15. 每卷至少规划1个"名场面"（iconic_scene）——那种让读者截图发朋友圈的画面
16. 名场面要有视觉冲击力：对比、反差、仪式感"""

TOOL = {
    "name": "plan_plot",
    "description": "规划全书剧情骨架：标题、里程碑事件、分卷结构",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "plot_framework": {
                "type": "object",
                "properties": {
                    "ultimate_goal": {"type": "string"},
                    "milestones": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "volume": {"type": "integer"},
                                "impact": {"type": "string"},
                                "turn_type": {"type": "string", "description": "转折类型：反转/升级/牺牲/揭露/背叛（可选）"},
                                "emotional_impact": {"type": "string", "description": "情感冲击描述（可选）"},
                            },
                            "required": ["index", "title", "description", "volume", "impact"],
                        },
                    },
                    "global_foreshadowing": {"type": "array", "items": {"type": "string"}},
                    "thematic_arcs": {"type": "array", "items": {"type": "string"}, "description": "跨卷主题弧线（可选）"},
                    "core_dilemmas": {"type": "array", "items": {"type": "string"}, "description": "全书核心困境（可选）"},
                },
                "required": ["ultimate_goal", "milestones", "global_foreshadowing"],
            },
            "volumes": {
                "type": "array",
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
                        "foreshadowing_seeds": {"type": "array", "items": {"type": "string"}, "description": "本卷埋下的伏笔（2-3条）（可选）"},
                        "foreshadowing_payoffs": {"type": "array", "items": {"type": "string"}, "description": "本卷兑现的前卷伏笔（可选）"},
                        "pacing_structure": {"type": "string", "description": "本卷节奏分布（如前30%铺垫→中40%积压→后20%爆发→尾10%悬念）（可选）"},
                        "protagonist_emotional_arc": {"type": "string", "description": "主角情绪变化弧线（如自信→挫败→觉醒→坚定）（可选）"},
                        "story_phase": {"type": "string", "description": "故事阶段：origin/rise/crisis/transcendence（可选）"},
                        "intensity_level": {"type": "string", "description": "强度等级：high/medium/low（可选）"},
                        "iconic_scene": {"type": "string", "description": "本卷名场面（让读者截图分享的画面）（可选）"},
                    },
                    "required": ["volume_num", "title", "theme", "antagonist_name", "core_pleasure_point", "protagonist_power_start", "protagonist_power_end", "ending_hook"],
                },
            },
        },
        "required": ["title", "plot_framework", "volumes"],
    },
}


def _chars_summary(characters: list[CharacterProfile], antagonists: list[AntagonistTier]) -> str:
    lines = ["主要人物："]
    for c in characters:
        lines.append(f"  {c.name}（{c.role}）- 起始境界：{c.current_power}")
    lines.append("反派梯队：")
    for a in sorted(antagonists, key=lambda x: x.tier):
        lines.append(f"  第{a.tier}层 {a.name}（{a.current_power}）- 预计第{a.defeat_volume}卷解决")
    return "\n".join(lines)


class PlotPlannerAgent(ThinkingSingleShotAgent):
    agent_name = "plot_planner"
    max_iterations = 3
    max_tokens = 16000
    thinking_budget = 10000
    temperature = 0.8

    def build_system_prompt(self, context: dict) -> str:
        base = SYSTEM_PROMPT
        disciplines = context.get("disciplines", [])
        if disciplines:
            guidance = get_agent_guidance(disciplines, "plot_planner")
            if guidance:
                base += f"\n\n【学科深度要求】\n本书融合以下学科视角，请在剧情规划中自然融入：\n\n{guidance}"
        return base

    def get_tool(self) -> tuple[dict, str]:
        return TOOL, "plan_plot"

    def build_prompt(self, context: dict) -> str:
        request: WebNovelRequest = context["request"]
        world: WorldSetting = context["world"]
        characters: list[CharacterProfile] = context["characters"]
        antagonists: list[AntagonistTier] = context["antagonists"]

        chars_info = _chars_summary(characters, antagonists)
        levels = world.power_system.levels

        volume_structure = "\n".join([
            f"  第{i+1}卷（{request.chapters_per_volume}章）"
            for i in range(request.num_volumes)
        ])

        discipline_instruction = ""
        if context.get("disciplines"):
            discipline_instruction = (
                "\n- 请填写 thematic_arcs（跨卷主题弧线，2-3条）"
                "\n- 请填写 core_dilemmas（全书核心困境，2-3条）"
                "\n- 每卷请填写 thematic_focus（本卷主题聚焦，30字）和 ethical_dilemma（本卷道德困境，30字）"
            )

        depth_instruction = (
            "\n- 每个 milestone 请填写 turn_type（转折类型：反转/升级/牺牲/揭露/背叛）和 emotional_impact（情感冲击，20字）"
            "\n- 每卷请填写 foreshadowing_seeds（本卷埋下的伏笔，2-3条）"
            "\n- 第2卷起请填写 foreshadowing_payoffs（本卷兑现的前卷伏笔）"
            "\n- 每卷请填写 pacing_structure（节奏分布，30字）和 protagonist_emotional_arc（主角情绪弧线，30字）"
            "\n- 每卷请填写 story_phase（故事阶段：origin/rise/crisis/transcendence）"
            "\n- 每卷请填写 intensity_level（强度等级：high/medium/low，连续2高强度卷后建议1低强度卷）"
            "\n- 每卷请填写 iconic_scene（名场面：让读者截图分享的画面，30字）"
        )

        return f"""类型：{request.genre}
核心爽点：{request.core_pleasure}
世界观：{world.description}

{chars_info}

力量体系（从低到高）：{" → ".join(lv.name for lv in levels)}

计划结构：
{volume_structure}

请规划全书剧情框架，严格遵守以下要求：
- title 要有网文感，避免过于文艺，不超过10字
- milestones 恰好 {request.num_volumes + 2} 个，覆盖全书关键转折
- volumes 恰好 {request.num_volumes} 个
- 每卷的 protagonist_power_start/end 必须是力量体系中的真实境界名
- 每卷反派名必须来自已设计的反派梯队
- core_pleasure_point 要具体到场景（如"李逸当众打脸张三丰，令在场千名弟子震撼"），不能泛泛而谈
- 最后一卷 ending_hook 可以是圆满收尾的描述{discipline_instruction}{depth_instruction}"""

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        request: WebNovelRequest = context["request"]
        world: WorldSetting = context["world"]
        antagonists: list[AntagonistTier] = context["antagonists"]

        issues = []
        valid_levels = {lv.name for lv in world.power_system.levels}
        valid_antag_names = {a.name for a in antagonists}

        volumes = result.get("volumes", [])
        if len(volumes) != request.num_volumes:
            issues.append(f"卷数应为{request.num_volumes}，实际{len(volumes)}")

        for v in volumes:
            if v.get("protagonist_power_start") and v["protagonist_power_start"] not in valid_levels:
                issues.append(f"第{v.get('volume_num')}卷 protagonist_power_start '{v['protagonist_power_start']}' 不在力量体系中")
            if v.get("protagonist_power_end") and v["protagonist_power_end"] not in valid_levels:
                issues.append(f"第{v.get('volume_num')}卷 protagonist_power_end '{v['protagonist_power_end']}' 不在力量体系中")
            if v.get("antagonist_name") and v["antagonist_name"] not in valid_antag_names:
                issues.append(f"第{v.get('volume_num')}卷反派 '{v['antagonist_name']}' 不在已设计的反派梯队中")

        milestones = result.get("plot_framework", {}).get("milestones", [])
        expected_milestones = request.num_volumes + 2
        if len(milestones) != expected_milestones:
            issues.append(f"milestones 应为{expected_milestones}个，实际{len(milestones)}")

        if issues:
            return False, "\n".join(f"- {i}" for i in issues)
        return True, ""

    def parse_result(self, result: dict, context: dict) -> tuple[str, PlotFramework, list[VolumePlan]]:
        pf_data = result["plot_framework"]
        milestones = [
            Milestone(**{k: v for k, v in m.items() if k in Milestone.model_fields})
            for m in pf_data["milestones"]
        ]
        plot_framework = PlotFramework(
            ultimate_goal=pf_data["ultimate_goal"],
            milestones=milestones,
            global_foreshadowing=pf_data.get("global_foreshadowing", []),
            thematic_arcs=pf_data.get("thematic_arcs", []),
            core_dilemmas=pf_data.get("core_dilemmas", []),
        )
        volumes = [
            VolumePlan(**{k: v for k, v in vd.items() if k in VolumePlan.model_fields})
            for vd in result["volumes"]
        ]
        return result["title"], plot_framework, volumes


# ── 公开接口（保持向后兼容） ─────────────────────────────────────────────────

async def plan_plot(
    client: LLMClient,
    request: WebNovelRequest,
    world: WorldSetting,
    characters: list[CharacterProfile],
    antagonists: list[AntagonistTier],
) -> tuple[str, PlotFramework, list[VolumePlan]]:
    """
    返回 (title, plot_framework, volumes)。
    thinking_text 附加到 plot_framework._thinking_text。
    """
    agent = PlotPlannerAgent()
    context = {
        "request": request,
        "world": world,
        "characters": characters,
        "antagonists": antagonists,
        "disciplines": request.disciplines,
    }
    title, plot_framework, volumes = await agent.run(client, context)

    # 从 context 提取 thinking_text 并附加到 plot_framework
    thinking_text = context.get("_thinking_text", "")
    if thinking_text:
        plot_framework._thinking_text = thinking_text

    return title, plot_framework, volumes
