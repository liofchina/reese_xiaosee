"""pleasure_system 单元测试"""
import pytest
from domain.pleasure_system import (
    get_story_phase, get_combat_tier, get_emotion_contrast_guidance,
    should_subvert, classify_pleasure_emotion, get_pleasure_formula,
    get_volume_pacing, get_chapter_pacing_template, get_hook_types,
    get_pleasure_guidance_for_writer, get_pleasure_guidance_for_outliner,
    get_story_phase_guidance, get_combat_guidance, get_title_guidance,
    PLEASURE_FORMULAS, SUBVERSION_INTERVAL,
)


class TestGetStoryPhase:
    @pytest.mark.parametrize("vol,total,expected", [
        (1, 100, "origin"),       # 1%
        (25, 100, "origin"),      # 25% boundary
        (26, 100, "rise"),        # just past 25%
        (50, 100, "rise"),        # 50% boundary
        (51, 100, "crisis"),      # just past 50%
        (75, 100, "crisis"),      # 75% boundary
        (76, 100, "transcendence"),  # just past 75%
        (100, 100, "transcendence"),  # 100%
    ])
    def test_boundaries(self, vol, total, expected):
        assert get_story_phase(vol, total) == expected

    def test_zero_total_volumes_no_crash(self):
        # total_volumes=0 → max(0,1)=1 → vol/1
        result = get_story_phase(1, 0)
        assert result == "transcendence"  # 1/1 = 1.0 > 0.75

    def test_first_volume(self):
        assert get_story_phase(1, 50) == "origin"

    def test_last_volume(self):
        assert get_story_phase(50, 50) == "transcendence"


class TestGetCombatTier:
    @pytest.mark.parametrize("rank,total,expected", [
        (1, 10, "low_tier"),      # 0.1
        (2, 10, "low_tier"),      # 0.2
        (3, 10, "mid_tier"),      # 0.3
        (6, 10, "mid_tier"),      # 0.6
        (7, 10, "high_tier"),     # 0.7
        (8, 10, "high_tier"),     # 0.8
        (9, 10, "top_tier"),      # 0.9
        (10, 10, "top_tier"),     # 1.0
    ])
    def test_tiers(self, rank, total, expected):
        assert get_combat_tier(rank, total) == expected

    def test_zero_total_no_crash(self):
        result = get_combat_tier(1, 0)
        assert result == "top_tier"  # 1/1 = 1.0 > 0.85


class TestEmotionContrastGuidance:
    def test_too_positive_triggers_warning(self):
        result = get_emotion_contrast_guidance(5, ["positive"] * 5)
        assert "连续正向体验过多" in result

    def test_too_negative_triggers_warning(self):
        result = get_emotion_contrast_guidance(5, ["negative"] * 5)
        assert "连续负向体验过多" in result

    def test_balanced_no_special_warning(self):
        # min_positive_streak=3, max_negative_streak=2
        # Need: positives < 3 AND negatives < 2 in last 5
        # 2 positive + 1 negative + 2 neutral → only if neutral exists
        # Since only "positive"/"negative"/"mixed" are options, use 2 pos + 1 neg
        result = get_emotion_contrast_guidance(5, ["positive", "positive", "negative"])
        # recent_pos=2 < 3, recent_neg=1 < 2 → no warning
        assert "连续正向体验过多" not in result
        assert "连续负向体验过多" not in result

    def test_volume_scaling_vol_1_10(self):
        result = get_emotion_contrast_guidance(5, [])
        assert "第5卷" in result

    def test_volume_scaling_vol_11_30(self):
        result = get_emotion_contrast_guidance(20, [])
        assert "第20卷" in result

    def test_volume_scaling_vol_31_60(self):
        result = get_emotion_contrast_guidance(45, [])
        assert "第45卷" in result

    def test_volume_scaling_vol_60_plus(self):
        result = get_emotion_contrast_guidance(80, [])
        assert "第80卷" in result

    def test_includes_arc_guidance(self):
        result = get_emotion_contrast_guidance(5, [])
        assert "情绪弧线" in result

    def test_short_recent_list(self):
        # 少于5个也不应崩溃
        result = get_emotion_contrast_guidance(5, ["positive"])
        assert "情绪对比调度指导" in result


class TestShouldSubvert:
    def test_at_interval_true(self):
        assert should_subvert(SUBVERSION_INTERVAL) is True

    def test_above_interval_true(self):
        assert should_subvert(SUBVERSION_INTERVAL + 5) is True

    def test_below_interval_false(self):
        assert should_subvert(SUBVERSION_INTERVAL - 1) is False

    def test_zero_false(self):
        assert should_subvert(0) is False


class TestClassifyPleasureEmotion:
    def test_positive_types(self):
        for ptype in ("逆袭打脸", "升级爽", "系统面板", "装逼收徒", "种田积累"):
            result = classify_pleasure_emotion(ptype)
            assert result == "positive", f"{ptype} should be positive"

    def test_negative_types(self):
        for ptype in ("虐心牺牲", "绝境求生", "背叛与觉醒", "失去与蜕变"):
            result = classify_pleasure_emotion(ptype)
            assert result == "negative", f"{ptype} should be negative"

    def test_mixed_types(self):
        assert classify_pleasure_emotion("绝望翻盘") == "mixed"

    def test_unknown_defaults_positive(self):
        assert classify_pleasure_emotion("不存在的类型") == "positive"

    def test_comedic_type(self):
        assert classify_pleasure_emotion("反差萌") == "positive"


class TestGetPleasureFormula:
    def test_known_formula(self):
        formula = get_pleasure_formula("逆袭打脸")
        assert "stages" in formula
        assert len(formula["stages"]) == 5

    def test_unknown_returns_default(self):
        formula = get_pleasure_formula("不存在")
        assert "stages" in formula
        assert len(formula["stages"]) == 5


class TestGetPleasureGuidanceForWriter:
    def test_positive_type(self):
        result = get_pleasure_guidance_for_writer("主角打脸", "逆袭打脸")
        assert "爽点释放指导" in result
        assert "正向体验" in result
        assert "禁忌" in result

    def test_negative_type_includes_compensation(self):
        result = get_pleasure_guidance_for_writer("师父牺牲", "虐心牺牲")
        assert "负向体验" in result
        assert "情绪补偿" in result

    def test_mixed_type_includes_compensation(self):
        result = get_pleasure_guidance_for_writer("绝境反击", "绝望翻盘")
        assert "混合体验" in result


class TestGetStoryPhaseGuidance:
    def test_known_phase(self):
        result = get_story_phase_guidance("origin")
        assert "origin" in result
        assert "核心叩问" in result

    def test_unknown_phase_defaults_to_origin(self):
        result = get_story_phase_guidance("unknown_phase")
        assert "核心叩问" in result


class TestGetCombatGuidance:
    def test_known_tier(self):
        result = get_combat_guidance("high_tier")
        assert "高阶战斗" in result
        assert "禁忌" in result

    def test_unknown_tier_defaults(self):
        result = get_combat_guidance("unknown")
        assert "战斗描写层级" in result


class TestGetTitleGuidance:
    def test_known_pacing_type(self):
        result = get_title_guidance("action")
        assert "标题要求" in result

    def test_unknown_pacing_type(self):
        result = get_title_guidance("unknown")
        assert "标题要求" in result
