"""
Agent 4 — 章节大纲师 ChapterOutliner
逐卷生成详细章节细纲：每章含开头钩子、核心事件、爽点、结尾钩子。

升级：继承 ThinkingSingleShotAgent，统一使用 AgentLoop 架构 + Extended Thinking。
"""

import logging
from core.llm_client import LLMClient
from models.novel import (
    WebNovelRequest, WorldSetting, CharacterProfile, AntagonistTier,
    VolumePlan, ChapterOutlineItem
)
from agents.base import ThinkingSingleShotAgent
from domain.disciplines import get_agent_guidance
from domain.pleasure_system import get_pleasure_guidance_for_outliner

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文章节规划师，精通用钩子和爽点控制读者留存。
你的任务是将卷规划细化为逐章大纲，确保每章都有明确的钩子和节奏。

章节设计铁律：
1. 每章开头必须兑现上一章的悬念，或直接进入新冲突（禁止冷场）
2. 每3-5章必须安排一个爽点释放（打脸/突破/揭秘），不能让读者空等
3. 每章结尾必须有钩子，让读者无法停下（悬念/意外/半截话）
4. 爽点前要有足够铺垫，积压越久，爆发越爽
5. 境界突破要安排在解决重大危机之后，不能无缘无故突破

【章节设计进阶要求】
6. 爽点执行：爽点不是"打赢就完"，必须有铺垫→积压→释放的完整过程
7. 钩子分类：每章结尾标注钩子类型（cliffhanger/revelation/threat_escalation/betrayal_hint/mystery_deepening/power_tease/countdown）
8. 场景节奏：每章标注节奏类型（action/buildup/revelation/aftermath/turning_point），避免连续同类型
9. 情感节拍：每章有明确的情感走向（如"紧张→绝望→反转→释然"）

【标题写作铁律】
10. 标题公式：信息量+悬念感+爽点暗示。禁止平淡标题（如"修炼日常""新的一天"）
11. 标题类型示例：action章用"XXX，杀！"，revelation章用"原来你是……"，buildup章用"暴风雨前的……"

【预期颠覆规则】
12. 每4-5次标准爽点后，安排1次"反套路"（subversion_type != none）：
    - escalation：爽点升级——读者以为打脸完了，结果还有更大的
    - twist：剧情反转——看似胜利实则是敌人的计划
    - deconstruct：解构套路——让主角意识到"变强"不是终点

【叙事视距规则】
13. narrative_distance 不能连续3章相同，建议：action章用close+medium，buildup章用medium+far，revelation章用close+far

【多视角规则】
14. pov 分配：protagonist 80% / antagonist 10% / love_interest 5% / side_character 5%
15. 反派视角章不超过连续1章，且必须紧跟主角章

【信息差张力】
16. dramatic_irony_active=true时，利用读者知道但角色不知道的真相制造焦虑感
17. 每5-8章至少1次信息差章节

【金句种子】
18. golden_sentence_seed：本章需要1句让读者截图的话"""

TOOL = {
    "name": "outline_volume_chapters",
    "description": "生成本卷逐章细纲，每章含钩子、核心事件、爽点",
    "input_schema": {
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_num": {"type": "integer"},
                        "volume_chapter_num": {"type": "integer"},
                        "title": {"type": "string"},
                        "hook_start": {"type": "string"},
                        "core_events": {"type": "array", "items": {"type": "string"}},
                        "pleasure_point": {"type": "string"},
                        "hook_end": {"type": "string"},
                        "protagonist_power": {"type": "string"},
                        "thematic_element": {"type": "string", "description": "本章主题元素（可选）"},
                        "knowledge_seed": {"type": "string", "description": "本章融入的知识点（可选）"},
                        "hook_type": {"type": "string", "description": "钩子类型：cliffhanger/revelation/threat_escalation/betrayal_hint/mystery_deepening/power_tease/countdown（可选）"},
                        "pacing_type": {"type": "string", "description": "章节节奏类型：action/buildup/revelation/aftermath/turning_point（可选）"},
                        "emotional_beat": {"type": "string", "description": "章内情感节拍（如紧张→绝望→反转→释然）（可选）"},
                        "narrative_distance": {"type": "string", "description": "叙事视距：close/medium/far，默认medium（可选）"},
                        "golden_sentence_seed": {"type": "string", "description": "金句种子：本章需要一句让读者截图的话（可选）"},
                        "subversion_type": {"type": "string", "description": "预期颠覆类型：none/escalation/twist/deconstruct（可选）"},
                        "pov": {"type": "string", "description": "视角：protagonist/love_interest/antagonist/side_character（可选）"},
                        "dramatic_irony_active": {"type": "boolean", "description": "是否启用信息差张力（可选）"},
                    },
                    "required": ["chapter_num", "volume_chapter_num", "title", "hook_start", "core_events", "hook_end", "protagonist_power"],
                },
            },
        },
        "required": ["chapters"],
    },
}


class ChapterOutlinerAgent(ThinkingSingleShotAgent):
    agent_name = "chapter_outliner"
    max_iterations = 3
    max_tokens = 12000
    thinking_budget = 8000
    temperature = 0.8

    def build_system_prompt(self, context: dict) -> str:
        base = SYSTEM_PROMPT
        disciplines = context.get("disciplines", [])
        if disciplines:
            guidance = get_agent_guidance(disciplines, "chapter_outliner")
            if guidance:
                base += f"\n\n【学科深度要求】\n本书融合以下学科视角，请在章节大纲中自然融入：\n\n{guidance}"
        return base

    def get_tool(self) -> tuple[dict, str]:
        return TOOL, "outline_volume_chapters"

    def build_prompt(self, context: dict) -> str:
        request: WebNovelRequest = context["request"]
        world: WorldSetting = context["world"]
        characters: list[CharacterProfile] = context["characters"]
        antagonists: list[AntagonistTier] = context["antagonists"]
        volume: VolumePlan = context["volume"]
        prev_volume_ending: str = context.get("prev_volume_ending", "")
        global_chapter_start: int = context["global_chapter_start"]

        antagonist = next(
            (a for a in antagonists if a.name == volume.antagonist_name),
            antagonists[0] if antagonists else None
        )
        antag_info = f"{antagonist.name}（{antagonist.current_power}）- {antagonist.motive}" if antagonist else "无明确反派"

        chapter_nums = list(range(global_chapter_start, global_chapter_start + request.chapters_per_volume))

        pleasure_hint = {
            "逆袭打脸": "每3章一次小打脸，卷高潮有1次大型打脸场面",
            "升级爽": "每5章一次境界突破或实力大幅提升",
            "系统面板": "每2-3章一次系统奖励或任务完成",
            "装逼收徒": "每4章一次低调被人轻视，高潮来一次完整揭露",
            "复仇": "每卷对仇人造成一次实质性打击，积累复仇进程",
            "种田积累": "每3章一次积累成果展示，让读者感受到进步",
        }.get(request.core_pleasure, "每5章一次明显的爽点释放")

        discipline_instruction = ""
        if context.get("disciplines"):
            discipline_instruction = (
                "\n- 每章请填写 thematic_element（本章主题元素，20字）"
                "\n- 每3-5章填写 knowledge_seed（本章融入的知识点，30字）"
            )

        depth_instruction = (
            "\n- 每章请填写 hook_type（钩子类型，从以下选择：cliffhanger/revelation/threat_escalation/betrayal_hint/mystery_deepening/power_tease/countdown）"
            "\n- 每章请填写 pacing_type（节奏类型：action/buildup/revelation/aftermath/turning_point），避免连续2章同类型"
            "\n- 每章请填写 emotional_beat（情感节拍，如'紧张→绝望→反转→释然'，20字）"
            "\n- 每章请填写 narrative_distance（叙事视距：close/medium/far，不能连续3章相同）"
            "\n- 每4-5章填写 subversion_type（预期颠覆：none/escalation/twist/deconstruct）"
            "\n- 每章请填写 pov（视角：protagonist/love_interest/antagonist/side_character）"
            "\n- 每5-8章设置 dramatic_irony_active=true"
            "\n- 每章填写 golden_sentence_seed（金句种子，20字以内）"
        )

        # 爽点释放公式指导
        pleasure_guidance = get_pleasure_guidance_for_outliner(request.core_pleasure)

        # 本卷主题聚焦信息
        thematic_info = ""
        if volume.thematic_focus:
            thematic_info = f"\n本卷主题聚焦：{volume.thematic_focus}"
        if volume.ethical_dilemma:
            thematic_info += f"\n本卷道德困境：{volume.ethical_dilemma}"

        return f"""当前卷：第{volume.volume_num}卷《{volume.title}》
本卷主题：{volume.theme}{thematic_info}
本卷主要反派：{antag_info}
本卷大爽点：{volume.core_pleasure_point}
本卷结尾钩子：{volume.ending_hook}
主角境界：{volume.protagonist_power_start} → {volume.protagonist_power_end}

上一卷结尾状态：{prev_volume_ending or "故事开始，主角处于起点状态"}

核心爽点类型：{request.core_pleasure}
爽点分布建议：{pleasure_hint}

本卷章节序号：第{chapter_nums[0]}章 到 第{chapter_nums[-1]}章（卷内第1章到第{request.chapters_per_volume}章）

请为本卷生成逐章细纲，严格遵守以下要求：
- chapters 恰好 {request.chapters_per_volume} 个
- chapter_num 从 {chapter_nums[0]} 到 {chapter_nums[-1]}，连续
- volume_chapter_num 从 1 到 {request.chapters_per_volume}，连续
- protagonist_power 随境界突破更新（本卷结束时达到 "{volume.protagonist_power_end}"）
- 爽点章节（pleasure_point非空）控制在 {max(2, request.chapters_per_volume // 4)} - {request.chapters_per_volume // 3} 章
- 最后一章的 hook_end 要体现本卷结尾钩子：{volume.ending_hook}
- hook_start 和 hook_end 要写得生动，让人有画面感{discipline_instruction}{depth_instruction}

{pleasure_guidance}"""

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        request: WebNovelRequest = context["request"]
        volume: VolumePlan = context["volume"]
        global_chapter_start: int = context["global_chapter_start"]
        world: WorldSetting = context["world"]

        issues = []
        chapters = result.get("chapters", [])
        valid_levels = {lv.name for lv in world.power_system.levels}

        if len(chapters) != request.chapters_per_volume:
            issues.append(f"章节数量应为{request.chapters_per_volume}，实际{len(chapters)}")

        expected_global = list(range(global_chapter_start, global_chapter_start + request.chapters_per_volume))
        actual_global = [c.get("chapter_num") for c in chapters]
        if actual_global != expected_global:
            issues.append(f"chapter_num 应为 {expected_global}，实际 {actual_global}")

        for c in chapters:
            if c.get("protagonist_power") and c["protagonist_power"] not in valid_levels:
                issues.append(f"第{c.get('chapter_num')}章 protagonist_power '{c['protagonist_power']}' 不在力量体系中")

        if issues:
            return False, "\n".join(f"- {i}" for i in issues)
        return True, ""

    def parse_result(self, result: dict, context: dict) -> list[ChapterOutlineItem]:
        return [
            ChapterOutlineItem(**{k: v for k, v in c.items() if k in ChapterOutlineItem.model_fields})
            for c in result["chapters"]
        ]


# ── 公开接口（保持向后兼容） ─────────────────────────────────────────────────

async def outline_volume(
    client: LLMClient,
    request: WebNovelRequest,
    world: WorldSetting,
    characters: list[CharacterProfile],
    antagonists: list[AntagonistTier],
    volume: VolumePlan,
    prev_volume_ending: str,
    global_chapter_start: int,
) -> list[ChapterOutlineItem]:
    """
    为单卷生成章节细纲。
    thinking_text 附加到第一个 chapter 的 _thinking_text 属性。
    """
    agent = ChapterOutlinerAgent()
    context = {
        "request": request,
        "world": world,
        "characters": characters,
        "antagonists": antagonists,
        "volume": volume,
        "prev_volume_ending": prev_volume_ending,
        "global_chapter_start": global_chapter_start,
        "disciplines": request.disciplines,
    }
    chapters = await agent.run(client, context)

    # 从 context 提取 thinking_text 并附加到第一个 chapter
    thinking_text = context.get("_thinking_text", "")
    if thinking_text and chapters:
        chapters[0]._thinking_text = thinking_text  # type: ignore

    return chapters
