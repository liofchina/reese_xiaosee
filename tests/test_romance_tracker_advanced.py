"""RomanceTracker 高级单元测试（补充现有 test_memory.py 的基础测试）"""
import pytest
from memory.romance_tracker import (
    RomanceTracker, RomanceState,
    ROMANCE_STAGES, STAGE_MIN_CHAPTERS, INTERACTION_WARNING_GAP,
)


class TestAdvanceStage:
    def _make_tracker(self, stage="stranger", stage_start=1, love_interest="师姐"):
        tracker = RomanceTracker()
        tracker.romances[love_interest] = RomanceState(
            love_interest=love_interest,
            protagonist="主角",
            stage=stage,
            stage_start_chapter=stage_start,
        )
        return tracker

    def test_normal_advance(self):
        tracker = self._make_tracker(stage="stranger", stage_start=1)
        tracker.advance_stage("师姐", chapter_num=1 + STAGE_MIN_CHAPTERS)
        assert tracker.romances["师姐"].stage == "acquaintance"
        assert tracker.romances["师姐"].stage_start_chapter == 1 + STAGE_MIN_CHAPTERS

    def test_too_fast_no_advance(self):
        tracker = self._make_tracker(stage="stranger", stage_start=1)
        tracker.advance_stage("师姐", chapter_num=3)  # only 2 chapters, < STAGE_MIN_CHAPTERS
        assert tracker.romances["师姐"].stage == "stranger"  # 未变

    def test_at_last_stage_no_advance(self):
        tracker = self._make_tracker(stage="together", stage_start=1)
        tracker.advance_stage("师姐", chapter_num=100)
        assert tracker.romances["师姐"].stage == "together"  # 已是最终阶段

    def test_unknown_love_interest_no_op(self):
        tracker = self._make_tracker()
        tracker.advance_stage("不存在的人", chapter_num=100)
        # 不应抛异常

    def test_advances_through_all_stages(self):
        tracker = self._make_tracker(stage="stranger", stage_start=0)
        chapter = 0
        for expected_next in ROMANCE_STAGES[1:]:
            chapter += STAGE_MIN_CHAPTERS
            tracker.advance_stage("师姐", chapter)
            assert tracker.romances["师姐"].stage == expected_next

    def test_exact_min_chapters_boundary(self):
        tracker = self._make_tracker(stage="friend", stage_start=10)
        # exactly STAGE_MIN_CHAPTERS later
        tracker.advance_stage("师姐", chapter_num=10 + STAGE_MIN_CHAPTERS)
        assert tracker.romances["师姐"].stage == "tension"

    def test_one_less_than_min_chapters(self):
        tracker = self._make_tracker(stage="friend", stage_start=10)
        tracker.advance_stage("师姐", chapter_num=10 + STAGE_MIN_CHAPTERS - 1)
        assert tracker.romances["师姐"].stage == "friend"  # 不推进


class TestCheckStagnation:
    def _make_tracker(self, stage="tension", stage_start=1, last_interaction=5):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐",
            protagonist="主角",
            stage=stage,
            stage_start_chapter=stage_start,
            last_interaction_chapter=last_interaction,
        )
        return tracker

    def test_no_interaction_warning(self):
        tracker = self._make_tracker(last_interaction=5)
        warnings = tracker.check_stagnation(5 + INTERACTION_WARNING_GAP + 1)
        assert any("停滞" in w for w in warnings)

    def test_recent_interaction_no_warning(self):
        tracker = self._make_tracker(last_interaction=20)
        warnings = tracker.check_stagnation(25)  # gap=5 < 10
        assert not any("停滞" in w for w in warnings)

    def test_stage_too_long_warning(self):
        tracker = self._make_tracker(stage="tension", stage_start=1, last_interaction=15)
        # stage_duration = 20 - 1 = 19 > STAGE_MIN_CHAPTERS * 3 = 15
        warnings = tracker.check_stagnation(20)
        assert any("拖沓" in w for w in warnings)

    def test_together_stage_exempt_from_dragging(self):
        tracker = self._make_tracker(stage="together", stage_start=1, last_interaction=50)
        warnings = tracker.check_stagnation(60)
        assert not any("拖沓" in w for w in warnings)

    def test_stranger_stage_exempt_from_dragging(self):
        tracker = self._make_tracker(stage="stranger", stage_start=1, last_interaction=50)
        warnings = tracker.check_stagnation(60)
        assert not any("拖沓" in w for w in warnings)

    def test_no_romances_empty_list(self):
        tracker = RomanceTracker()
        assert tracker.check_stagnation(100) == []

    def test_last_interaction_zero_no_gap_warning(self):
        tracker = self._make_tracker(last_interaction=0)
        warnings = tracker.check_stagnation(50)
        # last_interaction=0 条件不满足 (rs.last_interaction_chapter > 0)
        assert not any("停滞" in w for w in warnings)


class TestRecordInteraction:
    def test_records_moment(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
        )
        tracker.record_interaction(10, "主角", "师姐", "并肩作战")
        assert tracker.romances["师姐"].last_interaction_chapter == 10
        assert "第10章：并肩作战" in tracker.romances["师姐"].key_moments

    def test_unknown_characters_no_op(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
        )
        tracker.record_interaction(10, "路人甲", "路人乙", "对话")
        assert tracker.romances["师姐"].last_interaction_chapter == 0

    def test_max_key_moments_pruning(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
        )
        for i in range(25):
            tracker.record_interaction(i + 1, "主角", "师姐", f"事件{i}")
        assert len(tracker.romances["师姐"].key_moments) == RomanceTracker.MAX_KEY_MOMENTS


class TestGetContextForWriter:
    def test_empty_when_no_romances(self):
        tracker = RomanceTracker()
        assert tracker.get_context_for_writer(10) == ""

    def test_includes_stage_and_moments(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
            stage="tension", last_interaction_chapter=5,
            key_moments=["第5章：对视"],
        )
        ctx = tracker.get_context_for_writer(8)
        assert "暧昧" in ctx
        assert "第5章：对视" in ctx

    def test_warns_long_gap(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
            stage="tension", last_interaction_chapter=5,
        )
        ctx = tracker.get_context_for_writer(15)  # gap=10 > 5
        assert "未互动" in ctx


class TestSerialization:
    def test_roundtrip(self):
        tracker = RomanceTracker()
        tracker.romances["师姐"] = RomanceState(
            love_interest="师姐", protagonist="主角",
            stage="tension", stage_start_chapter=5,
            key_moments=["第5章：对视"], last_interaction_chapter=8,
            unresolved_tension="暗中观察",
        )
        data = tracker.to_dict()
        restored = RomanceTracker.from_dict(data)
        assert restored.romances["师姐"].stage == "tension"
        assert restored.romances["师姐"].unresolved_tension == "暗中观察"
