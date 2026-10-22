"""
tests/test_memory.py — 记忆子系统测试
"""

import pytest

from memory.entity_store import EntityStore, CharacterState, FactionState
from memory.rhythm_tracker import RhythmTracker
from memory.dialogue_system import DialogueSystem, DialogueProfile
from memory.romance_tracker import RomanceTracker, RomanceState
from memory.foreshadowing_manager import ForeshadowingManager
from memory.emotion_curve_tracker import EmotionCurveTracker
from memory.narrative_pattern_tracker import NarrativePatternTracker


class TestEntityStore:
    def test_create_and_serialize(self):
        store = EntityStore()
        store.characters["林逸"] = CharacterState(
            name="林逸",
            power_level="炼气一层",
            location="青云宗",
            role_type="main",
        )
        data = store.to_dict()
        restored = EntityStore.from_dict(data)
        assert "林逸" in restored.characters
        assert restored.characters["林逸"].power_level == "炼气一层"

    def test_update_from_extraction(self):
        store = EntityStore()
        store.characters["林逸"] = CharacterState(name="林逸", role_type="main")
        extraction = {
            "character_updates": [
                {"name": "林逸", "power_level": "炼气三层", "location": "丹房"}
            ]
        }
        store.update_from_extraction(5, extraction)
        assert store.characters["林逸"].power_level == "炼气三层"
        assert store.characters["林逸"].location == "丹房"
        assert store.characters["林逸"].last_updated_chapter == 5

    def test_prune_keeps_active_characters(self):
        store = EntityStore()
        # 主角不会被剪枝
        store.characters["主角"] = CharacterState(
            name="主角", role_type="main", last_appearance=100, appearance_count=50,
        )
        # 很久没出场的配角
        store.characters["配角A"] = CharacterState(
            name="配角A", role_type="side", last_appearance=1, appearance_count=1,
            first_appearance=1,
        )
        store.prune(100)
        assert "主角" in store.characters
        # 配角可能被压缩但不会被删除（EntityStore.prune 只压缩 key_events）


class TestRhythmTracker:
    def test_record_and_serialize(self):
        rt = RhythmTracker()
        rt.record_chapter(1, "buildup", "期待")
        rt.record_chapter(2, "action", "热血")
        rt.record_chapter(3, "action", "紧张")

        data = rt.to_dict()
        restored = RhythmTracker.from_dict(data)
        assert len(restored.chapters) == 3

    def test_context_generation(self):
        rt = RhythmTracker()
        rt.record_chapter(1, "action", "热血")
        rt.record_chapter(2, "action", "紧张")
        rt.record_chapter(3, "action", "燃")
        ctx = rt.get_context_for_writer()
        # 连续3章高张力应该产生警告
        assert ctx  # 应有上下文输出


class TestDialogueSystem:
    def test_create_and_serialize(self):
        ds = DialogueSystem()
        ds.profiles["林逸"] = DialogueProfile(
            character_name="林逸",
            sentence_length="极短(3-8字)",
            tone="冷淡",
        )
        data = ds.to_dict()
        restored = DialogueSystem.from_dict(data)
        assert "林逸" in restored.profiles
        assert restored.profiles["林逸"].tone == "冷淡"

    def test_dialogue_context(self):
        ds = DialogueSystem()
        ds.profiles["主角"] = DialogueProfile(
            character_name="主角",
            tone="冷淡",
            verbal_tics=["哼"],
        )
        ds.profiles["师父"] = DialogueProfile(
            character_name="师父",
            tone="文绉绉",
        )
        ctx = ds.get_dialogue_context(["主角", "师父"], chapter_num=5)
        assert "主角" in ctx
        assert "师父" in ctx
        assert "冷淡" in ctx

    def test_empty_context(self):
        ds = DialogueSystem()
        ctx = ds.get_dialogue_context(["不存在的角色"])
        assert ctx == ""


class TestRomanceTracker:
    def test_create_and_serialize(self):
        rt = RomanceTracker()
        rt.romances["师姐"] = RomanceState(
            love_interest="师姐",
            protagonist="林逸",
            stage="acquaintance",
            stage_start_chapter=5,
        )
        data = rt.to_dict()
        restored = RomanceTracker.from_dict(data)
        assert "师姐" in restored.romances
        assert restored.romances["师姐"].stage == "acquaintance"

    def test_record_interaction(self):
        rt = RomanceTracker()
        rt.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="林逸",
        )
        rt.record_interaction(10, "林逸", "师姐", "并肩作战")
        assert rt.romances["师姐"].last_interaction_chapter == 10
        assert len(rt.romances["师姐"].key_moments) == 1

    def test_stagnation_warning(self):
        rt = RomanceTracker()
        rt.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="林逸",
            stage="tension", stage_start_chapter=1,
            last_interaction_chapter=5,
        )
        warnings = rt.check_stagnation(50)
        assert len(warnings) > 0  # 应有停滞警告


class TestForeshadowingManager:
    def test_plant_and_harvest(self):
        fm = ForeshadowingManager()
        fid = fm.plant(5, "某神秘老者留下的玉简", (20, 40))
        assert fm.get_open_count() == 1

        fm.harvest(25, fid, "玉简中藏着上古功法")
        assert fm.get_open_count() == 0

    def test_overdue_detection(self):
        fm = ForeshadowingManager()
        fm.plant(1, "远古遗迹的线索", (5, 10))
        overdue = fm.get_overdue(15)
        assert len(overdue) == 1

    def test_serialize(self):
        fm = ForeshadowingManager()
        fm.plant(5, "伏笔测试", (10, 20))
        data = fm.to_dict()
        restored = ForeshadowingManager.from_dict(data)
        assert restored.get_open_count() == 1


class TestEmotionCurveTracker:
    def test_record_and_serialize(self):
        ect = EmotionCurveTracker()
        ect.record(1, ["好奇", "紧张", "震撼"])
        ect.record(2, ["温馨", "感动", "期待"])

        data = ect.to_dict()
        restored = EmotionCurveTracker.from_dict(data)
        assert len(restored.chapter_emotions) == 2


class TestNarrativePatternTracker:
    def test_record_and_serialize(self):
        npt = NarrativePatternTracker()
        npt.record(1, "underestimate_reveal")
        npt.record(5, "tournament_arc")
        npt.record(8, "underestimate_reveal")

        data = npt.to_dict()
        restored = NarrativePatternTracker.from_dict(data)
        assert len(restored.patterns) >= 2

    def test_fatigue_detection(self):
        npt = NarrativePatternTracker()
        npt.record(1, "underestimate_reveal")
        npt.record(5, "underestimate_reveal")
        npt.record(10, "underestimate_reveal")
        fatigued = npt.get_fatigued_patterns(12)
        assert "underestimate_reveal" in fatigued
