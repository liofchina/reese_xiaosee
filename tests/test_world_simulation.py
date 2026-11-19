import random

import pytest

from core.world_store import WorldStore
from domain import world_simulation
from domain.world_simulation import MAX_WORLD_EVENTS, advance_world, create_world, intervene_world
from models.world import REALM_NAMES, WorldConfig, WorldIntervention, WorldState


def test_seeded_world_replays_without_mutating_previous_snapshots():
    first = create_world(WorldConfig(name="Test world", seed=0))
    second = create_world(WorldConfig(name="Test world", seed=0))
    initial = first
    original = first.model_dump()

    for _ in range(20):
        first = advance_world(first)
        second = advance_world(second)

    assert first.seed == 0
    assert first.day == 21
    assert first.npcs == second.npcs
    assert first.regions == second.regions
    assert first.factions == second.factions
    assert first.events == second.events
    assert original["day"] == 1
    assert initial.model_dump() == original
    assert original["npcs"] != first.model_dump()["npcs"]


@pytest.mark.parametrize("seed", [17, 8901])
def test_long_running_world_keeps_bounds_routes_and_recent_history(seed):
    world = create_world(WorldConfig(seed=seed))
    for _ in range(100):
        previous = world
        world = advance_world(world)
        regions = {region.id: region for region in previous.regions}
        people = {npc.id: npc for npc in previous.npcs}
        for npc in world.npcs:
            before = people[npc.id]
            if npc.region_id != before.region_id:
                assert npc.region_id in regions[before.region_id].neighbors
        WorldState.model_validate(world.model_dump())

    ids = [event.id for event in world.events]
    assert len(ids) == MAX_WORLD_EVENTS
    assert ids == sorted(set(ids))
    assert world.events[-1].day == world.day
    assert any(npc.realm > 0 for npc in world.npcs)


def test_idle_regions_lose_prosperity_without_going_below_zero():
    world = create_world(WorldConfig(seed=42))
    world.regions[0].prosperity = 100
    world.regions[1].prosperity = 0
    for npc in world.npcs:
        npc.energy = 0

    changed = advance_world(world)

    assert 0 < changed.regions[0].prosperity < 100
    assert changed.regions[1].prosperity == 0
    assert world.regions[0].prosperity == 100


def test_merchants_can_choose_cultivation(monkeypatch):
    world = create_world(WorldConfig(seed=42))
    merchant = next(npc for npc in world.npcs if npc.trait == "经商")
    world.npcs = [merchant]
    merchant.realm = 1
    merchant.cultivation = 0
    merchant.energy = 100
    region = next(region for region in world.regions if region.id == merchant.region_id)
    region.spirit = 100

    class CultivatingRandom(random.Random):
        def choice(self, values):
            return "cultivate" if "cultivate" in values else values[0]

    monkeypatch.setattr(world_simulation.random, "Random", CultivatingRandom)
    changed = advance_world(world)

    assert changed.npcs[0].cultivation > 0
    assert merchant.cultivation == 0


@pytest.mark.parametrize("seed", [17, 8901])
def test_long_running_economy_stays_active_and_merchants_can_grow(seed):
    world = create_world(WorldConfig(seed=seed))
    initial_realms = {npc.id: npc.realm for npc in world.npcs if npc.trait == "经商"}
    recent_prosperity = []
    for _ in range(365):
        world = advance_world(world)
        if world.day > 335:
            recent_prosperity.extend(region.prosperity for region in world.regions)

    mean_prosperity = sum(recent_prosperity) / len(recent_prosperity)
    assert 10 < mean_prosperity < 90
    assert all(
        npc.realm > initial_realms[npc.id]
        for npc in world.npcs
        if npc.id in initial_realms
    )


def test_enlightenment_crosses_realm_threshold_but_never_exceeds_final_realm():
    world = create_world(WorldConfig(seed=4))
    world.npcs[0].realm = 1
    world.npcs[0].cultivation = 98
    world.npcs[1].realm = len(REALM_NAMES) - 1
    world.npcs[1].cultivation = 99

    changed = intervene_world(world, WorldIntervention(kind="enlightenment"))

    assert changed.day == world.day
    assert changed.npcs[0].realm == 2
    assert changed.npcs[0].cultivation == 6
    assert changed.npcs[1].realm == len(REALM_NAMES) - 1
    assert changed.npcs[1].cultivation == 99
    assert world.npcs[0].realm == 1
    assert changed.events[-1].kind == "intervention"


@pytest.mark.parametrize(("kind", "field"), [("rain", "spirit"), ("market", "prosperity")])
def test_regional_intervention_is_bounded_and_local(kind, field):
    world = create_world(WorldConfig(seed=12))
    setattr(world.regions[0], field, 96)
    unchanged_region = world.regions[1].model_copy(deep=True)
    changed = intervene_world(world, WorldIntervention(kind=kind, region_id=world.regions[0].id))

    assert getattr(changed.regions[0], field) == 100
    assert changed.regions[1] == unchanged_region
    assert getattr(world.regions[0], field) == 96
    with pytest.raises(ValueError, match="有效地点"):
        intervene_world(world, WorldIntervention(kind=kind, region_id="missing"))


def test_factions_spend_real_reserves_on_public_works():
    world = create_world(WorldConfig(seed=15))
    world.day = 2
    for person in world.npcs:
        person.energy = 0
    wealth = {faction.id: faction.wealth for faction in world.factions}
    changed = advance_world(world)

    for faction in changed.factions:
        assert faction.wealth == wealth[faction.id] - 12
    assert len([event for event in changed.events if event.kind == "faction"]) == 3


def test_faction_presence_can_change_a_region_owner(monkeypatch):
    world = create_world(WorldConfig(seed=15))
    world.day = 3
    for person in world.npcs:
        person.region_id = world.regions[0].id
        person.faction_id = "yunshang"
        person.trait = "修炼"
        person.energy = 100
    world.regions[0].spirit = 100

    class CalmRandom(random.Random):
        def choice(self, values):
            return values[0]

    monkeypatch.setattr(world_simulation.random, "Random", CalmRandom)
    changed = advance_world(world)

    assert world.regions[0].owner_id == "lingxiao"
    assert changed.regions[0].owner_id == "yunshang"
    assert any(event.kind == "faction" for event in changed.events)


def test_world_store_round_trips_updates_and_deletes_only_one_world(tmp_path):
    path = tmp_path / "nested" / "worlds.db"
    store = WorldStore(path)
    store.initialize()
    first = create_world(WorldConfig(seed=11))
    second = create_world(WorldConfig(seed=12))
    store.save(first)
    store.save(second)
    updated = advance_world(first)
    store.save(updated)

    restored = {world.id: world for world in WorldStore(path).load_all()}
    assert restored[first.id] == updated
    assert restored[second.id] == second
    store.delete(first.id)
    assert [world.id for world in store.load_all()] == [second.id]
    moved = path.with_suffix(".moved")
    path.rename(moved)
    moved.replace(path)
