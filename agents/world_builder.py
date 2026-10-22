"""
Agent 1 — 世界构建师 WorldBuilder
根据类型和核心爽点，生成力量体系、势力格局、世界规则。

升级：继承 AgentLoop，支持自校验（验证力量体系连续性、势力类型覆盖）。
"""

import asyncio
import math
import logging
from core.llm_client import LLMClient, ProviderRateLimitError, ProviderUnavailableError
from models.novel import (
    WebNovelRequest, WorldSetting, PowerSystem, PowerLevel, Faction
)
from agents.base import AgentLoop
from domain.disciplines import get_agent_guidance

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文世界观设计师，深谙各类网络小说的设定惯例。
你的任务是根据网文类型和核心爽点，设计自洽、有代入感的世界观。

要求：
1. 力量体系层级分明，每个境界有清晰的战力表现（读者能直观感受差距）
2. 境界之间差距悬殊，跨级战斗几乎不可能（才有压迫感和爽感）
3. 势力格局为主角成长留出足够空间（从最弱势力→最强势力，逐步升级）
4. 资源体系稀缺逻辑合理（否则主角轻松得到资源，失去张力）
5. 所有设定必须服务于核心爽点

【世界观深度要求】
6. 地理格局：设计至少3个层级区域（如：起始城→区域→大陆→界域），每个区域标注"建议境界等级"
7. 天地规则：设计至少1条天地法则（如天劫、灵气潮汐、禁忌之力），影响修炼节奏
8. 历史厚度：世界需有至少3个历史纪元，当前格局是历史的必然结果
9. 禁区/秘境：至少设计2个特殊地点，有明确的进入条件和风险收益

【战斗描写进化规则】
10. 为力量体系设计战斗描写分层（随境界提升，战斗方式质变）：
    - 低阶（前30%境界）：肉搏/兵器/简单术法，强调速度和技巧
    - 中阶（30-60%）：大范围法术/领域对抗，强调策略和资源管理
    - 高阶（60-90%）：规则对抗/因果律战斗，强调悟性和心境
    - 顶阶（最后10%）：概念碰撞/道之争鸣，强调哲学层面的对决

你可以使用 validate_power_system 和 validate_factions 工具来检查你的设计是否符合要求。
确认无误后，调用 submit_result 提交最终结果。"""

# ── 输出工具 Schema（submit_result） ─────────────────────────────────────────

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "提交最终的世界观设计结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "power_system": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "levels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "rank": {"type": "integer"},
                                "description": {"type": "string"},
                                "typical_power": {"type": "string"},
                            },
                            "required": ["name", "rank", "description", "typical_power"],
                        },
                    },
                    "breakthrough_conditions": {"type": "string"},
                    "special_rules": {"type": "string"},
                },
                "required": ["name", "levels", "breakthrough_conditions"],
            },
            "factions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction_type": {
                            "type": "string",
                            "enum": ["protagonist_side", "enemy_near", "enemy_mid", "enemy_boss", "neutral", "ally"],
                        },
                        "power_description": {"type": "string"},
                        "description": {"type": "string"},
                        "leader": {"type": "string"},
                    },
                    "required": ["name", "faction_type", "power_description", "description"],
                },
            },
            "resource_system": {"type": "string"},
            "special_rules": {"type": "string"},
            "philosophical_foundation": {"type": "string", "description": "世界的哲学/思想内核（可选）"},
            "cultural_system": {"type": "string", "description": "文化/知识/信仰体系（可选）"},
            "social_structure": {"type": "string", "description": "社会结构与运行逻辑（可选）"},
            "geography": {"type": "string", "description": "地理划分概述：至少3个层级区域+建议境界（可选）"},
            "history_summary": {"type": "string", "description": "关键历史事件概述：至少3个纪元（可选）"},
            "forbidden_zones": {"type": "string", "description": "禁区/秘境：进入条件+风险收益（可选）"},
        },
        "required": ["description", "power_system", "factions", "resource_system"],
    },
}

# ── 验证工具 ────────────────────────────────────────────────────────────────

VALIDATE_POWER_TOOL = {
    "name": "validate_power_system",
    "description": "验证力量体系设计：检查等级数量、rank连续性、描述唯一性",
    "input_schema": {
        "type": "object",
        "properties": {
            "levels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "rank": {"type": "integer"},
                        "typical_power": {"type": "string"},
                    },
                    "required": ["name", "rank"],
                },
            },
        },
        "required": ["levels"],
    },
}

VALIDATE_FACTIONS_TOOL = {
    "name": "validate_factions",
    "description": "验证势力格局：检查必需类型覆盖（主角方、近/中/终敌、中立/盟友）",
    "input_schema": {
        "type": "object",
        "properties": {
            "factions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction_type": {"type": "string"},
                    },
                    "required": ["name", "faction_type"],
                },
            },
        },
        "required": ["factions"],
    },
}


# ── 验证逻辑（纯 Python，不调 LLM） ────────────────────────────────────────

def _validate_power_system_handler(input_data: dict) -> dict:
    """本地验证力量体系"""
    levels = input_data.get("levels", [])
    issues = []

    if not levels:
        return {"valid": False, "issues": ["力量体系为空"]}

    # 检查 rank 连续性
    ranks = sorted(lv["rank"] for lv in levels)
    expected = list(range(1, len(ranks) + 1))
    if ranks != expected:
        issues.append(f"rank 不连续或不从1开始，当前: {ranks}，期望: {expected}")

    # 检查名称唯一
    names = [lv["name"] for lv in levels]
    if len(set(names)) != len(names):
        dupes = [n for n in names if names.count(n) > 1]
        issues.append(f"存在重复的境界名称: {list(set(dupes))}")

    # 检查 typical_power 唯一性
    powers = [lv.get("typical_power", "") for lv in levels]
    if len(set(powers)) < len(powers) * 0.8:  # 允许少量相似
        issues.append("部分境界的 typical_power 描述过于雷同，应体现明显差距")

    return {"valid": len(issues) == 0, "issues": issues}


def _validate_factions_handler(input_data: dict) -> dict:
    """本地验证势力格局"""
    factions = input_data.get("factions", [])
    issues = []

    types_present = {f["faction_type"] for f in factions}
    required_types = {"protagonist_side", "enemy_near", "enemy_boss"}
    missing = required_types - types_present
    if missing:
        issues.append(f"缺少必需势力类型: {missing}")

    # 至少有中立或盟友
    if not types_present & {"neutral", "ally"}:
        issues.append("缺少中立/盟友势力（至少需要一个 neutral 或 ally）")

    if len(factions) < 5:
        issues.append(f"势力数量不足，当前{len(factions)}个，至少需要5个")

    # 检查名称唯一
    names = [f["name"] for f in factions]
    if len(set(names)) != len(names):
        issues.append("存在重复的势力名称")

    return {"valid": len(issues) == 0, "issues": issues}


# ── WorldBuilderAgent 类 ─────────────────────────────────────────────────────

class WorldBuilderAgent(AgentLoop):
    agent_name = "world_builder"
    max_iterations = 3
    max_turns_per_iteration = 5
    max_tokens = 4000
    temperature = 0.8

    def build_system_prompt(self, context: dict) -> str:
        base = SYSTEM_PROMPT
        disciplines = context.get("disciplines", [])
        if disciplines:
            guidance = get_agent_guidance(disciplines, "world_builder")
            if guidance:
                base += f"\n\n【学科深度要求】\n本书融合以下学科视角，请在设计中自然融入（禁止百科式解释）：\n\n{guidance}"
        return base

    def build_tools(self, context: dict) -> list[dict]:
        return [VALIDATE_POWER_TOOL, VALIDATE_FACTIONS_TOOL, SUBMIT_TOOL]

    def build_tool_handlers(self, context: dict) -> dict:
        return {
            "validate_power_system": _validate_power_system_handler,
            "validate_factions": _validate_factions_handler,
        }

    def build_initial_messages(self, context: dict) -> list[dict]:
        request: WebNovelRequest = context["request"]
        total_chapters = request.num_volumes * request.chapters_per_volume
        num_levels = min(int(math.log2(max(request.num_volumes, 1)) * 5 + 8), 30)

        discipline_instruction = ""
        if context.get("disciplines"):
            discipline_instruction = (
                "\n- 请填写 philosophical_foundation（世界的哲学/思想内核，80字）"
                "\n- 请填写 cultural_system（文化/知识/信仰体系，80字）"
                "\n- 请填写 social_structure（社会结构与运行逻辑，80字）"
            )

        depth_instruction = (
            "\n- 请填写 geography（地理划分：至少3个层级区域+建议境界等级，80字）"
            "\n- 请填写 history_summary（历史事件：至少3个纪元概述，100字）"
            "\n- 请填写 forbidden_zones（禁区/秘境：至少2个特殊地点+进入条件，60字）"
        )

        prompt = f"""类型：{request.genre}{f"（{request.sub_genre}）" if request.sub_genre else ""}
核心爽点：{request.core_pleasure}
主角姓名：{request.protagonist_name}
主角起点：{request.protagonist_background}
金手指：{request.golden_finger}
用户世界观描述：{request.world_desc or "无，请自行设计"}
计划：{request.num_volumes}卷，共{total_chapters}章

请设计这部网文的世界观，严格遵守以下要求：
- 境界等级恰好 {num_levels} 个，从低到高，rank从1开始连续编号
- 主角起点境界设为第1-2级，本书结束时达到第{num_levels-1}-{num_levels}级
- 势力至少5个：主角方1个、近期敌人1个、中期敌人1个、终极敌人1个、中立/盟友至少1个
- faction_type 只能用：protagonist_side / enemy_near / enemy_mid / enemy_boss / neutral / ally
- 所有设定符合"{request.genre}"类型惯例
- description 100字，要有独特性，不要通用模板
- resource_system 80字，包含资源类型+稀缺逻辑+获取方式{discipline_instruction}{depth_instruction}

请先用 validate_power_system 和 validate_factions 工具检查设计，确认无误后再调用 submit_result 提交。"""

        return [{"role": "user", "content": prompt}]

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        """域校验：检查结构完整性和力量体系规则"""
        issues = []
        request: WebNovelRequest = context["request"]
        num_levels = min(int(math.log2(max(request.num_volumes, 1)) * 5 + 8), 30)

        # 检查力量体系
        ps = result.get("power_system", {})
        levels = ps.get("levels", [])
        if len(levels) != num_levels:
            issues.append(f"境界等级数量应为{num_levels}个，实际{len(levels)}个")

        power_validation = _validate_power_system_handler({"levels": levels})
        if not power_validation["valid"]:
            issues.extend(power_validation["issues"])

        # 检查势力
        factions_validation = _validate_factions_handler({"factions": result.get("factions", [])})
        if not factions_validation["valid"]:
            issues.extend(factions_validation["issues"])

        if issues:
            return False, "\n".join(f"- {i}" for i in issues)
        return True, ""

    def parse_result(self, result: dict, context: dict) -> WorldSetting:
        ps_data = result["power_system"]
        power_system = PowerSystem(
            name=ps_data["name"],
            levels=[PowerLevel(**lv) for lv in sorted(ps_data["levels"], key=lambda x: x["rank"])],
            breakthrough_conditions=ps_data["breakthrough_conditions"],
            special_rules=ps_data.get("special_rules", ""),
        )
        factions = [Faction(**f) for f in result["factions"]]
        return WorldSetting(
            description=result["description"],
            power_system=power_system,
            factions=factions,
            resource_system=result["resource_system"],
            special_rules=result.get("special_rules", ""),
            philosophical_foundation=result.get("philosophical_foundation", ""),
            cultural_system=result.get("cultural_system", ""),
            social_structure=result.get("social_structure", ""),
            geography=result.get("geography", ""),
            history_summary=result.get("history_summary", ""),
            forbidden_zones=result.get("forbidden_zones", ""),
        )


# ── 公开接口（保持向后兼容） ─────────────────────────────────────────────────

async def build_world(client: LLMClient, request: WebNovelRequest) -> WorldSetting:
    """带自校验的世界观构建"""
    agent = WorldBuilderAgent()
    return await agent.run(client, {
        "request": request,
        "disciplines": request.disciplines,
    })
