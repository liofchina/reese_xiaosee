"""
Agent 5 — 写作执行者 Writer
逐章流式写作，严格遵守网文写作铁律。

升级：
- 写完后使用 check_banned_words 自检禁用词
- 发现问题时做针对性修订
- 使用 count_words 验证字数
"""

import logging
from core.llm_client import LLMClient
from models.novel import (
    WebNovelRequest, WebNovelOutline, ChapterOutlineItem, ChapterResult
)
from tools.registry import ToolRegistry
from tools.reference_tools import check_banned_words_handler, count_words_handler
from domain.disciplines import get_agent_guidance
from domain.pleasure_system import get_pleasure_guidance_for_writer, get_chapter_pacing_template, get_combat_guidance, get_combat_tier

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """你是一位专业网文写手，出版过多部百万字以上的网络小说。

【网文写作铁律（不得违反）】
① 开头禁止：环境描写、天气描写、时间交代开头。第一句必须是动作/对话/冲突/关键信息。
② 段落控制：每段100-200字，手机屏幕友好，绝不写连续大段。
③ 对话有力：每句对话推进情节或展示性格，禁止无意义寒暄，禁止角色解释给读者听。
④ 结尾钩子：最后一段必须制造悬念/意外/新冲突，让读者必须翻下一章。不能用总结句结尾。
⑤ 爽点到位：如果本章标注了爽点，要写得酣畅淋漓——打脸要打到对方无话可说，突破要写出那种飞升感。
⑥ 节奏快：战斗场面利落有力，过渡场景一句带过，不拖沓，不水字数。

【禁用词汇】
× "不禁" "顿时" "忍不住" "猛地" "深深地" "不由得"
× "他心中感到" "她感到一阵" "内心充满了"（情绪用行为体现）
× 连续三次出现相同动词（说道/走向/看向）

【读者心理模型】
⑦ 前100字定生死：读者在前100字决定是否继续读，第一句必须是冲击性信息
⑧ 300字检查点：每300字读者会下意识评估"值不值得看"——需要节奏变化或新信息
⑨ 感官三重奏：每个重要场景至少融入视觉+听觉+触觉（或嗅觉），禁止纯视觉描写
⑩ 爽点释放曲线：打脸/升级/揭秘等爽点必须经历"铺垫→积压→释放"完整过程，不能直接给结果

【爽点写法铁律】
- 打脸前必须有足够被轻视的铺垫（被轻视越深，打脸越爽）
- 突破前必须有陷入绝境/困境的过程（越绝望，突破越爽）
- 揭秘前必须有读者的好奇心积累（悬念挂越久，揭秘越震撼）
- 旁观者反应是爽感的放大器——打脸后一定要写围观者的震撼

【内容合规要求（网文平台审核）】
① 感情/亲密场景：点到为止，用环境/情绪/眼神暗示，禁止露骨身体描写
② 暴力场景：可写战斗但不描写血腥细节（不写内脏/脑浆/肢解），用结果和反应代替过程
③ 政治安全：不影射现实政治人物/事件，不评论真实国家体制，架空即架空
④ 宗教/民族：不贬低任何宗教或民族，修仙/玄幻中的道/佛元素要尊重原典
⑤ 价值观：主角可灰色但底线清晰，不宣扬极端暴力/犯罪/赌博/毒品为正面
⑥ 不歪曲重大历史事件，穿越文要注意历史基本尊重

【对话差异化铁律】
⑪ 同一场景中不同角色的对话必须风格明显不同——蒙住名字也能分辨谁在说话
⑫ 主角的台词风格必须前后一致：如果设定为少言寡语，就不能突然长篇大论
⑬ 反派台词暗含威胁而非直接叫嚣，高手过招用暗示不用解释

【前情融入铁律】
⑭ 回流读者3秒回忆：本章前300字内必须自然提及上章关键事件（通过角色对话/内心/行动，禁止"上回说到"式回顾）
⑮ 读者不需要翻回去看前文就能理解本章，但也不能重复叙述

【幽默写法指导】
⑯ 反差萌：严肃场合的不合时宜行为 / 强者的意外弱点 / 高手的日常窘态
⑰ 幽默通过行为和反应体现，禁止"逗笑""好笑"等直接告诉读者该笑的词
⑱ 搞笑桥段不超过连续300字，之后必须回到主线节奏

【叙事视距写法】
⑲ close视距：写内心独白、身体感受、情绪波动
⑳ medium视距：写动作、对话、即时反应（最常用）
㉑ far视距：写全景、群体反应、时间跳跃

【力量体系】
{power_system}

【本书人物声口】
{character_voices}"""

REVISION_SYSTEM_PROMPT = """你是一位网文修正编辑。你需要修正文本中的禁用词和重复动词。

修正原则：
1. 只替换问题词汇/句式，保持其余内容不变
2. 替换后的表达要自然，不能生硬
3. "不禁" → 删除或用动作替代
4. "顿时" → 删除或用具体动作替代
5. "忍不住" → 删除，直接写动作
6. 内心描写 → 改为行为描写
7. 重复动词 → 用同义词替换"""


MAX_CHARACTER_VOICES = 8  # 系统提示词中最大角色声口数


def _select_relevant_characters(
    outline: WebNovelOutline,
    chapter_outline: ChapterOutlineItem | None = None,
    entity_store=None,
    max_chars: int = MAX_CHARACTER_VOICES,
) -> tuple[list, list]:
    """
    筛选与当前章节最相关的角色，防止 100+ 角色导致系统提示词溢出。
    返回 (selected_characters, selected_antagonists)
    """
    # 始终包含的角色
    always_include_roles = {"protagonist", "love_interest", "mentor"}
    must_include = [c for c in outline.characters if c.role in always_include_roles]
    others = [c for c in outline.characters if c.role not in always_include_roles]

    # 如果有章节大纲，优先包含大纲中提到的角色
    mentioned_names = set()
    if chapter_outline:
        text = " ".join(chapter_outline.core_events or [])
        text += " " + (chapter_outline.hook_start or "") + " " + (chapter_outline.hook_end or "")
        text += " " + (chapter_outline.pleasure_point or "")
        for c in outline.characters + list(outline.antagonists if hasattr(outline, 'antagonists') else []):
            if hasattr(c, 'name') and c.name in text:
                mentioned_names.add(c.name)

    # 从 entity_store 获取活跃角色
    active_names = set()
    if entity_store and hasattr(entity_store, 'get_active_characters'):
        active_chars = entity_store.get_active_characters(
            chapter_outline.chapter_num if chapter_outline else 0
        )
        active_names = {c.name for c in active_chars}

    # 排序：提到的 > 活跃的 > 其他
    def char_priority(c):
        if c.name in mentioned_names:
            return 0
        if c.name in active_names:
            return 1
        return 2

    others.sort(key=char_priority)
    selected = must_include + others
    selected = selected[:max_chars]

    # 反派：只保留当前卷反派 + 终极Boss
    selected_antags = []
    if hasattr(outline, 'antagonists'):
        current_vol = chapter_outline.volume_chapter_num if chapter_outline else 1
        for a in outline.antagonists:
            if a.tier == max(ag.tier for ag in outline.antagonists):  # 终极Boss
                selected_antags.append(a)
            elif a.name in mentioned_names:
                selected_antags.append(a)
            elif len(selected_antags) < 3:
                selected_antags.append(a)

    return selected, selected_antags


def _build_system_prompt(
    outline: WebNovelOutline,
    entity_store=None,
    chapter_outline: ChapterOutlineItem | None = None,
) -> str:
    ps = outline.world.power_system
    power_lines = [f"{ps.name}（从低到高）："]
    for lv in ps.levels:
        power_lines.append(f"  {lv.rank}. {lv.name}：{lv.typical_power}")
    power_lines.append(f"突破条件：{ps.breakthrough_conditions}")

    voice_lines = []
    role_map = {
        "protagonist": "主角", "love_interest": "感情线",
        "sidekick": "挚友", "mentor": "师父",
    }
    # 只选择与当前章节相关的角色，防止 100+ 角色溢出
    selected_chars, selected_antags = _select_relevant_characters(
        outline, chapter_outline, entity_store
    )
    for c in selected_chars:
        role_label = role_map.get(c.role, c.role)
        voice_lines.append(
            f"【{c.name}（{role_label}）】境界：{c.current_power}\n"
            f"  性格：{c.personality}\n"
            f"  说话风格：{c.speech_pattern}"
        )
        if c.psychological_profile:
            voice_lines.append(f"  心理特征：{c.psychological_profile}")
        if c.intellectual_stance:
            voice_lines.append(f"  思想立场：{c.intellectual_stance}")
        # 注入典型台词示例（来自角色设计或实体记忆）
        examples = getattr(c, 'speech_examples', []) or []
        if not examples and entity_store and c.name in entity_store.characters:
            examples = entity_store.characters[c.name].speech_examples
        if examples:
            voice_lines.append(f"  典型台词：")
            for ex in examples[:3]:
                voice_lines.append(f"    「{ex}」")
    for a in selected_antags:
        voice_lines.append(
            f"【{a.name}（第{a.tier}层反派）】境界：{a.current_power}\n"
            f"  动机：{a.motive}"
        )

    base = SYSTEM_PROMPT_TEMPLATE.format(
        power_system="\n".join(power_lines),
        character_voices="\n".join(voice_lines),
    )

    # 注入学科写作指导
    if outline.disciplines:
        guidance = get_agent_guidance(outline.disciplines, "writer")
        if guidance:
            base += (
                "\n\n【学科深度写作要求】\n"
                "本书融合以下学科视角。学科元素必须通过场景、对话、行为展现，禁止百科式解释或角色说教：\n\n"
                f"{guidance}"
            )

    return base


def _build_user_prompt(
    request: WebNovelRequest,
    outline: WebNovelOutline,
    chapter_outline: ChapterOutlineItem,
    volume_title: str,
    previous_summary: str,
) -> str:
    pleasure_instruction = ""
    if chapter_outline.pleasure_point:
        pleasure_guidance = get_pleasure_guidance_for_writer(
            chapter_outline.pleasure_point, request.core_pleasure
        )
        pleasure_instruction = f"""
【本章爽点任务】
{chapter_outline.pleasure_point}
→ 必须写出来，且要写得淋漓尽致，这是读者最期待的时刻。

{pleasure_guidance}"""

    thematic_instruction = ""
    if chapter_outline.thematic_element:
        thematic_instruction += f"\n【本章主题元素】{chapter_outline.thematic_element}"
    if chapter_outline.knowledge_seed:
        thematic_instruction += f"\n【知识种子】{chapter_outline.knowledge_seed}"
    if thematic_instruction:
        thematic_instruction += "\n→ 请在本章中自然融入以上元素，禁止直接说教。"

    # 章节节奏指导
    pacing_instruction = ""
    if chapter_outline.pacing_type:
        pacing_tmpl = get_chapter_pacing_template(chapter_outline.pacing_type)
        pacing_instruction = (
            f"\n【章节节奏】类型：{pacing_tmpl['description']}"
            f"\n节奏：{pacing_tmpl['rhythm']}，段落风格：{pacing_tmpl['paragraph_style']}"
            f"\n注意：{pacing_tmpl['forbidden']}"
        )
    if chapter_outline.emotional_beat:
        pacing_instruction += f"\n【情感节拍】{chapter_outline.emotional_beat}"

    # 战斗描写指导
    combat_instruction = ""
    if chapter_outline.pacing_type == "action":
        total_ranks = len(outline.world.power_system.levels)
        current_rank = 1
        for lv in outline.world.power_system.levels:
            if lv.name == chapter_outline.protagonist_power:
                current_rank = lv.rank
                break
        tier = get_combat_tier(current_rank, total_ranks)
        combat_instruction = f"\n\n{get_combat_guidance(tier)}"

    # 叙事视距
    distance_instruction = ""
    if hasattr(chapter_outline, 'narrative_distance') and chapter_outline.narrative_distance:
        dist_map = {
            "close": "本章使用近景视距：多写内心独白、身体感受、情绪波动",
            "medium": "本章使用中景视距：以动作和对话推进，节奏适中",
            "far": "本章使用远景视距：全景描写、群体反应、适合宏大场面",
        }
        distance_instruction = f"\n【叙事视距】{dist_map.get(chapter_outline.narrative_distance, '')}"

    # 信息差张力
    irony_instruction = ""
    if hasattr(chapter_outline, 'dramatic_irony_active') and chapter_outline.dramatic_irony_active:
        irony_instruction = "\n【信息差张力】本章启用信息差——读者知道某个真相但角色不知道，利用这种张力制造焦虑感和期待感"

    # 金句种子
    golden_instruction = ""
    if hasattr(chapter_outline, 'golden_sentence_seed') and chapter_outline.golden_sentence_seed:
        golden_instruction = f"\n【金句任务】本章需要一句让读者截图的话：「{chapter_outline.golden_sentence_seed}」"

    # 开书前3章特殊要求
    opening_instruction = ""
    if chapter_outline.chapter_num <= 3:
        opening_instruction = """
【开书黄金3章铁律】
- 第一句话就要有冲击力（不允许环境/天气/时间开头）
- 前3章内必须完成：①金手指首次触发 ②第一个小爽点 ③第一个悬念钩子
- 前3章是读者"试毒"期——每300字都要有信息密度，不允许任何水段落
- 主角人设要在前3章建立完毕：性格+实力+目标+说话风格"""

    prev_info = (
        f"【上章摘要（保持连贯）】\n{previous_summary}"
        if previous_summary
        else "【本章为故事开篇，无前情提要】"
    )

    return f"""第{chapter_outline.chapter_num}章（卷内第{chapter_outline.volume_chapter_num}章）
所属卷：{volume_title}
章节标题：{chapter_outline.title}
主角当前境界：{chapter_outline.protagonist_power}

【章节细纲】
开头（第一段要做的事）：{chapter_outline.hook_start}
本章核心事件：
{chr(10).join(f"  • {ev}" for ev in chapter_outline.core_events)}
结尾钩子（最后一段要做的事）：{chapter_outline.hook_end}
{pleasure_instruction}
{thematic_instruction}
{pacing_instruction}
{combat_instruction}
{distance_instruction}
{irony_instruction}
{golden_instruction}
{opening_instruction}
{prev_info}

请按照以上细纲，写出完整的章节正文。
字数要求：约{request.words_per_chapter // 120}-{request.words_per_chapter // 100}段，每段100-120字（总计{request.words_per_chapter}字左右）。
不要输出章节标题或任何额外说明，直接输出正文内容。"""


async def _make_summary(client: LLMClient, content: str, title: str) -> str:
    try:
        return await client.complete(
            f"请用100字以内概括以下章节的主要事件和关键信息，"
            f"重点记录：主角当前境界、重要人物状态、未解决的悬念、已发生的重大事件。\n\n"
            f"章节标题：{title}\n\n{content[:3000]}",
            max_tokens=300,
            temperature=0.3,
        )
    except Exception:
        return content[:200] + "…"


def _get_volume_num(chapter_outline: ChapterOutlineItem, outline: WebNovelOutline) -> int:
    for vol in outline.volumes:
        for ch in vol.chapters:
            if ch.chapter_num == chapter_outline.chapter_num:
                return vol.volume_num
    return 1


async def _self_check_and_revise(
    client: LLMClient,
    content: str,
    target_words: int,
) -> tuple[str, list[str]]:
    """
    写后自检：检查禁用词、字数，必要时修正。
    返回 (revised_content, issues_found)
    """
    issues_found = []

    # 禁用词检查
    ban_result = check_banned_words_handler({"text": content})
    if ban_result["has_issues"]:
        ban_details = []
        for w in ban_result["banned_words_found"]:
            ban_details.append(f"禁用词「{w['word']}」出现{w['count']}次")
        for v in ban_result["repeated_verbs"]:
            ban_details.append(f"动词「{v}」连续重复3次以上")
        issues_found.extend(ban_details)

        # 尝试修正
        try:
            revision_prompt = (
                f"以下文本存在网文禁用词问题：\n"
                f"{'、'.join(ban_details)}\n\n"
                f"请修正以下文本，只替换问题词汇，保持其余内容不变：\n\n{content}"
            )
            revised_parts = []
            async for text in client.stream(
                REVISION_SYSTEM_PROMPT,
                revision_prompt,
                max_tokens=max(4000, len(content) * 2),
                temperature=0.5,
            ):
                revised_parts.append(text)
            revised = "".join(revised_parts).strip()
            if revised and len(revised) > len(content) * 0.7:
                content = revised
                issues_found.append("[自动修正] 禁用词已修正")
        except Exception as e:
            logger.warning(f"禁用词自动修正失败: {e}")

    # 字数检查
    word_result = count_words_handler({"text": content})
    chinese_chars = word_result["chinese_chars"]
    if abs(chinese_chars - target_words) > target_words * 0.3:
        issues_found.append(f"字数偏差较大: 目标{target_words}字，实际{chinese_chars}字")

    return content, issues_found


async def write_chapter(
    client: LLMClient,
    request: WebNovelRequest,
    outline: WebNovelOutline,
    chapter_outline: ChapterOutlineItem,
    volume_title: str,
    previous_summary: str,
    registry: ToolRegistry | None = None,
    entity_context: str = "",
    entity_store=None,
    _continuation_content: str = "",
):
    """
    异步流式写作生成器，yield (event_type, data)：
    - ("chunk", str)        — 文本片段
    - ("stream_interrupted", dict) — 流中断，包含已写内容（供调用方决定续写）
    - ("result", ChapterResult)

    升级：
    - 写前通过 registry 查询相关章节摘要，增强上下文连贯性
    - 通过 entity_context 注入角色/阵营/伏笔的实时状态
    - 写完后自检禁用词和字数，必要时修正
    - 支持断流续写：_continuation_content 非空时从断点继续
    """
    system_prompt = _build_system_prompt(outline, entity_store=entity_store, chapter_outline=chapter_outline)

    # 写前上下文增强：从 registry 查询相关章节摘要
    extra_context = ""
    if registry and registry.has("search_chapter_summaries"):
        try:
            search_handler = registry.get_handler("search_chapter_summaries")
            keywords = chapter_outline.title
            if chapter_outline.core_events:
                keywords += " " + " ".join(chapter_outline.core_events[:2])
            search_result = search_handler({"query": keywords, "n": 3})
            if search_result.get("results"):
                context_lines = ["【相关前情回顾】"]
                for r in search_result["results"]:
                    context_lines.append(f"第{r['chapter_num']}章《{r['title']}》：{r['summary']}")
                extra_context = "\n".join(context_lines) + "\n\n"
        except Exception as e:
            logger.debug(f"章节摘要查询失败（非致命）: {e}")

    # 注入实体记忆上下文
    if entity_context:
        extra_context += entity_context + "\n\n"

    user_prompt = extra_context + _build_user_prompt(
        request, outline, chapter_outline, volume_title, previous_summary
    )

    # 断流续写：如果有已写内容，指示模型从断点继续
    if _continuation_content:
        # 只传最后 2000 字作为上下文，避免过长
        tail = _continuation_content[-2000:]
        user_prompt += f"""

【重要：以下是已写好的部分，请从断点处继续写作，不要重复已有内容】
--- 已完成部分 ---
{tail}
--- 请从此处继续 ---"""

    full_content = []

    try:
        async for text in client.stream(
            system_prompt,
            user_prompt,
            max_tokens=max(4000, request.words_per_chapter * 3),
            temperature=1.0,
        ):
            full_content.append(text)
            yield ("chunk", text)
    except Exception as e:
        partial = "".join(full_content).strip()
        if len(partial) >= 200:
            # 有足够内容可供续写，通知调用方
            logger.warning(f"流式写作中断（已缓存 {len(partial)} 字符）: {e}")
            yield ("stream_interrupted", {
                "partial_content": _continuation_content + partial,
                "error": str(e),
            })
            return
        else:
            # 内容太少，直接抛出让上层重试整章
            raise

    # 合并续写内容
    content = _continuation_content + "".join(full_content).strip()

    # 写后自检 & 修正
    content, self_check_issues = await _self_check_and_revise(
        client, content, request.words_per_chapter,
    )

    summary = await _make_summary(client, content, chapter_outline.title)
    volume_num = _get_volume_num(chapter_outline, outline)

    result = ChapterResult(
        volume_num=volume_num,
        chapter_num=chapter_outline.chapter_num,
        volume_chapter_num=chapter_outline.volume_chapter_num,
        title=chapter_outline.title,
        content=content,
        summary=summary,
        protagonist_power_end=chapter_outline.protagonist_power,
        consistency_issues=self_check_issues,
    )
    yield ("result", result)
