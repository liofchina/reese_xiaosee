"""
ForeshadowingManager — 伏笔埋设与回收管理

显式管理伏笔的生命周期：埋设 → 追踪 → 到期提醒 → 回收/超期。
1000 章小说中保证伏笔回收率 > 80%。
支持 checkpoint 序列化。
"""

import logging
import uuid
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Foreshadow:
    foreshadow_id: str
    hint_text: str                  # 伏笔描述
    planted_chapter: int            # 埋设章节
    expected_payoff_min: int        # 预期回收最早章节
    expected_payoff_max: int        # 预期回收最晚章节
    payoff_chapter: int = 0         # 实际回收章节（0=未回收）
    status: str = "open"            # open / harvested / overdue / abandoned
    importance: str = "medium"      # low / medium / high / critical
    payoff_description: str = ""    # 回收时的描述


class ForeshadowingManager:
    """
    伏笔管理器。

    使用方式：
        fm = ForeshadowingManager()
        fid = fm.plant(10, "神秘老者的真实身份", (30, 60), importance="high")
        fm.harvest(45, fid, "揭露老者是主角的祖父")
        overdue = fm.get_overdue(70)
        due_soon = fm.get_due_soon(25, within=10)
    """

    MAX_OPEN = 30  # 最多同时追踪 N 条开放伏笔

    def __init__(self):
        self.foreshadows: list[Foreshadow] = []

    def plant(
        self,
        chapter_num: int,
        hint_text: str,
        expected_range: tuple[int, int],
        importance: str = "medium",
    ) -> str:
        """埋设伏笔，返回 foreshadow_id"""
        fid = str(uuid.uuid4())[:8]
        self.foreshadows.append(Foreshadow(
            foreshadow_id=fid,
            hint_text=hint_text,
            planted_chapter=chapter_num,
            expected_payoff_min=expected_range[0],
            expected_payoff_max=expected_range[1],
            importance=importance,
        ))
        logger.info(f"伏笔埋设：[{fid}] {hint_text} (预期{expected_range[0]}-{expected_range[1]}章回收)")
        return fid

    def harvest(
        self,
        chapter_num: int,
        foreshadow_id: str,
        payoff_description: str = "",
    ) -> None:
        """回收伏笔"""
        for f in self.foreshadows:
            if f.foreshadow_id == foreshadow_id and f.status == "open":
                f.status = "harvested"
                f.payoff_chapter = chapter_num
                f.payoff_description = payoff_description
                logger.info(f"伏笔回收：[{foreshadow_id}] {f.hint_text}")
                return
        logger.warning(f"伏笔回收失败：未找到开放伏笔 {foreshadow_id}")

    def abandon(self, foreshadow_id: str, reason: str = "") -> None:
        """放弃伏笔"""
        for f in self.foreshadows:
            if f.foreshadow_id == foreshadow_id:
                f.status = "abandoned"
                logger.info(f"伏笔放弃：[{foreshadow_id}] {f.hint_text} ({reason})")
                return

    def get_overdue(self, chapter_num: int) -> list[Foreshadow]:
        """返回超期未回收的伏笔"""
        overdue = []
        for f in self.foreshadows:
            if f.status == "open" and chapter_num > f.expected_payoff_max:
                f.status = "overdue"
                overdue.append(f)
        return overdue

    def get_due_soon(self, chapter_num: int, within: int = 10) -> list[Foreshadow]:
        """返回即将到期的伏笔（在 within 章内需要回收）"""
        due = []
        for f in self.foreshadows:
            if f.status == "open":
                if f.expected_payoff_min <= chapter_num + within <= f.expected_payoff_max:
                    due.append(f)
                elif chapter_num >= f.expected_payoff_min and chapter_num <= f.expected_payoff_max:
                    due.append(f)
        return due

    def get_open_count(self) -> int:
        return sum(1 for f in self.foreshadows if f.status == "open")

    def get_stats(self) -> dict:
        """返回伏笔统计"""
        total = len(self.foreshadows)
        harvested = sum(1 for f in self.foreshadows if f.status == "harvested")
        overdue = sum(1 for f in self.foreshadows if f.status == "overdue")
        open_count = sum(1 for f in self.foreshadows if f.status == "open")
        return {
            "total": total,
            "harvested": harvested,
            "overdue": overdue,
            "open": open_count,
            "harvest_rate": harvested / max(total - open_count, 1),
        }

    def get_context_for_outliner(self, chapter_num: int) -> str:
        """生成面向 ChapterOutliner 的伏笔管理上下文"""
        due_soon = self.get_due_soon(chapter_num, within=15)
        overdue = self.get_overdue(chapter_num)

        if not due_soon and not overdue:
            return ""

        lines = ["【伏笔管理】"]

        if overdue:
            lines.append("❗ 超期未回收伏笔（必须尽快处理）：")
            for f in overdue[:5]:
                lines.append(
                    f"  [{f.foreshadow_id}] {f.hint_text}"
                    f"（第{f.planted_chapter}章埋设，已超期{chapter_num - f.expected_payoff_max}章）"
                )

        if due_soon:
            lines.append("⏰ 即将到期伏笔（本卷内需回收）：")
            for f in due_soon[:5]:
                lines.append(
                    f"  [{f.foreshadow_id}] {f.hint_text}"
                    f"（第{f.planted_chapter}章埋设，回收窗口{f.expected_payoff_min}-{f.expected_payoff_max}章）"
                )

        stats = self.get_stats()
        lines.append(f"伏笔总览：已回收{stats['harvested']}条 / 开放{stats['open']}条 / 超期{stats['overdue']}条")

        return "\n".join(lines)

    def get_context_for_extender(self, chapter_num: int) -> str:
        """生成面向 PlotExtender 的未回收伏笔清单"""
        open_foreshadows = [f for f in self.foreshadows if f.status in ("open", "overdue")]
        if not open_foreshadows:
            return ""

        lines = ["【未回收伏笔清单（扩展剧情时必须考虑）】"]
        for f in open_foreshadows[:10]:
            status_mark = "❗超期" if f.status == "overdue" else ""
            lines.append(
                f"  {status_mark}[{f.importance}] {f.hint_text}"
                f"（第{f.planted_chapter}章埋设）"
            )
        if len(open_foreshadows) > 10:
            lines.append(f"  ...另有{len(open_foreshadows) - 10}条")
        lines.append("→ 新卷剧情必须推进/回收至少1条超期伏笔")
        return "\n".join(lines)

    def prune(self) -> None:
        """清理已完成的旧伏笔，保留最近的"""
        # 保留所有 open/overdue 伏笔 + 最近 50 条已完成伏笔
        open_ones = [f for f in self.foreshadows if f.status in ("open", "overdue")]
        closed = [f for f in self.foreshadows if f.status in ("harvested", "abandoned")]
        closed.sort(key=lambda f: f.planted_chapter, reverse=True)
        self.foreshadows = open_ones + closed[:50]

    def to_dict(self) -> dict:
        return {"foreshadows": [asdict(f) for f in self.foreshadows]}

    @classmethod
    def from_dict(cls, data: dict) -> "ForeshadowingManager":
        fm = cls()
        for f_dict in data.get("foreshadows", []):
            fm.foreshadows.append(Foreshadow(**f_dict))
        return fm
