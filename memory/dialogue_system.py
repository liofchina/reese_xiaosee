"""
DialogueSystem — 角色对话风格管理

为每个核心角色维护对话风格矩阵，确保百万字长篇中角色声口不趋同。
支持 checkpoint 序列化。
"""

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class DialogueProfile:
    character_name: str
    sentence_length: str = "中等(10-20字)"  # "极短(3-8字)" / "中等(10-20字)" / "长句型(20+字)"
    tone: str = "温和"  # "嘲讽" / "温和" / "粗犷" / "文绉绉" / "冷淡" / "阴柔"
    verbal_tics: list[str] = field(default_factory=list)  # 口头禅
    forbidden_expressions: list[str] = field(default_factory=list)  # 绝不会说的话
    subtext_pattern: str = "直来直去"  # "话里有话" / "直来直去" / "沉默暗示"
    humor_style: str = "无"  # "毒舌" / "天然呆" / "冷幽默" / "无"
    emotional_range: str = "情绪外露"  # "喜怒不形于色" / "情绪外露" / "冷面热心"


# 角色类型到默认对话风格的映射
_ROLE_DEFAULTS: dict[str, dict] = {
    "protagonist": {
        "sentence_length": "极短(3-8字)",
        "tone": "冷淡",
        "subtext_pattern": "直来直去",
        "emotional_range": "喜怒不形于色",
    },
    "love_interest": {
        "sentence_length": "中等(10-20字)",
        "tone": "温和",
        "subtext_pattern": "话里有话",
        "emotional_range": "冷面热心",
    },
    "mentor": {
        "sentence_length": "长句型(20+字)",
        "tone": "文绉绉",
        "subtext_pattern": "话里有话",
        "humor_style": "冷幽默",
    },
    "sidekick": {
        "sentence_length": "中等(10-20字)",
        "tone": "粗犷",
        "subtext_pattern": "直来直去",
        "humor_style": "天然呆",
        "emotional_range": "情绪外露",
    },
}


class DialogueSystem:
    """
    角色对话风格管理器。

    使用方式：
        ds = DialogueSystem()
        ds.init_from_outline(outline)
        ctx = ds.get_dialogue_context(["主角", "师父"], chapter_num=10)
    """

    MAX_PROFILES = 20  # 最多维护 N 个角色对话画像

    def __init__(self):
        self.profiles: dict[str, DialogueProfile] = {}

    def init_from_outline(self, outline) -> None:
        """从大纲初始化对话画像"""
        for c in outline.characters:
            defaults = _ROLE_DEFAULTS.get(c.role, {})
            profile = DialogueProfile(
                character_name=c.name,
                sentence_length=getattr(c, "dialogue_sentence_length", "") or defaults.get("sentence_length", "中等(10-20字)"),
                tone=getattr(c, "dialogue_tone", "") or defaults.get("tone", "温和"),
                verbal_tics=getattr(c, "dialogue_verbal_tics", []) or [],
                forbidden_expressions=getattr(c, "dialogue_forbidden", []) or [],
                subtext_pattern=defaults.get("subtext_pattern", "直来直去"),
                humor_style=getattr(c, "humor_style", "") or defaults.get("humor_style", "无"),
                emotional_range=defaults.get("emotional_range", "情绪外露"),
            )
            # 从 speech_pattern 推断
            if c.speech_pattern:
                if any(k in c.speech_pattern for k in ["简短", "少言", "惜字"]):
                    profile.sentence_length = "极短(3-8字)"
                elif any(k in c.speech_pattern for k in ["长篇", "文雅", "古风"]):
                    profile.sentence_length = "长句型(20+字)"
                if any(k in c.speech_pattern for k in ["嘲讽", "毒舌", "刻薄"]):
                    profile.tone = "嘲讽"
                    profile.humor_style = "毒舌"
            self.profiles[c.name] = profile

        # 反派
        if hasattr(outline, "antagonists"):
            for a in outline.antagonists:
                self.profiles[a.name] = DialogueProfile(
                    character_name=a.name,
                    sentence_length="中等(10-20字)",
                    tone="阴柔" if a.tier >= 2 else "粗犷",
                    subtext_pattern="话里有话",
                    humor_style="无",
                    emotional_range="喜怒不形于色",
                )

    def get_dialogue_context(
        self,
        character_names: list[str],
        chapter_num: int = 0,
    ) -> str:
        """生成面向 Writer 的对话指导上下文"""
        relevant = [
            self.profiles[name]
            for name in character_names
            if name in self.profiles
        ]
        if not relevant:
            return ""

        lines = ["【角色对话差异化指导】"]
        lines.append("同一场景中不同角色的对话必须风格明显不同——蒙住名字也能分辨谁在说话。")
        lines.append("")

        for p in relevant[:8]:  # 最多 8 个
            parts = [f"▸ {p.character_name}："]
            parts.append(f"句长{p.sentence_length}，语气{p.tone}")
            if p.verbal_tics:
                parts.append(f"口头禅「{'」「'.join(p.verbal_tics[:3])}」")
            if p.forbidden_expressions:
                parts.append(f"禁说「{'」「'.join(p.forbidden_expressions[:3])}」")
            parts.append(f"潜台词：{p.subtext_pattern}，情绪：{p.emotional_range}")
            if p.humor_style != "无":
                parts.append(f"幽默：{p.humor_style}")
            lines.append("  ".join(parts))

        lines.append("")
        lines.append("【对话铁律】")
        lines.append("- 连续两句对话不超过30字；3人对话中不能2人语气相同")
        lines.append("- 重要对话用短句+停顿+动作穿插，禁止长篇大论式对白")
        lines.append("- 反派台词暗含威胁而非直接叫嚣，高手过招用暗示不用解释")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"profiles": {name: asdict(p) for name, p in self.profiles.items()}}

    @classmethod
    def from_dict(cls, data: dict) -> "DialogueSystem":
        ds = cls()
        for name, p_dict in data.get("profiles", {}).items():
            ds.profiles[name] = DialogueProfile(**p_dict)
        return ds
