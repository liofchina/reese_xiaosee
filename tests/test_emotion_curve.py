"""EmotionCurveTracker 单元测试"""
import pytest
from memory.emotion_curve_tracker import EmotionCurveTracker, PACING_EMOTION_MAP


class TestRecord:
    def test_records_emotions(self):
        ect = EmotionCurveTracker()
        ect.record(1, ["紧张", "燃", "震撼"])
        assert ect.chapter_emotions[1] == ["紧张", "燃", "震撼"]

    def test_max_chapters_pruning(self):
        ect = EmotionCurveTracker()
        for i in range(60):
            ect.record(i + 1, ["紧张"])
        assert len(ect.chapter_emotions) == ect.MAX_CHAPTERS
        # Keeps the most recent
        assert 60 in ect.chapter_emotions
        assert 1 not in ect.chapter_emotions


class TestCheckFlatness:
    def test_insufficient_data_no_warning(self):
        ect = EmotionCurveTracker()
        ect.record(1, ["紧张", "燃"])
        assert ect.check_flatness(window=3) == []

    def test_flat_curve_warning(self):
        ect = EmotionCurveTracker()
        # 3 chapters with only 2 unique emotions total
        ect.record(1, ["紧张"])
        ect.record(2, ["紧张"])
        ect.record(3, ["燃"])
        warnings = ect.check_flatness(window=3)
        assert any("平坦" in w for w in warnings)

    def test_diverse_no_warning(self):
        ect = EmotionCurveTracker()
        ect.record(1, ["紧张", "燃"])
        ect.record(2, ["震撼", "感动"])
        ect.record(3, ["悲伤", "温馨"])
        warnings = ect.check_flatness(window=3)
        assert not any("平坦" in w for w in warnings)

    def test_missing_surprise_emotions_warning(self):
        ect = EmotionCurveTracker()
        # 5 chapters without any surprise emotions (震撼/心寒/惊喜)
        for i in range(5):
            ect.record(i + 1, ["紧张", "燃", "温馨"])
        warnings = ect.check_flatness()
        assert any("转折缺失" in w for w in warnings)

    def test_has_surprise_no_turning_point_warning(self):
        ect = EmotionCurveTracker()
        for i in range(4):
            ect.record(i + 1, ["紧张", "燃"])
        ect.record(5, ["震撼", "紧张"])  # has surprise emotion
        warnings = ect.check_flatness()
        assert not any("转折缺失" in w for w in warnings)

    def test_fewer_than_5_chapters_no_surprise_warning(self):
        ect = EmotionCurveTracker()
        for i in range(4):
            ect.record(i + 1, ["紧张"])
        warnings = ect.check_flatness()
        assert not any("转折缺失" in w for w in warnings)


class TestCheckDiversity:
    def test_insufficient_data_no_warning(self):
        ect = EmotionCurveTracker()
        for i in range(5):
            ect.record(i + 1, ["紧张"])
        assert ect.check_diversity(window=10) == []

    def test_low_diversity_warning(self):
        ect = EmotionCurveTracker()
        # 10 chapters with only 3 unique emotions
        for i in range(10):
            ect.record(i + 1, ["紧张", "燃", "温馨"])
        warnings = ect.check_diversity(window=10)
        assert any("单一化" in w for w in warnings)

    def test_high_diversity_no_warning(self):
        ect = EmotionCurveTracker()
        emotions_list = [
            ["紧张", "燃"], ["震撼", "感动"], ["悲伤", "温馨"],
            ["愤怒", "释然"], ["恐惧", "期待"], ["好奇", "不安"],
            ["紧张", "热血"], ["心寒", "惊喜"], ["搞笑", "无奈"],
            ["绝望", "感动"],
        ]
        for i, ems in enumerate(emotions_list):
            ect.record(i + 1, ems)
        warnings = ect.check_diversity(window=10)
        assert warnings == []

    def test_exactly_6_unique_no_warning(self):
        ect = EmotionCurveTracker()
        # Distribute 6 unique emotions across 10 chapters
        emotions = ["紧张", "燃", "震撼", "感动", "悲伤", "温馨"]
        for i in range(10):
            ect.record(i + 1, [emotions[i % 6]])
        warnings = ect.check_diversity(window=10)
        assert warnings == []

    def test_5_unique_triggers_warning(self):
        ect = EmotionCurveTracker()
        emotions = ["紧张", "燃", "震撼", "感动", "悲伤"]
        for i in range(10):
            ect.record(i + 1, [emotions[i % 5]])
        warnings = ect.check_diversity(window=10)
        assert any("单一化" in w for w in warnings)


class TestGetSuggestedEmotions:
    def test_known_pacing_type(self):
        ect = EmotionCurveTracker()
        result = ect.get_suggested_emotions("action")
        assert result == PACING_EMOTION_MAP["action"]

    def test_unknown_pacing_type_defaults(self):
        ect = EmotionCurveTracker()
        result = ect.get_suggested_emotions("unknown")
        assert len(result) == 4


class TestGetContextForWriter:
    def test_includes_suggested_flow(self):
        ect = EmotionCurveTracker()
        ctx = ect.get_context_for_writer(1, "action")
        assert "情绪走向" in ctx
        assert "紧张" in ctx

    def test_includes_warnings_when_present(self):
        ect = EmotionCurveTracker()
        for i in range(5):
            ect.record(i + 1, ["紧张"])
        ctx = ect.get_context_for_writer(6, "action")
        assert "⚠" in ctx

    def test_includes_recent_stats(self):
        ect = EmotionCurveTracker()
        for i in range(3):
            ect.record(i + 1, ["紧张", "紧张", "燃"])
        ctx = ect.get_context_for_writer(4, "buildup")
        assert "高频情绪" in ctx


class TestSerialization:
    def test_roundtrip(self):
        ect = EmotionCurveTracker()
        ect.record(1, ["紧张", "燃"])
        ect.record(5, ["震撼", "感动"])

        data = ect.to_dict()
        restored = EmotionCurveTracker.from_dict(data)
        assert restored.chapter_emotions[1] == ["紧张", "燃"]
        assert restored.chapter_emotions[5] == ["震撼", "感动"]

    def test_keys_are_integers_after_restore(self):
        ect = EmotionCurveTracker()
        ect.record(10, ["紧张"])
        data = ect.to_dict()
        # to_dict converts keys to str
        assert "10" in data["chapter_emotions"]
        # from_dict converts back to int
        restored = EmotionCurveTracker.from_dict(data)
        assert 10 in restored.chapter_emotions
