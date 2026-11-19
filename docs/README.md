# 网文 AI 创作引擎 — 启动指南

## 世界在线：因果世界与经典仙侠沙盘

在项目根目录启动后打开 **http://localhost:8000/world**：

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

原小说创作页面仍在 `/`，两个页面可相互跳转。首次使用仍需按下文安装项目依赖。
没有模型密钥也能启动服务、创建世界和进行规则模拟；小说生成及 AI 功能会明确提示配置缺失。

### 因果世界：汀川初生

创建窗口默认选择“因果世界”，经典世界和原小说入口均保留。新规则创建独立存档，不把已有仙侠历史硬迁移到新设定。

- **七处地点、三十个人、两股组织**：田庄、矿区、林地、城市、渡口、工坊和旧观测所。断桥与已有工程款是公开的初始条件，不是预写的后续任务链。
- **物资与货币有账可查**：粮食、木材、矿石具有真实存量。收取、运输、交易只是转移；自然生长登记为产出，吃饭、研究、修桥和施术登记为消耗。每次状态校验都核对物资与货币总量。
- **人物有生计与计划**：生产、出售、运输、修桥、研究、休息由口粮、职业、钱、精力及已知消息决定，不再按性格随机抽动作。采区耗尽后，采集者会寻找其他工作。
- **信息并非全知**：人物到现场了解市价、道路、工程材料与预算，同行者只在同地传递已有消息。旧账簿可能过时；亲历洪水的记忆会影响之后的选路。界面将世界现状与人物所知分开显示。
- **行程与工程实际花时间**：道路有明确耗时；断桥会造成绕路，在途人物也要消耗口粮。工匠运来12份木材、4份矿石并投入12个工日，才会建成石桥。
- **力量改变通行规则**：研究者在观测所投入三次研究、每次消耗一份矿石后掌握“引流”。发动需要2份矿石与35点精力，降低水位25点，并形成持续至第三日后的临时浅滩；浅滩比桥面多走一日，并不能代替修桥。
- **公共事务也花真钱**：交易税和货栈每周的周转金结余进入公库，公职报酬、饥饿救济与工程拨款从公库支取。议事会根据桥损及可用财政追加工程预算，不会凭空生成新钱。
- **生命有后果**：饥饿和渡河险情会影响健康，人物会衰老和死亡；逝者不再行动，遗留物与事实不会消失。不会为了保持人口指标暗中复活或补给。

地图直接展示断路、临时浅滩和在途人物；在途位置为根据行程推算的显示，是否抵达由后端裁决。侧栏可查看货栈、可采资源、人物打算、近期记忆与消息日期；事实可展开变化和前因，历史支持分页及按人物、地点查询。

“洪水扰动”和“追加修桥委托”是明确标记的观察实验，需在汀川城或折潮渡确认后执行。追加委托从现有公库划拨40枚钱；不会强迫工匠施工，也不允许直接给所有人增加财富或修为。

这是验证因果闭环的第一个世界切片，不是完整 MMO 或体素游戏。当前尚无婚姻生育、代际继承、领土战争、完整建筑放置、轮回秘境或真实意识模型；有限资源与不利气候可能造成衰退和人口损失。人物保留近期16条重要记忆及已学知识，完整已提交事实另行归档。

### 经典仙侠沙盘

- 为世界命名并选择种子，建立六处相连地点、三方势力和九位各有心愿的人物。
- 在地图上观察人物旅行、修炼、采集、经商与巡守，查看势力资财、影响力和驻地变化。
- 经商人物以交易为主，也会修炼；繁荣有日常消耗，需要交易和势力修缮维持，不会永久只涨不降。
- 手动推进一日，或开启定时演化；随时暂停和调整每个世界日对应的现实时间。
- 对选中地点降下灵雨、开设集市，或让所有人物获得感悟。干预会写入事件簿。
- 配置现有模型后，主动请求世界纪事或人物对话；自动演化不会调用 AI。

AI 只解读已发生的事件、扮演选中的人物，不直接改写世界数值。
回复标明请求快照的历日；世界在等待 AI 时仍可继续演化。
模型失败或超过预算时返回错误，不会用规则文本冒充 AI 回复。

繁荣消耗与经商人物修炼是本次平衡调整，会影响之后的演化结果；不会重写已有事件或补算过去的消耗。
同一种子与相同操作可以复现当前规则下的演化，不保证与旧规则版本逐日一致。

### 存档和运行边界

- 世界独立保存在 `data/worlds.db`，不改动小说历史。每次成功推进或干预都会保存。
- 关闭网页不会删除世界；只要本服务仍运行，已启动的世界会继续演化。
- 新世界均从暂停开始。因果世界保存运行意图，运行中的世界在服务重启后自动继续；手动暂停仍保持暂停。经典世界在服务重启后保持暂停。
- 两种规则都不补算停机时间。真正全天候在线仍需要常驻服务，不能在电脑关机时继续计算。
- 快照保留最近200条事实和20条AI回复；新提交的事实另存SQLite历史表，与世界状态同事务提交。旧存档已经截去的历史不能补回。
- 历史是事实归档，不是逐帧状态回放；恢复依靠完整状态快照。当前没有多人角色扮演或账户系统。
- 页面每 2 秒同步服务器。自动推进依赖单个服务进程，仍须使用 `--workers 1`。
- 当前没有用户账户和权限隔离，仅用于可信的本机／内网环境；不要直接暴露到公网。

### 世界接口

| 方法 | 路径 | 用途 |
|------|------|------|
| GET / POST | `/api/worlds` | 列出／创建世界；`ruleset: "living"` 选择因果规则，省略仍为 `classic`，兼容旧客户端 |
| GET | `/api/worlds/capabilities` | 查看 AI 状态、规则集、职业／物资名称及历史能力 |
| GET / DELETE | `/api/worlds/{id}` | 读取／删除世界 |
| GET | `/api/worlds/{id}/events` | 事实历史；`limit` 为1–100，`before` 为排他的事实编号游标，可传 `region_id` 或 `npc_id` |
| GET | `/api/worlds/{id}/events/{event_id}` | 单条已提交事实，包含 `cause_ids` 和已记录的字段变化 |
| POST | `/api/worlds/{id}/control` | `start` / `pause` / `step`，可设置 `interval_seconds` |
| POST | `/api/worlds/{id}/intervene` | 经典规则：`rain` / `market` / `enlightenment`；因果规则：`flood` / `repair_contract` |
| POST | `/api/worlds/{id}/chronicle` | 按需生成纪事 |
| POST | `/api/worlds/{id}/chat` | 提交 `npc_id` 和 `question` 与人物对话 |

规则与接口测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_living_world.py tests\test_world_simulation.py tests\test_world_api.py
```

## 环境要求

- Python **3.11+**
- 小说生成及 AI 功能需要配置 Anthropic 或 OpenAI-Compatible 服务；规则世界无需模型
- 使用远程模型时需要对应 API Key 和网络连接；Ollama 路径目前为实验性支持

---

## 第一步：克隆 / 进入项目目录

```bash
cd reese_xiaosee
```

---

## 第二步：创建虚拟环境（推荐）

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

---

## 第三步：安装依赖

```bash
pip install -r requirements.txt
```

依赖清单：

| 包 | 用途 |
|----|------|
| `anthropic` | Claude API 调用 |
| `openai` | OpenAI-Compatible API 调用 |
| `httpx` | HTTP 请求、超时配置及 Ollama 健康检查 |
| `fastapi` | Web 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `python-dotenv` | 读取 `.env` 配置 |
| `pydantic` | 数据模型验证 |

---

## 第四步：配置 API Key

复制示例配置文件：

```bash
# Windows
Copy-Item .\resources\.env.example .\.env

# macOS / Linux
cp resources/.env.example .env
```

编辑 `.env`，填入你的 Anthropic API Key：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
```

> API Key 在 [console.anthropic.com](https://console.anthropic.com/) → API Keys 页面获取。

使用其他模型服务时，在 [配置模板](../resources/.env.example) 中选择对应的
`LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL` 和 `MODEL`。

---

## 第五步：启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--reload` | 代码修改后自动重启（开发模式，生产环境去掉）|
| `--host 0.0.0.0` | 允许局域网访问（仅本机访问可改为 `127.0.0.1`）|
| `--port 8000` | 端口号（可自定义）|

---

## 第六步：打开浏览器

```
http://localhost:8000
```

看到「⚡ 网文 AI 引擎」界面即启动成功。

---

## 项目目录结构

```
reese_xiaosee/
├── main.py                    # FastAPI 应用入口
├── generate.py                # CLI：新建、恢复、列举和导出
├── runner.py                  # CLI 检查点与断点续写
├── requirements.txt           # 依赖列表
├── requirements-dev.txt       # 测试与检查工具
├── .env                       # API Key（不要提交到 git）
├── agents/                    # Agent 实现与 Web 线性流水线
├── core/                      # LLM、SQLite、缓存、导出和护栏
├── domain/                    # 学科与爽点规则，预留 DAG 编排
├── memory/                    # 跨章状态与节奏追踪
├── models/novel.py            # Pydantic 数据模型
├── resources/
│   ├── .env.example           # 配置模板
│   └── static/index.html      # 前端单页应用
├── scripts/                   # 启动脚本
├── tests/                     # 单元与关键链路回归测试
├── docs/                      # 启动、技术与创作流程文档
├── data/                      # SQLite 数据库（自动创建）
├── output/                    # 按任务分目录保存生成结果
└── checkpoints/               # CLI 检查点（自动创建）
```

---

## 生成流程说明

启动后，在界面中：

1. **选择类型** — 玄幻 / 修仙 / 都市 / 穿越 / 系统 / 末世 / 无限 / 历史
2. **选择爽点** — 逆袭打脸 / 升级爽 / 系统面板 / 装逼收徒 / 复仇 / 种田积累
3. **填写主角** — 姓名、起点设定、金手指/外挂
4. **（可选）** 扩展设定：世界观描述、反派方向、感情线
5. **设定结构** — 卷数（1-10）、每卷章数（5-30）、每章字数（1000-5000）
6. **选择质量模式** — 标准 / 深度（增加一致性校验、质量评分及必要的局部修正）
7. 点击 **⚡ 开始创作**

Web 按以下顺序执行：

```
世界构建师 → 角色设计师 → 剧情规划师 → 章节大纲师 → 写作执行者
                                                       ↓ deep 模式
                                               一致性校验 → 质量评审
```

生成完成并保存成功后，可下载全书、世界观、人物和场景四个 Markdown 文件。
缺少生成结果、文件写入失败或数据库保存失败时，SSE 返回错误，不返回成功下载链接。

### Web 与 CLI 的能力边界

| 能力 | Web | CLI |
|------|-----|-----|
| 流式界面、人工审批 | 支持 | 不支持 |
| 检查点恢复 | 不支持 | `python generate.py resume <run-id>` |
| 动态续卷 | 尚未接入，界面无限模式开关不代表已支持 | `new --mode infinite` |
| deep 模式 | 一致性校验 + 质量评审 | 一致性校验 |

Web 使用 `agents/pipeline.py`，CLI 使用 `runner.py`，目前不是同一个执行引擎。
当前 Web 保存依赖 SSE 消费到完成事件，请保持页面连接；需要断点恢复时使用 CLI。

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/generate` | 启动生成任务，返回 `task_id` |
| `GET` | `/api/stream/{task_id}` | SSE 流式获取生成事件 |
| `POST` | `/api/cancel/{task_id}` | 取消生成 |
| `POST` | `/api/approve/{task_id}` | 提交人工审批 |
| `GET` | `/api/history` | 获取历史记录（最近20条）|
| `DELETE` | `/api/history/{task_id}` | 删除历史记录 |
| `GET` | `/api/download/{task_id}` | 下载 Markdown 文件 |
| `GET` | `/api/download/{task_id}/{file_type}` | 下载 worldbuilding / characters / scenes |

---

## 常见问题

**Q：启动后访问出现 404？**
确认 `resources/static/index.html` 文件存在，且 `uvicorn main:app` 在项目根目录执行。

**Q：生成时报 `AuthenticationError`？**
`.env` 文件中的 `ANTHROPIC_API_KEY` 填写有误或未激活。

**Q：生成时报 `overloaded_error`？**
模型服务当前负载较高。可重试的阶段会指数退避，重试耗尽后返回错误。

**Q：生成速度慢？**
生成耗时取决于模型、章节数量、字数、重试和质量模式，深度模式会增加调用次数。

**Q：如何在生产环境部署？**
```bash
# 去掉 --reload，保持单个 worker
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

任务队列、取消状态和人工审批保存在进程内，不能直接使用多 worker 或多实例部署。
服务重启也不能恢复 Web 任务；需要这些能力时，应先统一持久化任务状态和调度机制。

---

## 生产环境注意事项

- `.env` 文件**不要**提交到 Git（已在 `.gitignore` 中排除）
- 持久化 `data/`、`output/` 和 CLI 使用的 `checkpoints/`，定期通过历史管理清理不需要的生成结果
- `MAX_COST_PER_RUN` 设置单次运行的估算费用上限（美元，默认 10）；实际费用以服务商账单为准
- Provider 未返回用量时会记录警告，该次调用无法准确计入费用统计

## 开发验证

在项目根目录安装并运行已有测试工具：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests\test_generation.py tests\test_runner.py tests\test_llm_client.py
```

完整测试执行 `python -m pytest -q`。测试通过模拟模型响应执行，不需要真实 API 调用。
