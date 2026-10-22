#!/usr/bin/env python3
"""
网文无限生成引擎 CLI

用法：
  python generate.py new [选项]       # 新建生成任务
  python generate.py resume <run-id>  # 恢复中断的任务
  python generate.py list             # 查看所有任务
  python generate.py export <run-id>  # 导出当前进度为 Markdown

示例：
  python generate.py new \\
    --genre 玄幻 \\
    --core-pleasure 逆袭打脸 \\
    --protagonist-name 林逸 \\
    --protagonist-background 废材少年，被家族逐出 \\
    --golden-finger 万界交易系统 \\
    --volumes 5 \\
    --chapters-per-volume 20 \\
    --words-per-chapter 3000 \\
    --mode infinite \\
    --quality-mode standard

  python generate.py resume abc12345
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 日志配置 ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CHECKPOINT_ROOT = Path("checkpoints")


# ── 命令：new ─────────────────────────────────────────────────────────────────

def cmd_new(args):
    from models.novel import WebNovelRequest
    from runner import ResumableRunner

    request = WebNovelRequest(
        genre=args.genre,
        sub_genre=args.sub_genre or "",
        core_pleasure=args.core_pleasure,
        protagonist_name=args.protagonist_name,
        protagonist_background=args.protagonist_background,
        golden_finger=args.golden_finger,
        world_desc=args.world_desc or "",
        antagonist_direction=args.antagonist_direction or "",
        romance=args.romance or "",
        num_volumes=args.volumes,
        chapters_per_volume=args.chapters_per_volume,
        words_per_chapter=args.words_per_chapter,
        quality_mode=args.quality_mode,
        mode=args.mode,
    )

    run_id = uuid.uuid4().hex[:8]
    checkpoint_dir = CHECKPOINT_ROOT / run_id
    checkpoint_dir.mkdir(parents=True)

    logger.info(f"新建任务  run_id={run_id}")
    logger.info(f"  题材: {args.genre} | 爽点: {args.core_pleasure}")
    logger.info(f"  规模: {args.volumes}卷 × {args.chapters_per_volume}章 = "
                f"{args.volumes * args.chapters_per_volume}章（{'无限扩展' if args.mode == 'infinite' else '固定'}）")
    logger.info(f"  检查点: {checkpoint_dir}")
    logger.info(f"  输出:   output/{run_id}/")
    logger.info(f"  恢复命令: python generate.py resume {run_id}")

    runner = ResumableRunner(run_id, request, checkpoint_dir)
    _run_with_graceful_stop(runner)

    # 生成完成后自动导出
    _auto_export(run_id, checkpoint_dir, args.format)


# ── 命令：resume ──────────────────────────────────────────────────────────────

def cmd_resume(args):
    from models.novel import WebNovelRequest
    from runner import ResumableRunner

    run_id = args.run_id
    checkpoint_dir = CHECKPOINT_ROOT / run_id

    if not checkpoint_dir.exists():
        logger.error(f"检查点目录不存在 {checkpoint_dir}")
        sys.exit(1)

    req_path = checkpoint_dir / "request.json"
    if not req_path.exists():
        logger.error("找不到 request.json，检查点可能已损坏")
        sys.exit(1)

    request = WebNovelRequest(**json.loads(req_path.read_text(encoding="utf-8")))

    # 读取进度
    run_data = {}
    run_path = checkpoint_dir / "run.json"
    if run_path.exists():
        run_data = json.loads(run_path.read_text(encoding="utf-8"))

    completed = run_data.get("completed_chapters", 0)
    last_ch = run_data.get("last_chapter", "—")
    logger.info(f"恢复任务  run_id={run_id}")
    logger.info(f"  已完成: {completed} 章（最后第 {last_ch} 章）")
    logger.info(f"  模式: {request.mode}")

    runner = ResumableRunner(run_id, request, checkpoint_dir)
    _run_with_graceful_stop(runner)

    # 恢复完成后自动导出
    _auto_export(run_id, checkpoint_dir, args.format)


# ── 命令：list ────────────────────────────────────────────────────────────────

def cmd_list(args):
    if not CHECKPOINT_ROOT.exists():
        logger.info("暂无任何任务记录")
        return

    runs = []
    for d in sorted(CHECKPOINT_ROOT.iterdir()):
        if not d.is_dir():
            continue
        run_json = d / "run.json"
        req_json = d / "request.json"
        if not run_json.exists():
            continue
        run_data = json.loads(run_json.read_text(encoding="utf-8"))
        req_data = json.loads(req_json.read_text(encoding="utf-8")) if req_json.exists() else {}
        runs.append({
            "run_id": d.name,
            "status": run_data.get("status", "unknown"),
            "mode": run_data.get("mode", req_data.get("mode", "?")),
            "completed": run_data.get("completed_chapters", 0),
            "genre": req_data.get("genre", "?"),
            "updated_at": run_data.get("updated_at", "")[:16],
        })

    if not runs:
        logger.info("暂无任务记录")
        return

    print(f"\n{'run_id':<12} {'mode':<10} {'status':<10} {'题材':<8} {'已完成':<8} {'更新时间'}")
    print("─" * 70)
    for r in sorted(runs, key=lambda x: x["updated_at"], reverse=True):
        status_icon = {"running": "▶", "completed": "✅", "paused": "⏸", "failed": "❌"}.get(r["status"], "?")
        chapters_str = f"{r['completed']}章" if r["mode"] == "bounded" else f"{r['completed']}章/∞"
        print(f"{r['run_id']:<12} {r['mode']:<10} {status_icon} {r['status']:<8} "
              f"{r['genre']:<8} {chapters_str:<10} {r['updated_at']}")
    print()


# ── 命令：export ──────────────────────────────────────────────────────────────

def cmd_export(args):
    run_id = args.run_id
    checkpoint_dir = CHECKPOINT_ROOT / run_id

    if not checkpoint_dir.exists():
        logger.error(f"找不到任务 {run_id}")
        sys.exit(1)

    from core.exporters import export_novel, ExportFormat

    formats = [ExportFormat(f) for f in args.format]
    out_dir = Path("output") / run_id

    try:
        results = export_novel(run_id, checkpoint_dir, out_dir, formats)
        for fmt, path in results.items():
            logger.info(f"  ✓ 导出 {fmt.value}: {path}")
        if not results:
            logger.warning("未成功导出任何格式")
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)


# ── 优雅停止（Ctrl+C） ────────────────────────────────────────────────────────

def _auto_export(run_id: str, checkpoint_dir: Path, formats: list[str]):
    """生成完成后自动导出为指定格式"""
    from core.exporters import export_novel, ExportFormat

    fmt_list = [ExportFormat(f) for f in formats]
    out_dir = Path("output") / run_id

    try:
        results = export_novel(run_id, checkpoint_dir, out_dir, fmt_list)
        if results:
            logger.info("── 导出完成 ──")
            for fmt, path in results.items():
                logger.info(f"  ✓ {fmt.value}: {path}")
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"自动导出跳过: {e}")
    except Exception as e:
        logger.warning(f"自动导出失败（非致命）: {e}")


def _run_with_graceful_stop(runner):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _on_sigint(*_):
        logger.info("收到 Ctrl+C，写完当前章后停止（再按一次强制退出）...")
        runner._stop_requested = True
        signal.signal(signal.SIGINT, signal.SIG_DFL)   # 第二次直接退出

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        logger.info("强制退出")
    except Exception as e:
        logger.error(f"生成失败: {e}")
        runner._update_run(status="failed", error=str(e))
        raise
    finally:
        loop.close()


# ── 参数解析 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="网文无限生成引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # new
    p_new = sub.add_parser("new", help="新建生成任务")
    p_new.add_argument("--genre", required=True,
                       help="题材：玄幻/修仙/都市/穿越/系统/末世/无限/历史")
    p_new.add_argument("--sub-genre", default="", help="子题材（可选）")
    p_new.add_argument("--core-pleasure", required=True,
                       help="核心爽点：逆袭打脸/升级爽/系统面板/装逼收徒/复仇/种田积累")
    p_new.add_argument("--protagonist-name", required=True, help="主角姓名")
    p_new.add_argument("--protagonist-background", required=True,
                       help="主角起点（废材/失忆/穿越等）")
    p_new.add_argument("--golden-finger", required=True, help="金手指/外挂")
    p_new.add_argument("--world-desc", default="", help="世界观描述（可选）")
    p_new.add_argument("--antagonist-direction", default="", help="反派方向（可选）")
    p_new.add_argument("--romance", default="", help="感情线设定（可选）")
    p_new.add_argument("--volumes", type=int, default=5, help="初始规划卷数（默认5）")
    p_new.add_argument("--chapters-per-volume", type=int, default=10,
                       help="每卷章数（默认10，范围5-30）")
    p_new.add_argument("--words-per-chapter", type=int, default=2000,
                       help="每章字数（默认2000，范围1000-5000）")
    p_new.add_argument("--quality-mode", default="standard",
                       choices=["standard", "deep"], help="质量模式（默认standard）")
    p_new.add_argument("--mode", default="bounded",
                       choices=["bounded", "infinite"],
                       help="生成模式：bounded=有界完结 infinite=无限连载（默认bounded）")
    p_new.add_argument("--format", nargs="+", default=["txt"],
                       choices=["md", "txt", "epub"],
                       help="输出格式（可多选，默认 txt）。示例：--format txt epub")

    # resume
    p_resume = sub.add_parser("resume", help="恢复中断的任务")
    p_resume.add_argument("run_id", help="任务ID")
    p_resume.add_argument("--format", nargs="+", default=["txt"],
                          choices=["md", "txt", "epub"],
                          help="完成后输出格式（默认 txt）")

    # list
    sub.add_parser("list", help="查看所有任务")

    # export
    p_export = sub.add_parser("export", help="导出为小说格式文件")
    p_export.add_argument("run_id", help="任务ID")
    p_export.add_argument("--format", nargs="+", default=["txt"],
                          choices=["md", "txt", "epub"],
                          help="导出格式（可多选，默认 txt）")

    args = parser.parse_args()

    if args.command == "new":
        cmd_new(args)
    elif args.command == "resume":
        cmd_resume(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "export":
        cmd_export(args)


if __name__ == "__main__":
    main()
