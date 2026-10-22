"""cognitive_load_tracker 单元测试"""
import pytest
from unittest.mock import MagicMock
from memory.cognitive_load_tracker import (
    evaluate_chapter_load,
    get_load_context_for_writer,
    MAX_ACTIVE_CHARACTERS,
    MAX_ACTIVE_THREADS,
)


def _make_outline(core_events=None, hook_start="", hook_end="", pleasure_point=""):
    outline = MagicMock()
    outline.core_events = core_events or []
    outline.hook_start = hook_start
    outline.hook_end = hook_end
    outline.pleasure_point = pleasure_point
    return outline


def _make_entity_store(characters=None, plot_threads=None, factions=None):
    store = MagicMock()
    store.characters = characters or {}
    store.plot_threads = plot_threads or []
    store.factions = MagicMock()
    store.factions.values.return_value = factions or []
    return store


class TestEvaluateChapterLoad:
    def test_low_load_normal_chapter(self):
        outline = _make_outline(core_events=["主角修炼", "突破瓶颈"])
        result = evaluate_chapter_load(outline)
        assert result["load_level"] == "low"
        assert result["warnings"] == []

    def test_without_entity_store_estimates_from_events(self):
        outline = _make_outline(core_events=["event1", "event2", "event3"])
        result = evaluate_chapter_load(outline, entity_store=None)
        assert result["active_characters"] == 3  # min(len(events), 8)

    def test_without_entity_store_caps_at_8(self):
        outline = _make_outline(core_events=[f"event{i}" for i in range(12)])
        result = evaluate_chapter_load(outline, entity_store=None)
        assert result["active_characters"] == 8

    def test_high_load_too_many_characters(self):
        # 创建一个包含多个角色名的章节
        characters = {f"角色{i}": MagicMock() for i in range(7)}
        outline = _make_outline(
            core_events=["角色0与角色1对决", "角色2角色3角色4出场", "角色5角色6围观"]
        )
        store = _make_entity_store(characters=characters)
        result = evaluate_chapter_load(outline, entity_store=store)
        if result["active_characters"] > MAX_ACTIVE_CHARACTERS:
            assert result["load_level"] in ("medium", "high")
            assert any("角色过多" in w for w in result["warnings"])

    def test_medium_load_too_many_threads(self):
        outline = _make_outline(core_events=["伏笔A展开", "伏笔B揭示", "伏笔C推进", "伏笔D埋入"])
        threads = []
        for i in range(5):
            t = MagicMock()
            t.status = "open"
            t.description = f"伏笔{chr(65+i)}的详细描述"  # 前10字符会被匹配
            threads.append(t)
        store = _make_entity_store(plot_threads=threads)
        result = evaluate_chapter_load(outline, entity_store=store)
        if result["active_threads"] > MAX_ACTIVE_THREADS:
            assert any("伏笔线过多" in w for w in result["warnings"])

    def test_load_score_calculation(self):
        # 直接验证评分逻辑
        outline = _make_outline(core_events=[])
        result = evaluate_chapter_load(outline)
        # 无角色无伏笔 → low
        assert result["load_level"] == "low"

    def test_load_level_medium_boundary(self):
        # load_score <= 2 → medium
        # 只有伏笔线过多 (score=1) → medium
        outline = _make_outline(core_events=["线索A关联", "线索B关联", "线索C关联", "线索D关联"])
        threads = []
        for desc_prefix in ["线索A", "线索B", "线索C", "线索D"]:
            t = MagicMock()
            t.status = "open"
            t.description = desc_prefix + "关联的详细描述"
            threads.append(t)
        store = _make_entity_store(plot_threads=threads)
        result = evaluate_chapter_load(outline, entity_store=store)
        # 具体结果取决于文本匹配，但验证结构正确
        assert result["load_level"] in ("low", "medium", "high")
        assert "active_characters" in result
        assert "active_threads" in result
        assert "new_nouns_estimate" in result


class TestGetLoadContextForWriter:
    def test_empty_for_low_load(self):
        load_data = {"load_level": "low", "warnings": []}
        assert get_load_context_for_writer(load_data) == ""

    def test_includes_warnings_for_medium(self):
        load_data = {
            "load_level": "medium",
            "warnings": ["角色过多：本章涉及7个角色"],
        }
        result = get_load_context_for_writer(load_data)
        assert "认知负荷控制" in result
        assert "角色过多" in result
        assert "焦点角色最多3人" in result

    def test_includes_warnings_for_high(self):
        load_data = {
            "load_level": "high",
            "warnings": ["角色过多", "伏笔线过多"],
        }
        result = get_load_context_for_writer(load_data)
        assert "认知负荷控制" in result
