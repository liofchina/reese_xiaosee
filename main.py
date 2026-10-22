import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents.pipeline import run_pipeline
from models.novel import WebNovelRequest, WebNovelResult, ApprovalResponse
from core.db import init_db, save_novel, list_novels, delete_novel, get_novel
from core.observability import Tracer
from core.guardrails import sanitize_input, scan_output, get_guardrail_level
from core.llm_client import validate_provider_config

load_dotenv()

# ── 安全：UUID 格式校验 ────────────────────────────────────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _validate_task_id(task_id: str) -> None:
    """校验 task_id 为合法 UUID，防止路径穿越攻击"""
    if not _UUID_RE.match(task_id):
        raise HTTPException(status_code=400, detail="无效的任务 ID")

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 任务上下文（建议9：强化类型标注）─────────────────────────────────────────

TASK_TTL_SECONDS = 2 * 60 * 60  # 2 小时过期
TASK_CLEANUP_INTERVAL = 10 * 60  # 每 10 分钟清理一次


@dataclass
class TaskContext:
    cancel_event: asyncio.Event
    queue: asyncio.Queue
    request: WebNovelRequest
    in_queue: asyncio.Queue | None
    created_at: float = dc_field(default_factory=time.monotonic)


_tasks: dict[str, TaskContext] = {}


# ── 后台清理过期任务（建议3）────────────────────────────────────────────────

async def _cleanup_stale_tasks():
    """定期清理超过 TTL 的 task，防止内存泄漏"""
    while True:
        await asyncio.sleep(TASK_CLEANUP_INTERVAL)
        now = time.monotonic()
        stale = [
            tid for tid, ctx in _tasks.items()
            if now - ctx.created_at > TASK_TTL_SECONDS
        ]
        for tid in stale:
            ctx = _tasks.pop(tid, None)
            if ctx:
                ctx.cancel_event.set()
                logger.info(f"清理过期任务: {tid}")


# ── Lifespan（建议15：替代已弃用的 @app.on_event）────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_provider_config()
    init_db()
    cleanup_task = asyncio.create_task(_cleanup_stale_tasks())
    yield
    cleanup_task.cancel()


app = FastAPI(title="AI 网文生成器", lifespan=lifespan)

# ── CORS（建议6）─────────────────────────────────────────────────────────────

_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="resources/static"), name="static")


# ── 简易 IP 限流中间件（建议6）───────────────────────────────────────────────

_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_MAX = 5       # 每 IP 每分钟最多 5 次生成请求
RATE_LIMIT_WINDOW = 60   # 窗口 60 秒
RATE_LIMIT_MAX_IPS = 10000  # 最大跟踪 IP 数，防止内存泄漏


@app.middleware("http")
async def rate_limit_generate(request: Request, call_next):
    if request.url.path == "/api/generate" and request.method == "POST":
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        hits = _rate_limit_store.get(client_ip, [])
        hits = [t for t in hits if now - t < RATE_LIMIT_WINDOW]
        if len(hits) >= RATE_LIMIT_MAX:
            return StreamingResponse(
                iter([json.dumps({"detail": "请求过于频繁，请稍后再试"})]),
                status_code=429,
                media_type="application/json",
            )
        hits.append(now)
        _rate_limit_store[client_ip] = hits
        # 防止内存无限增长：超出上限时清理最旧条目
        if len(_rate_limit_store) > RATE_LIMIT_MAX_IPS:
            oldest_ip = min(_rate_limit_store, key=lambda k: _rate_limit_store[k][-1])
            del _rate_limit_store[oldest_ip]
    return await call_next(request)


@app.get("/")
async def index():
    return FileResponse("resources/static/index.html")


# ── 启动生成（POST）────────────────────────────────────────────────────────────

@app.post("/api/generate")
async def start_generate(request: WebNovelRequest):
    # ── 前置输入消毒（建议2）────────────────────────────────
    if get_guardrail_level() != "none":
        text_fields = [
            request.protagonist_background,
            request.golden_finger,
            request.world_desc,
            request.antagonist_direction,
            request.romance,
            request.sub_genre,
        ]
        for field_val in text_fields:
            if field_val:
                _, warnings = sanitize_input(field_val)
                if warnings:
                    raise HTTPException(
                        status_code=400,
                        detail=f"输入安全检查未通过: {'; '.join(warnings)}",
                    )

    task_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    cancel_event = asyncio.Event()

    # 交互模式下创建双向队列
    in_queue: asyncio.Queue | None = None
    if request.interactive:
        in_queue = asyncio.Queue()

    _tasks[task_id] = TaskContext(
        cancel_event=cancel_event,
        queue=queue,
        request=request,
        in_queue=in_queue,
    )

    asyncio.create_task(run_pipeline(request, queue, cancel_event, in_queue, task_id=task_id))
    return {"task_id": task_id}


# ── 用户审批（POST）── Human-in-the-Loop ─────────────────────────────────────

@app.post("/api/approve/{task_id}")
async def approve_output(task_id: str, response: ApprovalResponse):
    _validate_task_id(task_id)
    ctx = _tasks.get(task_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="任务不存在")

    if ctx.in_queue is None:
        raise HTTPException(status_code=400, detail="此任务未启用交互模式")

    await ctx.in_queue.put(response.model_dump())
    return {"message": "审批已提交"}


# ── SSE 流（GET）──────────────────────────────────────────────────────────────

@app.get("/api/stream/{task_id}")
async def stream_events(task_id: str):
    _validate_task_id(task_id)
    ctx = _tasks.get(task_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="任务不存在")

    cancel_event, queue, req, in_queue = ctx.cancel_event, ctx.queue, ctx.request, ctx.in_queue

    async def event_generator():
        novel_obj: WebNovelResult | None = None

        try:
            while True:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=1800)

                if event_type == "status":
                    yield f"event: status\ndata: {json.dumps({'message': data}, ensure_ascii=False)}\n\n"

                elif event_type == "world_ready":
                    yield f"event: world_ready\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "characters_ready":
                    yield f"event: characters_ready\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "plot_ready":
                    yield f"event: plot_ready\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "thinking":
                    # 新增：Agent 推理过程
                    yield f"event: thinking\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "volume_outline_ready":
                    yield f"event: volume_outline_ready\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "chapter_start":
                    yield f"event: chapter_start\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "chunk":
                    yield f"event: chunk\ndata: {json.dumps({'text': data}, ensure_ascii=False)}\n\n"

                elif event_type == "checker_start":
                    yield f"event: checker_start\ndata: {json.dumps({'chapter_num': data}, ensure_ascii=False)}\n\n"

                elif event_type == "correction_applied":
                    # 新增：自动修正已应用
                    yield f"event: correction_applied\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "quality_review":
                    yield f"event: quality_review\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "trace_summary":
                    yield f"event: trace_summary\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "chapter_done":
                    yield f"event: chapter_done\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "approval_required":
                    # 新增：请求用户审批
                    yield f"event: approval_required\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif event_type == "_novel_object":
                    # 内部事件，不推送前端，保存对象供写文件用
                    novel_obj = data

                elif event_type == "novel_complete":
                    # 保存 Markdown（全书 + 分文件）
                    if novel_obj:
                        out_dir = OUTPUT_DIR / task_id
                        out_dir.mkdir(parents=True, exist_ok=True)
                        # 全书
                        out_path = out_dir / "novel.md"
                        out_path.write_text(novel_obj.to_markdown(), encoding="utf-8")
                        # 分文件导出
                        (out_dir / "worldbuilding.md").write_text(
                            novel_obj.to_worldbuilding_markdown(), encoding="utf-8"
                        )
                        (out_dir / "characters.md").write_text(
                            novel_obj.to_characters_markdown(), encoding="utf-8"
                        )
                        (out_dir / "scenes.md").write_text(
                            novel_obj.to_scenes_markdown(), encoding="utf-8"
                        )
                        save_novel(
                            task_id=task_id,
                            title=novel_obj.title,
                            genre=req.genre,
                            core_pleasure=req.core_pleasure,
                            quality_mode=req.quality_mode,
                            num_volumes=len(novel_obj.outline.volumes),
                            total_chapters=len(novel_obj.chapters),
                            markdown_path=str(out_dir),
                        )
                        payload = {
                            "title": data.get("title", novel_obj.title),
                            "download_url": f"/api/download/{task_id}",
                        }
                    else:
                        payload = {"title": data.get("title", ""), "download_url": ""}

                    yield f"event: novel_complete\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break

                elif event_type == "cancelled":
                    yield f"event: cancelled\ndata: {json.dumps({'message': data}, ensure_ascii=False)}\n\n"
                    break

                elif event_type == "error":
                    yield f"event: error\ndata: {json.dumps({'message': data}, ensure_ascii=False)}\n\n"
                    break

        except asyncio.TimeoutError:
            yield f"event: error\ndata: {json.dumps({'message': '生成超时，请重试'}, ensure_ascii=False)}\n\n"
        finally:
            _tasks.pop(task_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 取消 ──────────────────────────────────────────────────────────────────────

@app.post("/api/cancel/{task_id}")
async def cancel_generation(task_id: str):
    _validate_task_id(task_id)
    ctx = _tasks.get(task_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="任务不存在或已完成")
    ctx.cancel_event.set()
    return {"message": "取消请求已发送"}


# ── 历史记录 ──────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history():
    return list_novels(limit=20)


@app.delete("/api/history/{task_id}")
async def remove_history(task_id: str):
    _validate_task_id(task_id)
    record = get_novel(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.get("markdown_path"):
        p = Path(record["markdown_path"]).resolve()
        # 安全校验：确保路径在 OUTPUT_DIR 内，防止任意文件删除
        if str(p).startswith(str(OUTPUT_DIR.resolve())) and p.exists():
            p.unlink()
    deleted = delete_novel(task_id)
    return {"deleted": deleted}


@app.get("/api/download/{task_id}")
async def download_novel(task_id: str):
    _validate_task_id(task_id)
    # 优先从目录结构查找
    dir_path = OUTPUT_DIR / task_id
    if dir_path.is_dir():
        novel_path = dir_path / "novel.md"
        if novel_path.exists():
            record = get_novel(task_id)
            filename = f"{record['title']}.md" if record else "novel.md"
            return FileResponse(novel_path, media_type="text/markdown", filename=filename)
    # 兼容旧的单文件格式
    record = get_novel(task_id)
    if record and record.get("markdown_path"):
        p = Path(record["markdown_path"])
        if p.is_file() and p.exists():
            filename = f"{record['title']}.md"
            return FileResponse(p, media_type="text/markdown", filename=filename)
        elif p.is_dir():
            novel_path = p / "novel.md"
            if novel_path.exists():
                filename = f"{record['title']}.md"
                return FileResponse(novel_path, media_type="text/markdown", filename=filename)
    out_path = OUTPUT_DIR / f"{task_id}.md"
    if out_path.exists():
        return FileResponse(out_path, media_type="text/markdown", filename="novel.md")
    raise HTTPException(status_code=404, detail="文件不存在或尚未生成完成")


@app.get("/api/download/{task_id}/{file_type}")
async def download_novel_part(task_id: str, file_type: str):
    """下载分文件：worldbuilding / characters / scenes"""
    _validate_task_id(task_id)
    allowed = {"worldbuilding", "characters", "scenes"}
    if file_type not in allowed:
        raise HTTPException(status_code=400, detail=f"文件类型必须是: {', '.join(allowed)}")

    dir_path = OUTPUT_DIR / task_id
    file_path = dir_path / f"{file_type}.md"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{file_type}.md 尚未生成")

    record = get_novel(task_id)
    title = record["title"] if record else task_id
    type_names = {"worldbuilding": "世界观", "characters": "人物设定", "scenes": "场景设定"}
    filename = f"{title}_{type_names.get(file_type, file_type)}.md"
    return FileResponse(file_path, media_type="text/markdown", filename=filename)


# ── 追踪记录 ──────────────────────────────────────────────────────────────────

@app.get("/api/traces/{task_id}")
async def get_traces(task_id: str):
    """获取指定任务的 LLM 调用追踪记录"""
    _validate_task_id(task_id)
    traces = Tracer.load_traces(task_id)
    if not traces:
        raise HTTPException(status_code=404, detail="无追踪记录")
    return {"task_id": task_id, "traces": traces}
