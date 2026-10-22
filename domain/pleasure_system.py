"""
爽点与节奏系统 — 为小说生成提供工业级写作规范

功能：
1. 各类爽点的5阶段释放公式
2. 卷/章节奏曲线定义
3. 钩子类型库
4. 供 Agent 使用的格式化指导文本
"""


# ── 爽点释放公式 ─────────────────────────────────────────────────────────────

PLEASURE_FORMULAS: dict[str, dict] = {
    "逆袭打脸": {
        "stages": [
            "①铺垫：对方出言不逊/轻视主角，旁观者或暗笑或不敢出声",
            "②蓄力：主角沉默应对或低调反击，让对方继续嚣张（越嚣张越好）",
            "③反转：主角一击即中，展露真实实力，对方表情凝固",
            "④涟漪：旁观者震惊→议论→传扬，打脸效果被放大",
            "⑤收尾：对方跪地/沉默/逃走，主角淡然离场，不做多余解释",
        ],
        "small_frequency": "每3章1次小打脸（口头反击/小展露）",
        "big_frequency": "卷高潮1次大打脸（当众碾压/颠覆认知）",
        "intensity_curve": "小打脸2-3分 → 中打脸5-6分 → 卷高潮9-10分",
        "key_technique": "铺垫时间越长、被轻视越深，打脸越爽。必须写旁观者反应作为爽感放大器。",
        "forbidden": "不能打完脸还留情面；不能打脸后自谦'我只是运气好'；不能跳过旁观者反应。",
    },
    "升级爽": {
        "stages": [
            "①困境：被强敌压制或遭遇瓶颈，现有实力明显不够",
            "②绝望：苦苦支撑，读者觉得这次真的要输了",
            "③契机：灵感闪现/危机触发顿悟/金手指启动",
            "④突破：渡劫/蜕变过程（要有仪式感+感官化描写——光芒/震动/天象）",
            "⑤碾压：以新境界实力逆转局面，打出之前不可能的攻击",
        ],
        "small_frequency": "每5章1次小突破（境界巩固/技能领悟）",
        "big_frequency": "卷高潮1次大突破（跨大境界/质变）",
        "intensity_curve": "小突破3-4分 → 中突破6-7分 → 卷高潮10分",
        "key_technique": "突破前的绝望感必须真实——读者真的觉得主角要输。突破时用感官化语言：光/热/声音/震动。",
        "forbidden": "不能无缘无故突破；不能'打坐三天就突破了'（太平淡）；突破后必须有战力对比。",
    },
    "系统面板": {
        "stages": [
            "①触发：完成任务/达成条件，系统提示音响起",
            "②展示：面板弹出，数据变化一目了然（属性+/奖励展示）",
            "③惊喜：隐藏奖励/额外奖励/稀有道具，超出预期",
            "④应用：立即使用新能力/道具，效果立竿见影",
            "⑤优越：与周围人对比，差距可视化（别人苦修一年不如系统一次奖励）",
        ],
        "small_frequency": "每2-3章1次系统互动（任务/奖励/提示）",
        "big_frequency": "每卷1次系统大升级（新功能解锁/系统进化）",
        "intensity_curve": "日常奖励2-3分 → 隐藏任务6-7分 → 系统进化10分",
        "key_technique": "数据变化要有对比感——'力量+500'本身不够爽，要写出这500意味着什么。",
        "forbidden": "不能让系统万能（要有限制/代价）；不能每次都是简单+属性（要有变化）。",
    },
    "装逼收徒": {
        "stages": [
            "①伪装：主角低调出场，被人当成普通人/弱者",
            "②轻视：旁人嘲笑/无视/施压，主角不动声色",
            "③露一手：主角不经意间展露一鳞半爪，但被当成巧合",
            "④全面揭露：关键时刻真实实力暴露，全场震惊",
            "⑤追随：之前轻视的人跪求拜师/加入，之前帮助过主角的人获得回报",
        ],
        "small_frequency": "每4章1次小展露（部分实力曝光）",
        "big_frequency": "卷高潮1次完整揭露",
        "intensity_curve": "小展露3分 → 中展露6分 → 完整揭露10分",
        "key_technique": "伪装时间越长，揭露越震撼。要安排'善待主角的小人物'，揭露后让他们获益。",
        "forbidden": "不能频繁揭露（会疲劳）；揭露后必须有实质性格局变化。",
    },
    "复仇": {
        "stages": [
            "①仇恨积累：回忆/闪回仇恨根源，让读者感同身受",
            "②接近：主角逐步接近仇人，但受阻/被打退",
            "③突破障碍：克服困难，终于直面仇人",
            "④复仇过程：不是一招秒杀——要让仇人经历恐惧、绝望、后悔",
            "⑤清算：仇人伏法，但主角并不只是快感——有复杂情绪",
        ],
        "small_frequency": "每卷对仇人造成1次实质性打击",
        "big_frequency": "终卷完成最终复仇",
        "intensity_curve": "初期打击3分 → 中期重创6-7分 → 最终清算10分",
        "key_technique": "仇恨要具体——不是抽象的'灭门之仇'，而是具体的画面和感受。复仇过程要让仇人'品尝到主角曾经的痛苦'。",
        "forbidden": "不能一刀秒杀仇人（太快，读者不过瘾）；复仇后主角不能毫无触动。",
    },
    "种田积累": {
        "stages": [
            "①规划：主角制定发展蓝图（修炼计划/建设规划/资源配置）",
            "②执行：逐步实施，遇到小困难逐一解决",
            "③里程碑：阶段性成果展示（数据对比/实力飞跃/势力壮大）",
            "④超预期：计划外的收获——偶然发现/意外机遇/连锁反应",
            "⑤格局升级：积累质变——从个人到团队到势力，视野升级",
        ],
        "small_frequency": "每3章1次积累成果展示",
        "big_frequency": "卷高潮1次格局质变",
        "intensity_curve": "日常积累2-3分 → 阶段成果5-6分 → 质变飞跃10分",
        "key_technique": "成果要有对比——展示积累前后的巨大差距。让读者有'参与建设'的代入感。",
        "forbidden": "不能只写结果不写过程；不能每次都顺利（要有挫折才真实）。",
    },

    # ── 负向情绪体验（虐心向） ────────────────────────────────────────────────
    # 好的网文不只有爽，还需要痛。痛是爽的前奏和放大器。
    # 没有低谷就没有高潮，没有失去就不懂珍贵。

    "虐心牺牲": {
        "stages": [
            "①温情铺垫：用2-3章建立读者与牺牲角色的情感连接——共患难/日常温馨/承诺",
            "②危机降临：不可抗的大危机出现，必须有人付出代价",
            "③抉择时刻：牺牲者明知结局却义无反顾——写出'选择'而非'被动死亡'",
            "④牺牲过程：不要一笔带过——写出最后的对话、眼神、未完成的话，让读者心碎",
            "⑤余波与蜕变：主角的悲痛不能一章消化——用沉默/行为变化/梦境表现，化悲痛为力量",
        ],
        "small_frequency": "每10-15章1次小别离（暂别/受伤/失散）",
        "big_frequency": "每2-3卷1次重要角色牺牲/永别",
        "intensity_curve": "小别离3-4分 → 重伤告别6-7分 → 至亲牺牲10分",
        "key_technique": "牺牲角色必须是读者真正喜欢的——花时间建立情感连接。"
                         "死亡前的最后一句话比死亡本身更重要。"
                         "牺牲后的沉默比嚎啕大哭更有力量。参考：《诡秘之主》克莱恩的每一次失去。",
        "forbidden": "不能为虐而虐（必须有叙事意义）；不能死后一章就遗忘；"
                     "不能让读者觉得'这个人死了作者也不在乎'；不能连续两章死重要角色（读者会麻木）。",
        "emotion_type": "negative",
    },
    "绝境求生": {
        "stages": [
            "①绝境降临：所有退路断绝——同伴失散、金手指失灵、实力被压制",
            "②身心折磨：不仅是肉体的痛——精神崩溃的边缘、信念动摇、回忆走马灯",
            "③一线生机：不是开挂——而是靠意志力/智慧/他人的遗志找到微弱希望",
            "④苦撑过程：反复受伤、反复站起，每一步都是煎熬，读者感受到'活着真难'",
            "⑤劫后余生：活下来但不完整——留下伤疤/心理阴影/失去了什么，人变得更沉默更强大",
        ],
        "small_frequency": "每卷1次小绝境（被围困/资源耗尽/受重伤）",
        "big_frequency": "每3-5卷1次大绝境（九死一生/全面崩盘）",
        "intensity_curve": "小困境4分 → 重大危机7分 → 九死一生10分",
        "key_technique": "绝境中不能开金手指——这是考验主角'人性'而非'实力'的时刻。"
                         "要写主角的恐惧——真正的勇敢不是不怕，是怕了还要上。"
                         "劫后余生的平静比绝境本身更打动人。参考：《凡人修仙传》韩立多次死里逃生。",
        "forbidden": "不能在绝境中突然领悟新技能（太假）；不能每次绝境都全员存活（无代价=无紧张感）；"
                     "不能用旁白说'他很痛苦'，要用行为和细节展现。",
        "emotion_type": "negative",
    },
    "背叛与觉醒": {
        "stages": [
            "①信任构建：用5+章建立主角与背叛者之间的深厚信任——并肩作战/共同经历",
            "②暗线伏笔：在信任表面下埋入2-3处微妙不对劲（只有回看才会发现）",
            "③背叛揭露：不能直接告知——让主角逐步发现真相，每一层都更心寒",
            "④情感崩塌：主角的愤怒→不信→心灰→自我怀疑，写出'被最信任的人捅刀'的锥心之痛",
            "⑤觉醒重生：从被背叛的废墟中站起来——不是变得冷血，而是变得更清醒、更强韧",
        ],
        "small_frequency": "每卷1-2个信任危机/疑心暗示",
        "big_frequency": "全书2-3次重大背叛（间隔10+卷）",
        "intensity_curve": "小怀疑2-3分 → 盟友背叛6-7分 → 至亲/师友背叛10分",
        "key_technique": "背叛者必须有自己的理由——不是单纯的坏，而是'不得不'或'另一种正义'。"
                         "背叛后不要急于复仇——先写主角内心世界的坍塌和重建。"
                         "最好的背叛是读者也会犹豫'他是不是有苦衷'。参考：《遮天》各种盟友反目。",
        "forbidden": "不能为背叛而背叛（要有充分动机）；不能反复背叛同一对关系（读者会不耐烦）；"
                     "背叛揭露后不能立刻和好——必须有足够的修复过程或彻底决裂。",
        "emotion_type": "negative",
    },
    "失去与蜕变": {
        "stages": [
            "①珍贵日常：展示主角所拥有的——不必华丽，但读者能感受到'这是他最在乎的'",
            "②失去过程：渐进式或突发式都可以——但失去的一刻必须有足够的叙事重量",
            "③空洞期：主角变得机械/麻木/暴走——用日常细节的变化展示失去的影响",
            "④触底反弹：在最低谷遇到触动（一句话/一个场景/一个旧物）——不是解脱，是接受",
            "⑤蜕变完成：主角变了——不是'忘记了'而是'带着伤痕前行'，行为模式永久改变",
        ],
        "small_frequency": "每卷1次小失去（失去机缘/错过/暂别）",
        "big_frequency": "每5卷1次重大失去（家园毁灭/至亲陨落/信念崩塌）",
        "intensity_curve": "小失去3分 → 重要物/人失去6-7分 → 核心信念崩塌10分",
        "key_technique": "失去不仅是死亡——可以是理想的幻灭、对世界认知的颠覆、珍视之物的不可逆损坏。"
                         "蜕变后的主角必须有可观察的行为变化——说话方式/做决定的逻辑/对他人的态度。"
                         "参考：《斗破苍穹》萧炎被退婚后的蜕变，《诡秘之主》克莱恩每次穿越回忆。",
        "forbidden": "不能失去后下一章就元气满满（太假）；不能所有失去都能弥补回来（否则无重量）；"
                     "不能用失去当工具人——失去本身必须改变故事走向。",
        "emotion_type": "negative",
    },
    "绝望翻盘": {
        "stages": [
            "①全面崩盘：不是一个问题，而是连环崩塌——盟友败退/阵地失守/底牌暴露/后路断绝",
            "②四面楚歌：每一个方向都是死路，连读者都觉得'这怎么可能赢'",
            "③最后的底牌：不是新的金手指——而是之前被忽视的线索/被低估的伙伴/被遗忘的承诺",
            "④逆风翻盘：每一步都是博弈，不是一招逆天——而是步步为营的反击，代价极大",
            "⑤惨胜收场：赢了，但付出了巨大代价——不是庆祝而是清点伤亡，胜利的苦涩",
        ],
        "small_frequency": "每卷末1次小规模被动转主动",
        "big_frequency": "全书3-4次大绝望翻盘（间隔8+卷）",
        "intensity_curve": "小翻盘5分 → 局部逆转7-8分 → 全面绝望翻盘10分",
        "key_technique": "翻盘的爽感与之前绝望的深度成正比——越绝望，翻盘越燃。"
                         "翻盘不能无代价——惨胜比完胜更真实更动人。"
                         "翻盘的关键不应是主角一个人，而是所有人的力量汇聚。"
                         "参考：几乎所有经典战役弧——先虐后爽，虐得越深爽得越狠。",
        "forbidden": "不能每次都翻盘（偶尔真的输才有紧张感）；翻盘不能靠突然冒出的新角色/新力量；"
                     "翻盘后不能立刻进入下一个绝望（读者需要喘息）。",
        "emotion_type": "mixed",  # 先虐后爽
    },

    # ── 幽默/轻松向 ──────────────────────────────────────────────────────────
    "反差萌": {
        "stages": [
            "①形象建立：角色在读者心中已有固定印象（冷酷/严肃/高冷/凶狠）",
            "②日常场景：脱离战斗/正事的私人空间或意外情境",
            "③反差行为：做出完全不符合'人设'的事（冷面师父偷吃零食/高冷女主迷路/凶悍反派怕虫子）",
            "④目击者反应：其他角色/读者的震惊→忍笑→破防",
            "⑤回归常态：角色假装什么都没发生，更加'正经'，反差感持续发酵",
        ],
        "small_frequency": "每5-8章1次轻松互动/反差时刻",
        "big_frequency": "每卷1-2次标志性名场面级的反差",
        "intensity_curve": "小反差笑点3分 → 名场面级反差7分 → 全员崩人设大乱斗10分",
        "key_technique": "反差的前提是人设足够坚固——形象越严肃，反差越好笑。"
                         "幽默来自角色性格而非段子，禁止网络流行语破坏世界观。"
                         "最好的幽默是角色自己不觉得好笑，但读者笑出声。",
        "forbidden": "不能为搞笑而搞笑（幽默中必须有角色真实一面的展示）；"
                     "不能让严肃角色彻底崩人设（有底线的反差）；"
                     "不能在虐心章节/紧张高潮中插入搞笑桥段。",
        "emotion_type": "positive",
    },
}

# 默认公式（未匹配时使用）
_DEFAULT_FORMULA = {
    "stages": [
        "①铺垫：建立期望/制造压力",
        "②积压：压力升级/困难加码",
        "③触发：关键契机出现",
        "④释放：爽点核心事件爆发",
        "⑤回响：后果+影响扩散",
    ],
    "small_frequency": "每5章1次小爽点",
    "big_frequency": "卷高潮1次大爽点",
    "intensity_curve": "小爽点3分 → 中爽点6分 → 大爽点10分",
    "key_technique": "铺垫越充分，释放越爽。永远不要跳过铺垫直接给结果。",
    "forbidden": "不能连续两章都是高潮（读者会疲劳）；不能爽点后立即进入下一个爽点。",
}


# ── 情绪对比系统（1000 章可持续性的关键） ────────────────────────────────────
# 连续 1000 章纯爽会导致读者脱敏。情绪对比系统调度正负体验的交替节奏。
# 核心原理：虐 → 爽 → 虐 → 爽，每个周期的情绪振幅递增。

EMOTION_CONTRAST_RULES = {
    "min_positive_streak": 3,    # 连续正向爽点不超过 N 章（超过触发负向事件）
    "max_negative_streak": 2,    # 连续负向体验不超过 N 章（超过必须给爽点释放）
    "major_loss_interval": 30,   # 每 N 章至少安排 1 次重大失去/牺牲
    "betrayal_interval": 80,     # 每 N 章至少安排 1 次信任危机/背叛
    "despair_before_climax": True,  # 每卷高潮前必须有 1-2 章绝境铺垫

    "volume_emotion_arc": {
        "opening": "希望+小紧张",
        "early_middle": "成长+小挫折",
        "mid_point": "重大失去/背叛 → 情绪谷底",
        "late_middle": "觉醒+奋起 → 情绪回升",
        "climax": "绝境 → 翻盘 → 情绪高峰",
        "ending": "余波+新的不安",
    },

    "emotion_intensity_scaling": {
        "vol_1_10": "轻虐为主，牺牲配角，主角成长痛苦",
        "vol_11_30": "中虐，开始牺牲重要配角，信任危机出现",
        "vol_31_60": "重虐，至亲/挚友可能陨落，世界观动摇",
        "vol_60_plus": "极虐，核心信念崩塌/重大反转，但每次低谷后给更大的爽点补偿",
    },
}

# 负向情绪对应的正向补偿映射
EMOTION_COMPENSATION = {
    "虐心牺牲": "为牺牲者复仇/完成遗志 → 用复仇爽/传承爽补偿",
    "绝境求生": "劫后余生的突破 → 用升级爽补偿",
    "背叛与觉醒": "觉醒后实力/格局跃升 → 用逆袭打脸补偿",
    "失去与蜕变": "蜕变后碾压同级 → 用装逼收徒补偿",
    "绝望翻盘": "翻盘本身即是最大爽点 → 自带补偿",
}


def get_emotion_contrast_guidance(volume_num: int, recent_emotion_types: list[str]) -> str:
    """
    根据当前卷号和最近章节的情绪类型，生成情绪对比指导。
    供 ChapterOutliner 使用。
    """
    lines = ["【情绪对比调度指导】"]

    # 判断当前情绪倾向
    recent_neg = sum(1 for e in recent_emotion_types[-5:] if e in ("negative", "mixed"))
    recent_pos = sum(1 for e in recent_emotion_types[-5:] if e == "positive")

    if recent_pos >= EMOTION_CONTRAST_RULES["min_positive_streak"]:
        lines.append("⚠ 连续正向体验过多，读者可能脱敏。本卷应安排负向情绪事件：")
        lines.append("  - 一次信任危机/暂时的失去/重要挫折")
        lines.append("  - 至少1章让主角陷入低谷")
    elif recent_neg >= EMOTION_CONTRAST_RULES["max_negative_streak"]:
        lines.append("⚠ 连续负向体验过多，读者可能弃书。本卷应安排爽点释放：")
        lines.append("  - 一次酣畅淋漓的逆袭/突破/打脸")
        lines.append("  - 让读者'等了很久'的正面回报")

    # 卷情绪弧线指导
    arc = EMOTION_CONTRAST_RULES["volume_emotion_arc"]
    lines.append(f"\n本卷情绪弧线建议：")
    for phase, desc in arc.items():
        lines.append(f"  {phase}: {desc}")

    # 虐心强度建议
    scaling = EMOTION_CONTRAST_RULES["emotion_intensity_scaling"]
    if volume_num <= 10:
        lines.append(f"\n当前阶段（第{volume_num}卷）：{scaling['vol_1_10']}")
    elif volume_num <= 30:
        lines.append(f"\n当前阶段（第{volume_num}卷）：{scaling['vol_11_30']}")
    elif volume_num <= 60:
        lines.append(f"\n当前阶段（第{volume_num}卷）：{scaling['vol_31_60']}")
    else:
        lines.append(f"\n当前阶段（第{volume_num}卷）：{scaling['vol_60_plus']}")

    return "\n".join(lines)


def classify_pleasure_emotion(pleasure_type: str) -> str:
    """分类爽点的情绪类型：positive / negative / mixed"""
    formula = PLEASURE_FORMULAS.get(pleasure_type, _DEFAULT_FORMULA)
    return formula.get("emotion_type", "positive")


# ── 故事宏观阶段 (#19) ────────────────────────────────────────────────────────
# 1000 章小说的四幕结构，确保主角动机始终清晰

STORY_PHASES = {
    "origin": {
        "range": "1-25%",
        "core_question": "主角能活下来吗？",
        "focus": "个人生存+基础能力建设",
        "scale": "个人→小团队",
        "motivation_anchor": "最初的承诺/仇恨/梦想",
        "emotion_baseline": "希望与恐惧交织",
    },
    "rise": {
        "range": "25-50%",
        "core_question": "主角能改变周围的人吗？",
        "focus": "势力建设+阵营对抗",
        "scale": "团队→势力→区域",
        "motivation_anchor": "从'我要变强'到'我要保护的人'",
        "emotion_baseline": "自信与责任并行",
    },
    "crisis": {
        "range": "50-75%",
        "core_question": "主角的信念经得起考验吗？",
        "focus": "信念动摇+世界观颠覆+至亲牺牲",
        "scale": "区域→大陆→跨界",
        "motivation_anchor": "从'保护的人'到'对世界的责任'",
        "emotion_baseline": "怀疑与坚韧较量",
    },
    "transcendence": {
        "range": "75-100%",
        "core_question": "主角会成为什么样的人？",
        "focus": "最终真相+终极对决+传承/退场",
        "scale": "全世界→超越世界",
        "motivation_anchor": "回到最初的那个问题，给出最终答案",
        "emotion_baseline": "超然与不舍",
    },
}


def get_story_phase(volume_num: int, total_volumes: int) -> str:
    """根据当前卷号判断故事阶段"""
    progress = volume_num / max(total_volumes, 1)
    if progress <= 0.25:
        return "origin"
    elif progress <= 0.50:
        return "rise"
    elif progress <= 0.75:
        return "crisis"
    else:
        return "transcendence"


def get_story_phase_guidance(phase: str) -> str:
    """获取当前故事阶段的写作指导"""
    p = STORY_PHASES.get(phase, STORY_PHASES["origin"])
    return (
        f"【故事阶段：{phase}（{p['range']}）】\n"
        f"核心叩问：{p['core_question']}\n"
        f"叙事焦点：{p['focus']}\n"
        f"格局范围：{p['scale']}\n"
        f"动机锚点：{p['motivation_anchor']}\n"
        f"情绪基调：{p['emotion_baseline']}"
    )


# ── 章节标题公式库 (#18) ─────────────────────────────────────────────────────

TITLE_FORMULAS: dict[str, list[str]] = {
    "action": [
        "动词+对象（'血战莽荒原'/'剑斩天骄'）",
        "角色名+行为（'李青一剑破苍穹'）",
        "对抗式（'谁与争锋'/'龙虎斗'）",
    ],
    "revelation": [
        "疑问句（'谁才是真正的叛徒？'）",
        "反转揭示（'十年前的真相'/'她的另一面'）",
        "悬念式（'第三个名字'/'不该打开的门'）",
    ],
    "buildup": [
        "暗示式（'暴风雨前'/'山雨欲来'）",
        "地点+氛围（'月夜黑风林'/'深渊之下'）",
        "准备式（'磨刀'/'棋局'）",
    ],
    "grief": [
        "告别式（'最后一杯酒'/'归途'）",
        "遗言式（'替我看看那片海'）",
        "反讽温柔（'回家'——越温柔越虐）",
    ],
    "comedic_relief": [
        "反差式（'大魔王的休息日'/'剑圣迷路了'）",
        "日常式（'集市风波'/'谁偷了丹药'）",
    ],
    "turning_point": [
        "短句冲击（'变天了'/'他回来了'）",
        "象征式（'破晓'/'第一道裂痕'）",
    ],
}


def get_title_guidance(pacing_type: str) -> str:
    """获取章节标题写法指导"""
    formulas = TITLE_FORMULAS.get(pacing_type, TITLE_FORMULAS.get("buildup", []))
    examples = " / ".join(formulas[:2]) if formulas else ""
    return (
        f"【标题要求】不超过10字，禁止'新的XX'/'XX的开始'。"
        f"参考：{examples}"
    )


# ── 世界扩展节奏 (#26) ───────────────────────────────────────────────────────

WORLD_EXPANSION_RULES = {
    "new_region_interval": 8,       # 每 8-12 卷引入一个新区域
    "new_faction_interval": 5,      # 每 5 卷引入 1-2 个新势力
    "max_active_factions": 8,       # 同时活跃势力不超过 8 个
    "max_active_regions": 3,        # 同时活跃区域不超过 3 个
    "power_ceiling_expand": 15,     # 每 15 卷解锁新的力量天花板
}


# ── 预期颠覆系统 (#2) ────────────────────────────────────────────────────────

SUBVERSION_TYPES = {
    "type_shift": "铺垫了A类爽点，实际释放B类（如铺垫打脸→变成牺牲虐心）",
    "timing_shift": "爽点不在章末，而在章首或章中（打破读者节奏预期）",
    "subject_shift": "不是主角的高光，而是配角/反派的高光时刻",
    "anti_climax": "铺垫了大战→智取/和解替代（不是每次都要打）",
}

SUBVERSION_INTERVAL = 4  # 每 N 次标准爽点后安排 1 次颠覆


def should_subvert(consecutive_standard_pleasures: int) -> bool:
    """是否应该安排预期颠覆"""
    return consecutive_standard_pleasures >= SUBVERSION_INTERVAL


# ── 战斗描写进化规则 (#16) ────────────────────────────────────────────────────

COMBAT_ESCALATION_RULES = {
    "low_tier": {
        "description": "低阶战斗（前25%力量体系）",
        "style": "肉搏+简单法术，描写物理动作为主",
        "focus": "速度、力量、技巧的直观对比",
        "forbidden": "不能出现毁天灭地的描写",
    },
    "mid_tier": {
        "description": "中阶战斗（25-60%力量体系）",
        "style": "法宝+阵法+策略，描写博弈和计谋为主",
        "focus": "资源消耗、走位、心理博弈",
        "forbidden": "不能只写蛮力对轰",
    },
    "high_tier": {
        "description": "高阶战斗（60-85%力量体系）",
        "style": "大道法则碰撞+概念对决，描写哲学理念交锋",
        "focus": "对'道'的理解深度决定胜负",
        "forbidden": "不能还在比拼招式——这个层次比的是境界",
    },
    "top_tier": {
        "description": "顶阶战斗（85%+力量体系）",
        "style": "不再'打架'——以势压人/一念成败/因果对决",
        "focus": "旁观者完全看不懂在打什么，用低阶视角的困惑感烘托层次",
        "forbidden": "不能写具体的物理交锋（已超越这个层次）",
    },
}


def get_combat_tier(current_rank: int, total_ranks: int) -> str:
    """根据当前力量等级获取战斗描写层级"""
    progress = current_rank / max(total_ranks, 1)
    if progress <= 0.25:
        return "low_tier"
    elif progress <= 0.60:
        return "mid_tier"
    elif progress <= 0.85:
        return "high_tier"
    else:
        return "top_tier"


def get_combat_guidance(tier: str) -> str:
    """获取战斗描写指导"""
    rules = COMBAT_ESCALATION_RULES.get(tier, COMBAT_ESCALATION_RULES["mid_tier"])
    return (
        f"【战斗描写层级：{rules['description']}】\n"
        f"风格：{rules['style']}\n"
        f"焦点：{rules['focus']}\n"
        f"禁忌：{rules['forbidden']}"
    )


# ── 卷节奏曲线 ───────────────────────────────────────────────────────────────

VOLUME_PACING = {
    "standard": {
        "opening_30pct": "建立冲突，读者期望值从低到中。"
                         "介绍本卷舞台、新角色、新威胁。"
                         "前3章内必须出现至少1个小冲突。",
        "middle_40pct": "积压压力，期望值从中到高。"
                        "主角遭遇连续挫折，伏笔密集埋设。"
                        "安排1-2次小爽点维持读者黏性。",
        "climax_20pct": "爆发释放，期望值达到峰值。"
                        "大爽点+大突破+反派对决。"
                        "节奏极快，短段落，密集对话。",
        "ending_10pct": "新威胁出现或格局剧变，期望值悬而未决。"
                        "为下一卷埋钩子。"
                        "不要完美收尾——留悬念。",
    },
}


# ── 章节节奏模板 ──────────────────────────────────────────────────────────────

CHAPTER_PACING_TEMPLATES = {
    "action": {
        "description": "战斗章/冲突章，全程高节奏",
        "rhythm": "快→快→极快",
        "paragraph_style": "短段落为主（80-120字），对话密集，动作描写利落",
        "forbidden": "禁止长段落环境描写，禁止内心独白超过2句",
    },
    "buildup": {
        "description": "铺垫章，积蓄压力，结尾加速",
        "rhythm": "慢→中→快",
        "paragraph_style": "中等段落（100-180字），信息密度递增，暗线推进",
        "forbidden": "禁止全章平淡无波，最后20%必须加速",
    },
    "revelation": {
        "description": "揭秘章，真相揭露后节奏剧变",
        "rhythm": "中→停顿→极快",
        "paragraph_style": "揭秘前中等节奏，揭秘瞬间用短句制造冲击，揭秘后快节奏处理反应",
        "forbidden": "真相不能一口气全说完，要层层剥开",
    },
    "aftermath": {
        "description": "缓冲章，处理后果+铺设新线索",
        "rhythm": "慢→慢→中",
        "paragraph_style": "较长段落（120-200字），角色互动为主，情感处理",
        "forbidden": "不能纯粹休息——必须在缓冲中埋入新线索/新冲突种子",
    },
    "turning_point": {
        "description": "转折章，格局发生重大变化",
        "rhythm": "中→停顿→爆发→余波",
        "paragraph_style": "转折前正常节奏，转折瞬间极短段落制造冲击，之后写角色反应",
        "forbidden": "转折不能突兀——前面必须有伏笔铺垫",
    },
    "grief": {
        "description": "虐心章，重大失去/牺牲/背叛发生",
        "rhythm": "慢→加速→冲击→沉寂",
        "paragraph_style": "事件前温情铺垫用中等段落，冲击瞬间用极短句，"
                          "之后用长段落写内心崩塌和沉默",
        "forbidden": "不能用旁白直接说'他很难过'——要用行为和细节展示。"
                     "不能一章之内从悲痛恢复。不能在悲伤中插入搞笑桥段。",
    },
    "desperation": {
        "description": "绝境章，走投无路/全面崩盘",
        "rhythm": "快→极快→窒息→一线光",
        "paragraph_style": "短段落密集堆叠压力，环境描写烘托压迫感，"
                          "对话极简——绝境中人不会说废话",
        "forbidden": "不能突然冒出救星；不能在绝境中大段回忆过去；"
                     "绝境要有物理感——寒冷/饥饿/伤痛/体力透支的描写。",
    },
}


# ── 钩子类型库 ────────────────────────────────────────────────────────────────

HOOK_TYPES = {
    "cliffhanger": {
        "description": "关键动作被打断",
        "example": "'他猛地回头，看到的不是敌人——而是...'",
        "technique": "在最紧张的瞬间切断叙述，让读者必须翻页",
    },
    "revelation": {
        "description": "惊人信息半截话",
        "example": "'原来所有人都错了。他不是什么废物——他是当年那个...'",
        "technique": "给出足够暗示让读者猜测，但不给确切答案",
    },
    "threat_escalation": {
        "description": "更大威胁出现",
        "example": "'远方天际，一道比刚才那人强十倍的气息正在逼近。'",
        "technique": "刚解决一个问题，更大的问题浮出水面",
    },
    "betrayal_hint": {
        "description": "信任动摇",
        "example": "'她转身离开时，手微不可察地颤了一下。只有他注意到了。'",
        "technique": "用极细微的细节暗示背叛/秘密，制造不安感",
    },
    "mystery_deepening": {
        "description": "谜题加深",
        "example": "'但这一切，为什么和他梦中看到的一模一样？'",
        "technique": "在解答一个问题的同时，引出更大的谜团",
    },
    "power_tease": {
        "description": "力量预兆",
        "example": "'丹田中那颗沉寂了三年的种子，在这一刻，发出了第一缕光。'",
        "technique": "暗示即将到来的突破/觉醒，让读者期待",
    },
    "countdown": {
        "description": "倒计时压力",
        "example": "'还有三天。三天后，他要么突破，要么——死。'",
        "technique": "设置明确的时间限制，制造紧迫感",
    },
    "sacrifice_foreshadow": {
        "description": "牺牲预兆",
        "example": "'她把那枚一直带着的玉佩塞到他手里，笑了笑：'替我留着。'",
        "technique": "用反常的温柔/交代/赠予暗示即将到来的牺牲，让读者隐隐不安",
    },
    "trust_crack": {
        "description": "信任裂痕",
        "example": "'他说的每个字都对，但她就是觉得哪里不对。这种感觉，让她第一次失眠。'",
        "technique": "用直觉层面的不安暗示背叛，比明确线索更折磨人",
    },
    "silent_aftermath": {
        "description": "沉默余波",
        "example": "'他坐在废墟中，一直到天亮。谁也不知道他在想什么。'",
        "technique": "用沉默和留白表达比文字更重的悲痛，让读者自行脑补",
    },
}


# ── 公开 API ──────────────────────────────────────────────────────────────────

def get_pleasure_formula(core_pleasure: str) -> dict:
    """获取指定爽点类型的释放公式"""
    return PLEASURE_FORMULAS.get(core_pleasure, _DEFAULT_FORMULA)


def get_volume_pacing(pacing_type: str = "standard") -> dict:
    """获取卷节奏曲线"""
    return VOLUME_PACING.get(pacing_type, VOLUME_PACING["standard"])


def get_chapter_pacing_template(chapter_type: str) -> dict:
    """获取章节节奏模板"""
    return CHAPTER_PACING_TEMPLATES.get(chapter_type, CHAPTER_PACING_TEMPLATES["buildup"])


def get_hook_types() -> dict:
    """获取所有钩子类型"""
    return HOOK_TYPES


def get_pleasure_guidance_for_writer(pleasure_point: str, core_pleasure: str) -> str:
    """为 Writer 生成具体的爽点写作指导"""
    formula = get_pleasure_formula(core_pleasure)
    emotion_type = formula.get("emotion_type", "positive")

    lines = [f"【爽点释放指导：{core_pleasure}】"]
    lines.append(f"本章爽点：{pleasure_point}")
    lines.append(f"情绪类型：{'负向体验（虐心向）' if emotion_type == 'negative' else '混合体验（先虐后爽）' if emotion_type == 'mixed' else '正向体验（爽感向）'}")
    lines.append(f"释放阶段：")
    for stage in formula["stages"]:
        lines.append(f"  {stage}")
    lines.append(f"核心技巧：{formula['key_technique']}")
    lines.append(f"禁忌：{formula['forbidden']}")

    # 负向情绪的补偿提示
    if emotion_type in ("negative", "mixed") and core_pleasure in EMOTION_COMPENSATION:
        lines.append(f"\n【情绪补偿】{EMOTION_COMPENSATION[core_pleasure]}")
        lines.append("→ 本章虐完后，后续1-2章内必须安排正向爽点释放作为补偿。")

    return "\n".join(lines)


def get_pleasure_guidance_for_outliner(core_pleasure: str) -> str:
    """为 ChapterOutliner 生成爽点分布指导"""
    formula = get_pleasure_formula(core_pleasure)

    lines = [f"【{core_pleasure}爽点分布指导】"]
    lines.append(f"小爽点频率：{formula['small_frequency']}")
    lines.append(f"大爽点频率：{formula['big_frequency']}")
    lines.append(f"强度曲线：{formula['intensity_curve']}")
    lines.append(f"核心技巧：{formula['key_technique']}")
    lines.append(f"禁忌：{formula['forbidden']}")
    lines.append("")
    lines.append("爽点释放5阶段：")
    for stage in formula["stages"]:
        lines.append(f"  {stage}")
    return "\n".join(lines)
