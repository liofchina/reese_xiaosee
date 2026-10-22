"""
ResumableRunner — 支持断点续写的网文生成引擎

检查点目录结构：
  checkpoints/{run_id}/
    request.json          - WebNovelRequest（含 mode）
    run.json              - 运行状态
    world.json            - WorldSetting
    characters.json       - {characters, antagonists}
    plot.json             - {title, plot_framework, volumes}
    outline_vol_{n}.json  - 第n卷章节细纲
    chapter_{n:04d}.json  - 第n章写作结果（流式写完立即存盘）

输出目录：
  output/{run_id}/
    vol_{n:03d}.md        - 每卷完成后立即导出
    novel.md              - 有界模式全书汇总
"""

import asyncio
import json
import logging
import os
import random
import signal
from datetime import datetime
from pathlib import Path

from core.llm_client import create_client, ProviderRateLimitError, ProviderUnavailableError, BudgetExceededError

logger = logging.getLogger(__name__)

from models.novel import (
    WebNovelRequest, WorldSetting, WebNovelOutline,
    CharacterProfile, AntagonistTier, PlotFramework, VolumePlan,
    ChapterOutlineItem, ChapterResult, Milestone,
)
from agents.world_builder import build_world
from agents.character_designer import design_characters
from agents.plot_planner import plan_plot
from agents.chapter_outliner import outline_volume
from agents.writer import write_chapter
from agents.consistency_checker import check_consistency
from agents.plot_extender import extend_plot
from domain.disciplines import resolve_disciplines, rotate_disciplines
from memory.entity_store import EntityStore
from memory.rhythm_tracker import RhythmTracker
from memory.extractor import extract_entity_changes
from memory.manager import MemoryManager

# ── 常量 ──────────────────────────────────────────────────────────────────────

EXTEND_WHEN_VOLUMES_LEFT = 2   # 剩余N卷时触发扩展
EXTEND_BY = 3                  # 每次扩展N卷
MAX_RETRY = 10                 # 最大重试次数
ROLLING_SUMMARY_WINDOW = 10    # 传给Writer的历史摘要窗口
VOL_SUMMARY_WINDOW = 3         # 传给Writer的卷摘要窗口
MAX_VOLUMES_INFINITE = int(os.environ.get("MAX_VOLUMES_INFINITE", "20"))  # 无限模式最大卷数


class ResumableRunner:
    def __init__(self, run_id: str, request: WebNovelRequest, checkpoint_dir: Path):
        self.run_id = run_id
        self.request = request
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.client = create_client()
        self._stop_requested = False
        # 统一记忆管理器（建议13）
        self.memory = MemoryManager()
        # 保留直接引用以兼容现有代码
        self.entity_store = self.memory.entity_store
        self.rhythm_tracker = self.memory.rhythm_tracker

    # ── 日志 ──────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        logger.info(f"[{self.run_id}] {msg}")

    # ── 检查点：原子读写 ───────────────────────────────────────────────────────

    def _ckpt(self, name: str) -> Path:
        return self.checkpoint_dir / f"{name}.json"

    def _load(self, name: str) -> dict | None:
        p = self._ckpt(name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 可能是上次写入一半时崩溃留下的损坏文件，忽略
            return None

    def _save(self, name: str, data):
        """原子写入：先写 .tmp 再 rename，防止写到一半时崩溃留下损坏文件"""
        p = self._ckpt(name)
        tmp = p.with_suffix(".tmp")
        if hasattr(data, "model_dump_json"):
            tmp.write_text(data.model_dump_json(), encoding="utf-8")
        else:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(p)

    def _update_run(self, **kwargs):
        current = self._load("run") or {}
        current.update(kwargs)
        current["updated_at"] = datetime.now().isoformat()
        self._save("run", current)

    # ── 重试包装器 ────────────────────────────────────────────────────────────

    async def _retry(self, fn, label: str):
        """指数退避重试，覆盖 rate limit / API overload / 网络错误"""
        for attempt in range(MAX_RETRY):
            if self._stop_requested:
                raise KeyboardInterrupt("收到停止信号")
            try:
                return await fn()

            except BudgetExceededError:
                # 预算超限不重试，直接停止
                raise

            except ProviderRateLimitError:
                delay = min(300, 2 ** (attempt + 1) + random.uniform(0, 2))
                self._log(f"  ⚠ Rate limit [{label}]，{delay:.0f}s 后重试（{attempt+1}/{MAX_RETRY}）")
                await asyncio.sleep(delay)

            except ProviderUnavailableError as e:
                delay = min(300, 2 ** (attempt + 1) * 3)
                self._log(f"  ⚠ API {e.status_code} [{label}]，{delay:.0f}s 后重试")
                await asyncio.sleep(delay)

            except (ConnectionError, TimeoutError, OSError) as e:
                delay = min(60, 2 ** attempt)
                self._log(f"  ⚠ 网络错误 [{label}]: {e}，{delay:.0f}s 后重试")
                await asyncio.sleep(delay)

        raise RuntimeError(f"[{label}] 已重试 {MAX_RETRY} 次，放弃")

    # ── 已完成章节 ────────────────────────────────────────────────────────────

    def _completed_chapter_nums(self) -> set[int]:
        nums = set()
        for p in self.checkpoint_dir.glob("chapter_*.json"):
            try:
                nums.add(int(p.stem.split("_")[1]))
            except (ValueError, IndexError):
                pass
        return nums

    def _load_rolling_summaries(self, completed: set[int]) -> list[str]:
        """从磁盘加载最近 ROLLING_SUMMARY_WINDOW 章摘要，用于跨会话连续性"""
        if not completed:
            return []
        recent = sorted(completed)[-ROLLING_SUMMARY_WINDOW:]
        summaries = []
        for num in recent:
            data = self._load(f"chapter_{num:04d}")
            if data and "summary" in data:
                summaries.append(f"第{num}章《{data.get('title', '')}》：{data['summary']}")
        return summaries

    def _load_volume_summaries(self) -> list[str]:
        """从磁盘加载所有卷摘要"""
        summaries = []
        for p in sorted(self.checkpoint_dir.glob("vol_summary_*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("summary"):
                summaries.append(f"第{data['volume_num']}卷《{data.get('title', '')}》：{data['summary']}")
        return summaries

    async def _generate_volume_summary(self, volume: VolumePlan, chapter_summaries: list[str]) -> str:
        """生成卷摘要（300字），用于长程上下文保持"""
        key = f"vol_summary_{volume.volume_num}"
        data = self._load(key)
        if data and data.get("summary"):
            return data["summary"]

        prompt = (
            f"请为以下小说卷写一段300字以内的摘要，包含：核心事件、角色变化、伏笔进展、本卷结局。\n\n"
            f"第{volume.volume_num}卷《{volume.title}》\n主题：{volume.theme}\n\n"
            f"各章摘要：\n" + "\n".join(chapter_summaries[-15:])
        )
        summary = await self._retry(
            lambda: self.client.complete(
                prompt=f"你是一个小说摘要助手。用简洁的中文概括剧情要点。\n\n{prompt}",
                max_tokens=500,
            ),
            f"卷摘要生成Vol{volume.volume_num}",
        )
        self._save(key, {
            "volume_num": volume.volume_num,
            "title": volume.title,
            "summary": summary,
        })
        self._log(f"  ✓ 第{volume.volume_num}卷摘要已生成")
        return summary

    def _save_entity_store(self):
        """保存实体记忆到检查点"""
        self._save("entity_store", self.entity_store.to_dict())

    def _load_entity_store(self):
        """从检查点恢复实体记忆"""
        data = self._load("entity_store")
        if data:
            self.entity_store = EntityStore.from_dict(data)
            self._log("  ✓ entity_store 已从检查点恢复")

    def _save_rhythm_tracker(self):
        """保存节奏追踪器到检查点"""
        self._save("rhythm_tracker", self.rhythm_tracker.to_dict())

    def _load_rhythm_tracker(self):
        """从检查点恢复节奏追踪器"""
        data = self._load("rhythm_tracker")
        if data:
            self.rhythm_tracker = RhythmTracker.from_dict(data)
            self._log("  ✓ rhythm_tracker 已从检查点恢复")

    def _save_all_trackers(self):
        """保存所有追踪器到检查点（通过 MemoryManager 统一管理）"""
        self.memory.save_all(lambda name, data: self._save(name, data))

    def _load_all_trackers(self):
        """从检查点恢复所有追踪器（通过 MemoryManager 统一管理）"""
        self.memory.load_all(lambda name: self._load(name))
        # 同步引用
        self.entity_store = self.memory.entity_store
        self.rhythm_tracker = self.memory.rhythm_tracker
        self._log("  ✓ 所有记忆子系统已从检查点恢复")

    # ── 主运行入口 ────────────────────────────────────────────────────────────

    async def run(self):
        self._log(f"▶ run_id={self.run_id}  mode={self.request.mode}")
        self._update_run(
            status="running",
            run_id=self.run_id,
            mode=self.request.mode,
            created_at=self._load("run").get("created_at", datetime.now().isoformat())
            if self._load("run") else datetime.now().isoformat(),
        )

        # 保存 request（首次运行时）
        if not self._ckpt("request").exists():
            self._save("request", self.request.model_dump())

        # ── Ollama 健康检查 & 模型预加载 ──────────────────────────────────
        if hasattr(self.client, 'health_check'):
            check = await self.client.health_check()
            if not check["ok"]:
                raise RuntimeError(f"Ollama 健康检查失败: {check['message']}")
            self._log(f"  ✓ Ollama 健康检查通过，可用模型: {', '.join(check['models'][:3])}")
            if hasattr(self.client, 'preload_model'):
                await self.client.preload_model()
                self._log(f"  ✓ 模型已预加载到 VRAM")

        # ── Stage 1: 世界构建 ──────────────────────────────────────────────
        # 学科解析
        disciplines = resolve_disciplines(
            self.request.genre,
            self.request.disciplines if self.request.disciplines else None,
        )
        self.request.disciplines = disciplines
        self._log(f"  ✓ 学科方向: {', '.join(disciplines)}")

        world = await self._stage_world()

        # ── Stage 2: 角色设计 ──────────────────────────────────────────────
        characters, antagonists = await self._stage_characters(world)

        # ── Stage 3: 剧情规划 ──────────────────────────────────────────────
        title, plot_framework, volumes = await self._stage_plot(world, characters, antagonists)

        # ── Stage 4-6: 逐卷 → 逐章（可恢复）─────────────────────────────
        completed_nums = self._completed_chapter_nums()
        rolling_summaries = self._load_rolling_summaries(completed_nums)
        volume_summaries = self._load_volume_summaries()
        self._load_all_trackers()
        self._log(f"  已完成 {len(completed_nums)} 章，继续从第 {max(completed_nums)+1 if completed_nums else 1} 章")

        volume_index = 0
        while True:
            # 无限模式：快接近规划末尾时自动扩展
            volumes = await self._maybe_extend(world, characters, antagonists, volumes, volume_index)

            if volume_index >= len(volumes):
                break  # 有界模式：规划完成

            volume = volumes[volume_index]

            # Stage 4: 生成本卷章节大纲（已有则跳过）
            chapter_outlines = await self._stage_outline(
                world, characters, antagonists, volume, volumes, volume_index
            )
            volume.chapters = chapter_outlines

            # 构建当前完整大纲对象（Writer 需要）
            # 长篇学科轮换：每 10 卷更换 2 个次要学科
            current_disciplines = rotate_disciplines(
                disciplines, volume.volume_num, self.request.genre
            )
            outline = WebNovelOutline(
                title=title,
                world=world,
                characters=characters,
                antagonists=antagonists,
                plot_framework=plot_framework,
                volumes=volumes,
                disciplines=current_disciplines,
            )

            # 首卷时初始化实体记忆（后续卷从检查点恢复）
            if volume_index == 0 and not self.entity_store.characters:
                self.entity_store.init_from_outline(outline)

            # Stage 5 & 6: 逐章写作
            self._log(f"\n── 第{volume.volume_num}卷《{volume.title}》 ──────────────────")
            for chapter_outline in chapter_outlines:
                if self._stop_requested:
                    self._log("收到停止信号，当前章完成后退出")
                    break

                num = chapter_outline.chapter_num

                if num in completed_nums:
                    self._log(f"  ✓ 第{num}章《{chapter_outline.title}》已完成，跳过")
                    continue

                self._log(f"  → 写作第{num}章《{chapter_outline.title}》"
                          f"{'（含爽点）' if chapter_outline.pleasure_point else ''}...")

                # 构建层级上下文：卷摘要 + 章节摘要 + 实体状态 + 节奏
                context_parts = []
                if volume_summaries:
                    recent_vol_summaries = volume_summaries[-VOL_SUMMARY_WINDOW:]
                    context_parts.append("【前卷回顾】\n" + "\n".join(recent_vol_summaries))
                if rolling_summaries:
                    context_parts.append("【近章摘要】\n" + "\n\n---\n".join(rolling_summaries[-5:]))
                entity_context = self.entity_store.get_writer_context(num)
                if entity_context:
                    context_parts.append(entity_context)
                rhythm_context = self.rhythm_tracker.get_context_for_writer()
                if rhythm_context:
                    context_parts.append(rhythm_context)
                previous_context = "\n\n".join(context_parts)

                chapter_result = await self._write_chapter_with_retry(
                    outline, chapter_outline, volume.title, previous_context
                )

                # deep 模式一致性校验
                if self.request.quality_mode == "deep":
                    self._log(f"  → 一致性校验第{num}章...")
                    chapter_result = await self._retry(
                        lambda cr=chapter_result, co=chapter_outline: check_consistency(
                            self.client, outline, co, cr, previous_context
                        ),
                        f"一致性校验第{num}章",
                    )

                # 立即存盘
                self._save(f"chapter_{num:04d}", chapter_result.model_dump())
                completed_nums.add(num)
                rolling_summaries.append(
                    f"第{num}章《{chapter_result.title}》：{chapter_result.summary}"
                )
                if len(rolling_summaries) > ROLLING_SUMMARY_WINDOW:
                    rolling_summaries.pop(0)

                # 提取实体状态变更并更新记忆
                try:
                    extraction = await self._retry(
                        lambda content=chapter_result.content: extract_entity_changes(
                            self.client, content,
                            known_characters=list(self.entity_store.characters.keys()),
                            known_factions=list(self.entity_store.factions.keys()),
                        ),
                        f"实体提取第{num}章",
                    )
                    self.entity_store.update_from_extraction(num, extraction)
                    self._save(f"extraction_{num:04d}", extraction)
                except Exception as e:
                    self._log(f"  ⚠ 实体提取失败（非致命）: {e}")
                    extraction = {}

                # 记录节奏
                self.rhythm_tracker.record_chapter(
                    num,
                    chapter_outline.pacing_type if hasattr(chapter_outline, 'pacing_type') else "buildup",
                    chapter_outline.emotional_beat if hasattr(chapter_outline, 'emotional_beat') else "",
                )

                # 实体记忆剪枝
                self.entity_store.prune(num)

                self._update_run(
                    completed_chapters=len(completed_nums),
                    last_chapter=num,
                    current_volume=volume.volume_num,
                )
                self._log(f"  ✓ 第{num}章完成")

            # 本卷完成，生成卷摘要 + 导出 + 保存记忆
            vol_chapter_summaries = []
            for ch in chapter_outlines:
                data = self._load(f"chapter_{ch.chapter_num:04d}")
                if data and "summary" in data:
                    vol_chapter_summaries.append(
                        f"第{ch.chapter_num}章：{data.get('summary', '')}"
                    )
            vol_summary = await self._generate_volume_summary(volume, vol_chapter_summaries)
            volume_summaries.append(f"第{volume.volume_num}卷《{volume.title}》：{vol_summary}")

            self._save_all_trackers()
            self._export_volume(volume, title)
            self._log(f"  📄 第{volume.volume_num}卷导出完成")
            volume_index += 1

            if self._stop_requested:
                break

        if not self._stop_requested and self.request.mode == "bounded":
            self._export_full_novel(volumes, title)
            self._update_run(status="completed", completed_chapters=len(completed_nums))
            cost = self.client.get_cost_summary()
            self._log(f"\n✅ 全书完成！共 {len(completed_nums)} 章")
            self._log(f"💰 总费用: ${cost['total_cost_usd']:.4f} "
                     f"({cost['total_calls']}次调用, {cost['total_tokens_in']+cost['total_tokens_out']:,} tokens)")
        else:
            self._update_run(status="paused", completed_chapters=len(completed_nums))
            cost = self.client.get_cost_summary()
            self._log(f"\n⏸ 已暂停，共完成 {len(completed_nums)} 章，可用 resume 继续")
            self._log(f"💰 当前费用: ${cost['total_cost_usd']:.4f} / ${cost['max_cost_usd']:.2f}")

    # ── 各阶段执行（有检查点则跳过）─────────────────────────────────────────

    async def _stage_world(self) -> WorldSetting:
        data = self._load("world")
        if data:
            self._log("  ✓ world 已有检查点")
            return WorldSetting(**data)
        self._log("  → 世界构建师正在设计力量体系...")
        result = await self._retry(
            lambda: build_world(self.client, self.request),
            "WorldBuilder",
        )
        self._save("world", result.model_dump())
        return result

    async def _stage_characters(self, world: WorldSetting) -> tuple[list[CharacterProfile], list[AntagonistTier]]:
        data = self._load("characters")
        if data:
            self._log("  ✓ characters 已有检查点")
            return (
                [CharacterProfile(**c) for c in data["characters"]],
                [AntagonistTier(**a) for a in data["antagonists"]],
            )
        self._log("  → 角色设计师正在设计人物档案...")
        characters, antagonists = await self._retry(
            lambda: design_characters(self.client, self.request, world),
            "CharacterDesigner",
        )
        self._save("characters", {
            "characters": [c.model_dump() for c in characters],
            "antagonists": [a.model_dump() for a in antagonists],
        })
        return characters, antagonists

    async def _stage_plot(
        self, world, characters, antagonists
    ) -> tuple[str, PlotFramework, list[VolumePlan]]:
        data = self._load("plot")
        if data:
            self._log("  ✓ plot 已有检查点")
            pf = data["plot_framework"]
            return (
                data["title"],
                PlotFramework(
                    ultimate_goal=pf["ultimate_goal"],
                    milestones=[Milestone(**m) for m in pf["milestones"]],
                    global_foreshadowing=pf.get("global_foreshadowing", []),
                ),
                [VolumePlan(**v) for v in data["volumes"]],
            )
        self._log("  → 剧情规划师正在规划里程碑事件...")
        title, plot_framework, volumes = await self._retry(
            lambda: plan_plot(self.client, self.request, world, characters, antagonists),
            "PlotPlanner",
        )
        self._save("plot", {
            "title": title,
            "plot_framework": plot_framework.model_dump(),
            "volumes": [v.model_dump() for v in volumes],
        })
        return title, plot_framework, volumes

    async def _stage_outline(
        self, world, characters, antagonists, volume, volumes, volume_index
    ) -> list[ChapterOutlineItem]:
        key = f"outline_vol_{volume.volume_num}"
        data = self._load(key)
        if data:
            self._log(f"  ✓ 第{volume.volume_num}卷大纲已有检查点")
            return [ChapterOutlineItem(**c) for c in data["chapters"]]

        prev_ending = volumes[volume_index - 1].ending_hook if volume_index > 0 else ""
        global_chapter_start = sum(
            len(volumes[i].chapters) for i in range(volume_index)
            if volumes[i].chapters
        ) + 1
        # 若前几卷尚无 chapters 数据（跨会话恢复），用 chapters_per_volume 估算
        if global_chapter_start == 1 and volume_index > 0:
            global_chapter_start = volume_index * self.request.chapters_per_volume + 1

        self._log(f"  → 章节大纲师正在规划第{volume.volume_num}卷...")
        chapter_outlines = await self._retry(
            lambda: outline_volume(
                self.client, self.request, world, characters, antagonists,
                volume, prev_ending, global_chapter_start,
            ),
            f"ChapterOutliner卷{volume.volume_num}",
        )
        self._save(key, {"chapters": [c.model_dump() for c in chapter_outlines]})
        return chapter_outlines

    # ── 章节写作（带重试 + 实时流式输出）────────────────────────────────────

    async def _write_chapter_with_retry(
        self,
        outline: WebNovelOutline,
        chapter_outline: ChapterOutlineItem,
        volume_title: str,
        previous_context: str,
    ) -> ChapterResult:
        chapter_result = None
        continuation_content = ""  # 跨重试保持，断流时累积已写内容

        async def _do():
            nonlocal chapter_result, continuation_content
            async for ev_type, ev_data in write_chapter(
                self.client, self.request, outline,
                chapter_outline, volume_title, previous_context,
                _continuation_content=continuation_content,
            ):
                if ev_type == "chunk":
                    pass  # 流式输出由 pipeline SSE 处理，CLI 模式下静默
                elif ev_type == "stream_interrupted":
                    continuation_content = ev_data["partial_content"]
                    self._log(f"\n  ⚠ 流中断，已缓存 {len(continuation_content)} 字符，将续写")
                    raise ConnectionError(ev_data["error"])
                elif ev_type == "result":
                    chapter_result = ev_data
            return chapter_result

        result = await self._retry(_do, f"写作第{chapter_outline.chapter_num}章")
        return result

    # ── 无限模式扩展 ──────────────────────────────────────────────────────────

    async def _maybe_extend(
        self, world, characters, antagonists, volumes, volume_index
    ) -> list[VolumePlan]:
        if self.request.mode != "infinite":
            return volumes
        # 无限模式卷数硬上限
        if len(volumes) >= MAX_VOLUMES_INFINITE:
            self._log(f"  ⚠ 已达无限模式卷数上限（{MAX_VOLUMES_INFINITE}卷），停止扩展")
            return volumes
        volumes_left = len(volumes) - volume_index
        if volumes_left > EXTEND_WHEN_VOLUMES_LEFT:
            return volumes

        self._log(f"  → 剩余 {volumes_left} 卷，扩展规划 {EXTEND_BY} 卷...")
        # 构建长程上下文：前3卷 + 中点卷 + 最近5卷摘要
        vol_sums = self._load_volume_summaries()
        story_parts = []
        if len(vol_sums) > 6:
            story_parts.extend(vol_sums[:3])
            mid = len(vol_sums) // 2
            story_parts.append(vol_sums[mid])
            story_parts.extend(vol_sums[-5:])
        else:
            story_parts = vol_sums
        story_so_far = "\n".join(story_parts) if story_parts else ""
        compressed_state = self.entity_store.get_compressed_state_summary(
            max(self._completed_chapter_nums()) if self._completed_chapter_nums() else 0
        )

        new_vols = await self._retry(
            lambda: extend_plot(
                self.client, self.request, world, characters, antagonists,
                volumes, EXTEND_BY,
                story_so_far=story_so_far,
                compressed_state=compressed_state,
            ),
            "PlotExtender",
        )
        volumes = volumes + new_vols

        # 更新 plot.json 中的 volumes 列表（不改 title/plot_framework）
        plot_data = self._load("plot")
        plot_data["volumes"] = [v.model_dump() for v in volumes]
        self._save("plot", plot_data)
        self._log(f"  ✓ 扩展完成，现已规划到第 {volumes[-1].volume_num} 卷")
        return volumes

    # ── Markdown 导出 ─────────────────────────────────────────────────────────

    def _export_volume(self, volume: VolumePlan, novel_title: str):
        out_dir = Path("output") / self.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        lines = [f"# {novel_title}\n", f"\n## 第{volume.volume_num}卷·{volume.title}\n\n> {volume.theme}\n"]
        for ch in volume.chapters:
            data = self._load(f"chapter_{ch.chapter_num:04d}")
            if not data:
                continue
            result = ChapterResult(**data)
            lines.append(f"\n### 第{result.volume_chapter_num}章·{result.title}\n")
            lines.append(result.content)
            if result.consistency_issues:
                lines.append(f"\n> *校验：{'|'.join(result.consistency_issues)}*")
            lines.append("")

        out_path = out_dir / f"vol_{volume.volume_num:03d}.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")

    def _export_full_novel(self, volumes: list[VolumePlan], novel_title: str):
        out_dir = Path("output") / self.run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        lines = [f"# {novel_title}\n"]
        for volume in volumes:
            lines.append(f"\n---\n## 第{volume.volume_num}卷·{volume.title}\n\n> {volume.theme}\n")
            for ch in volume.chapters:
                data = self._load(f"chapter_{ch.chapter_num:04d}")
                if not data:
                    continue
                result = ChapterResult(**data)
                lines.append(f"\n### 第{result.volume_chapter_num}章·{result.title}\n")
                lines.append(result.content)
                if result.consistency_issues:
                    lines.append(f"\n> *校验：{'|'.join(result.consistency_issues)}*")
                lines.append("")

        out_path = out_dir / "novel.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self._log(f"  📚 全书导出：{out_path}")
