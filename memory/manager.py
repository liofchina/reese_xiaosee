"""
MemoryManager — 精简版跨记忆系统聚合管理器

当前仅保留核心子系统：
- EntityStore: 角色/势力/物品状态追踪（保证一致性）
- RhythmTracker: 章节节奏追踪（保证叙事节奏）

其余子系统（DialogueSystem, RomanceTracker, NarrativePatternTracker,
ForeshadowingManager, EmotionCurveTracker）暂时禁用，
等核心pipeline稳定后再逐步启用。
"""

import copy
import logging
from pathlib import Path

from memory.entity_store import EntityStore
from memory.rhythm_tracker import RhythmTracker

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    精简版记忆管理器，仅保留核心追踪子系统。

    使用方式：
        mm = MemoryManager()
        mm.init_from_outline(outline)
        mm.update_after_chapter(chapter_num, extraction, pacing_type)
        mm.prune_all(chapter_num)
        mm.save_all(save_fn)
        mm.load_all(load_fn)
    """

    def __init__(self):
        self.entity_store = EntityStore()
        self.rhythm_tracker = RhythmTracker()

    def init_from_outline(self, outline) -> None:
        """从大纲初始化核心记忆子系统"""
        self.entity_store.init_from_outline(outline)

    def update_after_chapter(
        self,
        chapter_num: int,
        extraction: dict,
        pacing_type: str = "buildup",
        emotional_beat: str = "",
    ) -> None:
        """
        章节写完后，事务性更新记忆子系统。
        如果更新失败，回滚到更新前的状态。
        """
        snapshot = self._snapshot()

        try:
            # 1. 实体状态
            self.entity_store.update_from_extraction(chapter_num, extraction)

            # 2. 节奏追踪
            self.rhythm_tracker.record_chapter(chapter_num, pacing_type, emotional_beat)

        except Exception as e:
            logger.error(f"记忆更新失败，执行回滚: {e}")
            self._restore(snapshot)
            raise

    def prune_all(self, chapter_num: int) -> None:
        """统一剪枝（建议在每卷结束时调用）"""
        self.entity_store.prune(chapter_num)
        logger.info(f"记忆剪枝完成（chapter={chapter_num}）")

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def save_all(self, save_fn) -> None:
        """
        保存所有子系统到检查点。
        save_fn: 接收 (name, data) 的回调函数。
        """
        save_fn("entity_store", self.entity_store.to_dict())
        save_fn("rhythm_tracker", self.rhythm_tracker.to_dict())

    def load_all(self, load_fn) -> None:
        """
        从检查点恢复所有子系统。
        load_fn: 接收 (name) 返回 dict|None 的回调函数。
        """
        data = load_fn("entity_store")
        if data:
            self.entity_store = EntityStore.from_dict(data)

        data = load_fn("rhythm_tracker")
        if data:
            self.rhythm_tracker = RhythmTracker.from_dict(data)

    # ── 事务快照与回滚 ────────────────────────────────────────────────────────

    def _snapshot(self) -> dict:
        """创建所有子系统的深拷贝快照"""
        return {
            "entity_store": copy.deepcopy(self.entity_store),
            "rhythm_tracker": copy.deepcopy(self.rhythm_tracker),
        }

    def _restore(self, snapshot: dict) -> None:
        """从快照恢复所有子系统"""
        self.entity_store = snapshot["entity_store"]
        self.rhythm_tracker = snapshot["rhythm_tracker"]
