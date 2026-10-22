"""
RomanceTracker — 感情线独立追踪系统

追踪感情线阶段、关键事件、互动频率，防止感情线写崩。
支持 checkpoint 序列化。
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# 感情阶段定义（每阶段至少持续 5 章）
ROMANCE_STAGES = [
    "stranger",       # 陌生人
    "acquaintance",   # 相识
    "friend",         # 朋友
    "tension",        # 暧昧/张力
    "confession",     # 表白/确认
    "together",       # 在一起
]

STAGE_MIN_CHAPTERS = 5  # 每阶段最少持续章数
INTERACTION_WARNING_GAP = 10  # 超过 N 章无互动则警告


@dataclass
class RomanceState:
    love_interest: str
    protagonist: str
    stage: str = "stranger"
    stage_start_chapter: int = 0
    key_moments: list[str] = field(default_factory=list)  # "第X章：XXX"
    last_interaction_chapter: int = 0
    unresolved_tension: str = ""  # 当前未解决的感情张力


class RomanceTracker:
    """
    感情线追踪器。

    使用方式：
        rt = RomanceTracker()
        rt.init_from_outline(outline)
        rt.record_interaction(10, "主角", "师姐", "并肩作战后的沉默对视")
        warnings = rt.check_stagnation(30)
        ctx = rt.get_context_for_writer(35)
    """

    MAX_KEY_MOMENTS = 20

    def __init__(self):
        self.romances: dict[str, RomanceState] = {}  # keyed by love_interest name

    def init_from_outline(self, outline) -> None:
        """从大纲初始化感情线"""
        protagonist_name = ""
        for c in outline.characters:
            if c.role == "protagonist":
                protagonist_name = c.name
                break

        for c in outline.characters:
            if c.role == "love_interest" and protagonist_name:
                self.romances[c.name] = RomanceState(
                    love_interest=c.name,
                    protagonist=protagonist_name,
                    stage="stranger",
                    stage_start_chapter=1,
                )

    def record_interaction(
        self,
        chapter_num: int,
        char_a: str,
        char_b: str,
        event: str,
    ) -> None:
        """记录一次感情互动"""
        # 找到对应的感情线
        target = None
        for name, rs in self.romances.items():
            if name in (char_a, char_b):
                target = rs
                break
        if not target:
            return

        target.last_interaction_chapter = chapter_num
        moment = f"第{chapter_num}章：{event}"
        target.key_moments.append(moment)
        if len(target.key_moments) > self.MAX_KEY_MOMENTS:
            target.key_moments = target.key_moments[-self.MAX_KEY_MOMENTS:]

    def advance_stage(self, love_interest: str, chapter_num: int) -> None:
        """推进感情阶段"""
        rs = self.romances.get(love_interest)
        if not rs:
            return
        current_idx = ROMANCE_STAGES.index(rs.stage) if rs.stage in ROMANCE_STAGES else 0
        if current_idx < len(ROMANCE_STAGES) - 1:
            if chapter_num - rs.stage_start_chapter >= STAGE_MIN_CHAPTERS:
                rs.stage = ROMANCE_STAGES[current_idx + 1]
                rs.stage_start_chapter = chapter_num
                logger.info(f"感情线推进：{love_interest} → {rs.stage}")
            else:
                logger.warning(
                    f"感情线推进过快：{love_interest} 在 {rs.stage} 阶段仅 "
                    f"{chapter_num - rs.stage_start_chapter} 章就要推进"
                )

    def check_stagnation(self, chapter_num: int) -> list[str]:
        """检测感情线停滞"""
        warnings = []
        for name, rs in self.romances.items():
            gap = chapter_num - rs.last_interaction_chapter
            if rs.last_interaction_chapter > 0 and gap > INTERACTION_WARNING_GAP:
                warnings.append(
                    f"感情线停滞：{rs.protagonist}↔{name}（{rs.stage}阶段）"
                    f"已{gap}章无互动，读者可能遗忘"
                )
            # 阶段过久不推进
            stage_duration = chapter_num - rs.stage_start_chapter
            if stage_duration > STAGE_MIN_CHAPTERS * 3 and rs.stage not in ("together", "stranger"):
                warnings.append(
                    f"感情线拖沓：{name} 在「{rs.stage}」阶段已停留{stage_duration}章，"
                    f"建议推进或制造冲突"
                )
        return warnings

    def get_context_for_writer(self, chapter_num: int) -> str:
        """生成面向 Writer 的感情线上下文"""
        if not self.romances:
            return ""

        lines = ["【感情线状态】"]
        for name, rs in self.romances.items():
            stage_cn = {
                "stranger": "陌生", "acquaintance": "初识",
                "friend": "友人", "tension": "暧昧",
                "confession": "表白", "together": "恋人",
            }.get(rs.stage, rs.stage)
            lines.append(f"  {rs.protagonist}↔{name}：{stage_cn}阶段")
            if rs.key_moments:
                lines.append(f"    最近事件：{rs.key_moments[-1]}")
            if rs.unresolved_tension:
                lines.append(f"    未解决张力：{rs.unresolved_tension}")

            gap = chapter_num - rs.last_interaction_chapter
            if rs.last_interaction_chapter > 0 and gap > 5:
                lines.append(f"    ⚠ 已{gap}章未互动，本章如有该角色出场请推进感情线")

        lines.append("")
        lines.append("【感情线铁律】")
        lines.append("- 感情推进通过共患难/日常细节/眼神动作暗示，禁止突兀表白")
        lines.append("- 感情互动必须和主线剧情交织，不能独立存在")
        lines.append("- 禁止 NTR 暗示（除非明确设定为背叛觉醒类型）")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "romances": {name: asdict(rs) for name, rs in self.romances.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RomanceTracker":
        rt = cls()
        for name, rs_dict in data.get("romances", {}).items():
            rt.romances[name] = RomanceState(**rs_dict)
        return rt
