"""ForeshadowingManager 高级单元测试（补充 test_memory.py 的基础测试）"""
import pytest
from memory.foreshadowing_manager import ForeshadowingManager, Foreshadow


class TestPlant:
    def test_returns_id(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "神秘老者身份", (30, 60))
        assert isinstance(fid, str)
        assert len(fid) == 8

    def test_creates_open_foreshadow(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint", (30, 60), importance="high")
        assert len(fm.foreshadows) == 1
        f = fm.foreshadows[0]
        assert f.status == "open"
        assert f.importance == "high"
        assert f.planted_chapter == 10
        assert f.expected_payoff_min == 30
        assert f.expected_payoff_max == 60


class TestHarvest:
    def test_marks_harvested(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint", (30, 60))
        fm.harvest(45, fid, "揭露真相")
        assert fm.foreshadows[0].status == "harvested"
        assert fm.foreshadows[0].payoff_chapter == 45
        assert fm.foreshadows[0].payoff_description == "揭露真相"

    def test_only_harvests_open(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint", (30, 60))
        fm.harvest(45, fid, "first")
        # 尝试再次回收已 harvested 的
        fm.harvest(50, fid, "second")
        assert fm.foreshadows[0].payoff_chapter == 45  # 未被覆盖

    def test_nonexistent_id_no_crash(self):
        fm = ForeshadowingManager()
        fm.harvest(10, "nonexistent")  # should not raise


class TestAbandon:
    def test_marks_abandoned(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint", (30, 60))
        fm.abandon(fid, "剧情调整")
        assert fm.foreshadows[0].status == "abandoned"


class TestGetOverdue:
    def test_returns_overdue(self):
        fm = ForeshadowingManager()
        fm.plant(10, "hint1", (30, 50))  # payoff_max=50
        overdue = fm.get_overdue(51)
        assert len(overdue) == 1
        assert overdue[0].status == "overdue"

    def test_at_boundary_not_overdue(self):
        fm = ForeshadowingManager()
        fm.plant(10, "hint1", (30, 50))
        overdue = fm.get_overdue(50)  # chapter_num == max, not > max
        assert len(overdue) == 0

    def test_already_harvested_not_overdue(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint1", (30, 50))
        fm.harvest(40, fid)
        overdue = fm.get_overdue(60)
        assert len(overdue) == 0

    def test_marks_status_overdue(self):
        fm = ForeshadowingManager()
        fm.plant(10, "hint1", (30, 50))
        fm.get_overdue(51)
        assert fm.foreshadows[0].status == "overdue"


class TestGetDueSoon:
    def _make_fm(self, payoff_min=30, payoff_max=60):
        fm = ForeshadowingManager()
        fm.plant(10, "hint", (payoff_min, payoff_max))
        return fm

    def test_within_range_condition1(self):
        # chapter_num + within falls inside [min, max]
        fm = self._make_fm(30, 60)
        due = fm.get_due_soon(chapter_num=25, within=10)  # 25+10=35 in [30,60]
        assert len(due) == 1

    def test_within_range_condition2(self):
        # chapter_num itself is inside [min, max]
        fm = self._make_fm(30, 60)
        due = fm.get_due_soon(chapter_num=40, within=5)  # 40 in [30,60]
        assert len(due) == 1

    def test_before_range(self):
        fm = self._make_fm(30, 60)
        due = fm.get_due_soon(chapter_num=10, within=5)  # 10+5=15 < 30
        assert len(due) == 0

    def test_after_range(self):
        fm = self._make_fm(30, 60)
        due = fm.get_due_soon(chapter_num=65, within=5)  # 65 > 60 and 70 > 60
        assert len(due) == 0

    def test_only_open_status(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "hint", (30, 60))
        fm.harvest(35, fid)
        due = fm.get_due_soon(chapter_num=40, within=10)
        assert len(due) == 0


class TestGetStats:
    def test_empty(self):
        fm = ForeshadowingManager()
        stats = fm.get_stats()
        assert stats == {"total": 0, "harvested": 0, "overdue": 0, "open": 0, "harvest_rate": 0.0}

    def test_harvest_rate_calculation(self):
        fm = ForeshadowingManager()
        fm.plant(1, "a", (10, 20))
        fm.plant(2, "b", (10, 20))
        fid = fm.plant(3, "c", (10, 20))
        fm.harvest(15, fid)
        stats = fm.get_stats()
        # total=3, harvested=1, open=2
        # harvest_rate = 1 / max(3 - 2, 1) = 1/1 = 1.0
        assert stats["total"] == 3
        assert stats["harvested"] == 1
        assert stats["open"] == 2
        assert stats["harvest_rate"] == 1.0

    def test_harvest_rate_no_division_by_zero(self):
        fm = ForeshadowingManager()
        # All open → total - open = 0 → max(0, 1) = 1
        fm.plant(1, "a", (10, 20))
        stats = fm.get_stats()
        assert stats["harvest_rate"] == 0.0  # 0 / 1

    def test_mixed_statuses(self):
        fm = ForeshadowingManager()
        fid1 = fm.plant(1, "a", (10, 20))
        fid2 = fm.plant(2, "b", (10, 20))
        fm.plant(3, "c", (10, 20))
        fm.harvest(15, fid1)
        fm.get_overdue(25)  # marks fid2 and fid3 as overdue
        stats = fm.get_stats()
        assert stats["harvested"] == 1
        assert stats["overdue"] == 2
        assert stats["open"] == 0


class TestPrune:
    def test_keeps_open(self):
        fm = ForeshadowingManager()
        fm.plant(1, "open1", (10, 20))
        fm.plant(2, "open2", (10, 20))
        fm.prune()
        assert len(fm.foreshadows) == 2

    def test_limits_closed_to_50(self):
        fm = ForeshadowingManager()
        for i in range(60):
            fid = fm.plant(i, f"hint{i}", (i + 10, i + 20))
            fm.harvest(i + 15, fid)
        fm.prune()
        assert len(fm.foreshadows) <= 50


class TestGetOpenCount:
    def test_counts_correctly(self):
        fm = ForeshadowingManager()
        fm.plant(1, "a", (10, 20))
        fm.plant(2, "b", (10, 20))
        fid = fm.plant(3, "c", (10, 20))
        fm.harvest(15, fid)
        assert fm.get_open_count() == 2


class TestSerialization:
    def test_roundtrip(self):
        fm = ForeshadowingManager()
        fid = fm.plant(10, "神秘身份", (30, 60), importance="critical")
        fm.harvest(45, fid, "是祖父")

        data = fm.to_dict()
        restored = ForeshadowingManager.from_dict(data)
        assert len(restored.foreshadows) == 1
        assert restored.foreshadows[0].status == "harvested"
        assert restored.foreshadows[0].importance == "critical"
