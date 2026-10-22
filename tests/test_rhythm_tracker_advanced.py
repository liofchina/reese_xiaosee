"""RhythmTracker 高级单元测试"""
import pytest
from memory.rhythm_tracker import RhythmTracker, TENSION_MAP, ChapterRhythm


class TestRecordChapter:
    def test_records_with_correct_tension(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action")
        assert tracker.chapters[0].tension == TENSION_MAP["action"]
        assert tracker.chapters[0].pacing_type == "action"

    def test_unknown_pacing_defaults_to_05(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "unknown_type")
        assert tracker.chapters[0].tension == 0.5

    def test_max_chapters_pruning(self):
        tracker = RhythmTracker()
        for i in range(40):
            tracker.record_chapter(i + 1, "action")
        assert len(tracker.chapters) == RhythmTracker.MAX_CHAPTERS
        assert tracker.chapters[0].chapter_num == 11  # keeps last 30

    def test_stores_emotional_beat(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action", "紧张→燃→释然")
        assert tracker.chapters[0].emotional_beat == "紧张→燃→释然"


class TestValidateRhythm:
    def test_insufficient_data_no_warnings(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action")
        tracker.record_chapter(2, "buildup")
        assert tracker.validate_rhythm() == []

    def test_high_tension_streak(self):
        tracker = RhythmTracker()
        # action(0.9), turning_point(0.85), revelation(0.7) — all >= 0.7
        tracker.record_chapter(1, "action")
        tracker.record_chapter(2, "turning_point")
        tracker.record_chapter(3, "revelation")
        warnings = tracker.validate_rhythm()
        assert any("高张力" in w for w in warnings)

    def test_low_tension_streak(self):
        tracker = RhythmTracker()
        # aftermath(0.3), aftermath(0.3), aftermath(0.3) — all <= 0.4
        tracker.record_chapter(1, "aftermath")
        tracker.record_chapter(2, "aftermath")
        tracker.record_chapter(3, "aftermath")
        warnings = tracker.validate_rhythm()
        assert any("低张力" in w for w in warnings)

    def test_same_type_streak(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "buildup")
        tracker.record_chapter(2, "buildup")
        tracker.record_chapter(3, "buildup")
        warnings = tracker.validate_rhythm()
        assert any("同类型" in w for w in warnings)

    def test_varied_rhythm_no_warnings(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "buildup")    # 0.5
        tracker.record_chapter(2, "action")     # 0.9
        tracker.record_chapter(3, "aftermath")  # 0.3
        tracker.record_chapter(4, "revelation") # 0.7
        warnings = tracker.validate_rhythm()
        assert warnings == []

    def test_multiple_warnings_from_long_streak(self):
        tracker = RhythmTracker()
        for i in range(5):
            tracker.record_chapter(i + 1, "action")
        warnings = tracker.validate_rhythm()
        # 3 sliding windows of 3: (1,2,3), (2,3,4), (3,4,5)
        assert len(warnings) >= 3  # both high tension + same type for each window

    def test_only_checks_last_10(self):
        tracker = RhythmTracker()
        # Add 12 varied chapters
        types = ["action", "buildup", "aftermath", "revelation"] * 3
        for i, t in enumerate(types):
            tracker.record_chapter(i + 1, t)
        warnings = tracker.validate_rhythm()
        assert warnings == []  # varied types, no streaks

    def test_high_tension_boundary_at_0_7(self):
        tracker = RhythmTracker()
        # revelation is exactly 0.7 — should count as >= 0.7
        tracker.record_chapter(1, "revelation")  # 0.7
        tracker.record_chapter(2, "revelation")  # 0.7
        tracker.record_chapter(3, "revelation")  # 0.7
        warnings = tracker.validate_rhythm()
        assert any("高张力" in w for w in warnings)

    def test_low_tension_boundary_at_0_4(self):
        tracker = RhythmTracker()
        # Need tension <= 0.4: aftermath=0.3
        tracker.record_chapter(1, "aftermath")   # 0.3
        tracker.record_chapter(2, "aftermath")   # 0.3
        tracker.record_chapter(3, "aftermath")   # 0.3
        warnings = tracker.validate_rhythm()
        assert any("低张力" in w for w in warnings)


class TestGetContextForWriter:
    def test_empty_when_no_chapters(self):
        tracker = RhythmTracker()
        assert tracker.get_context_for_writer() == ""

    def test_includes_recent_chapters(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action")
        ctx = tracker.get_context_for_writer()
        assert "第1章" in ctx
        assert "动作" in ctx

    def test_includes_warning_when_present(self):
        tracker = RhythmTracker()
        for i in range(4):
            tracker.record_chapter(i + 1, "action")
        ctx = tracker.get_context_for_writer()
        assert "⚠" in ctx


class TestSerialization:
    def test_roundtrip(self):
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action", "紧张")
        tracker.record_chapter(2, "buildup", "期待")

        data = tracker.to_dict()
        restored = RhythmTracker.from_dict(data)
        assert len(restored.chapters) == 2
        assert restored.chapters[0].pacing_type == "action"
        assert restored.chapters[1].emotional_beat == "期待"
