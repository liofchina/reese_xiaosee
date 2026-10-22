"""EntityStore 高级单元测试 — 分类、剪枝、查询"""
import pytest
from memory.entity_store import (
    EntityStore, CharacterState, PlotThread, FactionState,
    InformationGap, ConflictArc, TimelineEvent,
)


class TestClassifyCharacter:
    def _make_store(self, **char_kwargs) -> EntityStore:
        store = EntityStore()
        defaults = {
            "name": "测试角色", "alive": True, "role_type": "side",
            "last_appearance": 50, "departure_status": "",
        }
        defaults.update(char_kwargs)
        store.characters["测试角色"] = CharacterState(**defaults)
        return store

    def test_active_recent_appearance(self):
        store = self._make_store(last_appearance=50)
        tier = store._classify_character(store.characters["测试角色"], chapter_num=55)
        assert tier == "active"

    def test_dormant_old_appearance(self):
        store = self._make_store(last_appearance=10, role_type="side")
        # chapter_num - last_appearance = 80 - 10 = 70 > ACTIVE_THRESHOLD=30
        tier = store._classify_character(store.characters["测试角色"], chapter_num=80)
        assert tier == "dormant"

    def test_main_character_always_active(self):
        store = self._make_store(last_appearance=10, role_type="main")
        # Even though 80 - 10 = 70 > threshold, main chars stay active
        tier = store._classify_character(store.characters["测试角色"], chapter_num=80)
        assert tier == "active"

    def test_archived_when_dead(self):
        store = self._make_store(alive=False)
        tier = store._classify_character(store.characters["测试角色"], chapter_num=50)
        assert tier == "archived"

    def test_archived_when_departed(self):
        store = self._make_store(departure_status="departed_explained")
        tier = store._classify_character(store.characters["测试角色"], chapter_num=50)
        assert tier == "archived"

    def test_active_with_zero_last_appearance(self):
        store = self._make_store(last_appearance=0)
        # last_appearance > 0 is False, so goes to "active"
        tier = store._classify_character(store.characters["测试角色"], chapter_num=100)
        assert tier == "active"


class TestPruneCharacters:
    def test_dormant_character_compression(self):
        store = EntityStore()
        store.characters["配角"] = CharacterState(
            name="配角", role_type="side", alive=True,
            last_appearance=10, departure_status="",
            key_events=[f"event{i}" for i in range(10)],
            known_facts=[f"fact{i}" for i in range(10)],
            speech_examples=["话1", "话2", "话3"],
        )
        store._prune_characters(chapter_num=80)  # 80-10=70 > 30 → dormant
        c = store.characters["配角"]
        assert len(c.key_events) <= store.MAX_KEY_EVENTS_DORMANT
        assert len(c.known_facts) <= 3
        assert len(c.speech_examples) <= 1

    def test_archived_character_extreme_compression(self):
        store = EntityStore()
        store.characters["死者"] = CharacterState(
            name="死者", alive=False, role_type="side",
            key_events=["event1", "event2", "event3"],
            known_facts=["fact1"], speech_examples=["话"],
            relationships={"主角": "朋友"}, goal_stack=["goal"],
        )
        store._prune_characters(chapter_num=50)
        c = store.characters["死者"]
        assert len(c.key_events) <= 1
        assert c.known_facts == []
        assert c.speech_examples == []
        assert c.relationships == {}
        assert c.goal_stack == []

    def test_active_character_caps_events(self):
        store = EntityStore()
        store.characters["主角"] = CharacterState(
            name="主角", role_type="main", alive=True,
            last_appearance=48, departure_status="",
            key_events=[f"event{i}" for i in range(20)],
        )
        store._prune_characters(chapter_num=50)
        c = store.characters["主角"]
        assert len(c.key_events) <= store.MAX_KEY_EVENTS_ACTIVE


class TestPrunePlotThreads:
    def _make_store_with_threads(self, threads: list[PlotThread]) -> EntityStore:
        store = EntityStore()
        store.plot_threads = threads
        return store

    def test_marks_stale_foreshadowing(self):
        store = EntityStore()
        store.plot_threads = [PlotThread(
            thread_id="t1", description="mystery", introduced_chapter=1,
            status="open", thread_type="foreshadowing", urgency="low",
        )]
        store._prune_plot_threads(chapter_num=200)  # 200-1=199 > 100
        assert store.plot_threads[0].status == "stale"

    def test_non_foreshadowing_not_marked_stale(self):
        store = EntityStore()
        store.plot_threads = [PlotThread(
            thread_id="t1", description="hook", introduced_chapter=1,
            status="open", thread_type="chapter_hook", urgency="low",
        )]
        store._prune_plot_threads(chapter_num=200)
        assert store.plot_threads[0].status == "open"  # not marked stale

    def test_overflow_abandons_low_priority(self):
        store = EntityStore()
        # Create MAX_OPEN_THREADS + 5 open threads with varying urgency
        threads = []
        for i in range(store.MAX_OPEN_THREADS + 5):
            urgency = "critical" if i < 5 else "low"
            threads.append(PlotThread(
                thread_id=f"t{i}", description=f"thread{i}",
                introduced_chapter=i + 1, status="open",
                thread_type="foreshadowing", urgency=urgency,
            ))
        store.plot_threads = threads
        store._prune_plot_threads(chapter_num=50)

        open_threads = [pt for pt in store.plot_threads if pt.status == "open"]
        assert len(open_threads) <= store.MAX_OPEN_THREADS
        # Critical ones should be kept
        critical_kept = [pt for pt in open_threads if pt.urgency == "critical"]
        assert len(critical_kept) == 5

    def test_removes_old_non_open_threads(self):
        store = EntityStore()
        store.plot_threads = [
            PlotThread(thread_id="old", description="old", introduced_chapter=1,
                       status="resolved", thread_type="foreshadowing", urgency="low"),
            PlotThread(thread_id="new", description="new", introduced_chapter=100,
                       status="open", thread_type="foreshadowing", urgency="low"),
        ]
        store._prune_plot_threads(chapter_num=250)
        # "old" introduced at ch1, 250-1=249 > 200, and status != open → removed
        ids = [pt.thread_id for pt in store.plot_threads]
        assert "old" not in ids
        assert "new" in ids


class TestGetMissingCharacters:
    def test_finds_missing_side_character(self):
        store = EntityStore()
        store.characters["配角A"] = CharacterState(
            name="配角A", alive=True, role_type="side",
            appearance_count=5, departure_status="",
            last_appearance=10,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        assert len(missing) == 1
        assert missing[0].name == "配角A"

    def test_excludes_dead_characters(self):
        store = EntityStore()
        store.characters["死者"] = CharacterState(
            name="死者", alive=False, role_type="side",
            appearance_count=5, departure_status="",
            last_appearance=10,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        assert len(missing) == 0

    def test_excludes_explained_departures(self):
        store = EntityStore()
        store.characters["离开者"] = CharacterState(
            name="离开者", alive=True, role_type="side",
            appearance_count=5, departure_status="departed_explained",
            last_appearance=10,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        assert len(missing) == 0

    def test_excludes_main_characters(self):
        store = EntityStore()
        store.characters["主角"] = CharacterState(
            name="主角", alive=True, role_type="main",
            appearance_count=5, departure_status="",
            last_appearance=10,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        assert len(missing) == 0

    def test_excludes_low_appearance_count(self):
        store = EntityStore()
        store.characters["路人"] = CharacterState(
            name="路人", alive=True, role_type="side",
            appearance_count=1, departure_status="",
            last_appearance=10,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        assert len(missing) == 0

    def test_within_threshold_not_missing(self):
        store = EntityStore()
        store.characters["配角"] = CharacterState(
            name="配角", alive=True, role_type="side",
            appearance_count=5, departure_status="",
            last_appearance=20,
        )
        missing = store.get_missing_characters(current_chapter=25, threshold=10)
        # 25-20=5, not > 10
        assert len(missing) == 0


class TestGetActiveAndDormant:
    def test_get_active_characters(self):
        store = EntityStore()
        store.characters["活跃"] = CharacterState(
            name="活跃", alive=True, role_type="side", last_appearance=48,
        )
        store.characters["休眠"] = CharacterState(
            name="休眠", alive=True, role_type="side", last_appearance=10,
        )
        active = store.get_active_characters(chapter_num=50)
        assert any(c.name == "活跃" for c in active)
        assert not any(c.name == "休眠" for c in active)

    def test_get_dormant_characters(self):
        store = EntityStore()
        store.characters["活跃"] = CharacterState(
            name="活跃", alive=True, role_type="side", last_appearance=48,
        )
        store.characters["休眠"] = CharacterState(
            name="休眠", alive=True, role_type="side", last_appearance=10,
        )
        dormant = store.get_dormant_characters(chapter_num=50)
        assert any(c.name == "休眠" for c in dormant)
        assert not any(c.name == "活跃" for c in dormant)


class TestPruneTimeline:
    def test_compresses_overflow(self):
        store = EntityStore()
        for i in range(40):
            store.timeline.append(TimelineEvent(
                chapter_num=i + 1, in_story_time=f"第{i+1}天",
                event_summary=f"事件{i+1}",
            ))
        store._prune_timeline()
        assert len(store.timeline) == store.MAX_TIMELINE
        assert store.compressed_history != ""

    def test_no_prune_under_limit(self):
        store = EntityStore()
        for i in range(10):
            store.timeline.append(TimelineEvent(
                chapter_num=i + 1, in_story_time=f"第{i+1}天",
                event_summary=f"事件{i+1}",
            ))
        store._prune_timeline()
        assert len(store.timeline) == 10
        assert store.compressed_history == ""


class TestPruneInfoGaps:
    def test_expires_old_gaps(self):
        store = EntityStore()
        store.information_gaps = [InformationGap(
            fact_id="ig1", description="秘密",
            introduced_chapter=1, resolved_chapter=0,
        )]
        store._prune_info_gaps(chapter_num=60)  # 60-1=59 > INFO_GAP_EXPIRE=50
        assert store.information_gaps[0].resolved_chapter == 60

    def test_recent_gaps_not_expired(self):
        store = EntityStore()
        store.information_gaps = [InformationGap(
            fact_id="ig1", description="秘密",
            introduced_chapter=30, resolved_chapter=0,
        )]
        store._prune_info_gaps(chapter_num=60)  # 60-30=30 < 50
        assert store.information_gaps[0].resolved_chapter == 0
