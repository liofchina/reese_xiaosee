from pydantic import BaseModel, Field
from typing import Optional


class WebNovelRequest(BaseModel):
    genre: str = Field(..., description="大类型：玄幻/修仙/都市/穿越/系统/末世/无限/历史")
    sub_genre: str = Field(default="", description="子类型描述")
    core_pleasure: str = Field(..., description="核心爽点：逆袭打脸/升级爽/系统面板/装逼收徒/复仇/种田积累")
    protagonist_name: str = Field(..., description="主角姓名")
    protagonist_background: str = Field(..., description="主角起点设定（废材/失忆/穿越等）")
    golden_finger: str = Field(..., description="金手指/外挂描述")
    world_desc: str = Field(default="", description="世界观简述（可选，不填则AI生成）")
    antagonist_direction: str = Field(default="", description="反派方向（可选）")
    romance: str = Field(default="", description="感情线设定（可选）")
    num_volumes: int = Field(default=3, ge=1)            # 初始规划卷数，无限模式下会动态扩展
    chapters_per_volume: int = Field(default=10, ge=5, le=30)
    words_per_chapter: int = Field(default=2000, ge=1000, le=5000)
    quality_mode: str = Field(default="standard")
    mode: str = Field(default="bounded")                 # "bounded" | "infinite"
    interactive: bool = Field(default=False, description="交互模式：每个 Agent 输出后等待用户审批")
    disciplines: list[str] = Field(default_factory=list, description="学科方向（空则按题材自动分配5个）")


# ── 世界观模型 ────────────────────────────────────────────────────────────────

class PowerLevel(BaseModel):
    name: str
    rank: int
    description: str
    typical_power: str   # 战力表现，如"可劈山，可毁城"


class PowerSystem(BaseModel):
    name: str
    levels: list[PowerLevel]
    breakthrough_conditions: str
    special_rules: str = ""


class Faction(BaseModel):
    name: str
    faction_type: str    # protagonist_side / enemy_near / enemy_mid / enemy_boss / neutral / ally
    power_description: str
    description: str
    leader: str = ""


class WorldSetting(BaseModel):
    description: str
    power_system: PowerSystem
    factions: list[Faction]
    resource_system: str
    special_rules: str = ""
    philosophical_foundation: str = Field(default="", description="世界的哲学/思想内核")
    cultural_system: str = Field(default="", description="文化/知识/信仰体系")
    social_structure: str = Field(default="", description="社会结构与运行逻辑")
    geography: str = Field(default="", description="地理划分概述（区域+建议境界等级）")
    history_summary: str = Field(default="", description="关键历史事件概述（3-5个纪元）")
    forbidden_zones: str = Field(default="", description="禁区/秘境描述（进入条件+风险收益）")


# ── 人物模型 ──────────────────────────────────────────────────────────────────

class CharacterProfile(BaseModel):
    name: str
    role: str            # protagonist / love_interest / sidekick / mentor / antagonist_1~3
    current_power: str   # 当前境界
    background: str
    golden_finger: str = ""
    personality: str
    motivation: str
    speech_pattern: str  # 说话风格（具体到习惯用词/句式）
    arc: str             # 成长弧线
    psychological_profile: str = Field(default="", description="核心心理特征/创伤/防御机制")
    intellectual_stance: str = Field(default="", description="信仰/哲学/知识立场")
    appearance: str = Field(default="", description="外观特征（标志性特征）")
    signature_move: str = Field(default="", description="标志性招式或习惯动作")
    hidden_agenda: str = Field(default="", description="隐藏目标/秘密")
    relationship_notes: str = Field(default="", description="与其他角色的关系张力")
    growth_trajectory: str = Field(default="", description="成长轨迹（初期→中期→后期）")
    # ── 角色 Agent 化扩展 ──
    core_beliefs: list[str] = Field(default_factory=list, description="核心信念/价值观/底线（2-3条）")
    prohibitions: list[str] = Field(default_factory=list, description="角色绝不会做的事（2-3条）")
    initial_goals: list[str] = Field(default_factory=list, description="初始目标栈（当前→长期）")
    speech_examples: list[str] = Field(default_factory=list, description="2-3句典型对话示例")
    # ── 对话差异化扩展 (#17) ──
    humor_style: str = Field(default="", description="幽默风格：毒舌/天然呆/冷幽默/无")
    dialogue_sentence_length: str = Field(default="", description="台词句长：极短(3-8字)/中等(10-20字)/长句型(20+字)")
    dialogue_tone: str = Field(default="", description="语气基调：嘲讽/温和/粗犷/文绉绉/冷淡")
    dialogue_verbal_tics: list[str] = Field(default_factory=list, description="口头禅列表")
    dialogue_forbidden: list[str] = Field(default_factory=list, description="角色绝不会说的话/表达")


class AntagonistTier(BaseModel):
    tier: int            # 1=近期, 2=中期, 3=终极
    name: str
    current_power: str
    motive: str
    weakness: str
    defeat_volume: int   # 预计第几卷解决
    heroic_code: str = Field(default="", description="反派的坚守底线")
    tragic_flaw: str = Field(default="", description="致命缺陷")
    sympathetic_element: str = Field(default="", description="读者可同情的地方")
    # ── 反派深度扩展 (#4) ──
    internal_conflict: str = Field(default="", description="反派内心的矛盾/挣扎")
    reader_sympathy_hook: str = Field(default="", description="让读者共情的关键设定")
    escalation_arc: list[str] = Field(default_factory=list, description="反派自身的成长弧线")
    fall_from_grace: str = Field(default="", description="反派曾经是'好人'的设定")


# ── 剧情骨架 ──────────────────────────────────────────────────────────────────

class Milestone(BaseModel):
    index: int
    title: str
    description: str
    volume: int
    impact: str          # 对主线格局的影响
    turn_type: str = Field(default="", description="转折类型（反转/升级/牺牲/揭露/背叛）")
    emotional_impact: str = Field(default="", description="情感冲击描述")


class PlotFramework(BaseModel):
    ultimate_goal: str
    milestones: list[Milestone]
    global_foreshadowing: list[str]   # 全书级伏笔
    thematic_arcs: list[str] = Field(default_factory=list, description="跨卷主题弧线")
    core_dilemmas: list[str] = Field(default_factory=list, description="全书核心困境")


# ── 章节大纲 ─────────────────────────────────────────────────────────────────

class ChapterOutlineItem(BaseModel):
    chapter_num: int          # 全书章节序号（从1开始）
    volume_chapter_num: int   # 卷内序号（从1开始）
    title: str
    hook_start: str           # 开头：兑现上章悬念 or 新冲突直入
    core_events: list[str]    # 主要事件（2-4个，动词+名词，具体）
    pleasure_point: str = ""  # 本章爽点（无则留空）
    hook_end: str             # 结尾钩子（让读者必须翻下一章）
    protagonist_power: str    # 本章结束时主角境界
    thematic_element: str = Field(default="", description="本章主题元素")
    knowledge_seed: str = Field(default="", description="本章融入的知识点")
    hook_type: str = Field(default="", description="钩子类型（cliffhanger/revelation/threat_escalation等）")
    pacing_type: str = Field(default="", description="章节节奏类型（action/buildup/revelation/aftermath/turning_point/grief/desperation/comedic_relief）")
    emotional_beat: str = Field(default="", description="章内情感节拍（如紧张→绝望→反转→释然）")
    # ── 叙事工程扩展 (#2,#3,#11,#12,#33) ──
    narrative_distance: str = Field(default="medium", description="叙事视距：close/medium/montage/panoramic")
    golden_sentence_seed: str = Field(default="", description="金句种子方向")
    subversion_type: str = Field(default="none", description="预期颠覆类型：none/type_shift/timing_shift/subject_shift")
    pov: str = Field(default="protagonist", description="叙事视角：protagonist/antagonist/side_character/bystander")
    dramatic_irony_active: bool = Field(default=False, description="本章是否存在读者-角色信息差")


# ── 卷规划 ───────────────────────────────────────────────────────────────────

class VolumePlan(BaseModel):
    volume_num: int
    title: str
    theme: str
    antagonist_name: str
    core_pleasure_point: str     # 本卷大爽点描述
    protagonist_power_start: str
    protagonist_power_end: str
    ending_hook: str             # 引出下一卷的钩子
    chapters: list[ChapterOutlineItem] = Field(default_factory=list)
    thematic_focus: str = Field(default="", description="本卷主题聚焦")
    ethical_dilemma: str = Field(default="", description="本卷道德困境")
    foreshadowing_seeds: list[str] = Field(default_factory=list, description="本卷埋下的伏笔")
    foreshadowing_payoffs: list[str] = Field(default_factory=list, description="本卷兑现的前卷伏笔")
    pacing_structure: str = Field(default="", description="快/慢/快的节奏分布")
    protagonist_emotional_arc: str = Field(default="", description="主角情绪变化弧线")
    # ── 叙事工程扩展 (#9,#13,#19) ──
    story_phase: str = Field(default="", description="故事宏观阶段：origin/rise/crisis/transcendence")
    intensity_level: str = Field(default="high", description="卷强度等级：high/medium/low")
    iconic_scene: str = Field(default="", description="本卷标志性名场面描述")


# ── 完整大纲 ─────────────────────────────────────────────────────────────────

class WebNovelOutline(BaseModel):
    title: str
    world: WorldSetting
    characters: list[CharacterProfile]
    antagonists: list[AntagonistTier]
    plot_framework: PlotFramework
    volumes: list[VolumePlan]
    disciplines: list[str] = Field(default_factory=list, description="已解析的学科列表")


# ── 写作结果 ─────────────────────────────────────────────────────────────────

class ChapterResult(BaseModel):
    volume_num: int
    chapter_num: int           # 全书
    volume_chapter_num: int    # 卷内
    title: str
    content: str
    summary: str               # 200字摘要，传递给下一章保持连贯
    protagonist_power_end: str
    consistency_issues: list[str] = Field(default_factory=list)
    hook_strength: int = -1    # 1-10，一致性校验器评分


class WebNovelResult(BaseModel):
    title: str
    outline: WebNovelOutline
    chapters: list[ChapterResult]

    def to_markdown(self) -> str:
        lines = [f"# {self.title}\n"]

        # 世界观
        w = self.outline.world
        lines.append("\n## 世界观\n")
        lines.append(w.description)
        lines.append(f"\n**力量体系：{w.power_system.name}**\n")
        for lvl in w.power_system.levels:
            lines.append(f"{lvl.rank}. {lvl.name}：{lvl.typical_power}")
        lines.append(f"\n突破条件：{w.power_system.breakthrough_conditions}")
        if w.special_rules:
            lines.append(f"\n特殊规则：{w.special_rules}")
        lines.append("")

        # 势力
        lines.append("\n## 势力格局\n")
        for f in w.factions:
            type_label = {
                "protagonist_side": "主角方", "enemy_near": "近期敌对",
                "enemy_mid": "中期敌对", "enemy_boss": "终极敌对",
                "neutral": "中立", "ally": "潜在盟友",
            }.get(f.faction_type, f.faction_type)
            lines.append(f"**{f.name}**（{type_label}）- {f.power_description}")
            if f.leader:
                lines.append(f"  领袖：{f.leader}")
        lines.append("")

        # 人物
        role_map = {
            "protagonist": "主角", "love_interest": "感情线",
            "sidekick": "挚友", "mentor": "师父",
            "antagonist_1": "近期反派", "antagonist_2": "中期反派", "antagonist_3": "终极反派",
        }
        lines.append("\n## 人物档案\n")
        for c in self.outline.characters:
            role_label = role_map.get(c.role, c.role)
            lines.append(f"**{c.name}**（{role_label}）  境界：{c.current_power}")
            lines.append(f"- 背景：{c.background}")
            lines.append(f"- 性格：{c.personality}")
            lines.append(f"- 动机：{c.motivation}")
            if c.golden_finger:
                lines.append(f"- 金手指：{c.golden_finger}")
            lines.append(f"- 说话风格：{c.speech_pattern}")
            lines.append("")

        # 反派梯队
        lines.append("\n## 反派梯队\n")
        for a in sorted(self.outline.antagonists, key=lambda x: x.tier):
            lines.append(f"**[第{a.tier}层] {a.name}**（预计第{a.defeat_volume}卷解决）")
            lines.append(f"- 实力：{a.current_power} | 动机：{a.motive}")
            lines.append(f"- 弱点：{a.weakness}")
            lines.append("")

        # 章节正文
        current_vol = None
        for chapter in self.chapters:
            if chapter.volume_num != current_vol:
                current_vol = chapter.volume_num
                vol = next(
                    (v for v in self.outline.volumes if v.volume_num == current_vol), None
                )
                if vol:
                    lines.append(
                        f"\n---\n## 第{current_vol}卷·{vol.title}\n\n> {vol.theme}\n"
                    )
            lines.append(f"\n### 第{chapter.volume_chapter_num}章·{chapter.title}\n")
            lines.append(chapter.content)
            if chapter.consistency_issues:
                lines.append(f"\n> *校验注记：{'|'.join(chapter.consistency_issues)}*")
            lines.append("")

        return "\n".join(lines)

    def to_worldbuilding_markdown(self) -> str:
        """导出世界观设定 MD"""
        w = self.outline.world
        lines = [f"# {self.title} — 世界观设定\n"]
        lines.append("\n## 世界描述\n")
        lines.append(w.description)
        lines.append(f"\n## 力量体系：{w.power_system.name}\n")
        for lvl in w.power_system.levels:
            lines.append(f"**{lvl.rank}. {lvl.name}**\n- 战力：{lvl.typical_power}\n- {lvl.description}\n")
        lines.append(f"\n**突破条件**：{w.power_system.breakthrough_conditions}")
        if w.power_system.special_rules:
            lines.append(f"\n**特殊规则**：{w.power_system.special_rules}")
        lines.append("\n## 势力格局\n")
        type_map = {
            "protagonist_side": "主角方", "enemy_near": "近期敌对",
            "enemy_mid": "中期敌对", "enemy_boss": "终极敌对",
            "neutral": "中立", "ally": "潜在盟友",
        }
        for f in w.factions:
            lines.append(f"### {f.name}（{type_map.get(f.faction_type, f.faction_type)}）\n")
            lines.append(f"- 实力：{f.power_description}")
            lines.append(f"- 描述：{f.description}")
            if f.leader:
                lines.append(f"- 领袖：{f.leader}")
            lines.append("")
        if w.resource_system:
            lines.append(f"\n## 资源体系\n\n{w.resource_system}")
        if w.geography:
            lines.append(f"\n## 地理版图\n\n{w.geography}")
        if w.history_summary:
            lines.append(f"\n## 历史纪元\n\n{w.history_summary}")
        if w.forbidden_zones:
            lines.append(f"\n## 禁区/秘境\n\n{w.forbidden_zones}")
        if w.philosophical_foundation:
            lines.append(f"\n## 哲学内核\n\n{w.philosophical_foundation}")
        if w.cultural_system:
            lines.append(f"\n## 文化体系\n\n{w.cultural_system}")
        if w.social_structure:
            lines.append(f"\n## 社会结构\n\n{w.social_structure}")
        return "\n".join(lines)

    def to_characters_markdown(self) -> str:
        """导出人物设定 MD"""
        lines = [f"# {self.title} — 人物档案\n"]
        role_map = {
            "protagonist": "主角", "love_interest": "感情线",
            "sidekick": "挚友", "mentor": "师父",
            "antagonist_1": "近期反派", "antagonist_2": "中期反派", "antagonist_3": "终极反派",
        }
        lines.append("\n## 主要角色\n")
        for c in self.outline.characters:
            role_label = role_map.get(c.role, c.role)
            lines.append(f"### {c.name}（{role_label}）\n")
            lines.append(f"- **境界**：{c.current_power}")
            lines.append(f"- **背景**：{c.background}")
            lines.append(f"- **性格**：{c.personality}")
            lines.append(f"- **动机**：{c.motivation}")
            lines.append(f"- **说话风格**：{c.speech_pattern}")
            lines.append(f"- **成长弧线**：{c.arc}")
            if c.golden_finger:
                lines.append(f"- **金手指**：{c.golden_finger}")
            if c.psychological_profile:
                lines.append(f"- **心理特征**：{c.psychological_profile}")
            if c.intellectual_stance:
                lines.append(f"- **思想立场**：{c.intellectual_stance}")
            if c.appearance:
                lines.append(f"- **外观**：{c.appearance}")
            if c.signature_move:
                lines.append(f"- **标志招式**：{c.signature_move}")
            if c.hidden_agenda:
                lines.append(f"- **隐藏目标**：{c.hidden_agenda}")
            if c.core_beliefs:
                lines.append(f"- **核心信念**：{'、'.join(c.core_beliefs)}")
            if c.prohibitions:
                lines.append(f"- **绝不会做**：{'、'.join(c.prohibitions)}")
            if c.speech_examples:
                lines.append(f"- **典型台词**：")
                for ex in c.speech_examples:
                    lines.append(f"  - 「{ex}」")
            lines.append("")

        lines.append("\n## 反派梯队\n")
        for a in sorted(self.outline.antagonists, key=lambda x: x.tier):
            lines.append(f"### [{a.tier}层] {a.name}（预计第{a.defeat_volume}卷解决）\n")
            lines.append(f"- **境界**：{a.current_power}")
            lines.append(f"- **动机**：{a.motive}")
            lines.append(f"- **弱点**：{a.weakness}")
            if a.heroic_code:
                lines.append(f"- **坚守底线**：{a.heroic_code}")
            if a.tragic_flaw:
                lines.append(f"- **致命缺陷**：{a.tragic_flaw}")
            if a.sympathetic_element:
                lines.append(f"- **可同情之处**：{a.sympathetic_element}")
            lines.append("")

        return "\n".join(lines)

    def to_scenes_markdown(self) -> str:
        """导出场景设定 MD（从卷主题和世界观提取）"""
        lines = [f"# {self.title} — 场景设定\n"]
        w = self.outline.world
        if w.geography:
            lines.append(f"\n## 主要地域\n\n{w.geography}\n")
        if w.forbidden_zones:
            lines.append(f"\n## 禁区与秘境\n\n{w.forbidden_zones}\n")
        lines.append("\n## 各卷场景概览\n")
        for vol in self.outline.volumes:
            lines.append(f"\n### 第{vol.volume_num}卷《{vol.title}》\n")
            lines.append(f"- **主题**：{vol.theme}")
            if vol.thematic_focus:
                lines.append(f"- **聚焦**：{vol.thematic_focus}")
            if vol.ethical_dilemma:
                lines.append(f"- **道德困境**：{vol.ethical_dilemma}")
            lines.append(f"- **主角境界**：{vol.protagonist_power_start} → {vol.protagonist_power_end}")
            lines.append(f"- **主要反派**：{vol.antagonist_name}")
            lines.append("")
        return "\n".join(lines)


# ── Human-in-the-Loop 审批模型 ─────────────────────────────────────────────

class ApprovalRequest(BaseModel):
    checkpoint_id: str
    agent_name: str
    data: dict
    editable_fields: list[str]


class ApprovalResponse(BaseModel):
    checkpoint_id: str = ""
    action: str = "approve"              # "approve" | "reject" | "modify"
    modifications: dict = Field(default_factory=dict)
    feedback: str = ""
