"""
EntityStore — 实体记忆系统

追踪小说中的动态实体状态：角色、阵营、伏笔线索。
解决长篇写作中最核心的一致性问题：Writer 对早期章节细节的遗忘。

设计原则：
- 状态随章节推进而更新，每章写完后提取变更
- 可序列化为 JSON，与检查点系统集成
- 可作为上下文注入 Writer / ConsistencyChecker 的 prompt
"""

import json
import logging
from dataclasses import dataclass, field, fields as dataclass_fields, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CharacterState:
    """角色动态状态（Agent 化：每个角色拥有灵魂/记忆/目标/禁忌）"""
    name: str
    power_level: str = ""           # 当前境界
    location: str = ""              # 当前位置
    alive: bool = True
    relationships: dict[str, str] = field(default_factory=dict)  # {角色名: 关系描述}
    key_events: list[str] = field(default_factory=list)          # 重要事件记录
    last_updated_chapter: int = 0
    # ── 角色 Agent 化扩展 ──
    core_beliefs: list[str] = field(default_factory=list)        # 核心信念/底线，几乎不变
    personality_traits: list[str] = field(default_factory=list)   # 行为模式，缓慢变化
    known_facts: list[str] = field(default_factory=list)         # 角色知道的信息（信息差追踪）
    goal_stack: list[str] = field(default_factory=list)          # [0]=当前目标, [-1]=终极目标
    prohibitions: list[str] = field(default_factory=list)        # 角色绝不会做的事
    speech_examples: list[str] = field(default_factory=list)     # 2-3句典型台词
    role_type: str = ""             # "main" / "side" / "antagonist"
    first_appearance: int = 0       # 首次出场章节
    last_appearance: int = 0        # 最近出场章节
    appearance_count: int = 0       # 出场章节次数
    departure_status: str = ""      # "" / "departed_explained" / "departed_unexplained"


@dataclass
class FactionState:
    """阵营动态状态"""
    name: str
    status: str = "active"          # active / destroyed / merged / hidden
    leader: str = ""
    key_events: list[str] = field(default_factory=list)
    last_updated_chapter: int = 0


@dataclass
class PlotThread:
    """伏笔/悬念线索"""
    thread_id: str
    description: str
    introduced_chapter: int
    resolved_chapter: int = 0       # 0=未解决
    status: str = "open"            # open / resolved / abandoned
    # ── 钩子管理扩展 ──
    thread_type: str = "foreshadowing"  # "foreshadowing" / "chapter_hook" / "mystery" / "promise"
    urgency: str = "low"                # "low" / "medium" / "high" / "critical"


@dataclass
class TimelineEvent:
    """故事内时间线事件"""
    chapter_num: int
    in_story_time: str              # "第三天·午后"
    event_summary: str
    characters_involved: list[str] = field(default_factory=list)
    location: str = ""


@dataclass
class InformationGap:
    """信息差追踪：谁知道什么，读者知道什么"""
    fact_id: str
    description: str
    known_by: list[str] = field(default_factory=list)
    unknown_to: list[str] = field(default_factory=list)
    reader_knows: bool = True
    dramatic_irony: bool = False     # 读者知道但角色不知道
    introduced_chapter: int = 0
    resolved_chapter: int = 0        # 0=未解决


@dataclass
class ConflictArc:
    """冲突升级追踪"""
    arc_id: str
    description: str
    current_level: str = "personal"  # "personal" → "organizational" → "world"
    level_history: list[str] = field(default_factory=list)
    introduced_chapter: int = 0
    resolved_chapter: int = 0
    status: str = "active"           # "active" / "resolved" / "dormant"


class EntityStore:
    """
    实体记忆存储。

    使用方式：
        store = EntityStore()
        store.init_from_outline(outline)  # 从大纲初始化角色/阵营
        store.update_from_extraction(chapter_num, extraction)  # 每章写完后更新
        context = store.get_writer_context(chapter_num)  # 注入 Writer prompt
        store.prune(chapter_num)  # 每章结束后剪枝，防止长篇 OOM
    """

    # ── 剪枝常量 ──
    ACTIVE_THRESHOLD = 30       # 最近 N 章出现过 → 活跃
    STALE_THREAD_THRESHOLD = 100  # 超过 N 章未解决的伏笔标记为 stale
    MAX_OPEN_THREADS = 20       # 活跃伏笔上限
    MAX_TIMELINE = 30           # 时间线事件上限
    MAX_INFO_GAPS = 20          # 信息差上限
    INFO_GAP_EXPIRE = 50        # 信息差过期章数
    MAX_CONFLICT_ARCS = 10      # 冲突弧上限
    MAX_KEY_EVENTS_ACTIVE = 5   # 活跃角色事件上限
    MAX_KEY_EVENTS_DORMANT = 2  # 休眠角色事件上限

    def __init__(self):
        self.characters: dict[str, CharacterState] = {}
        self.factions: dict[str, FactionState] = {}
        self.plot_threads: list[PlotThread] = []
        # ── 新增子系统 ──
        self.timeline: list[TimelineEvent] = []
        self.current_story_time: str = ""
        self.information_gaps: list[InformationGap] = []
        self.conflict_arcs: list[ConflictArc] = []
        # ── 长篇支持 ──
        self.compressed_history: str = ""  # 早期时间线压缩摘要

    def init_from_outline(self, outline) -> None:
        """从 WebNovelOutline 初始化实体状态"""
        # 初始化角色（含 Agent 化字段）
        for c in outline.characters:
            self.characters[c.name] = CharacterState(
                name=c.name,
                power_level=c.current_power,
                alive=True,
                core_beliefs=getattr(c, 'core_beliefs', []) or [],
                personality_traits=[c.personality] if c.personality else [],
                goal_stack=getattr(c, 'initial_goals', []) or [],
                prohibitions=getattr(c, 'prohibitions', []) or [],
                speech_examples=getattr(c, 'speech_examples', []) or [],
                role_type="main" if c.role in ("protagonist", "love_interest", "sidekick", "mentor") else "side",
            )
        for a in outline.antagonists:
            self.characters[a.name] = CharacterState(
                name=a.name,
                power_level=a.current_power,
                alive=True,
                role_type="antagonist",
            )

        # 初始化阵营
        for f in outline.world.factions:
            self.factions[f.name] = FactionState(
                name=f.name,
                leader=f.leader,
            )

        # 初始化全书伏笔
        for i, hint in enumerate(outline.plot_framework.global_foreshadowing):
            self.plot_threads.append(PlotThread(
                thread_id=f"foreshadow_{i}",
                description=hint,
                introduced_chapter=0,
            ))

    def update_from_extraction(self, chapter_num: int, extraction: dict) -> None:
        """
        根据每章提取的状态变更更新实体记忆。

        extraction 格式：
        {
            "character_updates": [
                {"name": "xxx", "power_level": "新境界", "location": "新位置",
                 "alive": true, "event": "事件描述"}
            ],
            "faction_updates": [
                {"name": "xxx", "status": "destroyed", "event": "被主角击败"}
            ],
            "new_threads": [
                {"description": "发现神秘地图碎片"}
            ],
            "resolved_threads": [
                {"thread_id": "foreshadow_0"}
            ]
        }
        """
        # 更新角色
        for cu in extraction.get("character_updates", []):
            name = cu.get("name", "")
            if name not in self.characters:
                # 新角色（章节中新出现的）
                self.characters[name] = CharacterState(name=name)

            state = self.characters[name]
            if cu.get("power_level"):
                state.power_level = cu["power_level"]
            if cu.get("location"):
                state.location = cu["location"]
            if "alive" in cu:
                state.alive = cu["alive"]
            if cu.get("event"):
                state.key_events.append(f"[第{chapter_num}章] {cu['event']}")
                # 只保留最近10条事件
                if len(state.key_events) > 10:
                    state.key_events = state.key_events[-10:]
            if cu.get("relationships"):
                state.relationships.update(cu["relationships"])
            state.last_updated_chapter = chapter_num

        # 更新阵营
        for fu in extraction.get("faction_updates", []):
            name = fu.get("name", "")
            if name not in self.factions:
                self.factions[name] = FactionState(name=name)

            state = self.factions[name]
            if fu.get("status"):
                state.status = fu["status"]
            if fu.get("leader"):
                state.leader = fu["leader"]
            if fu.get("event"):
                state.key_events.append(f"[第{chapter_num}章] {fu['event']}")
                if len(state.key_events) > 5:
                    state.key_events = state.key_events[-5:]
            state.last_updated_chapter = chapter_num

        # 新伏笔
        for nt in extraction.get("new_threads", []):
            tid = f"chapter_{chapter_num}_{len(self.plot_threads)}"
            self.plot_threads.append(PlotThread(
                thread_id=tid,
                description=nt["description"],
                introduced_chapter=chapter_num,
            ))

        # 解决伏笔
        for rt in extraction.get("resolved_threads", []):
            tid = rt.get("thread_id", "")
            for pt in self.plot_threads:
                if pt.thread_id == tid and pt.status == "open":
                    pt.status = "resolved"
                    pt.resolved_chapter = chapter_num

        # ── 章节钩子注册 ──
        hook = extraction.get("chapter_hook_registered")
        if hook and hook.get("description"):
            tid = f"hook_ch{chapter_num}"
            self.plot_threads.append(PlotThread(
                thread_id=tid,
                description=hook["description"],
                introduced_chapter=chapter_num,
                thread_type="chapter_hook",
                urgency=hook.get("urgency", "high"),
            ))

        # ── 时间线更新 ──
        tl = extraction.get("timeline_update")
        if tl:
            if tl.get("in_story_time"):
                self.current_story_time = tl["in_story_time"]
            for ev in tl.get("events", []):
                self.timeline.append(TimelineEvent(
                    chapter_num=chapter_num,
                    in_story_time=ev.get("time", self.current_story_time),
                    event_summary=ev.get("event", ""),
                    characters_involved=ev.get("characters", []),
                    location=ev.get("location", ""),
                ))
            # 保留最近 50 条时间线事件
            if len(self.timeline) > 50:
                self.timeline = self.timeline[-50:]

        # ── 信息差更新 ──
        for gap in extraction.get("new_info_gaps", []):
            fid = f"info_{chapter_num}_{len(self.information_gaps)}"
            known_by = gap.get("known_by", [])
            unknown_to = gap.get("unknown_to", [])
            reader_knows = gap.get("reader_knows", True)
            self.information_gaps.append(InformationGap(
                fact_id=fid,
                description=gap["description"],
                known_by=known_by,
                unknown_to=unknown_to,
                reader_knows=reader_knows,
                dramatic_irony=reader_knows and bool(unknown_to),
                introduced_chapter=chapter_num,
            ))
            # 同步到角色 known_facts
            for cname in known_by:
                if cname in self.characters:
                    self.characters[cname].known_facts.append(gap["description"])

        for upd in extraction.get("info_gap_updates", []):
            desc = upd.get("description", "")
            newly_knows = upd.get("newly_knows", [])
            for ig in self.information_gaps:
                if ig.description == desc and ig.resolved_chapter == 0:
                    for cname in newly_knows:
                        if cname in ig.unknown_to:
                            ig.unknown_to.remove(cname)
                        if cname not in ig.known_by:
                            ig.known_by.append(cname)
                        if cname in self.characters:
                            self.characters[cname].known_facts.append(desc)
                    if not ig.unknown_to:
                        ig.resolved_chapter = chapter_num
                        ig.dramatic_irony = False
                    break

        # ── 冲突更新 ──
        for cu in extraction.get("conflict_updates", []):
            desc = cu.get("description", "")
            new_level = cu.get("new_level", "")
            # 查找已有冲突
            found = False
            for arc in self.conflict_arcs:
                if arc.description == desc and arc.status == "active":
                    if new_level and new_level != arc.current_level:
                        arc.level_history.append(f"[第{chapter_num}章] {arc.current_level}→{new_level}")
                        arc.current_level = new_level
                    if cu.get("resolved"):
                        arc.status = "resolved"
                        arc.resolved_chapter = chapter_num
                    found = True
                    break
            if not found and desc:
                self.conflict_arcs.append(ConflictArc(
                    arc_id=f"conflict_{chapter_num}_{len(self.conflict_arcs)}",
                    description=desc,
                    current_level=new_level or "personal",
                    level_history=[f"[第{chapter_num}章] 引入（{new_level or 'personal'}）"],
                    introduced_chapter=chapter_num,
                ))

        # ── 角色出场追踪 ──
        appeared_chars = set()
        for cu in extraction.get("character_updates", []):
            name = cu.get("name", "")
            if name:
                appeared_chars.add(name)
        for name in appeared_chars:
            if name in self.characters:
                state = self.characters[name]
                if state.first_appearance == 0:
                    state.first_appearance = chapter_num
                state.last_appearance = chapter_num
                state.appearance_count += 1

        # ── 角色目标更新 ──
        for cu in extraction.get("character_updates", []):
            name = cu.get("name", "")
            if name in self.characters:
                if cu.get("new_goal"):
                    self.characters[name].goal_stack.insert(0, cu["new_goal"])
                    if len(self.characters[name].goal_stack) > 5:
                        self.characters[name].goal_stack = self.characters[name].goal_stack[:5]
                if cu.get("goal_completed"):
                    goal = cu["goal_completed"]
                    if goal in self.characters[name].goal_stack:
                        self.characters[name].goal_stack.remove(goal)

    def get_stale_hooks(self, current_chapter: int, threshold: int = 5) -> list[PlotThread]:
        """检测超过 threshold 章未兑现的章节钩子"""
        return [
            pt for pt in self.plot_threads
            if pt.status == "open"
            and pt.thread_type == "chapter_hook"
            and (current_chapter - pt.introduced_chapter) > threshold
        ]

    def get_missing_characters(self, current_chapter: int, threshold: int = 10) -> list[CharacterState]:
        """检测出场 2+ 次但超过 threshold 章未出现、无离场说明的配角"""
        return [
            c for c in self.characters.values()
            if c.alive
            and c.role_type == "side"
            and c.appearance_count >= 2
            and c.departure_status == ""
            and c.last_appearance > 0
            and (current_chapter - c.last_appearance) > threshold
        ]

    # ── 分层查询 ──────────────────────────────────────────────────────────────

    def _classify_character(self, c: CharacterState, chapter_num: int) -> str:
        """将角色分为 active / dormant / archived"""
        if not c.alive or c.departure_status == "departed_explained":
            return "archived"
        if c.last_appearance > 0 and (chapter_num - c.last_appearance) > self.ACTIVE_THRESHOLD:
            if c.role_type == "main":
                return "active"  # 主角永远活跃
            return "dormant"
        return "active"

    def get_active_characters(self, chapter_num: int) -> list[CharacterState]:
        """获取活跃角色列表"""
        return [
            c for c in self.characters.values()
            if self._classify_character(c, chapter_num) == "active"
        ]

    def get_dormant_characters(self, chapter_num: int) -> list[CharacterState]:
        """获取休眠角色列表"""
        return [
            c for c in self.characters.values()
            if self._classify_character(c, chapter_num) == "dormant"
        ]

    # ── 剪枝 ─────────────────────────────────────────────────────────────────

    def prune(self, chapter_num: int) -> None:
        """
        每章结束后调用，剪枝过期/低优先级数据，防止长篇 OOM。

        策略：
        - 休眠角色：事件压缩到 2 条，known_facts 压缩到 3 条
        - 归档角色：只保留名字、死亡原因、最终境界
        - 伏笔：100 章未解决标记 stale，只保留 20 个活跃线
        - 时间线：保留最近 30 条，更早的压缩到 compressed_history
        - 信息差：50 章过期自动关闭，上限 20
        - 冲突弧：已解决的移除，上限 10
        """
        self._prune_characters(chapter_num)
        self._prune_plot_threads(chapter_num)
        self._prune_timeline()
        self._prune_info_gaps(chapter_num)
        self._prune_conflict_arcs()
        self._prune_factions()
        logger.debug(f"[EntityStore] 剪枝完成 ch={chapter_num}: "
                      f"chars={len(self.characters)} threads={len(self.plot_threads)} "
                      f"timeline={len(self.timeline)} gaps={len(self.information_gaps)} "
                      f"arcs={len(self.conflict_arcs)}")

    def _prune_characters(self, chapter_num: int) -> None:
        for c in self.characters.values():
            tier = self._classify_character(c, chapter_num)
            if tier == "dormant":
                if len(c.key_events) > self.MAX_KEY_EVENTS_DORMANT:
                    c.key_events = c.key_events[-self.MAX_KEY_EVENTS_DORMANT:]
                if len(c.known_facts) > 3:
                    c.known_facts = c.known_facts[-3:]
                if len(c.speech_examples) > 1:
                    c.speech_examples = c.speech_examples[:1]
            elif tier == "archived":
                # 极度压缩：只保留核心信息
                c.key_events = c.key_events[-1:] if c.key_events else []
                c.known_facts = []
                c.speech_examples = []
                c.relationships = {}
                c.goal_stack = []
            elif tier == "active":
                if len(c.key_events) > self.MAX_KEY_EVENTS_ACTIVE:
                    c.key_events = c.key_events[-self.MAX_KEY_EVENTS_ACTIVE:]

    def _prune_plot_threads(self, chapter_num: int) -> None:
        # 标记超时伏笔为 stale
        for pt in self.plot_threads:
            if (pt.status == "open"
                    and pt.thread_type == "foreshadowing"
                    and (chapter_num - pt.introduced_chapter) > self.STALE_THREAD_THRESHOLD):
                pt.status = "stale"
                logger.debug(f"[EntityStore] 伏笔过期: {pt.thread_id} ({pt.description[:30]}...)")

        # 移除已解决/废弃/过期的低优先级线，只保留 MAX_OPEN_THREADS 个活跃线
        open_threads = [pt for pt in self.plot_threads if pt.status == "open"]
        if len(open_threads) > self.MAX_OPEN_THREADS:
            # 按紧急度和引入时间排序，保留最重要的
            urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            open_threads.sort(key=lambda pt: (urgency_order.get(pt.urgency, 3), -pt.introduced_chapter))
            keep_ids = {pt.thread_id for pt in open_threads[:self.MAX_OPEN_THREADS]}
            # 超出部分标记为 abandoned
            for pt in self.plot_threads:
                if pt.status == "open" and pt.thread_id not in keep_ids:
                    pt.status = "abandoned"

        # 移除非 open 且年代久远的线（节省内存）
        self.plot_threads = [
            pt for pt in self.plot_threads
            if pt.status == "open" or (chapter_num - pt.introduced_chapter) <= 200
        ]

    def _prune_timeline(self) -> None:
        if len(self.timeline) > self.MAX_TIMELINE:
            # 将溢出的事件压缩到 compressed_history
            overflow = self.timeline[:-self.MAX_TIMELINE]
            summary_parts = [f"[{ev.in_story_time}] {ev.event_summary}" for ev in overflow[-10:]]
            if summary_parts:
                new_summary = "；".join(summary_parts)
                if self.compressed_history:
                    self.compressed_history = self.compressed_history[-500:] + "；" + new_summary
                else:
                    self.compressed_history = new_summary
                # 总长度限制
                if len(self.compressed_history) > 1000:
                    self.compressed_history = self.compressed_history[-1000:]
            self.timeline = self.timeline[-self.MAX_TIMELINE:]

    def _prune_info_gaps(self, chapter_num: int) -> None:
        # 过期自动关闭
        for ig in self.information_gaps:
            if (ig.resolved_chapter == 0
                    and (chapter_num - ig.introduced_chapter) > self.INFO_GAP_EXPIRE):
                ig.resolved_chapter = chapter_num  # 标记为过期解决
                ig.dramatic_irony = False

        # 移除已解决的，只保留最近的 MAX_INFO_GAPS 个活跃
        active = [ig for ig in self.information_gaps if ig.resolved_chapter == 0]
        if len(active) > self.MAX_INFO_GAPS:
            active.sort(key=lambda ig: ig.introduced_chapter, reverse=True)
            keep_ids = {ig.fact_id for ig in active[:self.MAX_INFO_GAPS]}
            for ig in self.information_gaps:
                if ig.resolved_chapter == 0 and ig.fact_id not in keep_ids:
                    ig.resolved_chapter = chapter_num

        # 移除已解决且年代久远的
        self.information_gaps = [
            ig for ig in self.information_gaps
            if ig.resolved_chapter == 0 or (chapter_num - ig.introduced_chapter) <= 100
        ]

    def _prune_conflict_arcs(self) -> None:
        # 移除已解决的
        self.conflict_arcs = [arc for arc in self.conflict_arcs if arc.status != "resolved"]
        # 超出上限时移除最老的 dormant
        if len(self.conflict_arcs) > self.MAX_CONFLICT_ARCS:
            dormant = [arc for arc in self.conflict_arcs if arc.status == "dormant"]
            dormant.sort(key=lambda arc: arc.introduced_chapter)
            remove_ids = {arc.arc_id for arc in dormant[:len(self.conflict_arcs) - self.MAX_CONFLICT_ARCS]}
            self.conflict_arcs = [arc for arc in self.conflict_arcs if arc.arc_id not in remove_ids]

    def _prune_factions(self) -> None:
        # 已销毁阵营只保留事件摘要
        for f in self.factions.values():
            if f.status in ("destroyed", "merged"):
                f.key_events = f.key_events[-1:] if f.key_events else []

    def get_compressed_state_summary(self, chapter_num: int) -> str:
        """为 PlotExtender 提供全局压缩状态（500 字以内）"""
        parts = []
        # 休眠角色概况
        dormant = self.get_dormant_characters(chapter_num)
        if dormant:
            names = [c.name for c in dormant[:10]]
            parts.append(f"休眠角色({len(dormant)}人): {'、'.join(names)}")
        # 已解决伏笔数
        resolved = sum(1 for pt in self.plot_threads if pt.status == "resolved")
        stale = sum(1 for pt in self.plot_threads if pt.status == "stale")
        open_count = sum(1 for pt in self.plot_threads if pt.status == "open")
        parts.append(f"伏笔: {open_count}个活跃, {resolved}个已解决, {stale}个过期")
        # 压缩历史
        if self.compressed_history:
            parts.append(f"早期大事: {self.compressed_history[-300:]}")
        return "\n".join(parts)

    def get_writer_context(self, chapter_num: int, max_context_chars: int = 2000) -> str:
        """
        生成面向 Writer 的实体状态上下文摘要。
        按优先级输出各维度，超过 max_context_chars 时截断低优先级部分。
        """
        sections = []

        # P1: 角色状态（仅活跃角色，最高优先级）
        active_chars = self.get_active_characters(chapter_num)
        if active_chars:
            lines = ["【角色当前状态】"]
            for c in sorted(active_chars, key=lambda x: x.last_updated_chapter, reverse=True)[:10]:
                parts = [f"{c.name}（境界：{c.power_level}"]
                if c.location:
                    parts.append(f"，位置：{c.location}")
                parts.append("）")
                line = "".join(parts)
                if c.key_events:
                    line += f" — 最近：{c.key_events[-1]}"
                lines.append(f"  {line}")
            sections.append("\n".join(lines))

        # P1: 已死亡角色（避免复活）
        dead_chars = [c for c in self.characters.values() if not c.alive]
        if dead_chars:
            lines = ["【已死亡角色（不可再出场）】"]
            for c in dead_chars:
                lines.append(f"  {c.name}（{c.key_events[-1] if c.key_events else '已死亡'}）")
            sections.append("\n".join(lines))

        # P2: 未兑现钩子
        stale_hooks = self.get_stale_hooks(chapter_num)
        if stale_hooks:
            lines = ["【未兑现悬念（需尽快处理）】"]
            for pt in stale_hooks[:3]:
                lines.append(f"  - {pt.description}（第{pt.introduced_chapter}章设置，已过{chapter_num - pt.introduced_chapter}章）")
            sections.append("\n".join(lines))

        # P3: 信息差提醒（戏剧反讽）
        active_irony = [ig for ig in self.information_gaps if ig.dramatic_irony and ig.resolved_chapter == 0]
        if active_irony:
            lines = ["【信息差提醒】"]
            for ig in active_irony[:3]:
                unknown_str = "、".join(ig.unknown_to[:3])
                lines.append(f"  读者知道但[{unknown_str}]不知道：{ig.description}")
            sections.append("\n".join(lines))

        # P4: 角色行为禁忌
        chars_with_prohibitions = [
            c for c in self.characters.values()
            if c.alive and c.prohibitions and c.role_type in ("main", "antagonist")
        ]
        if chars_with_prohibitions:
            lines = ["【角色行为禁忌】"]
            for c in chars_with_prohibitions[:5]:
                lines.append(f"  {c.name}：{'｜'.join(c.prohibitions[:3])}")
            sections.append("\n".join(lines))

        # P5: 时间线（最近事件）
        if self.timeline:
            lines = [f"【当前时间线】故事时间：{self.current_story_time}"]
            for ev in self.timeline[-3:]:
                lines.append(f"  [{ev.in_story_time}] {ev.event_summary}")
            sections.append("\n".join(lines))

        # P6: 未解决伏笔
        open_threads = [pt for pt in self.plot_threads if pt.status == "open" and pt.thread_type == "foreshadowing"]
        if open_threads:
            lines = ["【未解决的伏笔】"]
            for pt in open_threads[-5:]:
                lines.append(f"  - {pt.description}（第{pt.introduced_chapter}章引入）")
            sections.append("\n".join(lines))

        # P7: 消失角色提醒
        missing = self.get_missing_characters(chapter_num)
        if missing:
            lines = ["【消失角色提醒（考虑交代去向）】"]
            for c in missing[:3]:
                lines.append(f"  {c.name}（最后出场：第{c.last_appearance}章，已消失{chapter_num - c.last_appearance}章）")
            sections.append("\n".join(lines))

        # P8: 冲突格局
        active_conflicts = [arc for arc in self.conflict_arcs if arc.status == "active"]
        if active_conflicts:
            lines = ["【冲突格局】"]
            level_label = {"personal": "个人", "organizational": "组织", "world": "世界"}
            for arc in active_conflicts[:3]:
                lines.append(f"  {arc.description}（{level_label.get(arc.current_level, arc.current_level)}级）")
            sections.append("\n".join(lines))

        # 按优先级截断
        result = ""
        for section in sections:
            if len(result) + len(section) + 2 > max_context_chars:
                break
            result += section + "\n\n"

        return result.strip()

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容的 dict"""
        return {
            "characters": {name: asdict(c) for name, c in self.characters.items()},
            "factions": {name: asdict(f) for name, f in self.factions.items()},
            "plot_threads": [asdict(pt) for pt in self.plot_threads],
            "timeline": [asdict(ev) for ev in self.timeline],
            "current_story_time": self.current_story_time,
            "information_gaps": [asdict(ig) for ig in self.information_gaps],
            "conflict_arcs": [asdict(arc) for arc in self.conflict_arcs],
            "compressed_history": self.compressed_history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EntityStore":
        """从 dict 反序列化（兼容新旧数据格式）"""
        store = cls()
        char_fields = {f.name for f in dataclass_fields(CharacterState)}
        faction_fields = {f.name for f in dataclass_fields(FactionState)}
        thread_fields = {f.name for f in dataclass_fields(PlotThread)}
        timeline_fields = {f.name for f in dataclass_fields(TimelineEvent)}
        info_gap_fields = {f.name for f in dataclass_fields(InformationGap)}
        conflict_fields = {f.name for f in dataclass_fields(ConflictArc)}

        for name, cdata in data.get("characters", {}).items():
            store.characters[name] = CharacterState(
                **{k: v for k, v in cdata.items() if k in char_fields}
            )
        for name, fdata in data.get("factions", {}).items():
            store.factions[name] = FactionState(
                **{k: v for k, v in fdata.items() if k in faction_fields}
            )
        for ptdata in data.get("plot_threads", []):
            store.plot_threads.append(PlotThread(
                **{k: v for k, v in ptdata.items() if k in thread_fields}
            ))
        for evdata in data.get("timeline", []):
            store.timeline.append(TimelineEvent(
                **{k: v for k, v in evdata.items() if k in timeline_fields}
            ))
        store.current_story_time = data.get("current_story_time", "")
        store.compressed_history = data.get("compressed_history", "")
        for igdata in data.get("information_gaps", []):
            store.information_gaps.append(InformationGap(
                **{k: v for k, v in igdata.items() if k in info_gap_fields}
            ))
        for arcdata in data.get("conflict_arcs", []):
            store.conflict_arcs.append(ConflictArc(
                **{k: v for k, v in arcdata.items() if k in conflict_fields}
            ))
        return store

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "EntityStore":
        return cls.from_dict(json.loads(json_str))
