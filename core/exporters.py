# -*- coding: utf-8 -*-
"""
多格式小说导出模块

支持格式：
- TXT：中文网文阅读器标准格式（默认）
- MD：Markdown 格式
- EPUB：电子书格式（需 pip install ebooklib）

用法：
    from core.exporters import export_novel, ExportFormat
    results = export_novel(run_id, checkpoint_dir, out_dir, [ExportFormat.TXT])
"""

import json
import logging
import re
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ExportFormat(str, Enum):
    MD = "md"
    TXT = "txt"
    EPUB = "epub"


# ── 文件名安全处理 ────────────────────────────────────────────────────────────

def _safe_filename(title: str, max_len: int = 50) -> str:
    """将小说标题转为安全文件名"""
    # 去除书名号等装饰字符
    name = re.sub(r"[《》【】〈〉「」『』]", "", title)
    # 去除文件系统不安全字符
    name = re.sub(r'[/\\:*?"<>|]', "", name)
    # 去除首尾空白
    name = name.strip()
    # 截断
    if len(name) > max_len:
        name = name[:max_len]
    return name or "novel"


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_novel_data(checkpoint_dir: Path) -> tuple[str, list[dict], dict[int, dict]]:
    """
    从检查点目录加载小说数据。

    返回：(title, volumes, chapters_dict)
    - title: 小说标题
    - volumes: 卷列表（含 chapters 大纲）
    - chapters_dict: {chapter_num: chapter_data}
    """
    plot_data = _load_json(checkpoint_dir / "plot.json")
    if not plot_data:
        raise FileNotFoundError("找不到 plot.json，剧情规划尚未完成")

    title = plot_data.get("title", "未命名小说")
    volumes = plot_data.get("volumes", [])

    # 为每卷加载章节大纲
    for vol in volumes:
        vol_num = vol.get("volume_num", 0)
        outline_data = _load_json(checkpoint_dir / f"outline_vol_{vol_num}.json")
        if outline_data:
            vol["chapters"] = outline_data.get("chapters", [])
        elif "chapters" not in vol:
            vol["chapters"] = []

    # 加载所有已完成的章节
    chapters_dict = {}
    for p in checkpoint_dir.glob("chapter_*.json"):
        try:
            num = int(p.stem.split("_")[1])
            data = _load_json(p)
            if data:
                chapters_dict[num] = data
        except (ValueError, IndexError):
            pass

    return title, volumes, chapters_dict


# ── Markdown 清洗（用于 TXT 导出）──────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """去除 Markdown 语法，保留纯文本"""
    # 去除校验注释行
    text = re.sub(r"^>\s*\*校验[：:].*?\*\s*$", "", text, flags=re.MULTILINE)
    # 去除标题标记
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 去除加粗和斜体
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # 去除引用标记
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # 去除分隔线
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    # 去除列表标记
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    return text


def _format_paragraphs(text: str) -> str:
    """将文本格式化为中文小说段落格式（全角缩进）"""
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        # 对话行（以引号开头）不缩进
        if para.startswith(("\u300c", "\u300e", "\u201c", "\"", "'", "\u2014\u2014")):
            lines.append(para)
        else:
            lines.append(f"\u3000\u3000{para}")
    return "\n".join(lines)


# ── TXT 导出 ─────────────────────────────────────────────────────────────────

def export_txt(title: str, volumes: list[dict], chapters: dict[int, dict], out_dir: Path) -> Path:
    """
    导出为中文网文 TXT 格式。
    UTF-8 with BOM 编码，兼容 Windows/Android 阅读器。
    """
    lines = [f"《{title}》", "", ""]

    for vol in volumes:
        vol_num = vol.get("volume_num", 0)
        vol_title = vol.get("title", "")

        # 卷分隔
        lines.append("═" * 30)
        lines.append(f"第{vol_num}卷\u3000{vol_title}")
        lines.append("═" * 30)
        lines.append("")

        # 按章节顺序输出
        chapter_outlines = vol.get("chapters", [])
        for ch_outline in chapter_outlines:
            ch_num = ch_outline.get("chapter_num", 0)
            ch_data = chapters.get(ch_num)
            if not ch_data:
                continue

            ch_title = ch_data.get("title", ch_outline.get("title", ""))
            vol_ch_num = ch_data.get("volume_chapter_num", ch_num)
            content = ch_data.get("content", "")

            # 章节标题
            lines.append("")
            lines.append(f"第{vol_ch_num}章\u3000{ch_title}")
            lines.append("")

            # 正文：去除 Markdown，格式化段落
            clean_content = _strip_markdown(content)
            formatted = _format_paragraphs(clean_content)
            lines.append(formatted)
            lines.append("")

    # 写入文件（UTF-8 BOM）
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_filename(title)}.txt"
    out_path = out_dir / filename
    out_path.write_text("\ufeff" + "\n".join(lines), encoding="utf-8")
    return out_path


# ── MD 导出 ──────────────────────────────────────────────────────────────────

def export_md(title: str, volumes: list[dict], chapters: dict[int, dict], out_dir: Path) -> Path:
    """导出为 Markdown 格式（全书合并版）"""
    lines = [f"# {title}\n"]

    for vol in volumes:
        vol_num = vol.get("volume_num", 0)
        vol_title = vol.get("title", "")
        vol_theme = vol.get("theme", "")

        lines.append(f"\n---\n## 第{vol_num}卷·{vol_title}\n")
        if vol_theme:
            lines.append(f"> {vol_theme}\n")

        chapter_outlines = vol.get("chapters", [])
        for ch_outline in chapter_outlines:
            ch_num = ch_outline.get("chapter_num", 0)
            ch_data = chapters.get(ch_num)
            if not ch_data:
                continue

            ch_title = ch_data.get("title", ch_outline.get("title", ""))
            vol_ch_num = ch_data.get("volume_chapter_num", ch_num)
            content = ch_data.get("content", "")

            lines.append(f"\n### 第{vol_ch_num}章·{ch_title}\n")
            lines.append(content)

            issues = ch_data.get("consistency_issues", [])
            if issues:
                lines.append(f"\n> *校验：{'|'.join(issues)}*")
            lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_filename(title)}.md"
    out_path = out_dir / filename
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ── EPUB 导出 ────────────────────────────────────────────────────────────────

_EPUB_CSS = """
body {
    font-family: "Source Han Serif SC", "Noto Serif CJK SC", "SimSun", serif;
    line-height: 1.8;
    text-indent: 2em;
    margin: 1em;
}
h1, h2, h3 {
    text-indent: 0;
    margin-top: 1.5em;
}
h1 { font-size: 1.5em; text-align: center; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; }
p { margin: 0.5em 0; }
"""


def export_epub(title: str, volumes: list[dict], chapters: dict[int, dict], out_dir: Path) -> Path:
    """
    导出为 EPUB 电子书格式。
    需要 ebooklib 库：pip install ebooklib
    """
    try:
        from ebooklib import epub
    except ImportError:
        raise ImportError(
            "EPUB 导出需要 ebooklib 库。请运行: pip install ebooklib"
        )

    book = epub.EpubBook()
    book.set_identifier(f"reese-ag-{_safe_filename(title)}")
    book.set_title(title)
    book.set_language("zh")
    book.add_author("AI 网文生成器")

    # CSS 样式
    style = epub.EpubItem(
        uid="style", file_name="style/default.css",
        media_type="text/css", content=_EPUB_CSS.encode("utf-8"),
    )
    book.add_item(style)

    spine = ["nav"]
    toc = []

    for vol in volumes:
        vol_num = vol.get("volume_num", 0)
        vol_title = vol.get("title", "")
        vol_chapters = []

        chapter_outlines = vol.get("chapters", [])
        for ch_outline in chapter_outlines:
            ch_num = ch_outline.get("chapter_num", 0)
            ch_data = chapters.get(ch_num)
            if not ch_data:
                continue

            ch_title = ch_data.get("title", ch_outline.get("title", ""))
            vol_ch_num = ch_data.get("volume_chapter_num", ch_num)
            content = ch_data.get("content", "")

            # 将内容转为 HTML 段落
            clean_content = _strip_markdown(content)
            paragraphs = [p.strip() for p in clean_content.split("\n") if p.strip()]
            html_content = "".join(f"<p>{p}</p>\n" for p in paragraphs)

            # 创建 EPUB 章节
            epub_ch = epub.EpubHtml(
                title=f"第{vol_ch_num}章 {ch_title}",
                file_name=f"ch_{ch_num:04d}.xhtml",
                lang="zh",
            )
            epub_ch.content = (
                f"<h3>第{vol_ch_num}章\u3000{ch_title}</h3>\n{html_content}"
            ).encode("utf-8")
            epub_ch.add_item(style)
            book.add_item(epub_ch)
            spine.append(epub_ch)
            vol_chapters.append(epub_ch)

        if vol_chapters:
            toc.append(
                (epub.Section(f"第{vol_num}卷 {vol_title}"), vol_chapters)
            )

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_filename(title)}.epub"
    out_path = out_dir / filename
    epub.write_epub(str(out_path), book)
    return out_path


# ── 统一导出入口 ─────────────────────────────────────────────────────────────

_EXPORTERS = {
    ExportFormat.MD: export_md,
    ExportFormat.TXT: export_txt,
    ExportFormat.EPUB: export_epub,
}


def export_novel(
    run_id: str,
    checkpoint_dir: Path,
    out_dir: Path,
    formats: list[ExportFormat] | None = None,
) -> dict[ExportFormat, Path]:
    """
    统一导出入口。从检查点加载数据，按指定格式导出。

    参数：
        run_id: 任务 ID
        checkpoint_dir: 检查点目录路径
        out_dir: 输出目录
        formats: 导出格式列表（默认 [TXT]）

    返回：{格式: 输出文件路径}
    """
    if formats is None:
        formats = [ExportFormat.TXT]

    title, volumes, chapters = _load_novel_data(checkpoint_dir)

    if not chapters:
        raise ValueError("没有已完成的章节，无法导出")

    results = {}
    for fmt in formats:
        exporter = _EXPORTERS[fmt]
        try:
            path = exporter(title, volumes, chapters, out_dir)
            results[fmt] = path
            logger.info(f"导出 {fmt.value}: {path}")
        except ImportError as e:
            logger.warning(str(e))
        except Exception as e:
            logger.error(f"导出 {fmt.value} 失败: {e}")

    return results
