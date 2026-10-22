# reese-ag — 网文 AI 创作引擎 · 项目技术文档

> 面向开发者和 AI 的完整项目说明。快速启动请参阅 [README.md](README.md)。

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构总览](#2-系统架构总览)
3. [目录结构](#3-目录结构)
4. [核心数据模型](#4-核心数据模型)
5. [LLM 客户端抽象层](#5-llm-客户端抽象层)
6. [八大 Agent 详解](#6-八大-agent-详解)
7. [流水线编排](#7-流水线编排)
8. [记忆与状态系统](#8-记忆与状态系统)
9. [内容治理子系统](#9-内容治理子系统)
10. [工具系统](#10-工具系统)
11. [断点续写引擎](#11-断点续写引擎)
12. [可观测性](#12-可观测性)
13. [Web 服务与前端](#13-web-服务与前端)
14. [CLI 接口](#14-cli-接口)
15. [配置参考](#15-配置参考)
16. [开发指南](#16-开发指南)
17. [关键设计模式与决策](#17-关键设计模式与决策)

---

## 1. 项目概述

### 1.1 定位

reese-ag 是一个 **AI 驱动的中文网文（Web Novel）自动生成引擎**。它编排 8 个专业化 AI Agent，从用户给出的类型、爽点、主角设定出发，自动完成世界构建、角色设计、剧情规划、章节大纲、逐章写作、一致性校验、质量评审的全流程。

核心特点：
- **多 Agent 流水线**：8 个 Agent 各司其职，输出自校验
- **流式写作**：章节内容通过 SSE 实时推送，前端逐字显示
- **跨章记忆**：EntityStore 追踪角色状态、信息差、时间线、冲突弧
- **断点续写**：检查点机制，中断后可从任意位置恢复
- **多 LLM Provider**：支持 Anthropic / DeepSeek / 通义千问 / 月之暗面 / 智谱 / 豆包 / Ollama 本地模型
- **Human-in-the-Loop**：交互模式下可审批/修改每个 Agent 输出

### 1.2 技术栈

| 层面 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI + Uvicorn |
| 数据模型 | Pydantic v2 |
| LLM SDK | anthropic, openai（OpenAI-Compatible） |
| 数据库 | SQLite（历史持久化 + 调用追踪 + 语义缓存） |
| 前端 | 单页 HTML（原生 JS + SSE） |
| 协议 | SSE（Server-Sent Events）实时流 |

### 1.3 代码统计

| 类别 | 文件数 | 行数 |
|------|--------|------|
| Agent 模块 | 9 | ~2,900 |
| 核心引擎 | 7 | ~2,400 |
| 记忆系统 | 4 | ~770 |
| 工具系统 | 3 | ~580 |
| 数据模型 | 1 | ~280 |
| 前端 | 1 | ~710 |
| **总计** | **~34** | **~8,400** |

---

## 2. 系统架构总览

### 2.1 核心数据流

```
用户请求（WebNovelRequest）
    │
    ▼
┌─────────────────────── Agent 流水线 ────────────────────────┐
│                                                              │
│  Agent 1: WorldBuilder ──→ WorldSetting                     │
│      ↓                                                       │
│  Agent 2: CharacterDesigner ──→ Characters + Antagonists    │
│      ↓                                                       │
│  Agent 3: PlotPlanner ──→ PlotFramework + VolumePlans       │
│      ↓                                                       │
│  Agent 4: ChapterOutliner (×N卷) ──→ ChapterOutlineItems   │
│      ↓                                                       │
│  ┌── 逐章循环 ──────────────────────────────────────────┐   │
│  │  Agent 5: Writer ──→ ChapterResult (流式)            │   │
│  │      ↓                                                │   │
│  │  Agent 6: ConsistencyChecker ──→ 校验 + 自动修正     │   │
│  │      ↓                                                │   │
│  │  Agent 7: QualityCritic ──→ 8维度评分                │   │
│  │      ↓                                                │   │
│  │  EntityStore.update() ← Extractor 提取状态变更       │   │
│  │  RhythmTracker.record()                               │   │
│  └───────────────────────────────────────────────────────┘   │
│      ↓ (无限模式)                                            │
│  Agent 8: PlotExtender ──→ 新卷规划                         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
WebNovelResult → Markdown 导出 + SQLite 持久化
```

### 2.2 辅助系统

```
┌─────────────────────────────────────────────────────────┐
│                    辅助子系统                             │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ EntityStore  │  │ RhythmTracker│  │ PleasureSystem│  │
│  │ 跨章实体记忆  │  │ 节奏张力追踪  │  │ 爽点释放公式  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Disciplines  │  │ ToolRegistry │  │ Guardrails   │  │
│  │ 20学科知识注入│  │ 工具注册中心  │  │ 安全护栏     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Tracer       │  │ Cache        │  │ ModelRouter  │  │
│  │ 调用追踪/成本 │  │ 语义缓存     │  │ 模型路由     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.3 双入口

| 入口 | 文件 | 用途 |
|------|------|------|
| Web 服务 | `main.py` | FastAPI + SSE，浏览器交互 |
| 命令行 | `generate.py` | CLI，脚本化批量生成 |

两者共用 `runner.py`（ResumableRunner）作为底层执行引擎。

---

## 3. 目录结构

```
reese-ag/
├── main.py                     # FastAPI 应用入口 (~240 行)
├── generate.py                 # CLI 入口 (~300 行)
├── runner.py                   # 断点续写引擎 (~480 行)
├── llm_client.py               # 多 Provider LLM 抽象 (~1,000 行)
├── db.py                       # SQLite 持久化 (~80 行)
├── cache.py                    # LLM 语义缓存 (~130 行)
├── observability.py            # Token 追踪 & 成本估算 (~210 行)
├── orchestrator.py             # DAG 编排引擎（预留） (~300 行)
├── prompt_loader.py            # Prompt 版本管理 (~125 行)
├── disciplines.py              # 20 学科知识注入 (~640 行)
├── pleasure_system.py          # 爽点释放公式 (~265 行)
├── guardrails.py               # 安全护栏 (~110 行)
│
├── models/
│   └── novel.py                # Pydantic 数据模型 (~280 行)
│
├── agents/
│   ├── base.py                 # Agent 基类 (~310 行)
│   ├── pipeline.py             # 线性流水线编排 (~435 行)
│   ├── world_builder.py        # Agent 1: 世界构建师 (~330 行)
│   ├── character_designer.py   # Agent 2: 角色设计师 (~350 行)
│   ├── plot_planner.py         # Agent 3: 剧情规划师 (~250 行)
│   ├── chapter_outliner.py     # Agent 4: 章节大纲师 (~230 行)
│   ├── writer.py               # Agent 5: 写作执行者 (~370 行)
│   ├── consistency_checker.py  # Agent 6: 一致性校验者 (~260 行)
│   ├── quality_critic.py       # Agent 7: 质量评审 (~185 行)
│   └── plot_extender.py        # Agent 8: 故事扩展 (~180 行)
│
├── memory/
│   ├── __init__.py             # 导出 EntityStore 等
│   ├── entity_store.py         # 实体记忆系统 (~540 行)
│   ├── extractor.py            # LLM 状态提取器 (~110 行)
│   └── rhythm_tracker.py       # 节奏张力追踪 (~120 行)
│
├── tools/
│   ├── __init__.py
│   ├── registry.py             # 工具注册中心 (~95 行)
│   ├── reference_tools.py      # 参考查询工具 (~280 行)
│   └── mcp_client.py           # MCP 外部工具桥接 (~200 行)
│
├── static/
│   └── index.html              # 前端单页应用 (~710 行)
│
├── .env.example                # 配置模板
├── requirements.txt            # 依赖清单
├── README.md                   # 快速启动指南
├── PROJECT.md                  # 本文档
├── 创作流程.md                  # 网文创作流程设计文档
│
├── data/                       # SQLite 数据库（自动创建）
├── output/                     # 生成的 Markdown（自动创建）
└── checkpoints/                # 断点续写检查点（自动创建）
```

---

## 4. 核心数据模型

文件：`models/novel.py`

### 4.1 输入模型

**WebNovelRequest** — 用户输入的小说生成请求

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `genre` | str | 必填 | 大类型：玄幻/修仙/都市/穿越/系统/末世/无限/历史 |
| `sub_genre` | str | "" | 子类型描述 |
| `core_pleasure` | str | 必填 | 核心爽点：逆袭打脸/升级爽/系统面板/装逼收徒/复仇/种田积累 |
| `protagonist_name` | str | 必填 | 主角姓名 |
| `protagonist_background` | str | 必填 | 主角起点设定 |
| `golden_finger` | str | 必填 | 金手指/外挂描述 |
| `world_desc` | str | "" | 世界观简述（可选） |
| `antagonist_direction` | str | "" | 反派方向（可选） |
| `romance` | str | "" | 感情线设定（可选） |
| `num_volumes` | int | 3 | 规划卷数（1-10） |
| `chapters_per_volume` | int | 10 | 每卷章数（5-30） |
| `words_per_chapter` | int | 2000 | 每章字数（1000-5000） |
| `quality_mode` | str | "standard" | 质量模式：standard / deep |
| `mode` | str | "bounded" | 生成模式：bounded（有限）/ infinite（无限） |
| `interactive` | bool | false | 交互模式：Agent 输出后等待用户审批 |
| `disciplines` | list[str] | [] | 学科方向（空则按题材自动分配 5 个） |

### 4.2 世界观模型

**WorldSetting**

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | str | 世界观总述 |
| `power_system` | PowerSystem | 力量体系 |
| `factions` | list[Faction] | 势力列表 |
| `resource_system` | str | 资源体系描述 |
| `special_rules` | str | 特殊规则 |
| `philosophical_foundation` | str | 哲学/思想内核 |
| `cultural_system` | str | 文化/知识/信仰体系 |
| `social_structure` | str | 社会结构与运行逻辑 |
| `geography` | str | 地理划分（区域+建议境界等级） |
| `history_summary` | str | 历史纪元概述（3-5个） |
| `forbidden_zones` | str | 禁区/秘境（进入条件+风险收益） |

**PowerSystem**：`name` + `levels: list[PowerLevel]` + `breakthrough_conditions` + `special_rules`

**PowerLevel**：`name` + `rank` (int) + `description` + `typical_power`

**Faction**：`name` + `faction_type` (protagonist_side/enemy_near/enemy_mid/enemy_boss/neutral/ally) + `power_description` + `description` + `leader`

### 4.3 人物模型

**CharacterProfile**

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 姓名 |
| `role` | str | 角色定位：protagonist / love_interest / sidekick / mentor |
| `current_power` | str | 当前境界 |
| `background` | str | 背景故事 |
| `golden_finger` | str | 金手指描述 |
| `personality` | str | 性格特征 |
| `motivation` | str | 核心动机 |
| `speech_pattern` | str | 说话风格（习惯用词/句式） |
| `arc` | str | 成长弧线 |
| `psychological_profile` | str | 心理特征/创伤/防御机制 |
| `intellectual_stance` | str | 信仰/哲学/知识立场 |
| `appearance` | str | 外观特征 |
| `signature_move` | str | 标志性招式或习惯动作 |
| `hidden_agenda` | str | 隐藏目标/秘密 |
| `relationship_notes` | str | 与其他角色的关系张力 |
| `growth_trajectory` | str | 成长轨迹（初期→中期→后期） |
| `core_beliefs` | list[str] | 核心信念/价值观/底线（2-3条） |
| `prohibitions` | list[str] | 角色绝不会做的事（2-3条） |
| `initial_goals` | list[str] | 初始目标栈（当前→长期） |
| `speech_examples` | list[str] | 典型对话示例（2-3句） |

**AntagonistTier**

| 字段 | 类型 | 说明 |
|------|------|------|
| `tier` | int | 层级：1=近期, 2=中期, 3=终极 |
| `name` | str | 姓名 |
| `current_power` | str | 境界 |
| `motive` | str | 动机 |
| `weakness` | str | 弱点 |
| `defeat_volume` | int | 预计被解决的卷数 |
| `heroic_code` | str | 反派的坚守底线 |
| `tragic_flaw` | str | 致命缺陷 |
| `sympathetic_element` | str | 读者可同情的地方 |

### 4.4 剧情模型

**PlotFramework**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ultimate_goal` | str | 终极目标 |
| `milestones` | list[Milestone] | 里程碑事件 |
| `global_foreshadowing` | list[str] | 全书级伏笔 |
| `thematic_arcs` | list[str] | 跨卷主题弧线 |
| `core_dilemmas` | list[str] | 全书核心困境 |

**Milestone**：`index` + `title` + `description` + `volume` + `impact` + `turn_type` (反转/升级/牺牲/揭露/背叛) + `emotional_impact`

**VolumePlan**

| 字段 | 类型 | 说明 |
|------|------|------|
| `volume_num` | int | 卷号 |
| `title` | str | 卷标题 |
| `theme` | str | 本卷主题 |
| `antagonist_name` | str | 本卷反派 |
| `core_pleasure_point` | str | 本卷大爽点 |
| `protagonist_power_start/end` | str | 主角起止境界 |
| `ending_hook` | str | 引出下卷的钩子 |
| `chapters` | list[ChapterOutlineItem] | 章节细纲 |
| `ethical_dilemma` | str | 本卷道德困境 |
| `foreshadowing_seeds` | list[str] | 本卷埋下的伏笔 |
| `foreshadowing_payoffs` | list[str] | 本卷兑现的前卷伏笔 |
| `pacing_structure` | str | 节奏分布 |
| `protagonist_emotional_arc` | str | 主角情绪变化弧线 |

### 4.5 章节模型

**ChapterOutlineItem** — 章节细纲

| 字段 | 类型 | 说明 |
|------|------|------|
| `chapter_num` | int | 全书序号 |
| `volume_chapter_num` | int | 卷内序号 |
| `title` | str | 章节标题 |
| `hook_start` | str | 开头事件 |
| `core_events` | list[str] | 核心事件（2-4个） |
| `pleasure_point` | str | 本章爽点（无则空） |
| `hook_end` | str | 结尾钩子 |
| `protagonist_power` | str | 本章结束时主角境界 |
| `thematic_element` | str | 主题元素 |
| `knowledge_seed` | str | 融入的知识点 |
| `hook_type` | str | 钩子类型（7种） |
| `pacing_type` | str | 节奏类型（5种） |
| `emotional_beat` | str | 情感节拍 |

**ChapterResult** — 写作结果

| 字段 | 类型 | 说明 |
|------|------|------|
| `volume_num` | int | 所属卷 |
| `chapter_num` | int | 全书序号 |
| `volume_chapter_num` | int | 卷内序号 |
| `title` | str | 标题 |
| `content` | str | 正文内容 |
| `summary` | str | 200字摘要（传递给下一章） |
| `protagonist_power_end` | str | 主角境界 |
| `consistency_issues` | list[str] | 校验问题列表 |
| `hook_strength` | int | 钩子强度评分（1-10） |

### 4.6 输出与审批模型

**WebNovelOutline**：`title` + `world` + `characters` + `antagonists` + `plot_framework` + `volumes` + `disciplines`

**WebNovelResult**：`title` + `outline` + `chapters`，含 `to_markdown()` 导出方法

**ApprovalRequest**：`checkpoint_id` + `agent_name` + `data` + `editable_fields`

**ApprovalResponse**：`action` (approve/reject/modify) + `modifications` + `feedback`

---

## 5. LLM 客户端抽象层

文件：`llm_client.py` (~1,000 行)

### 5.1 基类 LLMClient

| 方法 | 说明 |
|------|------|
| `tool_call(system, prompt, tool, tool_name, ...)` | 强制工具调用，返回结构化 dict |
| `stream(system, prompt, ...)` | 异步流式文本生成，yield 文本片段 |
| `complete(prompt, ...)` | 单次补全（短文本任务） |
| `multi_turn_tool_call(system, tools, handlers, ...)` | 多轮 Agent 循环，支持工具调用链 |
| `tool_call_with_thinking(system, prompt, tool, ...)` | Extended Thinking 模式，返回 (tool_input, thinking_text) |

### 5.2 Provider 实现

| 实现类 | Provider | 特点 |
|--------|----------|------|
| `AnthropicClient` | Claude (Anthropic) | 原生支持，Extended Thinking，模型路由 |
| `OpenAICompatibleClient` | DeepSeek / 通义千问 / 月之暗面 / 智谱 / 豆包 | 工具格式自动转换（Anthropic→OpenAI） |
| `OllamaClient` | Ollama 本地模型 | 健康检查、模型预加载、JSON 修复（4层策略）、上下文窗口管理 |

### 5.3 工厂函数

```python
create_client()  # 读取 LLM_PROVIDER 环境变量，返回对应 Client 实例
```

### 5.4 模型路由

通过 `MODEL_ROUTING` 环境变量配置不同 Agent 使用不同模型：

```json
{"writer_summary": "claude-haiku-4-5-20251001", "plot_planner": "claude-opus-4-6"}
```

未配置的 Agent 使用默认 `MODEL` 环境变量。

### 5.5 错误处理

- `ProviderRateLimitError`：速率限制，触发指数退避重试
- `ProviderUnavailableError`：服务不可用，触发重试
- Ollama 特有：OOM、模型未就绪、连接超时等分类处理

---

## 6. 八大 Agent 详解

### 6.1 Agent 基类（agents/base.py）

三种 Agent 模式：

| 模式 | 类 | 说明 |
|------|-----|------|
| 多轮循环 | `AgentLoop` | 迭代式自校验，最多 N 轮，直到通过校验或调用 submit_result |
| 单次调用 | `SingleShotAgent` | 一次 tool_call 完成 |
| 思维链调用 | `ThinkingSingleShotAgent` | 启用 Extended Thinking (budget=10000 tokens) |

AgentLoop 核心流程：
```
build_system_prompt() → build_tools() → build_initial_messages()
    ↓
  迭代循环（最多 max_iterations 次）：
    LLM 调用 → 校验输出 → 通过？→ 返回结果
                              ↓ 不通过
                        注入反馈 → 继续迭代
```

### 6.2 Agent 1: 世界构建师（WorldBuilder）

文件：`agents/world_builder.py`

| 属性 | 值 |
|------|-----|
| 基类 | AgentLoop |
| 输入 | WebNovelRequest |
| 输出 | WorldSetting |
| 自带工具 | validate_power_system, validate_factions, submit_result |

**System Prompt 要点**：
- 力量体系等级清晰、相邻等级差悬殊、上限模糊
- 地理至少 3 层（村落→国家→大陆→更大世界）
- 历史纪元 3+ 个，禁区 2+ 个
- 力量体系服务于爽点设计

**自校验**：
- 等级连续性（rank 从 1 到 N）
- 名称唯一性
- 势力类型完整性（必须有 protagonist_side, enemy_near/mid/boss, neutral/ally）
- 预期等级数 = `num_volumes * 2 + 3`

### 6.3 Agent 2: 角色设计师（CharacterDesigner）

文件：`agents/character_designer.py`

| 属性 | 值 |
|------|-----|
| 基类 | AgentLoop |
| 输入 | WebNovelRequest + WorldSetting |
| 输出 | (list[CharacterProfile], list[AntagonistTier]) |
| 自带工具 | validate_power_references, validate_antagonist_tiers, submit_result |

**System Prompt 要点**：
- 主角低谷起点，反派梯队式升级
- 每个角色说话风格有辨识度
- 角色 Agent 化：core_beliefs（2-3条）、prohibitions（2-3条）、goal_stack、speech_examples
- 反派三维度：底线(heroic_code) + 缺陷(tragic_flaw) + 共情点(sympathetic_element)

**自校验**：
- 必须有 protagonist 角色
- 所有 current_power 必须在力量体系等级列表中
- 反派 tier 1→N，defeat_volume 连续

### 6.4 Agent 3: 剧情规划师（PlotPlanner）

文件：`agents/plot_planner.py`

| 属性 | 值 |
|------|-----|
| 基类 | ThinkingSingleShotAgent（Extended Thinking） |
| 输入 | WebNovelRequest + WorldSetting + Characters + Antagonists |
| 输出 | (title, PlotFramework, list[VolumePlan]) |
| 工具 | plan_plot |

**System Prompt 要点**：
- 每卷完整故事弧（压迫→成长→爽点爆发）
- 里程碑事件标注转折类型和情感冲击
- 卷级伏笔管理（seeds / payoffs）
- 主题弧线（2-3条跨卷）和核心困境（2-3个）

**校验**：
- 里程碑数 = `num_volumes + 2`
- 卷数 = `num_volumes`
- 力量等级引用有效
- 反派名在 antagonists 列表中

### 6.5 Agent 4: 章节大纲师（ChapterOutliner）

文件：`agents/chapter_outliner.py`

| 属性 | 值 |
|------|-----|
| 基类 | ThinkingSingleShotAgent |
| 输入 | 卷规划 + 全局设定 |
| 输出 | list[ChapterOutlineItem] |
| 工具 | outline_volume_chapters |

**System Prompt 要点**：
- 每 3-5 章必须有爽点
- 每章必须有结尾钩子（7 种钩子类型）
- 5 种章节节奏类型（action/buildup/revelation/aftermath/turning_point）
- 爽点执行路径：铺垫→积压→释放

**校验**：
- 章数 = `chapters_per_volume`
- 全书序号连续
- 爽点分布合理（2-4章含爽点标注）

### 6.6 Agent 5: 写作执行者（Writer）

文件：`agents/writer.py`

| 属性 | 值 |
|------|-----|
| 模式 | 流式生成（非 AgentLoop，直接 client.stream） |
| 输入 | 章节细纲 + 上章摘要 + EntityStore 上下文 + RhythmTracker 上下文 |
| 输出 | 流式 yield ("chunk", text) → ("result", ChapterResult) |
| 后处理 | 禁用词自检 + 字数校验 + 自动修正 |

**写作铁律（System Prompt）**：
1. 开头禁止环境/天气/时间描写，第一句必须是动作/对话/冲突
2. 每段 100-200 字，手机友好
3. 对话有力，每句推进情节
4. 结尾必须制造悬念
5. 爽点写到位（打脸要彻底、突破要有飞升感）
6. 节奏快（战斗利落、过渡一句带过）

**禁用词**：`不禁 / 顿时 / 忍不住 / 猛地 / 深深地 / 不由得 / 他心中感到 / 她感到一阵 / 内心充满了`

**读者心理模型**：
- 前 100 字定生死
- 每 300 字是读者评估检查点
- 重要场景必须融入视觉+听觉+触觉
- 爽点必须经历"铺垫→积压→释放"完整过程

**上下文注入**：
- 通过 ToolRegistry 查询相关历史章节摘要
- 通过 EntityStore 获取角色状态/信息差/禁忌
- 通过 RhythmTracker 获取近期节奏走势
- 学科写作指导（从 disciplines 系统）

**写后自检（_self_check_and_revise）**：
1. `check_banned_words_handler`：扫描禁用词和重复动词
2. 发现问题→LLM 自动修正（REVISION_SYSTEM_PROMPT）
3. `count_words_handler`：字数偏差 >30% 报警

**断流续写**：
- 流式生成中断（已有 ≥200 字）→ yield ("stream_interrupted", {partial_content})
- 调用方可传入 `_continuation_content` 从断点继续

### 6.7 Agent 6: 一致性校验者（ConsistencyChecker）

文件：`agents/consistency_checker.py`

| 属性 | 值 |
|------|-----|
| 模式 | 直接 tool_call（非 AgentLoop） |
| 输入 | 章节正文 + 大纲 + 设定 + 实体上下文 |
| 输出 | 修正后的 ChapterResult |
| 工具 | check_chapter_consistency |
| 触发条件 | quality_mode = "deep" |

**16 类校验**：
力量一致性 / 角色一致性 / 设定一致性 / 爽点落实 / 主题一致性 / 时间连贯性 / 地理位置 / 因果逻辑 / 伏笔推进 / 时间线一致性 / 信息差一致性 / 角色声音偏离 / 禁止项违反 / 钩子断裂 / 角色消失 / 其他

**自动修正循环**（最多 2 轮）：
```
校验 → needs_rewrite=true? → 生成修正 → 重新校验 → 通过/再修正
                    ↓ false
                  直接通过
```

触发修正的条件：力量矛盾 / hook_strength < 5 / 严重爽点缺失

### 6.8 Agent 7: 质量评审（QualityCritic）

文件：`agents/quality_critic.py`

| 属性 | 值 |
|------|-----|
| 基类 | SingleShotAgent |
| 输入 | 章节细纲 + 章节正文 |
| 输出 | 8 维度评分 dict |
| 触发条件 | quality_mode = "deep" |
| 失败处理 | 非阻塞，失败返回默认分数 |

**8 维度评分**（均为 1-10 分）：
1. 爽点满足度（excitement_score）
2. 节奏适当性（pacing_score）
3. 沉浸感（immersion_score）
4. 翻页欲（page_turner_score）
5. 深度（depth_score）
6. 原创性（originality_score）
7. 感官丰富度（sensory_score）
8. 角色辨识度（voice_score）

另有 `overall_score`、`strengths[]`、`improvements[]`（最多3条）、`needs_rewrite` 标志。

### 6.9 Agent 8: 故事扩展（PlotExtender）

文件：`agents/plot_extender.py`

| 属性 | 值 |
|------|-----|
| 基类 | SingleShotAgent |
| 输入 | 已完成内容 + 设定 |
| 输出 | list[VolumePlan] |
| 触发条件 | mode = "infinite"，剩余 ≤2 卷时自动触发 |

**扩展原则**：
- 格局升级（新世界/新维度）
- 力量连续性（新卷起始 = 上卷结束）
- 反派梯队升级
- 新伏笔种子

---

## 7. 流水线编排

文件：`agents/pipeline.py`

### 7.1 执行流程

```python
async def run_pipeline(request, queue, cancel_event, in_queue=None, task_id=""):
```

1. 创建 LLM Client
2. Ollama 健康检查（如适用）
3. 输入安全护栏扫描
4. 学科解析（resolve_disciplines）
5. Agent 1-4 依次执行（每个 Agent 后检查 cancel_event）
6. 构建 WebNovelOutline + 初始化 EntityStore + RhythmTracker + ToolRegistry
7. 逐章循环：Writer → ConsistencyChecker → QualityCritic → 更新记忆
8. 输出安全扫描 + Markdown 导出

### 7.2 SSE 事件流

所有事件通过 `asyncio.Queue` 推送，格式为 `(event_type, data)`：

| 事件类型 | data 类型 | 说明 |
|---------|----------|------|
| `status` | str | 进度文本 |
| `disciplines_resolved` | dict | 已解析的学科 |
| `world_ready` | dict | WorldSetting |
| `characters_ready` | dict | {characters, antagonists} |
| `plot_ready` | dict | {title, plot_framework, volumes} |
| `thinking` | dict | {agent, text} — Agent 推理过程 |
| `volume_outline_ready` | dict | {volume_num, title, chapters} |
| `chapter_start` | dict | {volume_num, chapter_num, title, pleasure_point} |
| `chunk` | str | 章节文本片段（流式） |
| `checker_start` | int | 开始校验的章节号 |
| `correction_applied` | dict | {chapter_num, hook_strength, issues_fixed} |
| `quality_review` | dict | 8 维度评分结果 |
| `chapter_done` | dict | ChapterResult |
| `approval_required` | dict | {checkpoint_id, agent_name, data, editable_fields} |
| `trace_summary` | dict | LLM 调用统计 |
| `novel_complete` | dict | {title} |
| `cancelled` | str | 用户取消 |
| `error` | str | 异常信息 |

### 7.3 Human-in-the-Loop

交互模式下（`interactive=True`），在以下节点暂停等待用户审批：

1. 世界观完成后（可修改 description, resource_system, special_rules）
2. 角色设计完成后（可修改 characters, antagonists）
3. 剧情规划完成后（可修改 title, volumes）

审批流程：
- Pipeline 发送 `approval_required` 事件
- 等待用户通过 `in_queue` 回复 ApprovalResponse
- `approve`：继续
- `reject` + feedback：Agent 根据反馈重新生成
- 超时（10分钟）：自动通过

---

## 8. 记忆与状态系统

### 8.1 EntityStore（memory/entity_store.py）

**核心职责**：追踪跨章节的角色状态、阵营、伏笔、时间线、信息差、冲突弧。

#### 状态数据结构

**CharacterState**

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 角色名 |
| `power_level` | str | 当前境界 |
| `location` | str | 当前位置 |
| `alive` | bool | 是否存活 |
| `relationships` | dict[str, str] | 与其他角色的关系 |
| `key_events` | list[str] | 经历的关键事件 |
| `last_updated_chapter` | int | 最后更新章节 |
| `core_beliefs` | list[str] | 核心信念（不变） |
| `personality_traits` | list[str] | 性格特征（缓变） |
| `known_facts` | list[str] | 已知信息（只增不减） |
| `goal_stack` | list[str] | 目标栈 |
| `prohibitions` | list[str] | 行为禁忌 |
| `speech_examples` | list[str] | 典型台词 |
| `role_type` | str | 角色类型 |
| `first/last_appearance` | int | 首次/末次出场章节 |
| `appearance_count` | int | 出场次数 |
| `departure_status` | str | 离场状态 |

**其他数据结构**：
- `FactionState`：阵营状态（status: active/destroyed/merged/hidden）
- `PlotThread`：伏笔线（status: open/resolved/abandoned，thread_type: foreshadowing/chapter_hook/mystery/promise）
- `TimelineEvent`：时间线事件（in_story_time + characters_involved）
- `InformationGap`：信息差（known_by / unknown_to / reader_knows / dramatic_irony）
- `ConflictArc`：冲突弧（current_level: personal→organizational→world）

#### 核心方法

| 方法 | 说明 |
|------|------|
| `init_from_outline(outline)` | 从大纲初始化所有实体 |
| `update_from_extraction(chapter_num, extraction)` | 章后更新状态 |
| `get_stale_hooks(chapter_num, threshold=5)` | 检测悬挂太久的钩子 |
| `get_missing_characters(chapter_num, threshold=10)` | 检测消失太久的配角 |
| `get_writer_context(chapter_num, max_context_chars=2000)` | 生成优先级排序的上下文 |
| `to_dict() / from_dict()` | JSON 序列化/反序列化 |

#### Writer 上下文优先级

| 优先级 | 内容 |
|--------|------|
| P1 | 角色状态快照 + 已死角色 |
| P2 | 未兑现钩子 |
| P3 | 信息差（戏剧反讽） |
| P4 | 角色行为禁忌 |
| P5 | 时间线 |
| P6 | 未解决伏笔 |
| P7 | 消失角色提醒 |
| P8 | 冲突格局 |

超出 `max_context_chars`（默认 2000）时从低优先级开始截断。

### 8.2 Extractor（memory/extractor.py）

**LLM 驱动的状态提取器**。每章写完后调用，从正文提取：

- 角色更新：power_level、location、alive、relationship_change、new_goal/goal_completed
- 阵营更新：leader、status
- 新伏笔 / 已解决伏笔
- 章末钩子注册
- 时间线更新
- 新信息差 / 信息差变更
- 冲突弧变更

### 8.3 RhythmTracker（memory/rhythm_tracker.py）

**纯 Python 模块（无 LLM 依赖）**。追踪每章的节奏张力值。

张力映射：
```
action = 0.9,  turning_point = 0.85,  revelation = 0.7,
buildup = 0.5,  aftermath = 0.3
```

自动检测规则：
- 连续 3+ 章高张力（≥0.7）→ 警告"读者疲劳"
- 连续 3+ 章低张力（≤0.4）→ 警告"读者流失"
- 连续 3+ 章同类型 → 警告"节奏单调"

`get_context_for_writer()` 生成可视化张力条形图注入 Writer 上下文。

---

## 9. 内容治理子系统

### 9.1 爽点系统（pleasure_system.py）

**6 种爽点类型的 5 阶段释放公式**：

| 爽点类型 | 5 阶段 | 小爽频率 | 大爽频率 |
|---------|--------|---------|---------|
| 逆袭打脸 | 铺垫→蓄力→反转→涟漪→收尾 | 每 3 章 | 卷高潮 |
| 升级爽 | 困境→绝望→契机→突破→碾压 | 每 5 章 | 卷高潮 |
| 系统面板 | 触发→展示→惊喜→应用→优越 | 每 2-3 章 | 每卷系统进化 |
| 装逼收徒 | 伪装→轻视→露一手→揭露→追随 | 每 4 章 | 卷高潮 |
| 复仇 | 积累→接近→突破→过程→清算 | 每卷 1 次 | 终卷 |
| 种田积累 | 规划→执行→里程碑→超预期→升级 | 每 3 章 | 卷高潮 |

**7 种钩子类型**：cliffhanger / revelation / threat_escalation / betrayal_hint / mystery_deepening / power_tease / countdown

**5 种章节节奏模板**：action / buildup / revelation / aftermath / turning_point

**核心 API**：
- `get_pleasure_formula(core_pleasure)` → 公式 dict
- `get_pleasure_guidance_for_writer(pleasure_point, core_pleasure)` → Writer 指导
- `get_pleasure_guidance_for_outliner(core_pleasure)` → Outliner 指导
- `get_chapter_pacing_template(pacing_type)` → 节奏模板

### 9.2 多学科系统（disciplines.py）

**20 种学科方向**：
哲学 / 心理学 / 历史 / 社会学 / 物理学 / 伦理学 / 经济学 / 军事学 / 宗教神话学 / 科技 / 医学 / 政治学 / 生物学 / 天文学 / 数学 / 美学音乐 / 人类学 / 语言学 / 建筑学 / 法学

**题材→学科自动映射**：
```
玄幻 → [哲学, 物理学, 宗教/神话学, 军事学, 心理学]
修仙 → [哲学, 宗教/神话学, 医学, 天文学, 心理学]
都市 → [心理学, 社会学, 经济学, 法学, 科技]
穿越 → [历史, 政治学, 军事学, 经济学, 社会学]
系统 → [科技, 数学, 经济学, 心理学, 物理学]
末世 → [生物学, 军事学, 社会学, 心理学, 科技]
无限 → [物理学, 心理学, 哲学, 科技, 军事学]
历史 → [历史, 政治学, 军事学, 伦理学, 经济学]
```

**每种学科对每个 Agent 有专属指导**（agent_guidance）：
- WorldBuilder：影响世界规则设计
- CharacterDesigner：影响角色心理/思想
- PlotPlanner：影响剧情转折逻辑
- ChapterOutliner：影响知识种子分布
- Writer：影响细节描写方式

**核心 API**：
- `resolve_disciplines(genre, user_override)` → 最终 5 个学科
- `get_agent_guidance(disciplines, agent_name)` → Agent 系统提示注入文本

### 9.3 安全护栏（guardrails.py）

**三级配置**（环境变量 `GUARDRAIL_LEVEL`）：

| 级别 | 输入过滤 | 输出扫描 |
|------|---------|---------|
| none | 不过滤 | 不扫描 |
| basic | Prompt 注入检测 | 暴力内容标记（不过滤） |
| strict | Prompt 注入 + PII 检测 | 暴力标记 + 危险内容过滤 |

- 输入：检测 "ignore instructions"、"system prompt"、角色切换等注入模式
- 输出：检测暴力/图形内容模式，strict 模式下过滤自杀方法、爆炸/毒药制造等

---

## 10. 工具系统

### 10.1 ToolRegistry（tools/registry.py）

**集中式工具注册中心**，支持内建工具和 MCP 外部工具。

```python
registry = ToolRegistry()
registry.register(name, description, input_schema, handler, source="builtin")
registry.get_tool(name)          # → Anthropic 工具格式 dict
registry.get_handler(name)       # → Callable
registry.has(name)               # → bool
registry.list_tools(source=None) # → list[str]
```

### 10.2 内建参考工具（tools/reference_tools.py）

| 工具名 | 说明 | 使用场景 |
|--------|------|---------|
| `check_banned_words` | 检测禁用词和重复动词 | Writer 写后自检 |
| `count_words` | 统计中文字符数 | Writer 字数校验 |
| `lookup_character` | 查询角色档案 | Agent 循环中参考 |
| `lookup_power_level` | 查询力量等级详情 | Agent 校验境界引用 |
| `lookup_faction` | 查询势力信息 | Agent 参考 |
| `search_chapter_summaries` | 关键词搜索历史章节摘要 | Writer 写前上下文增强 |

**动态更新**：每章完成后重新注册 `search_chapter_summaries`，使后续章节可查询前文。

### 10.3 MCP 桥接（tools/mcp_client.py）

通过 Model Context Protocol 接入外部工具服务器。

配置：
```
MCP_SERVERS={"novel_research": {"command": "npx", "args": ["-y", "novel-research-server"]}}
```

`MCPToolBridge` 类：
- 通过子进程启动 MCP 服务器
- JSON-RPC 通信协议
- 自动发现工具并注册到 ToolRegistry（source="mcp:{server_name}"）

---

## 11. 断点续写引擎

文件：`runner.py` (~480 行)

### 11.1 ResumableRunner

```python
runner = ResumableRunner(run_id, request, checkpoint_dir)
await runner.run()  # bounded 模式
# 或
await runner.run()  # infinite 模式（自动扩展）
```

### 11.2 检查点目录结构

```
checkpoints/{run_id}/
├── request.json          # WebNovelRequest
├── run.json              # 运行状态
├── world.json            # WorldSetting
├── characters.json       # {characters, antagonists}
├── plot.json             # {title, plot_framework, volumes}
├── outline_vol_{n}.json  # 第 n 卷章节细纲
└── chapter_{n:04d}.json  # 第 n 章写作结果
```

**原子写入**：先写 `.tmp` 文件再 rename，防止写入中崩溃导致文件损坏。

### 11.3 恢复逻辑

1. `_completed_chapter_nums()`：扫描已有 `chapter_*.json` 文件
2. 跳过已完成章节
3. `_load_rolling_summaries()`：加载最近 5 章摘要，恢复跨会话上下文
4. 从中断点继续执行

### 11.4 重试机制

指数退避重试（最多 10 次）：
- `ProviderRateLimitError`：min 2s, max 300s
- `ProviderUnavailableError`：重试
- 网络错误（ConnectionError, TimeoutError）：重试

### 11.5 双模式

| 模式 | 行为 |
|------|------|
| bounded | 写完规划卷数后结束，导出完整 novel.md |
| infinite | 接近最后 2 卷时自动调用 PlotExtender 扩展 3 卷，循环直到手动停止 |

### 11.6 信号处理

`SIGINT`（Ctrl+C）设置 `_stop_requested` 标志，当前章节写完后优雅暂停。

### 11.7 导出

- `_export_volume()`：每卷完成后导出 `output/{run_id}/vol_{n:03d}.md`
- `_export_full_novel()`：bounded 模式结束时汇总为 `output/{run_id}/novel.md`

---

## 12. 可观测性

### 12.1 Tracer（observability.py）

**LLMCallTrace** — 单次 LLM 调用记录：

| 字段 | 说明 |
|------|------|
| task_id | 任务 ID |
| agent_name | Agent 名称 |
| method | tool_call / stream / complete / multi_turn / thinking |
| model | 使用的模型 |
| tokens_in / tokens_out | Token 数 |
| latency_ms | 延迟（毫秒） |
| cost_usd | 估算费用（美元） |
| success | 是否成功 |
| error | 错误信息 |

**成本估算**（MODEL_PRICING，美元/百万 Token）：
```
claude-sonnet-4-6:          input=3.0,  output=15.0
claude-haiku-4-5-20251001:  input=0.8,  output=4.0
deepseek-chat:              input=0.14, output=0.28
```

**AgentSpan** — Agent 级执行统计：iterations, total_tokens, total_cost, time_window

**Tracer.get_summary()** → 总体统计 + 每 Agent 明细

### 12.2 语义缓存（cache.py）

可选功能（`LLM_CACHE_ENABLED=true`）：
- SQLite 存储
- 内容寻址 hash（system + prompt + 参数）
- 低温度调用（temperature ≤ 0.5）自动缓存
- 避免开发调试时重复 LLM 调用

### 12.3 数据库（db.py）

SQLite 表 `novels`：
- task_id, title, genre, core_pleasure, quality_mode, chapters (int), created_at, markdown_path

提供历史查询和导出管理。

---

## 13. Web 服务与前端

### 13.1 API 端点（main.py）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate` | 启动生成任务，返回 {task_id} |
| GET | `/api/stream/{task_id}` | SSE 事件流（600s 超时） |
| POST | `/api/approve/{task_id}` | 交互模式审批回复 |
| POST | `/api/cancel/{task_id}` | 取消生成 |
| GET | `/api/history` | 历史记录（最近 20 条） |
| DELETE | `/api/history/{task_id}` | 删除记录+文件 |
| GET | `/api/download/{task_id}` | 下载 Markdown |
| GET | `/api/traces/{task_id}` | 查询 LLM 调用追踪 |

### 13.2 SSE 流机制

```python
@app.get("/api/stream/{task_id}")
async def stream_events(task_id):
    # 从 asyncio.Queue 获取事件
    # 转为 SSE 格式：data: {json}\n\n
    # 事件类型映射为 event: 字段
    # novel_complete / error / cancelled 时结束流
```

### 13.3 前端（static/index.html）

单页应用（~710 行 HTML+CSS+JS）：

- **表单**：类型/爽点/主角设定/参数配置
- **实时流显示**：逐字展现 Writer 输出
- **阶段展示**：世界观 → 角色 → 剧情 → 大纲 → 写作，各阶段卡片
- **审批弹窗**：交互模式下弹出审批/修改界面
- **历史管理**：查看/删除/下载历史生成
- **暗色主题**：深紫/红/金配色

---

## 14. CLI 接口

文件：`generate.py`

### 14.1 命令

```bash
# 新建生成任务
python generate.py new \
  --genre 玄幻 \
  --core-pleasure 逆袭打脸 \
  --protagonist-name 林逸 \
  --protagonist-background "废材少年，被家族逐出" \
  --golden-finger "万界交易系统" \
  --volumes 5 \
  --chapters-per-volume 20 \
  --words-per-chapter 3000 \
  --mode infinite \
  --quality-mode deep

# 恢复中断的任务
python generate.py resume <run-id>

# 查看所有任务
python generate.py list

# 导出当前进度
python generate.py export <run-id>
```

### 14.2 参数对照

| CLI 参数 | 对应字段 | 默认值 |
|----------|---------|--------|
| `--genre` | genre | 必填 |
| `--core-pleasure` | core_pleasure | 必填 |
| `--protagonist-name` | protagonist_name | 必填 |
| `--protagonist-background` | protagonist_background | 必填 |
| `--golden-finger` | golden_finger | 必填 |
| `--world-desc` | world_desc | "" |
| `--volumes` | num_volumes | 3 |
| `--chapters-per-volume` | chapters_per_volume | 10 |
| `--words-per-chapter` | words_per_chapter | 2000 |
| `--mode` | mode | bounded |
| `--quality-mode` | quality_mode | standard |

---

## 15. 配置参考

所有配置通过 `.env` 文件设置（复制 `.env.example`）。

### 15.1 LLM Provider 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `LLM_PROVIDER` | 提供商：anthropic / openai-compatible / ollama | anthropic |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |
| `MODEL` | 模型名称 | claude-sonnet-4-6 |
| `LLM_API_KEY` | OpenAI-Compatible API Key | — |
| `LLM_BASE_URL` | OpenAI-Compatible Base URL | — |

### 15.2 Ollama 专属配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `OLLAMA_BASE_URL` | Ollama 地址 | http://localhost:11434 |
| `OLLAMA_CONNECT_TIMEOUT` | 模型加载超时（秒） | 30 |
| `OLLAMA_READ_TIMEOUT` | 生成超时（秒） | 300 |
| `OLLAMA_CONTEXT_WINDOW` | 上下文窗口 | 32768 |
| `OLLAMA_KEEPALIVE` | VRAM 保持时间（分钟） | 30 |
| `OLLAMA_CHARS_PER_TOKEN` | 中文字符/Token 比例 | 1.5 |

### 15.3 高级配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `MODEL_ROUTING` | 模型路由（JSON） | — |
| `LLM_CACHE_ENABLED` | 语义缓存开关 | false |
| `GUARDRAIL_LEVEL` | 安全护栏级别：none/basic/strict | none |
| `MCP_SERVERS` | MCP 外部工具服务器（JSON） | — |
| `PROMPT_VERSION` | Prompt 版本号 | v1 |

### 15.4 Provider 快速切换示例

**DeepSeek**（推荐，性价比高）：
```env
LLM_PROVIDER=openai-compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
MODEL=deepseek-chat
```

**通义千问**（国内稳定）：
```env
LLM_PROVIDER=openai-compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-max
```

**Ollama 本地**：
```env
LLM_PROVIDER=ollama
MODEL=qwen3:27b
```

---

## 16. 开发指南

### 16.1 新增 Agent

1. 在 `agents/` 下创建新文件，继承 `AgentLoop` / `SingleShotAgent` / `ThinkingSingleShotAgent`
2. 实现必要方法：
   - `build_system_prompt(context)` → str
   - `build_tools(context)` → list[dict]
   - `build_tool_handlers(context)` → dict[str, Callable]
   - `validate_result(result, context)` → (bool, str)
   - `parse_result(result, context)` → domain object
3. 在 `pipeline.py` 或 `runner.py` 中调用新 Agent
4. 在 `disciplines.py` 中为新 Agent 添加学科指导（如需要）

### 16.2 新增工具

1. 在 `tools/reference_tools.py` 中定义 handler 函数和 tool schema
2. 在 `register_reference_tools()` 中注册
3. 工具在 Agent 的 multi_turn_tool_call 循环中可被自动调用

### 16.3 新增学科

在 `disciplines.py` 的 `DISCIPLINE_POOL` 中添加 `DisciplineSpec`：

```python
DisciplineSpec(
    name="新学科",
    description="对叙事的贡献描述",
    agent_guidance={
        "world_builder": "世界构建指导...",
        "character_designer": "角色设计指导...",
        "plot_planner": "剧情规划指导...",
        "chapter_outliner": "章节大纲指导...",
        "writer": "写作指导...",
    },
)
```

然后在 `GENRE_DISCIPLINE_MAP` 中关联到适用的题材。

### 16.4 新增 LLM Provider

1. 在 `llm_client.py` 中继承 `LLMClient`
2. 实现 `tool_call` / `stream` / `complete` 方法
3. 在 `create_client()` 工厂函数中添加分支

---

## 17. 关键设计模式与决策

### 17.1 迭代自校验 Agent

Agent 不是单次调用，而是循环调用直到输出通过校验。WorldBuilder 会校验力量等级连续性，CharacterDesigner 校验境界引用有效性。这避免了 LLM 输出结构不完整或数据不一致的问题。

### 17.2 流式优先的 Writer

Writer 不是一次性返回完整章节，而是通过 `async for text in client.stream()` 逐字推送。这使得前端可以实时显示写作进度。流中断时保存已有内容，支持从断点续写。

### 17.3 优先级截断的上下文注入

Writer 的上下文窗口有限。EntityStore 按 8 级优先级排列信息，超出预算时从低优先级截断。确保最关键的信息（角色状态、信息差）始终被注入。

### 17.4 原子检查点

所有 checkpoint 文件先写 `.tmp` 再 rename，保证写入原子性。崩溃后不会出现半写文件。恢复时自动跳过已完成章节。

### 17.5 多 Provider 统一抽象

所有 LLM Provider 共享相同接口（tool_call / stream / complete）。Anthropic 原生工具格式作为内部标准，OpenAI-Compatible 客户端自动转换。Ollama 客户端额外处理 JSON 修复和上下文窗口管理。

### 17.6 记忆只增不减

`CharacterState.known_facts` 只增不减（除非有特殊设定如失忆）。这保证了信息差追踪的可靠性——角色"知道什么"永远是已知事实的超集。

### 17.7 非阻塞质量评审

QualityCritic 失败不阻塞流水线。评分结果仅供参考和展示，不影响章节输出。ConsistencyChecker 的自动修正才是强制性的质量保障。

### 17.8 向后兼容的序列化

EntityStore 的 `from_dict()` 使用字段过滤：只加载当前数据类已定义的字段。这使得新增字段后旧检查点仍可正常加载。

---

*本文档基于代码实现编写，如有疑问请对照源文件。最后更新：2026-04-29。*
