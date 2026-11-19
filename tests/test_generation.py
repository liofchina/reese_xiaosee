import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import main
from agents import pipeline
from core import db
from models.novel import (
    ChapterOutlineItem,
    ChapterResult,
    PlotFramework,
    PowerLevel,
    PowerSystem,
    VolumePlan,
    WebNovelOutline,
    WebNovelRequest,
    WebNovelResult,
    WorldSetting,
)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(main, "OUTPUT_DIR", output)
    monkeypatch.setattr(main, "_tasks", {})
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "novels.db")
    db.init_db()
    return output


@pytest.fixture
def generation():
    request = WebNovelRequest(
        genre="fantasy",
        core_pleasure="growth",
        protagonist_name="Hero",
        protagonist_background="An apprentice",
        golden_finger="A hidden library",
        num_volumes=1,
    )
    chapter_outline = ChapterOutlineItem(
        chapter_num=1,
        volume_chapter_num=1,
        title="The beginning",
        hook_start="A discovery",
        core_events=["Find the library"],
        hook_end="An unopened door",
        protagonist_power="Apprentice",
    )
    volume = VolumePlan(
        volume_num=1,
        title="First steps",
        theme="Discovery",
        antagonist_name="Rival",
        core_pleasure_point="Learning",
        protagonist_power_start="Apprentice",
        protagonist_power_end="Apprentice",
        ending_hook="A new journey",
        chapters=[chapter_outline],
    )
    world = WorldSetting(
        description="A fictional world",
        power_system=PowerSystem(
            name="Learning",
            levels=[
                PowerLevel(
                    name="Apprentice",
                    rank=1,
                    description="A beginner",
                    typical_power="Basic skills",
                )
            ],
            breakthrough_conditions="Practice",
        ),
        factions=[],
        resource_system="Books",
    )
    outline = WebNovelOutline(
        title="The library",
        world=world,
        characters=[],
        antagonists=[],
        plot_framework=PlotFramework(
            ultimate_goal="Learn the truth", milestones=[], global_foreshadowing=[]
        ),
        volumes=[volume],
    )
    chapter = ChapterResult(
        volume_num=1,
        chapter_num=1,
        volume_chapter_num=1,
        title=chapter_outline.title,
        content="The apprentice opened the hidden library.",
        summary="The library was found.",
        protagonist_power_end="Apprentice",
    )
    return request, WebNovelResult(title=outline.title, outline=outline, chapters=[chapter])


async def _consume_events(request, queue):
    task_id = str(uuid.uuid4())
    main._tasks[task_id] = main.TaskContext(asyncio.Event(), queue, request, None)
    response = await main.stream_events(task_id)
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return task_id, "".join(chunks)


def _save_history(task_id: str, path: Path) -> None:
    db.save_novel(
        task_id=task_id,
        title="The library",
        genre="fantasy",
        core_pleasure="growth",
        quality_mode="standard",
        num_volumes=1,
        total_chapters=1,
        markdown_path=str(path),
    )


async def test_pipeline_completion_exports_files_and_saves_history(storage, generation, monkeypatch):
    request, novel = generation
    outline = novel.outline
    monkeypatch.setattr(pipeline, "create_client", lambda: object())
    monkeypatch.setattr(pipeline, "resolve_disciplines", lambda *args: [])
    monkeypatch.setattr(pipeline, "build_world", AsyncMock(return_value=outline.world))
    monkeypatch.setattr(pipeline, "design_characters", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(
        pipeline,
        "plan_plot",
        AsyncMock(return_value=(novel.title, outline.plot_framework, outline.volumes)),
    )
    monkeypatch.setattr(
        pipeline, "outline_volume", AsyncMock(return_value=outline.volumes[0].chapters)
    )
    monkeypatch.setattr(pipeline, "extract_entity_changes", AsyncMock(return_value={}))

    async def write_chapter(*args, **kwargs):
        yield "chunk", novel.chapters[0].content
        yield "result", novel.chapters[0]

    monkeypatch.setattr(pipeline, "write_chapter", write_chapter)
    queue = asyncio.Queue()
    await pipeline.run_pipeline(request, queue, asyncio.Event())
    task_id, events = await _consume_events(request, queue)

    completion = next(event for event in events.split("\n\n") if "event: novel_complete" in event)
    payload = json.loads(completion.split("data: ", 1)[1])
    assert payload["download_url"] == f"/api/download/{task_id}"
    assert {path.name for path in (storage / task_id).iterdir()} == {
        "novel.md", "worldbuilding.md", "characters.md", "scenes.md",
    }
    record = db.get_novel(task_id)
    assert record["total_chapters"] == 1
    assert record["markdown_path"] == str(storage / task_id)
    download = await main.download_novel(task_id)
    assert novel.chapters[0].content in Path(download.path).read_text(encoding="utf-8")
    assert queue.empty()


async def test_completion_without_result_reports_error(storage, generation):
    request, _ = generation
    queue = asyncio.Queue()
    await queue.put(("novel_complete", {"title": "Missing result"}))

    task_id, events = await _consume_events(request, queue)

    assert "event: error\n" in events
    assert "event: novel_complete\n" not in events
    assert db.get_novel(task_id) is None


@pytest.mark.parametrize("error", [OSError("disk full"), sqlite3.OperationalError("database locked")])
async def test_save_failure_is_not_reported_as_completion(storage, generation, monkeypatch, error):
    request, novel = generation
    queue = asyncio.Queue()
    await queue.put(("_novel_object", novel))
    await queue.put(("novel_complete", {"title": novel.title}))

    def fail_save(**kwargs):
        raise error

    monkeypatch.setattr(main, "save_novel", fail_save)
    task_id, events = await _consume_events(request, queue)

    assert "event: error\n" in events
    assert "event: novel_complete\n" not in events
    assert db.get_novel(task_id) is None


@pytest.mark.parametrize("legacy", [False, True])
async def test_delete_history_removes_export_and_record(storage, legacy):
    task_id = str(uuid.uuid4())
    path = storage / (f"{task_id}.md" if legacy else task_id)
    if legacy:
        path.write_text("A legacy novel", encoding="utf-8")
    else:
        path.mkdir()
        (path / "novel.md").write_text("A novel", encoding="utf-8")
    _save_history(task_id, path)

    assert await main.remove_history(task_id) == {"deleted": True}
    assert not path.exists()
    assert db.get_novel(task_id) is None


@pytest.mark.parametrize("location", ["root", "sibling"])
async def test_delete_history_rejects_paths_outside_task_output(storage, location):
    task_id = str(uuid.uuid4())
    path = storage if location == "root" else storage.with_name("output-backup")
    path.mkdir(exist_ok=True)
    marker = path / "keep.md"
    marker.write_text("Keep this file", encoding="utf-8")
    _save_history(task_id, path)

    with pytest.raises(HTTPException) as exc_info:
        await main.remove_history(task_id)

    assert exc_info.value.status_code == 400
    assert marker.exists()
    assert db.get_novel(task_id) is not None


def test_history_connections_are_closed_after_each_operation(storage, monkeypatch):
    connections = []
    connect = sqlite3.connect

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", track_connection)
    db.init_db()
    task_id = str(uuid.uuid4())
    _save_history(task_id, storage / task_id)
    db.get_novel(task_id)
    db.list_novels()
    db.delete_novel(task_id)

    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
