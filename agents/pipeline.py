"""
六 Agent 网文生成流水线：
WorldBuilder → CharacterDesigner → PlotPlanner → ChapterOutliner(×N卷) → Writer(×N章) → ConsistencyChecker(deep)

升级：
- 新增 thinking SSE 事件（展示 Agent 推理过程）
- 支持 Human-in-the-Loop（interactive 模式下用户可审批/修改每个 Agent 的输出）
- 支持 ConsistencyChecker 自动修正反馈

SSE 事件格式：(event_type, data)
- ("status", str)
- ("world_ready", dict)            — WorldSetting
- ("characters_ready", dict)       — {characters, antagonists}
- ("plot_ready", dict)             — {title, plot_framework, volumes}
- ("thinking", dict)               — {agent, text}  ★ 新增：Agent 推理过程
- ("volume_outline_ready", dict)   — {volume_num, title, chapters}
- ("chapter_start", dict)          — {volume_num, chapter_num, volume_chapter_num, title}
- ("chunk", str)
- ("checker_start", int)           — chapter_num
- ("correction_applied", dict)     — ★ 新增：自动修正已应用
- ("chapter_done", dict)           — ChapterResult
- ("approval_required", dict)      — ★ 新增：请求用户审批
- ("novel_complete", dict)         — {title}
- ("cancelled", str)
- ("error", str)
"""

import asyncio
import logging
import random
from core.llm_client import create_client, ProviderRateLimitError, ProviderUnavailableError, BudgetExceededError
from models.novel import WebNovelRequest, WebNovelOutline, WebNovelResult
from agents.world_builder import build_world
from agents.character_designer import design_characters
from agents.plot_planner import plan_plot
from agents.chapter_outliner import outline_volume
from agents.writer import write_chapter
from agents.consistency_checker import check_consistency
from agents.quality_critic import evaluate_quality
from domain.disciplines import resolve_disciplines
from tools.registry import ToolRegistry
from tools.reference_tools import register_reference_tools
from memory.entity_store import EntityStore
from memory.extractor import extract_entity_changes
from memory.rhythm_tracker import RhythmTracker
from core.observability import Tracer, LLMCallTrace
from core.guardrails import sanitize_input, scan_output, get_guardrail_level

logger = logging.getLogger(__name__)

_MAX_RETRY = 8


async def _retry(fn, label: str, queue: asyncio.Queue | None = None):
    """指数退避重试，覆盖 rate limit / API overload / 网络错误"""
    for attempt in range(_MAX_RETRY):
        try:
            return await fn()
        except BudgetExceededError:
            raise
        except ProviderRateLimitError:
            delay = min(300, 2 ** (attempt + 1) + random.uniform(0, 2))
            logger.warning(f"Rate limit [{label}]，{delay:.0f}s 后重试（{attempt+1}/{_MAX_RETRY}）")
            if queue:
                await queue.put(("status", f"⚠ API 限速，{delay:.0f}s 后重试..."))
            await asyncio.sleep(delay)
        except ProviderUnavailableError as e:
            delay = min(300, 2 ** (attempt + 1) * 3)
            logger.warning(f"API {e.status_code} [{label}]，{delay:.0f}s 后重试")
            if queue:
                await queue.put(("status", f"⚠ API 暂时不可用，{delay:.0f}s 后重试..."))
            await asyncio.sleep(delay)
        except (ConnectionError, TimeoutError, OSError) as e:
            delay = min(60, 2 ** attempt)
            logger.warning(f"网络错误 [{label}]: {e}，{delay:.0f}s 后重试")
            if queue:
                await queue.put(("status", f"⚠ 网络错误，{delay:.0f}s 后重试..."))
            await asyncio.sleep(delay)
    raise RuntimeError(f"[{label}] 已重试 {_MAX_RETRY} 次，放弃")


async def _wait_approval(
    queue: asyncio.Queue,
    in_queue: asyncio.Queue | None,
    agent_name: str,
    data: dict,
    editable_fields: list[str],
) -> dict | None:
    """
    请求用户审批。返回 ApprovalResponse dict 或 None（超时/非交互模式）。
    """
    if in_queue is None:
        return None

    import uuid
    checkpoint_id = str(uuid.uuid4())[:8]

    await queue.put(("approval_required", {
        "checkpoint_id": checkpoint_id,
        "agent_name": agent_name,
        "data": data,
        "editable_fields": editable_fields,
    }))

    try:
        response = await asyncio.wait_for(in_queue.get(), timeout=600)  # 10 分钟超时
        return response
    except asyncio.TimeoutError:
        logger.warning(f"审批超时（{agent_name}），自动通过")
        return {"action": "approve"}


async def run_pipeline(
    request: WebNovelRequest,
    queue: asyncio.Queue,
    cancel_event: asyncio.Event,
    in_queue: asyncio.Queue | None = None,
    task_id: str = "",
) -> None:
    try:
        client = create_client()
        interactive = getattr(request, "interactive", False) and in_queue is not None

        # ── 初始化追踪器 ─────────────────────────────────
        tracer = Tracer(task_id=task_id) if task_id else None

        # ── Ollama 健康检查 & 模型预加载 ─────────────────
        if hasattr(client, 'health_check'):
            check = await client.health_check()
            if not check["ok"]:
                await queue.put(("error", f"Ollama 健康检查失败: {check['message']}"))
                return
            await queue.put(("status", f"Ollama 已连接，模型: {client.model}"))
            if hasattr(client, 'preload_model'):
                await client.preload_model()

        # ── 输入安全护栏（已在 main.py 入口层前置，此处做二次检查）─────
        if get_guardrail_level() != "none":
            text_fields = [
                ("protagonist_background", request.protagonist_background),
                ("golden_finger", request.golden_finger),
                ("world_desc", request.world_desc),
            ]
            for field_name, field_val in text_fields:
                if field_val:
                    sanitized, warnings = sanitize_input(field_val)
                    if warnings:
                        logger.warning(f"输入护栏警告 ({field_name}): {warnings}")
                        await queue.put(("status", f"⚠ 输入安全检查: {'; '.join(warnings)}"))
                    setattr(request, field_name, sanitized)

        # ── 学科解析 ─────────────────────────────────────
        disciplines = resolve_disciplines(
            request.genre,
            request.disciplines if request.disciplines else None,
        )
        request.disciplines = disciplines
        await queue.put(("disciplines_resolved", {
            "disciplines": disciplines, "genre": request.genre,
        }))

        # ── Agent 1: WorldBuilder ─────────────────────────────────
        await queue.put(("status", "世界构建师正在设计力量体系与势力格局..."))
        world = await _retry(lambda: build_world(client, request), "WorldBuilder", queue)
        await queue.put(("world_ready", world.model_dump()))

        if cancel_event.is_set():
            await queue.put(("cancelled", "用户已取消"))
            return

        # Human-in-the-Loop: 用户审批世界观
        if interactive:
            approval = await _wait_approval(
                queue, in_queue, "world_builder",
                world.model_dump(),
                ["description", "resource_system", "special_rules"],
            )
            if approval and approval.get("action") == "reject":
                # 重跑，注入反馈（简化处理：重跑一次）
                await queue.put(("status", f"根据反馈重新构建世界观: {approval.get('feedback', '')}"))
                world = await build_world(client, request)
                await queue.put(("world_ready", world.model_dump()))

        # ── Agent 2: CharacterDesigner ───────────────────────────
        await queue.put(("status", "角色设计师正在设计人物档案与反派梯队..."))
        characters, antagonists = await _retry(
            lambda: design_characters(client, request, world), "CharacterDesigner", queue
        )
        await queue.put(("characters_ready", {
            "characters": [c.model_dump() for c in characters],
            "antagonists": [a.model_dump() for a in antagonists],
        }))

        if cancel_event.is_set():
            await queue.put(("cancelled", "用户已取消"))
            return

        # Human-in-the-Loop: 用户审批人物设计
        if interactive:
            approval = await _wait_approval(
                queue, in_queue, "character_designer",
                {
                    "characters": [c.model_dump() for c in characters],
                    "antagonists": [a.model_dump() for a in antagonists],
                },
                ["characters", "antagonists"],
            )
            if approval and approval.get("action") == "reject":
                await queue.put(("status", f"根据反馈重新设计人物: {approval.get('feedback', '')}"))
                characters, antagonists = await design_characters(client, request, world)
                await queue.put(("characters_ready", {
                    "characters": [c.model_dump() for c in characters],
                    "antagonists": [a.model_dump() for a in antagonists],
                }))

        # ── Agent 3: PlotPlanner ─────────────────────────────────
        await queue.put(("status", "剧情规划师正在深度思考里程碑事件与分卷结构..."))
        title, plot_framework, volumes = await _retry(
            lambda: plan_plot(client, request, world, characters, antagonists),
            "PlotPlanner", queue,
        )

        # 推送 thinking 事件（如果有）
        thinking_text = getattr(plot_framework, "_thinking_text", "")
        if thinking_text:
            await queue.put(("thinking", {"agent": "plot_planner", "text": thinking_text}))

        await queue.put(("plot_ready", {
            "title": title,
            "plot_framework": plot_framework.model_dump(),
            "volumes": [v.model_dump() for v in volumes],
        }))

        if cancel_event.is_set():
            await queue.put(("cancelled", "用户已取消"))
            return

        # Human-in-the-Loop: 用户审批剧情规划
        if interactive:
            approval = await _wait_approval(
                queue, in_queue, "plot_planner",
                {
                    "title": title,
                    "plot_framework": plot_framework.model_dump(),
                    "volumes": [v.model_dump() for v in volumes],
                },
                ["title", "volumes"],
            )
            if approval and approval.get("action") == "reject":
                await queue.put(("status", f"根据反馈重新规划剧情: {approval.get('feedback', '')}"))
                title, plot_framework, volumes = await plan_plot(
                    client, request, world, characters, antagonists
                )
                thinking_text = getattr(plot_framework, "_thinking_text", "")
                if thinking_text:
                    await queue.put(("thinking", {"agent": "plot_planner", "text": thinking_text}))
                await queue.put(("plot_ready", {
                    "title": title,
                    "plot_framework": plot_framework.model_dump(),
                    "volumes": [v.model_dump() for v in volumes],
                }))

        # ── Agent 4: ChapterOutliner (逐卷) ──────────────────────
        global_chapter_start = 1
        all_chapter_outlines = []   # 按顺序存所有章节细纲

        for volume in volumes:
            if cancel_event.is_set():
                await queue.put(("cancelled", "用户已取消"))
                return

            prev_ending = volumes[volume.volume_num - 2].ending_hook if volume.volume_num > 1 else ""
            await queue.put((
                "status",
                f"章节大纲师正在深度思考第{volume.volume_num}卷《{volume.title}》的章节钩子..."
            ))

            chapter_outlines = await _retry(
                lambda v=volume, pe=prev_ending, gcs=global_chapter_start: outline_volume(
                    client, request, world, characters, antagonists,
                    v, pe, gcs,
                ),
                f"ChapterOutliner卷{volume.volume_num}", queue,
            )

            # 推送 thinking 事件（如果有）
            if chapter_outlines:
                ch_thinking = getattr(chapter_outlines[0], "_thinking_text", "")
                if ch_thinking:
                    await queue.put(("thinking", {
                        "agent": f"chapter_outliner_vol{volume.volume_num}",
                        "text": ch_thinking,
                    }))

            volume.chapters = chapter_outlines
            all_chapter_outlines.extend(chapter_outlines)
            global_chapter_start += len(chapter_outlines)

            await queue.put(("volume_outline_ready", {
                "volume_num": volume.volume_num,
                "title": volume.title,
                "chapters": [c.model_dump() for c in chapter_outlines],
            }))

        # 构建完整大纲对象
        outline = WebNovelOutline(
            title=title,
            world=world,
            characters=characters,
            antagonists=antagonists,
            plot_framework=plot_framework,
            volumes=volumes,
            disciplines=disciplines,
        )

        # ── 注册共享参考工具 ─────────────────────────────────
        registry = ToolRegistry()
        register_reference_tools(registry, outline=outline, chapters=[])

        # ── 初始化实体记忆 ───────────────────────────────────
        entity_store = EntityStore()
        entity_store.init_from_outline(outline)

        # ── 初始化节奏追踪器 ─────────────────────────────────
        rhythm_tracker = RhythmTracker()

        # ── Agent 5 & 6: Writer → ConsistencyChecker (逐章) ─────
        all_results = []
        previous_summary = ""

        # 预构建 chapter_num → volume 映射，避免 O(N²) 查找
        _chapter_to_volume = {}
        for v in volumes:
            for ch in v.chapters:
                _chapter_to_volume[ch.chapter_num] = v

        for chapter_outline in all_chapter_outlines:
            if cancel_event.is_set():
                await queue.put(("cancelled", "用户已取消"))
                return

            # 找到所属卷
            volume = _chapter_to_volume.get(chapter_outline.chapter_num, volumes[0])

            await queue.put(("chapter_start", {
                "volume_num": volume.volume_num,
                "chapter_num": chapter_outline.chapter_num,
                "volume_chapter_num": chapter_outline.volume_chapter_num,
                "title": chapter_outline.title,
                "pleasure_point": chapter_outline.pleasure_point,
            }))
            await queue.put((
                "status",
                f"写作第{chapter_outline.chapter_num}章《{chapter_outline.title}》"
                f"{'（含爽点）' if chapter_outline.pleasure_point else ''}..."
            ))

            # 原生异步流式写作
            chapter_result = None
            # 合并实体上下文 + 节奏上下文
            entity_ctx = entity_store.get_writer_context(chapter_outline.chapter_num)
            rhythm_ctx = rhythm_tracker.get_context_for_writer()
            combined_context = entity_ctx
            if rhythm_ctx:
                combined_context += ("\n\n" + rhythm_ctx) if combined_context else rhythm_ctx

            async for ev_type, ev_data in write_chapter(
                client, request, outline, chapter_outline,
                volume.title, previous_summary,
                registry=registry,
                entity_context=combined_context,
                entity_store=entity_store,
            ):
                if ev_type == "chunk":
                    await queue.put(("chunk", ev_data))
                elif ev_type == "result":
                    chapter_result = ev_data

            if cancel_event.is_set():
                await queue.put(("cancelled", "用户已取消"))
                return

            # ── Agent 6: ConsistencyChecker (deep 模式) ──────────
            if request.quality_mode == "deep" and chapter_result:
                await queue.put(("checker_start", chapter_outline.chapter_num))
                await queue.put(("status", f"一致性校验第{chapter_outline.chapter_num}章..."))

                original_content = chapter_result.content
                chapter_result = await _retry(
                    lambda cr=chapter_result, co=chapter_outline, ps=previous_summary, ec=entity_ctx: check_consistency(
                        client, outline, co, cr, ps, entity_context=ec,
                    ),
                    f"ConsistencyChecker第{chapter_outline.chapter_num}章", queue,
                )

                # 检测是否发生了自动修正
                if chapter_result.content != original_content:
                    await queue.put(("correction_applied", {
                        "chapter_num": chapter_outline.chapter_num,
                        "hook_strength": chapter_result.hook_strength,
                        "issues_fixed": len([
                            i for i in chapter_result.consistency_issues
                            if "[自动修正]" in i
                        ]),
                    }))

            # ── 质量评审（deep 模式）──────────────────────────
            if request.quality_mode == "deep" and chapter_result:
                await queue.put(("status", f"质量评审第{chapter_outline.chapter_num}章..."))
                quality_eval = await _retry(
                    lambda co=chapter_outline, cr=chapter_result: evaluate_quality(
                        client, co, cr, core_pleasure=request.core_pleasure,
                    ),
                    f"QualityEvaluator第{chapter_outline.chapter_num}章", queue,
                )
                if quality_eval.get("overall_score", -1) > 0:
                    await queue.put(("quality_review", {
                        "chapter_num": chapter_outline.chapter_num,
                        "overall_score": quality_eval["overall_score"],
                        "excitement_score": quality_eval["excitement_score"],
                        "pacing_score": quality_eval["pacing_score"],
                        "immersion_score": quality_eval["immersion_score"],
                        "page_turner_score": quality_eval["page_turner_score"],
                        "needs_rewrite": quality_eval["needs_rewrite"],
                        "strengths": quality_eval.get("strengths", []),
                        "improvements": quality_eval.get("improvements", []),
                    }))

                    # 质量门控：低分触发重写（每章最多1次）
                    if (quality_eval.get("needs_rewrite") or quality_eval.get("overall_score", 10) < 5) and chapter_result:
                        improvements = quality_eval.get("improvements", [])
                        if improvements:
                            # 精准局部修正：每次只修 1-2 个最严重的问题
                            top_issues = improvements[:2]
                            fix_instruction = (
                                "请精准修正以下问题段落，只改动有问题的段落±1段，其余内容原封不动返回：\n"
                                + "\n".join(f"- {imp}" for imp in top_issues)
                                + "\n\n注意：不要重写整章！只修改有问题的具体段落，返回完整章节内容。"
                            )
                            await queue.put(("status", f"精准修正第{chapter_outline.chapter_num}章（质量评分{quality_eval['overall_score']}分）..."))
                            try:
                                rewrite_parts = []
                                async for text in client.stream(
                                    "你是一位网文精修编辑。只修改指出的问题段落（±1段范围），其余内容必须原封不动。",
                                    f"{fix_instruction}\n\n原文：\n{chapter_result.content}",
                                    max_tokens=max(4000, len(chapter_result.content) * 2),
                                    temperature=0.5,
                                ):
                                    rewrite_parts.append(text)
                                revised = "".join(rewrite_parts).strip()
                                if revised and len(revised) > len(chapter_result.content) * 0.7:
                                    chapter_result.content = revised
                                    chapter_result.consistency_issues.append(
                                        f"[精准修正] 评分{quality_eval['overall_score']}→修正{len(top_issues)}处"
                                    )
                            except Exception as e:
                                logger.warning(f"质量精准修正失败（非致命）: {e}")

            if chapter_result:
                # ── 输出安全扫描 ──────────────────────────────
                if get_guardrail_level() != "none":
                    scanned_content, output_flags = scan_output(chapter_result.content)
                    if output_flags:
                        logger.warning(f"输出护栏标记（第{chapter_outline.chapter_num}章）: {output_flags}")
                        chapter_result.content = scanned_content

                all_results.append(chapter_result)
                previous_summary = chapter_result.summary
                await queue.put(("chapter_done", chapter_result.model_dump()))

                # 更新章节摘要搜索工具（新章节可被后续 Agent 查询）
                register_reference_tools(registry, outline=outline, chapters=all_results)

                # 提取实体状态变更并更新记忆
                try:
                    extraction = await extract_entity_changes(
                        client,
                        chapter_result.content,
                        known_characters=list(entity_store.characters.keys()),
                        known_factions=list(entity_store.factions.keys()),
                    )
                    entity_store.update_from_extraction(
                        chapter_outline.chapter_num, extraction
                    )
                except Exception as e:
                    logger.warning(f"实体提取失败（非致命，第{chapter_outline.chapter_num}章）: {e}")

                # 记录章节节奏
                rhythm_tracker.record_chapter(
                    chapter_outline.chapter_num,
                    chapter_outline.pacing_type or "buildup",
                    chapter_outline.emotional_beat or "",
                )

        novel = WebNovelResult(title=title, outline=outline, chapters=all_results)

        # 发送追踪摘要
        if tracer:
            await queue.put(("trace_summary", tracer.get_summary()))

        await queue.put(("novel_complete", {"title": title}))

        # 存到队列的一个特殊槽位，供 main.py 取用保存
        await queue.put(("_novel_object", novel))

    except asyncio.CancelledError:
        logger.info("Pipeline 已取消")
        await queue.put(("cancelled", "任务已取消"))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Pipeline 收到终止信号")
        await queue.put(("cancelled", "系统终止"))
    except Exception as e:
        logger.exception("Pipeline 异常")
        await queue.put(("error", str(e)))


def _get_volume_num(chapter_outline, volumes) -> int:
    for vol in volumes:
        for ch in vol.chapters:
            if ch.chapter_num == chapter_outline.chapter_num:
                return vol.volume_num
    return 1
