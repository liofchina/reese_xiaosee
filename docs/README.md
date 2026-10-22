# 网文 AI 创作引擎 — 启动指南

## 环境要求

- Python **3.11+**
- Anthropic API Key（[获取地址](https://console.anthropic.com/)）
- 网络连接（调用 Claude API）

---

## 第一步：克隆 / 进入项目目录

```bash
cd reese-ag
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
| `fastapi` | Web 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `python-dotenv` | 读取 `.env` 配置 |
| `pydantic` | 数据模型验证 |

---

## 第四步：配置 API Key

复制示例配置文件：

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

编辑 `.env`，填入你的 Anthropic API Key：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
```

> API Key 在 [console.anthropic.com](https://console.anthropic.com/) → API Keys 页面获取。

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
reese-ag/
├── main.py                    # FastAPI 应用入口
├── db.py                      # SQLite 持久化
├── requirements.txt           # 依赖列表
├── .env                       # API Key（不要提交到 git）
├── .env.example               # 配置模板
│
├── models/
│   └── novel.py               # 全部数据模型
│
├── agents/
│   ├── world_builder.py       # Agent 1：世界观构建师
│   ├── character_designer.py  # Agent 2：角色设计师
│   ├── plot_planner.py        # Agent 3：剧情规划师
│   ├── chapter_outliner.py    # Agent 4：章节大纲师
│   ├── writer.py              # Agent 5：写作执行者
│   ├── consistency_checker.py # Agent 6：一致性校验者
│   └── pipeline.py            # 六 Agent 异步流水线
│
├── static/
│   └── index.html             # 前端单页应用
│
├── data/
│   └── novels.db              # SQLite 数据库（自动创建）
│
├── output/
│   └── *.md                   # 生成的小说 Markdown（自动创建）
│
└── 网文创作流程.md             # 系统设计文档
```

---

## 生成流程说明

启动后，在界面中：

1. **选择类型** — 玄幻 / 修仙 / 都市 / 穿越 / 系统 / 末世 / 无限 / 历史
2. **选择爽点** — 逆袭打脸 / 升级爽 / 系统面板 / 装逼收徒 / 复仇 / 种田积累
3. **填写主角** — 姓名、起点设定、金手指/外挂
4. **（可选）** 扩展设定：世界观描述、反派方向、感情线
5. **设定结构** — 卷数（1-10）、每卷章数（5-30）、每章字数（1000-5000）
6. **选择质量模式** — 标准（快）/ 深度（含一致性校验 + 钩子评分）
7. 点击 **⚡ 开始创作**

AI 将依次执行六个 Agent：

```
世界构建师 → 角色设计师 → 剧情规划师 → 章节大纲师 → 写作执行者 → 一致性校验者
  (~30s)       (~20s)       (~30s)      (每卷~20s)    (每章流式)    (deep模式)
```

生成完成后可下载完整 Markdown 文件。

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/generate` | 启动生成任务，返回 `task_id` |
| `GET` | `/api/stream/{task_id}` | SSE 流式获取生成事件 |
| `POST` | `/api/cancel/{task_id}` | 取消生成 |
| `GET` | `/api/history` | 获取历史记录（最近20条）|
| `DELETE` | `/api/history/{task_id}` | 删除历史记录 |
| `GET` | `/api/download/{task_id}` | 下载 Markdown 文件 |

---

## 常见问题

**Q：启动后访问出现 404？**
确认 `static/index.html` 文件存在，且 `uvicorn main:app` 在项目根目录执行。

**Q：生成时报 `AuthenticationError`？**
`.env` 文件中的 `ANTHROPIC_API_KEY` 填写有误或未激活。

**Q：生成时报 `overloaded_error`？**
Claude API 当前负载较高，系统会自动重试3次，一般稍等即可。

**Q：生成速度慢？**
默认标准模式下，3卷×10章 大约需要 15-30 分钟（取决于 API 响应速度和每章字数）。深度模式因增加一致性校验，时间约多 30%。

**Q：如何在生产环境部署？**
```bash
# 去掉 --reload，增加 workers
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## 生产环境注意事项

- `.env` 文件**不要**提交到 Git（已在 `.gitignore` 中排除）
- `data/` 和 `output/` 目录会自动创建，定期清理 `output/*.md` 防止磁盘占满
- API Key 费用：每次完整生成（3卷30章）大约消耗 $0.5-2 美元，视字数而定
