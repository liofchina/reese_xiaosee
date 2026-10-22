"""
Agent 2 — 角色设计师 CharacterDesigner
根据类型、爽点和世界设定，设计完整人物档案与反派梯队。

升级：继承 AgentLoop，支持自校验（验证力量等级引用、反派梯队覆盖）。
"""

import logging
from core.llm_client import LLMClient
from models.novel import (
    WebNovelRequest, WorldSetting, CharacterProfile, AntagonistTier
)
from agents.base import AgentLoop
from domain.disciplines import get_agent_guidance

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文人物设计师，深谙网络小说的人物塑造之道。
你的任务是根据类型、爽点和世界设定，设计有鲜明特色、服务于爽点的人物体系。

要求：
1. 主角起点足够低（废材/落魄/普通），才能形成强烈的前后反差
2. 每个角色说话风格必须明显不同，读者不看名字也能辨认
3. 反派梯队层层递进，每层比主角当时强2-3个大境界，既有压迫感又能被超越
4. 感情线角色设计要有独立性格，不只是主角的附属品
5. 所有配角都要服务于核心爽点，不做无意义工具人

【角色深度要求】
6. 反派尊严：每个反派必须有读者可能尊重的一面——坚守的底线、值得同情的过去、致命但可理解的缺陷
7. 角色秘密：至少2个角色有隐藏目标或秘密身份，为后续剧情转折埋种
8. 关系张力：每个角色与主角的关系不是单向的——有潜在冲突点、利益交叉
9. 外观标识：每个角色有1个标志性视觉特征（读者脑中能浮现画面）
10. 成长轨迹：主角和主要配角需有明确的"初期→中期→后期"变化路径

【角色 Agent 化要求】
11. 核心信念：每个主要角色必须有2-3条核心信念/底线（如"绝不背叛同伴"），这是角色的"灵魂"
12. 行为禁忌：每个角色写出2-3条绝不会做的事，用于后续一致性校验
13. 目标栈：每个角色的初始目标（当前目标 + 长期目标），目标可以冲突
14. 典型台词：每个角色写2-3句典型台词示例，体现其独特的说话风格

你可以使用 validate_power_references 和 validate_antagonist_tiers 工具来检查设计。
确认无误后，调用 submit_result 提交最终结果。

【对话差异化设计】
15. 对话句长：每个角色设定对话句长风格（极短/中等/长句型），确保差异化
16. 口头禅：至少主角和2个配角要有口头禅（1-2个词），增加辨识度
17. 对话禁区：每个角色写出绝不会说的话/表达方式
18. 幽默风格：如果角色有幽默元素，指定风格（毒舌/天然呆/冷幽默）

【反派立体化设计】
19. 内心矛盾：每个重要反派必须有内心挣扎——他不是纯粹的恶，他有两难选择
20. 读者同情：每个反派有一个"如果我是他，我可能也会这样做"的同情锚点
21. 堕落轨迹：终极反派要有清晰的"曾经也是好人→逐步走向深渊"的堕落弧线"""

# ── 工具定义 ────────────────────────────────────────────────────────────────

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "提交最终的人物设计结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["protagonist", "love_interest", "sidekick", "mentor"],
                        },
                        "current_power": {"type": "string"},
                        "background": {"type": "string"},
                        "golden_finger": {"type": "string"},
                        "personality": {"type": "string"},
                        "motivation": {"type": "string"},
                        "speech_pattern": {"type": "string"},
                        "arc": {"type": "string"},
                        "psychological_profile": {"type": "string", "description": "核心心理特征/创伤/防御机制（可选）"},
                        "intellectual_stance": {"type": "string", "description": "信仰/哲学/知识立场（可选）"},
                        "appearance": {"type": "string", "description": "标志性外观特征（可选）"},
                        "signature_move": {"type": "string", "description": "标志性招式或习惯动作（可选）"},
                        "hidden_agenda": {"type": "string", "description": "隐藏目标/秘密（可选）"},
                        "relationship_notes": {"type": "string", "description": "与其他角色的关系张力（可选）"},
                        "growth_trajectory": {"type": "string", "description": "成长轨迹：初期→中期→后期（可选）"},
                        "core_beliefs": {"type": "array", "items": {"type": "string"}, "description": "核心信念/价值观/底线（2-3条）"},
                        "prohibitions": {"type": "array", "items": {"type": "string"}, "description": "角色绝不会做的事（2-3条）"},
                        "initial_goals": {"type": "array", "items": {"type": "string"}, "description": "初始目标栈：当前→长期"},
                        "speech_examples": {"type": "array", "items": {"type": "string"}, "description": "2-3句典型对话示例"},
                        "humor_style": {"type": "string", "description": "幽默风格：毒舌/天然呆/冷幽默/无（可选）"},
                        "dialogue_sentence_length": {"type": "string", "description": "对话句长：极短(3-8字)/中等(10-20字)/长句型(20+字)（可选）"},
                        "dialogue_tone": {"type": "string", "description": "对话语气：嘲讽/温和/粗犷/文绉绉/冷淡/阴柔（可选）"},
                        "dialogue_verbal_tics": {"type": "array", "items": {"type": "string"}, "description": "口头禅（1-2个词）（可选）"},
                        "dialogue_forbidden": {"type": "array", "items": {"type": "string"}, "description": "角色绝不会说的话（可选）"},
                    },
                    "required": ["name", "role", "current_power", "background", "personality", "motivation", "speech_pattern", "arc"],
                },
            },
            "antagonists": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tier": {"type": "integer"},
                        "name": {"type": "string"},
                        "current_power": {"type": "string"},
                        "motive": {"type": "string"},
                        "weakness": {"type": "string"},
                        "defeat_volume": {"type": "integer"},
                        "heroic_code": {"type": "string", "description": "反派的坚守底线（可选）"},
                        "tragic_flaw": {"type": "string", "description": "致命缺陷（可选）"},
                        "sympathetic_element": {"type": "string", "description": "读者可同情的地方（可选）"},
                        "internal_conflict": {"type": "string", "description": "反派内心矛盾/挣扎（可选）"},
                        "reader_sympathy_hook": {"type": "string", "description": "读者同情锚点（可选）"},
                        "escalation_arc": {"type": "array", "items": {"type": "string"}, "description": "反派升级路线（可选）"},
                        "fall_from_grace": {"type": "string", "description": "反派堕落方式（可选）"},
                    },
                    "required": ["tier", "name", "current_power", "motive", "weakness", "defeat_volume"],
                },
            },
        },
        "required": ["characters", "antagonists"],
    },
}

VALIDATE_POWER_REFS_TOOL = {
    "name": "validate_power_references",
    "description": "验证所有角色的 current_power 是否匹配世界观力量体系中的等级名",
    "input_schema": {
        "type": "object",
        "properties": {
            "character_powers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current_power": {"type": "string"},
                    },
                    "required": ["name", "current_power"],
                },
            },
        },
        "required": ["character_powers"],
    },
}

VALIDATE_ANTAG_TIERS_TOOL = {
    "name": "validate_antagonist_tiers",
    "description": "验证反派梯队：检查tier数量、defeat_volume覆盖是否完整",
    "input_schema": {
        "type": "object",
        "properties": {
            "antagonists": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tier": {"type": "integer"},
                        "name": {"type": "string"},
                        "defeat_volume": {"type": "integer"},
                    },
                    "required": ["tier", "name", "defeat_volume"],
                },
            },
        },
        "required": ["antagonists"],
    },
}


# ── 验证 handler（纯 Python） ─────────────────────────────────────────────

def _make_power_refs_handler(world: WorldSetting):
    """创建闭包，捕获 world 中的合法等级名"""
    valid_names = {lv.name for lv in world.power_system.levels}

    def handler(input_data: dict) -> dict:
        issues = []
        for cp in input_data.get("character_powers", []):
            if cp["current_power"] not in valid_names:
                issues.append(
                    f"{cp['name']} 的境界 '{cp['current_power']}' 不在力量体系中。"
                    f"合法等级：{', '.join(sorted(valid_names))}"
                )
        return {"valid": len(issues) == 0, "issues": issues}

    return handler


def _make_antag_tiers_handler(num_volumes: int):
    """创建闭包，捕获 num_volumes"""
    def handler(input_data: dict) -> dict:
        issues = []
        antags = input_data.get("antagonists", [])

        if len(antags) != num_volumes:
            issues.append(f"反派数量应为{num_volumes}个（每卷一个），实际{len(antags)}个")

        tiers = sorted(a["tier"] for a in antags)
        expected_tiers = list(range(1, num_volumes + 1))
        if tiers != expected_tiers:
            issues.append(f"tier 应从1到{num_volumes}连续，实际: {tiers}")

        defeat_volumes = sorted(a["defeat_volume"] for a in antags)
        if defeat_volumes != expected_tiers:
            issues.append(f"defeat_volume 应从1到{num_volumes}各一个，实际: {defeat_volumes}")

        return {"valid": len(issues) == 0, "issues": issues}

    return handler


# ── CharacterDesignerAgent 类 ─────────────────────────────────────────────

class CharacterDesignerAgent(AgentLoop):
    agent_name = "character_designer"
    max_iterations = 3
    max_turns_per_iteration = 5
    max_tokens = 5000
    temperature = 0.85

    def build_system_prompt(self, context: dict) -> str:
        base = SYSTEM_PROMPT
        disciplines = context.get("disciplines", [])
        if disciplines:
            guidance = get_agent_guidance(disciplines, "character_designer")
            if guidance:
                base += f"\n\n【学科深度要求】\n本书融合以下学科视角，请在人物设计中自然融入：\n\n{guidance}"
        return base

    def build_tools(self, context: dict) -> list[dict]:
        return [VALIDATE_POWER_REFS_TOOL, VALIDATE_ANTAG_TIERS_TOOL, SUBMIT_TOOL]

    def build_tool_handlers(self, context: dict) -> dict:
        world: WorldSetting = context["world"]
        request: WebNovelRequest = context["request"]
        return {
            "validate_power_references": _make_power_refs_handler(world),
            "validate_antagonist_tiers": _make_antag_tiers_handler(request.num_volumes),
        }

    def build_initial_messages(self, context: dict) -> list[dict]:
        request: WebNovelRequest = context["request"]
        world: WorldSetting = context["world"]

        levels = world.power_system.levels
        lowest = levels[0].name if levels else "第一境界"
        highest = levels[-1].name if levels else "最高境界"

        ps_lines = [f"力量体系：{world.power_system.name}"]
        for lv in levels:
            ps_lines.append(f"  {lv.rank}. {lv.name}（{lv.typical_power}）")
        ps_summary = "\n".join(ps_lines)

        romance_line = f"\n感情线设定：{request.romance}" if request.romance else ""
        antagonist_hint = f"\n反派方向：{request.antagonist_direction}" if request.antagonist_direction else ""

        discipline_instruction = ""
        if context.get("disciplines"):
            discipline_instruction = (
                "\n\n学科深度字段（请为每个主要角色填写）："
                "\n- psychological_profile：核心心理特征/创伤/防御机制（50字）"
                "\n- intellectual_stance：信仰/哲学/知识立场（30字）"
            )

        depth_instruction = (
            "\n\n角色深度字段（请为每个角色填写）："
            "\n- appearance：1个标志性视觉特征，让读者脑中有画面（20字）"
            "\n- signature_move：标志性招式或习惯动作（20字）"
            "\n- hidden_agenda：隐藏目标/秘密（至少2个角色有，其余可留空）（30字）"
            "\n- relationship_notes：与主角的关系张力/潜在冲突点（30字）"
            "\n- growth_trajectory：初期→中期→后期变化路径（40字）"
            "\n\n反派深度字段（请为每个反派填写）："
            "\n- heroic_code：反派坚守的底线（20字）"
            "\n- tragic_flaw：致命缺陷（20字）"
            "\n- sympathetic_element：读者可同情的地方（30字）"
        )

        dialogue_instruction = (
            "\n\n对话差异化字段（请为每个角色填写）："
            "\n- humor_style：幽默风格（毒舌/天然呆/冷幽默/无）"
            "\n- dialogue_sentence_length：对话句长（极短/中等/长句型）"
            "\n- dialogue_tone：对话语气（嘲讽/温和/粗犷/文绉绉/冷淡）"
            "\n- dialogue_verbal_tics：口头禅（1-2个词，至少主角和2个配角）"
            "\n- dialogue_forbidden：角色绝不会说的话"
            "\n\n反派深度补充字段："
            "\n- internal_conflict：反派内心矛盾（30字）"
            "\n- reader_sympathy_hook：读者同情锚点（30字）"
            "\n- escalation_arc：反派升级路线（2-3步）"
            "\n- fall_from_grace：终极反派堕落方式（30字）"
        )

        prompt = f"""类型：{request.genre}
核心爽点：{request.core_pleasure}
主角：{request.protagonist_name}
主角起点：{request.protagonist_background}
金手指：{request.golden_finger}{romance_line}{antagonist_hint}
计划卷数：{request.num_volumes}卷

{ps_summary}

请设计本书的人物体系，严格遵守以下要求：

人物设计要求：
- characters 必须包含：protagonist（主角）、love_interest（感情线，如有）、sidekick（挚友/兄弟）、mentor（师父/引路人）
- 主角起点境界必须是 "{lowest}"（最低级），体现低谷起点
- 其他配角境界略高于主角起点（{levels[1].name if len(levels) > 1 else lowest}左右）
- speech_pattern 必须让每个角色说话方式明显不同，举1-2个例句说明

反派设计要求：
- antagonists 恰好 {request.num_volumes} 个（每卷一个主要反派，每层tier递增1）
- tier 1 反派境界：{levels[min(2, len(levels)-1)].name}（比主角开局高2-3级）
- 每升一层，反派境界提高2-3个大境界
- defeat_volume 表示被主角解决的卷数，从1到{request.num_volumes}
- 终极反派（tier={request.num_volumes}）境界应达到 "{highest}" 附近{discipline_instruction}{depth_instruction}{dialogue_instruction}

请先用 validate_power_references 和 validate_antagonist_tiers 检查设计，确认无误后再调用 submit_result 提交。"""

        return [{"role": "user", "content": prompt}]

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        """域校验"""
        issues = []
        world: WorldSetting = context["world"]
        request: WebNovelRequest = context["request"]
        valid_names = {lv.name for lv in world.power_system.levels}

        # 检查角色力量引用
        for c in result.get("characters", []):
            if c.get("current_power") and c["current_power"] not in valid_names:
                issues.append(f"角色 {c['name']} 的境界 '{c['current_power']}' 不在力量体系中")

        # 检查反派力量引用
        for a in result.get("antagonists", []):
            if a.get("current_power") and a["current_power"] not in valid_names:
                issues.append(f"反派 {a['name']} 的境界 '{a['current_power']}' 不在力量体系中")

        # 检查反派梯队
        antag_validation = _make_antag_tiers_handler(request.num_volumes)(
            {"antagonists": result.get("antagonists", [])}
        )
        if not antag_validation["valid"]:
            issues.extend(antag_validation["issues"])

        # 检查必需角色
        roles = {c.get("role") for c in result.get("characters", [])}
        if "protagonist" not in roles:
            issues.append("缺少 protagonist（主角）角色")

        if issues:
            return False, "\n".join(f"- {i}" for i in issues)
        return True, ""

    def parse_result(self, result: dict, context: dict) -> tuple[list[CharacterProfile], list[AntagonistTier]]:
        characters = [
            CharacterProfile(**{k: v for k, v in c.items() if k in CharacterProfile.model_fields})
            for c in result["characters"]
        ]
        antagonists = [
            AntagonistTier(**{k: v for k, v in a.items() if k in AntagonistTier.model_fields})
            for a in result["antagonists"]
        ]
        return characters, antagonists


# ── 公开接口（保持向后兼容） ─────────────────────────────────────────────────

async def design_characters(
    client: LLMClient,
    request: WebNovelRequest,
    world: WorldSetting,
) -> tuple[list[CharacterProfile], list[AntagonistTier]]:
    """带自校验的人物设计"""
    agent = CharacterDesignerAgent()
    return await agent.run(client, {
        "request": request,
        "world": world,
        "disciplines": request.disciplines,
    })
