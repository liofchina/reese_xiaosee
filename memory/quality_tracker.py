"""
QualityTracker — 质量趋势监控

追踪每章质量评分，检测质量衰减趋势，生成预警。
支持 checkpoint 序列化。
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class ChapterQuality:
    chapter_num: int
    overall_score: float = -1
    excitement_score: float = -1
    pacing_score: float = -1
    immersion_score: float = -1
    page_turner_score: float = -1
    originality_score: float = -1
    needs_rewrite: bool = False


class QualityTracker:
    """
    质量趋势追踪器。

    使用方式：
        tracker = QualityTracker()
        tracker.record(chapter_num, quality_eval_dict)
        warnings = tracker.check_trends()
        context = tracker.get_context_for_writer()
    """

    MAX_RECORDS = 50  # 只保留最近 N 章记录
    ROLLING_WINDOW = 10  # 滚动窗口大小
    SCORE_THRESHOLD = 6.0  # 平均分低于此值触发警告
    ORIGINALITY_THRESHOLD = 5.0  # 新意分低于此值触发警告
    ORIGINALITY_STREAK = 5  # 连续 N 章低新意触发 PlotExtender 通知

    def __init__(self):
        self.records: list[ChapterQuality] = []

    def record(self, chapter_num: int, quality_eval: dict) -> None:
        self.records.append(ChapterQuality(
            chapter_num=chapter_num,
            overall_score=quality_eval.get("overall_score", -1),
            excitement_score=quality_eval.get("excitement_score", -1),
            pacing_score=quality_eval.get("pacing_score", -1),
            immersion_score=quality_eval.get("immersion_score", -1),
            page_turner_score=quality_eval.get("page_turner_score", -1),
            originality_score=quality_eval.get("originality_score", -1),
            needs_rewrite=quality_eval.get("needs_rewrite", False),
        ))
        if len(self.records) > self.MAX_RECORDS:
            self.records = self.records[-self.MAX_RECORDS:]

    def check_trends(self) -> list[str]:
        """检测质量趋势问题，返回警告列表"""
        warnings = []
        valid = [r for r in self.records if r.overall_score > 0]
        if len(valid) < self.ROLLING_WINDOW:
            return warnings

        # 滚动平均分检查
        recent = valid[-self.ROLLING_WINDOW:]
        avg_score = sum(r.overall_score for r in recent) / len(recent)
        if avg_score < self.SCORE_THRESHOLD:
            warnings.append(
                f"质量预警：最近{self.ROLLING_WINDOW}章平均分{avg_score:.1f}（阈值{self.SCORE_THRESHOLD}），"
                f"请提升叙事张力和情节深度"
            )

        # 连续低新意检查
        originality_scores = [r.originality_score for r in valid[-self.ORIGINALITY_STREAK:]
                              if r.originality_score > 0]
        if (len(originality_scores) >= self.ORIGINALITY_STREAK
                and all(s < self.ORIGINALITY_THRESHOLD for s in originality_scores)):
            warnings.append(
                f"创新预警：连续{self.ORIGINALITY_STREAK}章新意评分低于{self.ORIGINALITY_THRESHOLD}，"
                f"建议引入叙事转折或新角色/新冲突"
            )

        # 连续低爽感检查
        excitement_scores = [r.excitement_score for r in valid[-5:] if r.excitement_score > 0]
        if len(excitement_scores) >= 5 and all(s < 5.0 for s in excitement_scores):
            warnings.append("爽感预警：连续5章爽感评分低于5分，读者可能流失")

        return warnings

    def needs_plot_twist(self) -> bool:
        """是否需要通知 PlotExtender 引入叙事转折"""
        valid = [r for r in self.records if r.originality_score > 0]
        if len(valid) < self.ORIGINALITY_STREAK:
            return False
        recent = valid[-self.ORIGINALITY_STREAK:]
        return all(r.originality_score < self.ORIGINALITY_THRESHOLD for r in recent)

    def get_context_for_writer(self) -> str:
        """生成面向 Writer 的质量上下文"""
        warnings = self.check_trends()
        if not warnings:
            return ""
        lines = ["【质量趋势预警】"]
        for w in warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"records": [asdict(r) for r in self.records]}

    @classmethod
    def from_dict(cls, data: dict) -> "QualityTracker":
        tracker = cls()
        for r in data.get("records", []):
            tracker.records.append(ChapterQuality(**r))
        return tracker
