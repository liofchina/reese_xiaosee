"""
Agent 8 — 质量评审 QualityCritic（可选）
从读者视角评估章节质量：爽感、节奏、原创性。
低分章节可触发重写建议。

设计理念（CrewAI - Consensual Process）：
与 ConsistencyChecker 形成多视角评审。
ConsistencyChecker 关注事实一致性，QualityCritic 关注读者体验。
"""

import logging
from core.llm_client import LLMClient
from models.novel import WebNovelOutline, ChapterOutlineItem, ChapterResult
from agents.base import SingleShotAgent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深网文读者和评论家，每年阅读超过200部网文。
你从读者体验的角度评估章节质量，而非写作技巧。

评估维度：
1. 爽感（1-10）：读者看完这章有没有感到过瘾？打脸打得够不够狠？突破写得够不够爽？
2. 节奏（1-10）：该快的地方快了吗？该慢的地方有没有拖沓？有没有长段落让读者走神？
3. 代入感（1-10）：读者能代入主角吗？对话真实吗？情绪共鸣强不强？
4. 翻页欲（1-10）：章节结尾让你想翻下一章吗？还是可以放下手机睡觉？
5. 深度（1-10）：本章有没有让读者思考？知识/学科元素是否自然融入？有无思想性？
6. 原创性（1-10）：情节有新意还是套路重复？对话有没有脱离模板？7分以上才算有新鲜感
7. 感官层次（1-10）：描写是否调动了多种感官（视觉+听觉+触觉+嗅觉）？还是纯视觉？
8. 角色辨识度（1-10）：不看名字能分辨谁在说话吗？每个角色有独特的语言习惯吗？
9. 连读不疲劳（1-10）：连续读5章不想停？还是读2章就累了？节奏变化是否到位？
10. 社交分享潜力（1-10）：有没有让读者想截图发朋友圈/群里讨论的句子或场面？
11. 回流友好度（1-10）：一周没看再回来，3秒能接上剧情吗？前情融入是否自然？

你的评分要严格：
- 7分以上：优秀，这章能留住读者
- 5-6分：及格，不会掉粉但也不涨粉
- 4分以下：危险，可能导致读者弃书

只打分和给具体改进建议，不要空泛的表扬。"""

TOOL = {
    "name": "evaluate_chapter_quality",
    "description": "从读者视角评估章节质量，给出各维度评分和改进建议",
    "input_schema": {
        "type": "object",
        "properties": {
            "excitement_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "爽感评分",
            },
            "pacing_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "节奏评分",
            },
            "immersion_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "代入感评分",
            },
            "page_turner_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "翻页欲评分",
            },
            "depth_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "深度评分：思想性、学科元素融入度",
            },
            "originality_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "原创性评分：情节新意、对话脱离模板程度",
            },
            "sensory_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "感官层次评分：多感官调动程度",
            },
            "character_voice_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "角色辨识度评分：不看名字能否分辨说话人",
            },
            "binge_readability": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "连读不疲劳评分",
            },
            "social_shareability": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "社交分享潜力评分",
            },
            "recap_efficiency": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "回流读者友好度评分",
            },
            "predicted_complaints": {
                "type": "array", "items": {"type": "string"},
                "description": "预测读者可能的吐槽点（最多3条）",
            },
            "iq_offline_risk": {
                "type": "boolean",
                "description": "是否存在角色智商下线风险",
            },
            "padding_risk": {
                "type": "boolean",
                "description": "是否存在水字数嫌疑",
            },
            "emotion_sequence": {
                "type": "array", "items": {"type": "string"},
                "description": "本章情绪曲线（4-6个情绪词：好奇/紧张/绝望/燃/震撼等）",
            },
            "narrative_patterns_used": {
                "type": "array", "items": {"type": "string"},
                "description": "本章使用的叙事套路（如underestimate_reveal等）",
            },
            "overall_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": "综合评分",
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "做得好的地方（最多2条）",
            },
            "improvements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "问题位置（如'开头第2段'）"},
                        "issue": {"type": "string", "description": "问题描述"},
                        "suggestion": {"type": "string", "description": "具体改进建议"},
                    },
                    "required": ["location", "issue", "suggestion"],
                },
                "description": "需要改进的地方（最多3条）",
            },
            "needs_rewrite": {
                "type": "boolean",
                "description": "综合评分低于5分时为true",
            },
        },
        "required": [
            "excitement_score", "pacing_score", "immersion_score",
            "page_turner_score", "overall_score",
            "strengths", "improvements", "needs_rewrite",
        ],
    },
}


class QualityCriticAgent(SingleShotAgent):
    agent_name = "quality_critic"
    max_iterations = 2
    max_tokens = 2000
    temperature = 0.4

    def build_system_prompt(self, context: dict) -> str:
        return SYSTEM_PROMPT

    def get_tool(self) -> tuple[dict, str]:
        return TOOL, "evaluate_chapter_quality"

    def build_prompt(self, context: dict) -> str:
        chapter_outline: ChapterOutlineItem = context["chapter_outline"]
        chapter_result: ChapterResult = context["chapter_result"]
        core_pleasure: str = context.get("core_pleasure", "")

        pleasure_task = ""
        if chapter_outline.pleasure_point:
            pleasure_task = f"\n本章爽点任务：{chapter_outline.pleasure_point}"

        return f"""【章节信息】
第{chapter_outline.chapter_num}章《{chapter_outline.title}》
核心爽点类型：{core_pleasure}
预期结尾钩子：{chapter_outline.hook_end}{pleasure_task}

【章节正文】
{chapter_result.content[:8000]}

{"⚠ 本章为开书前3章，评分标准加倍严格：前3章决定读者去留，任何维度低于7分都应标记needs_rewrite=true" if chapter_outline.chapter_num <= 3 else ""}

请从读者角度严格评估这一章的质量。"""

    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        overall = result.get("overall_score", 0)
        if not (1 <= overall <= 10):
            return False, f"overall_score 应为1-10，实际{overall}"
        return True, ""

    def parse_result(self, result: dict, context: dict) -> dict:
        return result


# ── 公开接口 ─────────────────────────────────────────────────────────────────

async def evaluate_quality(
    client: LLMClient,
    chapter_outline: ChapterOutlineItem,
    chapter_result: ChapterResult,
    core_pleasure: str = "",
) -> dict:
    """
    评估章节质量。返回评分和改进建议。
    失败时返回默认评分（不阻塞流水线）。
    """
    agent = QualityCriticAgent()
    try:
        return await agent.run(client, {
            "chapter_outline": chapter_outline,
            "chapter_result": chapter_result,
            "core_pleasure": core_pleasure,
        })
    except Exception as e:
        logger.warning(f"质量评审失败（非致命）: {e}")
        return {
            "excitement_score": -1,
            "pacing_score": -1,
            "immersion_score": -1,
            "page_turner_score": -1,
            "overall_score": -1,
            "strengths": [],
            "improvements": [],
            "needs_rewrite": False,
        }
