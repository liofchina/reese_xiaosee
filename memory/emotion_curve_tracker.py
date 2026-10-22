"""
EmotionCurveTracker — 读者情绪曲线追踪

追踪每章的情绪序列，检测平坦/单一化异常，为 Writer 生成情绪目标。
支持 checkpoint 序列化。
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# 情绪类型池
EMOTION_TYPES = [
    "好奇", "紧张", "绝望", "燃", "震撼", "不安",
    "温馨", "悲伤", "愤怒", "释然", "恐惧", "感动",
    "搞笑", "期待", "心寒", "热血", "无奈", "惊喜",
]

# 节奏类型对应的建议情绪曲线
PACING_EMOTION_MAP: dict[str, list[str]] = {
    "action": ["紧张", "热血", "燃", "震撼"],
    "buildup": ["好奇", "不安", "期待", "紧张"],
    "revelation": ["好奇", "震撼", "心寒", "释然"],
    "aftermath": ["无奈", "温馨", "感动", "期待"],
    "turning_point": ["紧张", "震撼", "心寒", "不安"],
    "grief": ["温馨", "紧张", "悲伤", "心寒"],
    "desperation": ["紧张", "绝望", "恐惧", "燃"],
    "comedic_relief": ["搞笑", "温馨", "惊喜", "好奇"],
}


class EmotionCurveTracker:
    """
    情绪曲线追踪器。

    使用方式：
        ect = EmotionCurveTracker()
        ect.record(1, ["紧张", "绝望", "燃", "震撼"])
        warnings = ect.check_flatness()
        ctx = ect.get_context_for_writer(2, "action")
    """

    MAX_CHAPTERS = 50  # 只保留最近 N 章记录

    def __init__(self):
        self.chapter_emotions: dict[int, list[str]] = {}

    def record(self, chapter_num: int, emotions: list[str]) -> None:
        """记录章节情绪序列"""
        self.chapter_emotions[chapter_num] = emotions
        # 剪枝
        if len(self.chapter_emotions) > self.MAX_CHAPTERS:
            sorted_keys = sorted(self.chapter_emotions.keys())
            for k in sorted_keys[:-self.MAX_CHAPTERS]:
                del self.chapter_emotions[k]

    def check_flatness(self, window: int = 3) -> list[str]:
        """检测连续 N 章情绪曲线平坦（无起伏）"""
        warnings = []
        if len(self.chapter_emotions) < window:
            return warnings

        recent_keys = sorted(self.chapter_emotions.keys())[-window:]
        all_emotions = []
        for k in recent_keys:
            all_emotions.extend(self.chapter_emotions[k])

        unique = set(all_emotions)
        if len(unique) <= 2:
            warnings.append(
                f"情绪平坦预警：最近{window}章仅出现{len(unique)}种情绪（{', '.join(unique)}），"
                f"缺乏起伏变化"
            )

        # 检查是否缺少"震撼/意外"类情绪
        surprise_emotions = {"震撼", "心寒", "惊喜"}
        recent_5 = sorted(self.chapter_emotions.keys())[-5:]
        has_surprise = False
        for k in recent_5:
            if surprise_emotions & set(self.chapter_emotions[k]):
                has_surprise = True
                break
        if not has_surprise and len(recent_5) >= 5:
            warnings.append("转折缺失预警：最近5章没有震撼/意外情绪，建议安排剧情转折")

        return warnings

    def check_diversity(self, window: int = 10) -> list[str]:
        """检测情绪多样性"""
        warnings = []
        recent_keys = sorted(self.chapter_emotions.keys())[-window:]
        if len(recent_keys) < window:
            return warnings

        all_emotions = set()
        for k in recent_keys:
            all_emotions.update(self.chapter_emotions[k])

        if len(all_emotions) < 6:
            warnings.append(
                f"情绪单一化预警：最近{window}章仅覆盖{len(all_emotions)}种情绪"
                f"（建议≥6种），读者体验趋于单调"
            )
        return warnings

    def get_suggested_emotions(self, pacing_type: str) -> list[str]:
        """根据节奏类型建议情绪曲线"""
        return PACING_EMOTION_MAP.get(pacing_type, ["好奇", "紧张", "释然", "期待"])

    def get_context_for_writer(
        self,
        chapter_num: int,
        pacing_type: str = "buildup",
    ) -> str:
        """生成面向 Writer 的情绪曲线指导"""
        warnings = self.check_flatness() + self.check_diversity()
        suggested = self.get_suggested_emotions(pacing_type)

        if not warnings and not suggested:
            return ""

        lines = ["【本章情绪曲线目标】"]
        if suggested:
            flow = " → ".join(suggested)
            lines.append(f"  情绪走向：{flow}")
            lines.append(f"  开头情绪：{suggested[0]}  → 结尾情绪：{suggested[-1]}")

        if warnings:
            lines.append("")
            for w in warnings:
                lines.append(f"  ⚠ {w}")

        # 最近情绪统计
        recent_keys = sorted(self.chapter_emotions.keys())[-5:]
        if recent_keys:
            recent_all = []
            for k in recent_keys:
                recent_all.extend(self.chapter_emotions[k])
            from collections import Counter
            counter = Counter(recent_all)
            top3 = counter.most_common(3)
            if top3:
                lines.append(f"  最近高频情绪：{'、'.join(f'{e}({c}次)' for e, c in top3)}")
                lines.append(f"  → 尽量引入不同情绪避免重复")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"chapter_emotions": {str(k): v for k, v in self.chapter_emotions.items()}}

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionCurveTracker":
        ect = cls()
        for k, v in data.get("chapter_emotions", {}).items():
            ect.chapter_emotions[int(k)] = v
        return ect
