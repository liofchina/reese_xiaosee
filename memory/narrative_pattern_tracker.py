"""
NarrativePatternTracker — 叙事套路去重

追踪已使用的叙事套路，检测疲劳，生成黑名单。
防止同一套路在 1000 章中被反复使用导致读者脱敏。
支持 checkpoint 序列化。
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# 已知叙事套路模式
KNOWN_PATTERNS: dict[str, str] = {
    "underestimate_reveal": "被轻视后展露实力",
    "last_moment_breakthrough": "最后关头突破",
    "mysterious_helper": "神秘人出手相助",
    "flashback_powerup": "回忆触发顿悟",
    "tournament_arc": "比武大会/竞技场",
    "treasure_hunt": "寻宝探秘",
    "betrayal_reveal": "背叛揭露",
    "power_inheritance": "传承/继承力量",
    "rescue_mission": "营救行动",
    "auction_bidding": "拍卖会竞价",
    "poison_cure": "中毒/解毒",
    "identity_reveal": "身份揭露",
    "time_pressure": "限时任务/倒计时",
    "trapped_escape": "被困密室/阵法脱出",
    "old_enemy_returns": "旧敌重现",
    "master_test": "师父/前辈考验",
}


class NarrativePatternTracker:
    """
    叙事套路追踪器。

    使用方式：
        npt = NarrativePatternTracker()
        npt.record(10, "underestimate_reveal")
        npt.record(15, "underestimate_reveal")
        npt.record(22, "underestimate_reveal")
        fatigued = npt.get_fatigued_patterns(25)
        # → ["underestimate_reveal"]  (20章内用了3次)
    """

    FATIGUE_THRESHOLD = 3   # 窗口内同一套路 N 次触发疲劳
    FATIGUE_WINDOW = 20     # 检测窗口（章数）
    COOLDOWN = 10           # 疲劳后冷却 N 章

    def __init__(self):
        self.patterns: dict[str, list[int]] = {}  # pattern_type → [chapter_nums]

    def record(self, chapter_num: int, pattern_type: str) -> None:
        """记录使用的叙事套路"""
        if pattern_type not in self.patterns:
            self.patterns[pattern_type] = []
        self.patterns[pattern_type].append(chapter_num)
        # 只保留最近 100 章的记录
        self.patterns[pattern_type] = [
            ch for ch in self.patterns[pattern_type]
            if ch > chapter_num - 100
        ]

    def get_fatigued_patterns(self, chapter_num: int) -> list[str]:
        """返回当前处于疲劳冷却期的套路黑名单"""
        fatigued = []
        for pattern, chapters in self.patterns.items():
            recent = [ch for ch in chapters if ch > chapter_num - self.FATIGUE_WINDOW]
            if len(recent) >= self.FATIGUE_THRESHOLD:
                # 检查是否还在冷却期
                last_use = max(recent)
                if chapter_num - last_use < self.COOLDOWN:
                    fatigued.append(pattern)
        return fatigued

    def get_pattern_stats(self, chapter_num: int, window: int = 50) -> dict[str, int]:
        """返回最近 N 章的套路使用统计"""
        stats = {}
        for pattern, chapters in self.patterns.items():
            count = sum(1 for ch in chapters if ch > chapter_num - window)
            if count > 0:
                stats[pattern] = count
        return dict(sorted(stats.items(), key=lambda x: -x[1]))

    def get_context_for_outliner(self, chapter_num: int) -> str:
        """生成面向 ChapterOutliner 的套路提示"""
        fatigued = self.get_fatigued_patterns(chapter_num)
        stats = self.get_pattern_stats(chapter_num, window=30)

        if not fatigued and not stats:
            return ""

        lines = ["【叙事套路管理】"]

        if fatigued:
            lines.append("⚠ 以下套路已疲劳，本卷禁用：")
            for p in fatigued:
                desc = KNOWN_PATTERNS.get(p, p)
                lines.append(f"  ✗ {desc}（{p}）")

        if stats:
            lines.append("最近30章套路使用统计：")
            for pattern, count in list(stats.items())[:5]:
                desc = KNOWN_PATTERNS.get(pattern, pattern)
                lines.append(f"  {desc}：{count}次")

        lines.append("→ 尽量使用未用过的套路，保持新鲜感")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"patterns": self.patterns}

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativePatternTracker":
        npt = cls()
        npt.patterns = data.get("patterns", {})
        return npt
