import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/novels.db")


def init_db() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS novels (
                task_id        TEXT PRIMARY KEY,
                title          TEXT NOT NULL,
                genre          TEXT,
                core_pleasure  TEXT,
                quality_mode   TEXT,
                num_volumes    INTEGER,
                total_chapters INTEGER,
                created_at     TEXT NOT NULL,
                markdown_path  TEXT
            )
        """)
        conn.commit()


def save_novel(
    task_id: str,
    title: str,
    genre: str,
    core_pleasure: str,
    quality_mode: str,
    num_volumes: int,
    total_chapters: int,
    markdown_path: str,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO novels
                (task_id, title, genre, core_pleasure, quality_mode,
                 num_volumes, total_chapters, created_at, markdown_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, title, genre, core_pleasure, quality_mode,
                num_volumes, total_chapters,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                markdown_path,
            ),
        )
        conn.commit()


def list_novels(limit: int = 20) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM novels ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_novel(task_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM novels WHERE task_id = ?", (task_id,))
        conn.commit()
    return cur.rowcount > 0


def get_novel(task_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM novels WHERE task_id = ?", (task_id,)
        ).fetchone()
    return dict(row) if row else None
