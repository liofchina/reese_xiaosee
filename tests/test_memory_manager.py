"""
tests/test_memory_manager.py — MemoryManager 聚合管理器测试（精简版）
"""

import pytest

from memory.manager import MemoryManager
from memory.entity_store import CharacterState


class TestMemoryManagerUpdateAndRollback:
    def test_successful_update(self):
        mm = MemoryManager()
        mm.entity_store.characters["林逸"] = CharacterState(name="林逸", role_type="main")

        extraction = {
            "character_updates": [
                {"name": "林逸", "power_level": "炼气三层", "location": "丹房"}
            ],
        }
        mm.update_after_chapter(5, extraction, pacing_type="revelation", emotional_beat="震撼")

        assert mm.entity_store.characters["林逸"].power_level == "炼气三层"
        assert len(mm.rhythm_tracker.chapters) == 1

    def test_rollback_on_failure(self):
        mm = MemoryManager()
        mm.entity_store.characters["林逸"] = CharacterState(
            name="林逸", role_type="main", power_level="炼气一层",
        )
        mm.rhythm_tracker.record_chapter(1, "buildup", "期待")

        # 测试快照和恢复机制
        snapshot = mm._snapshot()
        mm.entity_store.characters["林逸"].power_level = "金丹期"
        mm.rhythm_tracker.record_chapter(99, "action", "燃")

        # 手动恢复
        mm._restore(snapshot)
        assert mm.entity_store.characters["林逸"].power_level == "炼气一层"
        assert len(mm.rhythm_tracker.chapters) == 1


class TestMemoryManagerSerialization:
    def test_save_and_load(self):
        mm = MemoryManager()
        mm.entity_store.characters["林逸"] = CharacterState(name="林逸", role_type="main")
        mm.rhythm_tracker.record_chapter(1, "buildup")

        # 模拟 save/load
        storage = {}

        def save_fn(name, data):
            storage[name] = data

        def load_fn(name):
            return storage.get(name)

        mm.save_all(save_fn)

        mm2 = MemoryManager()
        mm2.load_all(load_fn)

        assert "林逸" in mm2.entity_store.characters
        assert len(mm2.rhythm_tracker.chapters) == 1


class TestMemoryManagerPruning:
    def test_prune_all(self):
        mm = MemoryManager()
        mm.entity_store.characters["主角"] = CharacterState(
            name="主角", role_type="main", last_appearance=100, appearance_count=50,
        )
        mm.rhythm_tracker.record_chapter(1, "action")

        # 不应抛异常
        mm.prune_all(100)
        assert "主角" in mm.entity_store.characters
