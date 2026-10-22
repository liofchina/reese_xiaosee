"""
RhythmTracker — 情绪节奏曲线追踪

纯 Python 模块（无 LLM 依赖），用于：
- 记录每章的节奏类型和张力值
- 检测连续高张力/低张力/同类型等节奏问题
- 生成面向 Writer 的节奏上下文提示
"""

from dataclasses import dataclass, field, asdict


TENSION_MAP: dict[str, float] = {
    "action": 0.9,
    "turning_point": 0.85,
    "revelation": 0.7,
    "buildup": 0.5,
    "aftermath": 0.3,
}

TENSION_LABEL: dict[str, str] = {
    "action": "动作",
    "turning_point": "转折",
    "revelation": "揭秘",
    "buildup": "铺垫",
    "aftermath": "收束",
}


@dataclass
class ChapterRhythm:
    chapter_num: int
    pacing_type: str
    tension: float
    emotional_beat: str = ""


class RhythmTracker:
    """
    情绪节奏追踪器。

    使用方式：
        tracker = RhythmTracker()
        tracker.record_chapter(1, "action", "紧张→爆发→释然")
        warnings = tracker.validate_rhythm()
        context = tracker.get_context_for_writer()
    """

    MAX_CHAPTERS = 30  # 只保留最近 N 章节奏数据

    def __init__(self):
        self.chapters: list[ChapterRhythm] = []

    def record_chapter(self, chapter_num: int, pacing_type: str, emotional_beat: str = "") -> None:
        tension = TENSION_MAP.get(pacing_type, 0.5)
        self.chapters.append(ChapterRhythm(
            chapter_num=chapter_num,
            pacing_type=pacing_type,
            tension=tension,
            emotional_beat=emotional_beat,
        ))
        # 剪枝：只保留最近 MAX_CHAPTERS 条
        if len(self.chapters) > self.MAX_CHAPTERS:
            self.chapters = self.chapters[-self.MAX_CHAPTERS:]

    def validate_rhythm(self) -> list[str]:
        """检测节奏问题，返回警告列表（只检查最近 10 章）"""
        warnings = []
        recent = self.chapters[-10:] if len(self.chapters) > 10 else self.chapters
        if len(recent) < 3:
            return warnings

        for i in range(len(recent) - 2):
            window = recent[i:i + 3]

            # 连续 3+ 章高张力
            if all(ch.tension >= 0.7 for ch in window):
                warnings.append(
                    f"第{window[0].chapter_num}-{window[2].chapter_num}章连续高张力，读者会疲劳，建议插入舒缓章节"
                )

            # 连续 3+ 章低张力
            if all(ch.tension <= 0.4 for ch in window):
                warnings.append(
                    f"第{window[0].chapter_num}-{window[2].chapter_num}章连续低张力，读者可能流失，建议加入冲突"
                )

            # 连续 3+ 章同类型
            types = set(ch.pacing_type for ch in window)
            if len(types) == 1:
                label = TENSION_LABEL.get(window[0].pacing_type, window[0].pacing_type)
                warnings.append(
                    f"第{window[0].chapter_num}-{window[2].chapter_num}章连续同类型（{label}），节奏单调"
                )

        return warnings

    def get_context_for_writer(self) -> str:
        """生成面向 Writer 的节奏上下文"""
        if not self.chapters:
            return ""

        recent = self.chapters[-5:]
        lines = ["【近期节奏走势】"]
        for ch in recent:
            bar = "█" * int(ch.tension * 10)
            label = TENSION_LABEL.get(ch.pacing_type, ch.pacing_type)
            lines.append(f"  第{ch.chapter_num}章 [{label}] {bar} ({ch.tension:.1f})")

        warnings = self.validate_rhythm()
        if warnings:
            lines.append(f"  ⚠ {warnings[-1]}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"chapters": [asdict(ch) for ch in self.chapters]}

    @classmethod
    def from_dict(cls, data: dict) -> "RhythmTracker":
        tracker = cls()
        for ch_data in data.get("chapters", []):
            tracker.chapters.append(ChapterRhythm(**ch_data))
        return tracker
