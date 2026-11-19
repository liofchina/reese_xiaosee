import asyncio
import json
import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from core import db, world_runtime
from core.llm_client import BudgetExceededError, LLMClient
from core.world_runtime import WorldRuntime
from core.world_store import WorldStore
from domain.world_events import record_event
from domain.world_simulation import create_world
from models.world import WorldChatRequest, WorldConfig, WorldControl, WorldMemory


@pytest.fixture
async def runtime(tmp_path):
    instance = WorldRuntime(WorldStore(tmp_path / "worlds.db"))
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


async def test_auto_clock_advances_only_started_worlds(runtime):
    world = await runtime.create(WorldConfig(seed=17))
    started = await runtime.control(world.id, WorldControl(action="start", interval_seconds=3))
    assert started.running
    due = runtime._next_ticks[world.id]
    await runtime._tick_due(due + 0.1)
    assert runtime.get(world.id).day == world.day + 1
    await runtime.control(world.id, WorldControl(action="pause"))
    await runtime._tick_due(due + 100)
    assert runtime.get(world.id).day == world.day + 1
    assert not runtime.get(world.id).running


async def test_restart_restores_progress_but_does_not_resume_without_consent(tmp_path):
    store = WorldStore(tmp_path / "worlds.db")
    store.initialize()
    saved = create_world(WorldConfig(seed=42))
    saved.running = True
    saved.day = 13
    store.save(saved)
    runtime = WorldRuntime(store)
    await runtime.start()
    try:
        restored = runtime.get(saved.id)
        assert restored.day == 13
        assert not restored.running
        assert not store.load_all()[0].running
    finally:
        await runtime.close()


async def test_concurrent_commands_keep_every_committed_step(runtime):
    world = await runtime.create(WorldConfig(seed=1))
    await asyncio.gather(
        *[runtime.control(world.id, WorldControl(action="step")) for _ in range(8)]
    )
    saved = runtime.store.load_all()[0]
    assert runtime.get(world.id).day == 9
    assert saved.day == 9
    assert saved.revision == 9


async def test_failed_save_does_not_change_live_world(runtime, monkeypatch):
    world = await runtime.create(WorldConfig(seed=1))

    def fail(_world):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(runtime.store, "save", fail)
    with pytest.raises(HTTPException) as error:
        await runtime.control(world.id, WorldControl(action="step"))
    assert error.value.status_code == 503
    assert runtime.get(world.id) == world


async def test_auto_clock_pauses_and_exposes_storage_errors(runtime, monkeypatch):
    world = await runtime.create(WorldConfig(seed=1))
    await runtime.control(world.id, WorldControl(action="start"))
    before = runtime.get(world.id)

    def fail(_world):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(runtime.store, "save", fail)
    await runtime._tick_due(runtime._next_ticks[world.id] + 1)

    paused = runtime.get(world.id)
    assert not paused.running
    assert paused.day == before.day
    assert paused.last_error


@pytest.fixture
def ai_client(monkeypatch):
    client = MagicMock(spec=LLMClient)
    client.complete = AsyncMock(return_value="A chronicle grounded in the saved events.")
    client.close = AsyncMock()
    client.get_cost_summary.return_value = {
        "total_tokens_in": 20,
        "total_tokens_out": 15,
        "total_cost_usd": 0.0001,
    }
    monkeypatch.setattr(world_runtime, "validate_provider_config", lambda: None)
    monkeypatch.setattr(world_runtime, "create_client", lambda: client)
    return client


async def test_ai_adds_a_snapshot_chronicle_without_overwriting_newer_days(runtime, ai_client):
    world = await runtime.create(WorldConfig(seed=1))

    async def complete(*args, **kwargs):
        await runtime.control(world.id, WorldControl(action="step"))
        return "A chronicle for the first day."

    ai_client.complete.side_effect = complete
    updated = await runtime.ask_ai(world.id)

    assert updated.day == 2
    assert updated.ai_entries[-1].day == 1
    assert updated.ai_entries[-1].text == "A chronicle for the first day."
    assert updated.ai_entries[-1].tokens_in == 20
    assert len(updated.npcs) == len(world.npcs)
    ai_client.close.assert_awaited_once()


async def test_ai_budget_failure_closes_client_and_does_not_invent_an_answer(runtime, ai_client):
    world = await runtime.create(WorldConfig(seed=1))
    ai_client.complete.side_effect = BudgetExceededError("test budget")

    with pytest.raises(HTTPException) as error:
        await runtime.ask_ai(world.id)

    assert error.value.status_code == 402
    assert runtime.get(world.id).ai_entries == []
    ai_client.close.assert_awaited_once()


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "novels.db")
    monkeypatch.setattr(
        main, "WorldRuntime", lambda: WorldRuntime(WorldStore(tmp_path / "worlds.db"))
    )
    monkeypatch.setattr(main, "_rate_limit_store", {})
    with TestClient(main.app) as client:
        yield client


def test_world_page_and_rules_work_without_model_credentials(web_client):
    assert web_client.get("/world").status_code == 200
    assert "/world" in web_client.get("/").text
    capabilities = web_client.get("/api/worlds/capabilities").json()
    assert capabilities["ai_configured"] is False

    response = web_client.post("/api/worlds", json={"name": "Test world", "seed": 12})
    assert response.status_code == 201
    world = response.json()
    world_id = world["id"]
    assert len(world["npcs"]) == 9
    assert len(world["regions"]) == 6
    changed = web_client.post(f"/api/worlds/{world_id}/control", json={"action": "step"})
    assert changed.json()["day"] == 2
    rain = web_client.post(
        f"/api/worlds/{world_id}/intervene",
        json={"kind": "rain", "region_id": world["regions"][0]["id"]},
    )
    assert rain.status_code == 200
    assert rain.json()["events"][-1]["kind"] == "intervention"
    assert web_client.post(f"/api/worlds/{world_id}/chronicle").status_code == 503
    assert web_client.get("/api/history").json() == []
    assert web_client.delete(f"/api/worlds/{world_id}").status_code == 204
    assert web_client.get(f"/api/worlds/{world_id}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"seed": -1},
        {"interval_seconds": 0},
    ],
)
def test_create_rejects_invalid_world_settings(web_client, payload):
    assert web_client.post("/api/worlds", json=payload).status_code == 422
    assert web_client.get("/api/worlds").json() == []


def test_invalid_interventions_do_not_change_world_and_running_world_cannot_step(web_client):
    world = web_client.post("/api/worlds", json={"seed": 12}).json()
    world_id = world["id"]
    invalid = web_client.post(
        f"/api/worlds/{world_id}/intervene",
        json={"kind": "rain", "region_id": "missing"},
    )
    assert invalid.status_code == 400
    assert web_client.get(f"/api/worlds/{world_id}").json()["revision"] == world["revision"]
    started = web_client.post(
        f"/api/worlds/{world_id}/control",
        json={"action": "start", "interval_seconds": 3},
    )
    assert started.json()["running"]
    assert (
        web_client.post(
            f"/api/worlds/{world_id}/control",
            json={"action": "step"},
        ).status_code
        == 409
    )
    assert (
        web_client.post(
            f"/api/worlds/{world_id}/control",
            json={"action": "pause"},
        ).json()["running"]
        is False
    )


def test_novel_generation_reports_missing_model_configuration(web_client):
    response = web_client.post(
        "/api/generate",
        json={
            "genre": "fantasy",
            "core_pleasure": "growth",
            "protagonist_name": "Hero",
            "protagonist_background": "An apprentice",
            "golden_finger": "A library",
        },
    )
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


async def test_living_world_resumes_after_restart_without_fabricating_offline_days(tmp_path):
    store = WorldStore(tmp_path / "living.db")
    first = WorldRuntime(store)
    await first.start()
    world = await first.create(WorldConfig(seed=42, ruleset="living"))
    await first.control(world.id, WorldControl(action="start", interval_seconds=5))
    await first.close()
    assert store.load_all()[0].running
    restored = WorldRuntime(store)
    await restored.start()
    try:
        assert restored.get(world.id).running
        assert restored.get(world.id).day == 1
        await restored._tick_due(restored._next_ticks[world.id] + 0.1)
        assert restored.get(world.id).day == 2
    finally:
        await restored.close()


async def test_old_world_json_keeps_classic_rules_and_can_still_advance(tmp_path):
    store = WorldStore(tmp_path / "old.db")
    store.initialize()
    old = create_world(WorldConfig(seed=17))
    payload = old.model_dump()
    for key in ("ruleset", "roads", "river_level", "ledger"):
        payload.pop(key)
    for person in payload["npcs"]:
        person.pop("life")
    for region in payload["regions"]:
        region.pop("market")
        region.pop("reserves")
    for event in payload["events"]:
        event.pop("cause_ids")
        event.pop("effects")
    with closing(sqlite3.connect(store.path)) as conn:
        conn.execute("INSERT INTO worlds (id, state) VALUES (?, ?)", (old.id, json.dumps(payload)))
        conn.commit()
    restored = WorldRuntime(store)
    await restored.start()
    try:
        updated = await restored.control(old.id, WorldControl(action="step"))
        assert updated.ruleset == "classic"
        assert updated.day == 2
        assert len(updated.npcs) == 9
        assert updated.ledger is None
    finally:
        await restored.close()


async def test_archive_survives_the_recent_window_and_paginates_without_duplicates(runtime):
    world = await runtime.create(WorldConfig(seed=42, ruleset="living"))
    pending = runtime.get(world.id)
    opening_id = pending.events[0].id
    for index in range(230):
        record_event(pending, "test", f"Fact {index}", "A committed fact.", npc_id=pending.npcs[0].id)
    runtime._commit(pending)
    assert len(runtime.get(world.id).events) == 200
    assert runtime.event(world.id, opening_id).kind == "origin"
    ids = []
    before = None
    while True:
        page = runtime.history(world.id, before=before, limit=37)
        ids.extend(event.id for event in page.events)
        if not page.has_more:
            break
        before = page.next_before
    assert len(ids) == len(set(ids)) == pending.next_event_id - 1
    assert ids == sorted(ids, reverse=True)
    assert len(runtime.history(world.id, npc_id=pending.npcs[0].id, limit=100).events) == 100
    await runtime.delete(world.id)
    assert runtime.store.event(world.id, opening_id) is None


async def test_archive_failure_rolls_back_both_snapshot_and_facts(runtime):
    world = await runtime.create(WorldConfig(seed=42, ruleset="living"))
    with closing(sqlite3.connect(runtime.store.path)) as conn:
        conn.execute("""
            CREATE TRIGGER reject_new_facts BEFORE INSERT ON world_events
            WHEN NEW.event_id > 2 BEGIN
                SELECT RAISE(ABORT, 'archive unavailable');
            END
        """)
        conn.commit()
    with pytest.raises(HTTPException) as error:
        await runtime.control(world.id, WorldControl(action="step"))
    assert error.value.status_code == 503
    assert runtime.get(world.id) == world
    assert runtime.store.load_all()[0] == world
    assert not runtime.history(world.id, before=3).has_more


async def test_invalid_rule_result_pauses_auto_clock_without_committing(runtime, monkeypatch):
    world = await runtime.create(WorldConfig(seed=42, ruleset="living"))
    await runtime.control(world.id, WorldControl(action="start"))

    def invalid(_world):
        raise ValueError("unbalanced inventory")

    monkeypatch.setattr(world_runtime, "advance_world", invalid)
    await runtime._tick_due(runtime._next_ticks[world.id] + 1)
    failed = runtime.get(world.id)
    assert failed.day == 1
    assert not failed.running
    assert "规则校验失败" in failed.last_error


async def test_living_dialogue_uses_personal_memories_not_other_peoples_secrets(runtime, ai_client):
    world = await runtime.create(WorldConfig(seed=42, ruleset="living"))
    current = runtime._worlds[world.id]
    person = current.npcs[0]
    person.life.memories.append(
        WorldMemory(event_id=1, day=1, kind="observation", subject_id="farm",
                    detail="LOCAL_MEMORY_ONLY")
    )
    record_event(current, "secret", "Secret elsewhere", "REMOTE_SECRET_NOT_KNOWN",
                 region_id="ruins", npc_id=current.npcs[-1].id)
    runtime._commit(current)
    await runtime.ask_ai(world.id, WorldChatRequest(npc_id=person.id, question="What do you know?"))
    prompt = ai_client.complete.call_args.args[0]
    assert "LOCAL_MEMORY_ONLY" in prompt
    assert "REMOTE_SECRET_NOT_KNOWN" not in prompt
    ai_client.close.assert_awaited_once()


def test_living_world_api_exposes_fact_history_and_rejects_invalid_paging(web_client):
    world = web_client.post("/api/worlds", json={"seed": 42, "ruleset": "living"}).json()
    assert len(world["npcs"]) == 30
    assert world["ledger"]["initial_money"] > 0
    base = f"/api/worlds/{world['id']}"
    assert web_client.post(f"{base}/control", json={"action": "step"}).status_code == 200
    page = web_client.get(f"{base}/events", params={"limit": 1}).json()
    assert page["has_more"]
    assert len(page["events"]) == 1
    assert web_client.get(f"{base}/events/1").json()["kind"] == "origin"
    assert web_client.get(f"{base}/events/999999").status_code == 404
    assert web_client.get(f"{base}/events", params={"limit": 101}).status_code == 422
    assert web_client.get(f"{base}/events", params={"before": 0}).status_code == 422
