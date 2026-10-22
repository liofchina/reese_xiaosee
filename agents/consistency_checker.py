"""
Agent 6 — 一致性校验者 ConsistencyChecker（deep 模式专用）
校验章节内容与设定的一致性。

升级：发现严重问题时触发自动修正（最多2轮），而非仅记录。
"""

import asyncio
import logging
from core.llm_client import LLMClient
from models.novel import WebNovelOutline, ChapterOutlineItem, ChapterResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的网文编辑，专门负责一致性校验和质量把关。
你的任务是对照世界设定和角色档案，检查章节内容是否存在矛盾或问题。

校验重点：
1. 力量一致性：主角或其他角色的境界描述是否与设定冲突？有无不合理的越级表现？
2. 角色一致性：人物性格、说话风格是否与档案一致？有无角色说话千人一面？
3. 设定一致性：地名、势力名、道具名是否前后一致？有无自相矛盾？
4. 钩子强度：结尾是否有效制造了悬念？读者是否有动力翻下一章？（1-10分）
5. 爽点落实：如果有爽点任务，是否真正写出来了？还是点到即止？
6. 主题一致性：学科元素是否自然融入？有无突兀说教？角色思想立场是否前后一致？
7. 时间连贯性：章节间的时间流动是否合理？有无"刚打完就恢复如初"？
8. 地理位置：角色的位置移动是否合理？有无"瞬移"？
9. 因果逻辑：事件之间是否有因果关系？有无"无缘无故发生的事"？
10. 伏笔推进：前文埋下的伏笔在本章是否有推进或呼应？
11. 时间线一致性：多角色视角下的时间是否对齐？有无时间矛盾？
12. 信息差一致性：角色是否引用了自己不应该知道的信息？（检查信息差数据）
13. 角色声音偏离：角色的说话方式是否与其典型台词风格一致？
14. 禁止项违反：角色是否做了违反其核心信念/底线的行为？（检查禁忌列表）
15. 钩子断裂：前章设置的悬念是否在本章或近期得到回应？
16. 角色消失：出场过的配角是否无故消失太久？
17. 钩子兑现时效：上章结尾钩子必须在本章前500字内得到回应（不必解决，但必须提及/推进）

输出简洁，只报告真实问题，不鸡蛋里挑骨头。"""

TOOL = {
    "name": "check_chapter_consistency",
    "description": "校验章节内容的一致性，评估钩子强度，返回问题列表",
    "input_schema": {
        "type": "object",
        "properties": {
            "hook_strength": {"type": "integer", "minimum": 1, "maximum": 10},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["力量一致性", "角色一致性", "设定一致性", "爽点落实", "主题一致性", "时间连贯性", "地理位置", "因果逻辑", "伏笔推进", "时间线一致性", "信息差一致性", "角色声音偏离", "禁止项违反", "钩子断裂", "角色消失", "其他"],
                        },
                        "location": {"type": "string"},
                        "problem": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["type", "location", "problem", "suggestion"],
                },
            },
            "needs_rewrite": {
                "type": "boolean",
                "description": "是否存在严重问题需要修正（力量矛盾、钩子极弱等）",
            },
        },
        "required": ["hook_strength", "issues", "needs_rewrite"],
    },
}

REWRITE_SYSTEM_PROMPT = """你是一位网文修正编辑。你需要根据校验报告，对章节内容做针对性修正。

修正原则：
1. 只修有问题的部分，保持其余内容不变
2. 修正后的文本必须与原文自然衔接
3. 保持原有的写作风格和节奏
4. 如果是钩子太弱，只修改最后1-2段"""


def _build_prompt(
    outline: WebNovelOutline,
    chapter_outline: ChapterOutlineItem,
    chapter_result: ChapterResult,
    previous_summary: str,
    entity_context: str = "",
) -> str:
    ps = outline.world.power_system
    level_names = [lv.name for lv in ps.levels]

    chars_info = "\n".join(
        f"  {c.name}（{c.role}）- 境界：{c.current_power}，性格：{c.personality[:30]}"
        for c in outline.characters
    )
    antags_info = "\n".join(
        f"  {a.name}（第{a.tier}层）- 境界：{a.current_power}"
        for a in outline.antagonists
    )

    pleasure_task = f"本章爽点任务：{chapter_outline.pleasure_point}" if chapter_outline.pleasure_point else "本章无明确爽点任务"

    # 主题一致性上下文
    thematic_context = ""
    if hasattr(outline, 'disciplines') and outline.disciplines:
        thematic_context = f"\n\n学科方向：{', '.join(outline.disciplines)}"
    if chapter_outline.thematic_element:
        thematic_context += f"\n本章主题元素：{chapter_outline.thematic_element}"
    if chapter_outline.knowledge_seed:
        thematic_context += f"\n本章知识种子：{chapter_outline.knowledge_seed}"

    return f"""【设定参考】
力量体系等级（从低到高）：{" → ".join(level_names)}
主角本章应处境界：{chapter_outline.protagonist_power}

主要人物：
{chars_info}

反派：
{antags_info}

上章摘要：{previous_summary or "无"}

【本章任务】
{pleasure_task}
预期结尾钩子：{chapter_outline.hook_end}{thematic_context}

{entity_context}

【本章正文】
{chapter_result.content[:8000]}

请校验以上内容，要求：
- hook_strength 为1-10整数（1=毫无悬念，10=极强钩子）
- issues 只列真实问题，没有问题时返回空数组
- 最多列5个最重要的问题
- needs_rewrite 为 true 当：存在"力量一致性"问题 或 hook_strength < 5 或 存在严重"爽点落实"问题"""


def _build_rewrite_prompt(
    chapter_result: ChapterResult,
    issues: list[dict],
    hook_strength: int,
    chapter_outline: ChapterOutlineItem,
) -> str:
    """构建针对性修正 prompt"""
    issue_lines = []
    for i in issues:
        issue_lines.append(f"- [{i['type']}] {i['location']}：{i['problem']}\n  建议：{i['suggestion']}")

    hook_instruction = ""
    if hook_strength < 5:
        hook_instruction = f"""
【钩子修正要求】
当前钩子强度仅 {hook_strength}/10，结尾太弱。
预期钩子效果：{chapter_outline.hook_end}
请重写最后1-2段，制造更强的悬念。"""

    return f"""以下章节存在问题，请做精准局部修正（只改问题段落，保持其余100%不变）：

【发现的问题】
{chr(10).join(issue_lines)}
{hook_instruction}

【修正原则】
- 一次最多修正2个问题
- 只修改问题所在的段落及其前后各1段
- 其余内容原封不动复制
- 修正后的段落要与上下文自然衔接

【原始正文】
{chapter_result.content}

请输出修正后的完整章节正文。只替换问题段落，其余内容必须与原文完全相同。
不要输出章节标题或任何额外说明，直接输出修正后的正文。"""


async def check_consistency(
    client: LLMClient,
    outline: WebNovelOutline,
    chapter_outline: ChapterOutlineItem,
    chapter_result: ChapterResult,
    previous_summary: str,
    entity_context: str = "",
) -> ChapterResult:
    """
    校验章节一致性。
    升级：发现严重问题时自动触发修正（最多2轮修正循环）。
    失败时返回原始结果，不阻塞流水线。
    """
    max_correction_rounds = 2
    current_result = chapter_result

    for correction_round in range(max_correction_rounds + 1):
        # 第一步：校验
        prompt = _build_prompt(outline, chapter_outline, current_result, previous_summary, entity_context)

        check_data = None
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(2)
            try:
                check_data = await client.tool_call(
                    SYSTEM_PROMPT, prompt, TOOL, "check_chapter_consistency",
                    max_tokens=1500, temperature=0.3,
                )
                break
            except Exception as e:
                logger.warning(f"一致性校验第{attempt+1}次失败: {e}")
                continue

        if check_data is None:
            # 校验完全失败，返回原始结果
            return current_result

        # 更新校验结果
        issues_raw = check_data.get("issues", [])
        issues = [
            f"[{i['type']}] {i['location']}：{i['problem']}"
            for i in issues_raw
        ]
        hook_strength = int(check_data.get("hook_strength", -1))
        needs_rewrite = check_data.get("needs_rewrite", False)

        current_result.hook_strength = hook_strength
        current_result.consistency_issues = issues

        # 判断是否需要修正
        if not needs_rewrite or correction_round >= max_correction_rounds:
            if correction_round > 0:
                logger.info(f"第{chapter_outline.chapter_num}章: 经过{correction_round}轮修正完成")
            return current_result

        # 第二步：自动修正
        logger.info(
            f"第{chapter_outline.chapter_num}章: 发现严重问题（hook={hook_strength}, "
            f"issues={len(issues_raw)}），触发第{correction_round+1}轮修正"
        )

        rewrite_prompt = _build_rewrite_prompt(
            current_result, issues_raw, hook_strength, chapter_outline,
        )

        try:
            # 使用流式生成修正版本
            corrected_content = []
            async for text in client.stream(
                REWRITE_SYSTEM_PROMPT,
                rewrite_prompt,
                max_tokens=max(4000, len(current_result.content) * 2),
                temperature=0.7,
            ):
                corrected_content.append(text)

            corrected_text = "".join(corrected_content).strip()
            if corrected_text and len(corrected_text) > len(current_result.content) * 0.5:
                # 修正成功，更新内容
                current_result.content = corrected_text
                current_result.consistency_issues.append(
                    f"[自动修正] 第{correction_round+1}轮修正已应用"
                )
            else:
                logger.warning("修正文本过短或为空，保留原始内容")
                return current_result

        except Exception as e:
            logger.warning(f"自动修正失败: {e}，保留当前内容")
            return current_result

    return current_result
