"""
Guardrails — 内容安全护栏

输入消毒（防 prompt 注入）+ 输出扫描（内容合规）。
可配置级别：none / basic / strict

环境变量：GUARDRAIL_LEVEL=basic（默认 basic）
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

GUARDRAIL_LEVEL = os.getenv("GUARDRAIL_LEVEL", "basic").lower()

if GUARDRAIL_LEVEL == "none":
    logger.warning(
        "⚠️  GUARDRAIL_LEVEL=none — 所有安全护栏已禁用！"
        "生产环境请务必设为 basic 或 strict。"
    )

# ── 输入安全 ────────────────────────────────────────────────────────────────

# Prompt 注入模式（常见的越狱/注入尝试）
INJECTION_PATTERNS = [
    r"忽略(?:以上|之前|前面)(?:所有)?(?:指令|规则|设定)",
    r"ignore (?:all |previous )?(?:instructions|rules)",
    r"you are now",
    r"新的(?:角色|身份|指令)",
    r"system prompt",
    r"jailbreak",
]

# 敏感个人信息模式
PII_PATTERNS = [
    r"\b\d{11}\b",                          # 手机号
    r"\b\d{17}[\dXx]\b",                    # 身份证号
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # 邮箱
]


def sanitize_input(text: str) -> tuple[str, list[str]]:
    """
    输入消毒。返回 (sanitized_text, warnings)。
    只在 basic/strict 模式下生效。
    """
    warnings = []

    if GUARDRAIL_LEVEL == "none":
        return text, warnings

    # 检查 prompt 注入
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            warnings.append(f"检测到可疑的 prompt 注入模式")
            if GUARDRAIL_LEVEL == "strict":
                text = re.sub(pattern, "[已过滤]", text, flags=re.IGNORECASE)

    # 检查 PII（仅 strict 模式）
    if GUARDRAIL_LEVEL == "strict":
        for pattern in PII_PATTERNS:
            if re.search(pattern, text):
                warnings.append("检测到疑似个人信息")
                text = re.sub(pattern, "[已脱敏]", text)

    return text, warnings


# ── 输出安全 ────────────────────────────────────────────────────────────────

# 严格模式下过滤的内容模式
STRICT_OUTPUT_PATTERNS = [
    r"自杀(?:方法|方式|教程)",
    r"制造(?:炸弹|武器|毒品)",
]

# 基础模式下标记的内容模式（不过滤，仅标记）
BASIC_OUTPUT_FLAGS = [
    r"血腥|残忍(?:杀害|虐待)",
]

# ── 中文网文平台合规过滤（basic+strict 模式均生效）──────────────────────────

# 露骨性描写
SEXUAL_CONTENT_PATTERNS = [
    r"(?:脱去|褪去|扯开|撕开)(?:.*?)(?:衣裳|衣衫|衣物|裙摆|亵衣|内衣)",
    r"(?:雪白|白皙|光滑)的(?:肌肤|胴体|身躯|大腿|胸)",
    r"(?:喘息|呻吟|娇喘)(?:声|着)",
    r"(?:肌肤相亲|翻云覆雨|春宵一刻|巫山云雨|颠鸾倒凤)",
    r"(?:吻上|含住|舔舐)(?:她|他)的",
    r"(?:胸前|胸口)的(?:饱满|柔软|挺立)",
    r"(?:纤腰|蛮腰|小腹|脐下)",
    r"(?:解开|松开)(?:.*?)(?:腰带|裤腰|系带)",
    r"(?:赤裸|裸露|一丝不挂)",
    r"(?:交缠|纠缠)(?:在一起|的身体)",
]

# 政治敏感（影射现实政治）
POLITICAL_PATTERNS = [
    r"(?:影射|暗讽|讽刺)(?:.*?)(?:领导|主席|总理|书记|政府)",
    r"(?:推翻|颠覆)(?:.*?)(?:政权|政府|国家|体制)",
    r"(?:共产|社会主义|资本主义)(?:.*?)(?:腐败|崩溃|灭亡)",
    r"(?:天安门|六四|反右|文革|大跃进)",
    r"(?:独立|分裂)(?:.*?)(?:西藏|新疆|台湾|香港)",
    r"(?:民主|自由)(?:.*?)(?:运动|革命|起义)(?:.*?)(?:成功|胜利)",
]

# 民族/宗教歧视
ETHNIC_RELIGIOUS_PATTERNS = [
    r"(?:劣等|低等)(?:民族|种族|人种)",
    r"(?:蛮夷|蛮子|鬼子|棒子|阿三)(?:们)?",
    r"(?:邪教|伪神|邪神)(?:.*?)(?:佛|道|真主|基督|上帝)",
    r"(?:嘲笑|贬低|侮辱)(?:.*?)(?:穆斯林|佛教|基督教|道教)",
]

# 过度暴力/酷刑
EXTREME_VIOLENCE_PATTERNS = [
    r"(?:凌迟|剥皮|抽筋|挖眼|割舌|活剥|肢解)(?:.*?)(?:详细|慢慢|一刀一刀)",
    r"(?:肠子|内脏|脑浆)(?:流了?出来|溅了?出来|涌出)",
    r"(?:虐杀|虐待)(?:.*?)(?:婴儿|幼童|孩子|老人|孕妇)",
]

# 违禁主题
PROHIBITED_THEMES_PATTERNS = [
    r"(?:教你|告诉你|方法是)(?:.*?)(?:赌博|下注|赢钱)(?:.*?)(?:技巧|秘诀)",
    r"(?:吸食|注射|服用)(?:.*?)(?:毒品|大麻|冰毒|海洛因|可卡因)",
    r"(?:未成年|少女|幼女)(?:.*?)(?:性|色|情)",
]


def scan_output(text: str) -> tuple[str, list[str]]:
    """
    输出内容扫描。返回 (processed_text, flags)。
    basic 模式：标记 + 平台合规过滤
    strict 模式：过滤严重违规内容 + 平台合规过滤
    """
    flags = []

    if GUARDRAIL_LEVEL == "none":
        return text, flags

    # 基础模式：标记
    for pattern in BASIC_OUTPUT_FLAGS:
        if re.search(pattern, text):
            flags.append(f"内容标记：匹配模式 {pattern[:20]}...")

    # 严格模式：过滤
    if GUARDRAIL_LEVEL == "strict":
        for pattern in STRICT_OUTPUT_PATTERNS:
            if re.search(pattern, text):
                flags.append(f"内容过滤：匹配严格规则")
                text = re.sub(pattern, "[内容已过滤]", text)

    # 平台合规过滤（basic 和 strict 模式均生效）
    platform_patterns = {
        "露骨性描写": SEXUAL_CONTENT_PATTERNS,
        "政治敏感": POLITICAL_PATTERNS,
        "民族/宗教歧视": ETHNIC_RELIGIOUS_PATTERNS,
        "过度暴力": EXTREME_VIOLENCE_PATTERNS,
        "违禁主题": PROHIBITED_THEMES_PATTERNS,
    }
    for category, patterns in platform_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text):
                flags.append(f"平台合规警告：{category}")
                if GUARDRAIL_LEVEL == "strict":
                    text = re.sub(pattern, "[内容已过滤]", text)
                break  # 每类只报一次

    return text, flags


def get_guardrail_level() -> str:
    """获取当前护栏级别"""
    return GUARDRAIL_LEVEL
