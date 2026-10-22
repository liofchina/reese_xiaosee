"""NarrativePatternTracker 单元测试"""
import pytest
from memory.narrative_pattern_tracker import NarrativePatternTracker, KNOWN_PATTERNS


class TestRecord:
    def test_records_pattern(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        assert "underestimate_reveal" in npt.patterns
        assert 10 in npt.patterns["underestimate_reveal"]

    def test_prunes_old_records(self):
        npt = NarrativePatternTracker()
        npt.record(1, "underestimate_reveal")
        npt.record(50, "underestimate_reveal")
        npt.record(110, "underestimate_reveal")
        # chapter 1 should be pruned (110 - 100 = 10, 1 < 10)
        assert 1 not in npt.patterns["underestimate_reveal"]
        assert 50 in npt.patterns["underestimate_reveal"]
        assert 110 in npt.patterns["underestimate_reveal"]

    def test_multiple_patterns(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(15, "tournament_arc")
        assert len(npt.patterns) == 2


class TestGetFatiguedPatterns:
    def test_fatigued_when_threshold_reached(self):
        npt = NarrativePatternTracker()
        # 3 uses within 20-chapter window, last use within cooldown
        npt.record(10, "underestimate_reveal")
        npt.record(15, "underestimate_reveal")
        npt.record(22, "underestimate_reveal")
        fatigued = npt.get_fatigued_patterns(25)
        assert "underestimate_reveal" in fatigued

    def test_not_fatigued_below_threshold(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(15, "underestimate_reveal")
        # Only 2 uses < FATIGUE_THRESHOLD=3
        fatigued = npt.get_fatigued_patterns(25)
        assert "underestimate_reveal" not in fatigued

    def test_not_fatigued_after_cooldown(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(12, "underestimate_reveal")
        npt.record(14, "underestimate_reveal")
        # Check at chapter 30: last_use=14, 30-14=16 >= COOLDOWN=10
        fatigued = npt.get_fatigued_patterns(30)
        assert "underestimate_reveal" not in fatigued

    def test_not_fatigued_outside_window(self):
        npt = NarrativePatternTracker()
        # All uses outside the 20-chapter window
        npt.record(1, "underestimate_reveal")
        npt.record(3, "underestimate_reveal")
        npt.record(5, "underestimate_reveal")
        fatigued = npt.get_fatigued_patterns(30)  # window: 30-20=10, all < 10
        assert "underestimate_reveal" not in fatigued

    def test_multiple_fatigued_patterns(self):
        npt = NarrativePatternTracker()
        for ch in [10, 12, 14]:
            npt.record(ch, "underestimate_reveal")
            npt.record(ch, "tournament_arc")
        fatigued = npt.get_fatigued_patterns(16)
        assert "underestimate_reveal" in fatigued
        assert "tournament_arc" in fatigued

    def test_at_cooldown_boundary(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(12, "underestimate_reveal")
        npt.record(15, "underestimate_reveal")
        # chapter_num - last_use = 25 - 15 = 10, which is NOT < COOLDOWN=10
        fatigued = npt.get_fatigued_patterns(25)
        assert "underestimate_reveal" not in fatigued

    def test_just_inside_cooldown(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(12, "underestimate_reveal")
        npt.record(15, "underestimate_reveal")
        # chapter_num - last_use = 24 - 15 = 9 < COOLDOWN=10
        fatigued = npt.get_fatigued_patterns(24)
        assert "underestimate_reveal" in fatigued


class TestGetPatternStats:
    def test_returns_counts_in_window(self):
        npt = NarrativePatternTracker()
        npt.record(30, "underestimate_reveal")
        npt.record(35, "underestimate_reveal")
        npt.record(40, "tournament_arc")
        stats = npt.get_pattern_stats(50, window=50)
        assert stats["underestimate_reveal"] == 2
        assert stats["tournament_arc"] == 1

    def test_excludes_outside_window(self):
        npt = NarrativePatternTracker()
        npt.record(1, "underestimate_reveal")
        stats = npt.get_pattern_stats(50, window=10)  # window: 50-10=40, 1 < 40
        assert "underestimate_reveal" not in stats

    def test_sorted_by_count_descending(self):
        npt = NarrativePatternTracker()
        npt.record(10, "a")
        npt.record(11, "b")
        npt.record(12, "b")
        npt.record(13, "c")
        npt.record(14, "c")
        npt.record(15, "c")
        stats = npt.get_pattern_stats(20, window=50)
        keys = list(stats.keys())
        assert keys[0] == "c"
        assert keys[1] == "b"
        assert keys[2] == "a"

    def test_empty_returns_empty(self):
        npt = NarrativePatternTracker()
        assert npt.get_pattern_stats(10) == {}


class TestGetContextForOutliner:
    def test_empty_when_no_patterns(self):
        npt = NarrativePatternTracker()
        assert npt.get_context_for_outliner(10) == ""

    def test_includes_fatigued(self):
        npt = NarrativePatternTracker()
        for ch in [10, 12, 14]:
            npt.record(ch, "underestimate_reveal")
        ctx = npt.get_context_for_outliner(16)
        assert "疲劳" in ctx
        assert "禁用" in ctx

    def test_includes_stats(self):
        npt = NarrativePatternTracker()
        npt.record(10, "tournament_arc")
        ctx = npt.get_context_for_outliner(20)
        assert "统计" in ctx


class TestSerialization:
    def test_roundtrip(self):
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(20, "tournament_arc")

        data = npt.to_dict()
        restored = NarrativePatternTracker.from_dict(data)
        assert restored.patterns == npt.patterns
