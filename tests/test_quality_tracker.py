"""QualityTracker 单元测试"""
import pytest
from memory.quality_tracker import QualityTracker, ChapterQuality


class TestRecord:
    def test_records_chapter(self):
        tracker = QualityTracker()
        tracker.record(1, {"overall_score": 7.5, "originality_score": 6.0})
        assert len(tracker.records) == 1
        assert tracker.records[0].chapter_num == 1
        assert tracker.records[0].overall_score == 7.5

    def test_defaults_to_negative_one(self):
        tracker = QualityTracker()
        tracker.record(1, {})
        assert tracker.records[0].overall_score == -1
        assert tracker.records[0].excitement_score == -1

    def test_max_records_pruning(self):
        tracker = QualityTracker()
        for i in range(60):
            tracker.record(i + 1, {"overall_score": 7.0})
        assert len(tracker.records) == QualityTracker.MAX_RECORDS
        # 保留最近的记录
        assert tracker.records[0].chapter_num == 11
        assert tracker.records[-1].chapter_num == 60


class TestCheckTrends:
    def _make_tracker(self, scores: list[float], originality: float = 7.0, excitement: float = 7.0):
        tracker = QualityTracker()
        for i, s in enumerate(scores, 1):
            tracker.record(i, {
                "overall_score": s,
                "originality_score": originality,
                "excitement_score": excitement,
            })
        return tracker

    def test_insufficient_data_returns_empty(self):
        tracker = self._make_tracker([7.0] * 5)  # < ROLLING_WINDOW=10
        assert tracker.check_trends() == []

    def test_avg_below_threshold_triggers_warning(self):
        tracker = self._make_tracker([5.0] * 12)  # avg=5.0 < 6.0
        warnings = tracker.check_trends()
        assert any("质量预警" in w for w in warnings)
        assert any("5.0" in w for w in warnings)

    def test_avg_above_threshold_no_warning(self):
        tracker = self._make_tracker([8.0] * 12)
        assert tracker.check_trends() == []

    def test_avg_at_threshold_no_warning(self):
        tracker = self._make_tracker([6.0] * 12)  # avg == threshold
        warnings = tracker.check_trends()
        assert not any("质量预警" in w for w in warnings)

    def test_originality_streak_triggers_warning(self):
        tracker = QualityTracker()
        for i in range(12):
            tracker.record(i + 1, {
                "overall_score": 8.0,
                "originality_score": 4.0,  # < ORIGINALITY_THRESHOLD=5.0
                "excitement_score": 8.0,
            })
        warnings = tracker.check_trends()
        assert any("创新预警" in w for w in warnings)

    def test_originality_streak_broken_no_warning(self):
        tracker = QualityTracker()
        for i in range(12):
            score = 4.0 if i != 10 else 7.0  # 第11章打断
            tracker.record(i + 1, {
                "overall_score": 8.0,
                "originality_score": score,
                "excitement_score": 8.0,
            })
        warnings = tracker.check_trends()
        assert not any("创新预警" in w for w in warnings)

    def test_excitement_streak_triggers_warning(self):
        tracker = QualityTracker()
        for i in range(12):
            tracker.record(i + 1, {
                "overall_score": 8.0,
                "originality_score": 8.0,
                "excitement_score": 4.0,  # < 5.0
            })
        warnings = tracker.check_trends()
        assert any("爽感预警" in w for w in warnings)

    def test_multiple_warnings_simultaneous(self):
        tracker = QualityTracker()
        for i in range(12):
            tracker.record(i + 1, {
                "overall_score": 4.0,
                "originality_score": 3.0,
                "excitement_score": 3.0,
            })
        warnings = tracker.check_trends()
        assert len(warnings) == 3

    def test_ignores_invalid_scores(self):
        tracker = QualityTracker()
        # 前10章有效但高分，后续无效分
        for i in range(10):
            tracker.record(i + 1, {"overall_score": 8.0})
        for i in range(5):
            tracker.record(i + 11, {"overall_score": -1})  # invalid
        warnings = tracker.check_trends()
        assert warnings == []  # 只有10条有效记录，avg=8.0


class TestNeedsPlotTwist:
    def test_true_when_streak(self):
        tracker = QualityTracker()
        for i in range(6):
            tracker.record(i + 1, {"originality_score": 4.0})
        assert tracker.needs_plot_twist() is True

    def test_false_when_insufficient_data(self):
        tracker = QualityTracker()
        for i in range(3):
            tracker.record(i + 1, {"originality_score": 4.0})
        assert tracker.needs_plot_twist() is False

    def test_false_when_streak_broken(self):
        tracker = QualityTracker()
        for i in range(4):
            tracker.record(i + 1, {"originality_score": 4.0})
        tracker.record(5, {"originality_score": 7.0})  # 打断
        assert tracker.needs_plot_twist() is False

    def test_false_with_invalid_scores(self):
        tracker = QualityTracker()
        for i in range(6):
            tracker.record(i + 1, {"originality_score": -1})  # invalid
        assert tracker.needs_plot_twist() is False


class TestGetContextForWriter:
    def test_empty_when_no_warnings(self):
        tracker = QualityTracker()
        for i in range(12):
            tracker.record(i + 1, {
                "overall_score": 8.0,
                "originality_score": 8.0,
                "excitement_score": 8.0,
            })
        assert tracker.get_context_for_writer() == ""

    def test_includes_warnings(self):
        tracker = QualityTracker()
        for i in range(12):
            tracker.record(i + 1, {"overall_score": 4.0, "originality_score": 3.0, "excitement_score": 3.0})
        ctx = tracker.get_context_for_writer()
        assert "质量趋势预警" in ctx


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        tracker = QualityTracker()
        tracker.record(1, {"overall_score": 7.5, "originality_score": 6.0})
        tracker.record(2, {"overall_score": 8.0, "needs_rewrite": True})

        data = tracker.to_dict()
        restored = QualityTracker.from_dict(data)

        assert len(restored.records) == 2
        assert restored.records[0].overall_score == 7.5
        assert restored.records[1].needs_rewrite is True
