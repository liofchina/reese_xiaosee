import pytest

from domain.living_world import BRIDGE_ID, _move, _repair, life_of, route_for
from domain.world_simulation import advance_world, create_world, intervene_world
from models.world import (
    WorldConfig,
    WorldGoods,
    WorldIntervention,
    WorldLedger,
    WorldMemory,
    WorldRoadKnowledge,
    WorldState,
)


def living_world(seed=42):
    return create_world(WorldConfig(name="Causal test", seed=seed, ruleset="living"))


def reset_opening_ledger(world):
    stocks = [region.reserves for region in world.regions]
    stocks.extend(region.market.stock for region in world.regions)
    stocks.extend(life_of(npc).inventory for npc in world.npcs)
    stocks.extend(road.materials for road in world.roads)
    world.ledger = WorldLedger(
        initial_goods=WorldGoods.total(stocks),
        initial_money=(
            sum(region.market.coins for region in world.regions)
            + sum(life_of(npc).coins for npc in world.npcs)
            + sum(faction.wealth for faction in world.factions)
            + sum(road.repair_budget for road in world.roads)
        ),
    )


@pytest.mark.parametrize("seed", [17, 42])
def test_living_world_replays_and_keeps_material_and_money_accounts(seed):
    first, second = living_world(seed), living_world(seed)
    initial = first.model_dump()
    before = first
    for _ in range(40):
        first = advance_world(first)
        second = advance_world(second)
    assert first.npcs == second.npcs
    assert first.regions == second.regions
    assert first.roads == second.roads
    assert first.events == second.events
    assert before.model_dump() == initial
    assert first.ledger.initial_money == before.ledger.initial_money
    assert first.ledger.produced.food > 0
    assert first.ledger.consumed.food > 0
    WorldState.model_validate(first.model_dump())


def test_a_farmer_moves_existing_crop_into_inventory_instead_of_minting_wealth():
    world = living_world()
    farmer = world.npcs[0]
    world.npcs = [farmer]
    reset_opening_ledger(world)
    coins = life_of(farmer).coins
    initial_food = life_of(farmer).inventory.food
    changed = advance_world(world)
    person = changed.npcs[0]
    assert life_of(person).inventory.food == initial_food - 1 + 6
    assert life_of(person).coins == coins
    assert changed.ledger.consumed.food == 1
    assert any(event.kind == "production" and event.npc_id == farmer.id for event in changed.events)


def test_a_purchase_has_a_real_counterparty_and_does_not_create_coins():
    world = living_world()
    npc = next(person for person in world.npcs if life_of(person).profession == "guard")
    world.npcs = [npc]
    life_of(npc).inventory.food = 1
    reset_opening_ledger(world)
    before_coins = life_of(npc).coins
    region = next(region for region in world.regions if region.id == npc.region_id)
    before_stock, before_cash = region.market.stock.food, region.market.coins
    changed = advance_world(world)
    market = next(region.market for region in changed.regions if region.id == npc.region_id)
    buyer = life_of(changed.npcs[0])
    assert buyer.inventory.food > 0
    assert buyer.coins < before_coins
    assert market.stock.food == before_stock - buyer.inventory.food
    assert market.coins - before_cash == before_coins - buyer.coins
    assert changed.ledger.initial_money == world.ledger.initial_money


def test_recent_flood_memory_changes_a_route_under_identical_physical_conditions():
    world = living_world()
    npc = world.npcs[0]
    life = life_of(npc)
    life.risk_tolerance = 0
    bridge = next(road for road in world.roads if road.id == BRIDGE_ID)
    bridge.ford_until_day = 20
    life.known_roads[BRIDGE_ID] = WorldRoadKnowledge(
        passable=True, day=1, travel_days=2
    )
    direct = route_for(world, npc, "city")
    assert BRIDGE_ID in [road.id for road in direct]
    life.memories.append(
        WorldMemory(event_id=1, day=1, kind="flood", subject_id=BRIDGE_ID,
                    detail="A witnessed flood, not global knowledge.")
    )
    cautious = route_for(world, npc, "city")
    assert BRIDGE_ID not in [road.id for road in cautious]


def test_travel_uses_persisted_time_instead_of_teleporting():
    world = living_world()
    npc = world.npcs[0]
    npc.region_id = "city"
    life_of(npc).inventory.food = 10
    reset_opening_ledger(world)
    assert _move(world, npc, "mine")
    assert life_of(npc).journey.total_days == 3
    person_id = npc.id
    for remaining in (2, 1):
        world = advance_world(world)
        person = next(person for person in world.npcs if person.id == person_id)
        assert person.region_id == "city"
        assert life_of(person).journey.remaining_days == remaining
    world = advance_world(world)
    assert next(person for person in world.npcs if person.id == person_id).region_id == "mine"


def test_builders_complete_a_real_bridge_and_consume_materials():
    world = living_world()
    completion = None
    for _ in range(30):
        world = advance_world(world)
        completion = next(
            (event for event in world.pending_events if event.title == "汀川石桥重新通行"), None
        )
        if completion:
            break
    assert completion is not None
    bridge = next(road for road in world.roads if road.id == BRIDGE_ID)
    assert bridge.integrity == 100
    assert world.ledger.consumed.wood >= 12
    assert world.ledger.consumed.ore >= 4
    assert completion.cause_ids


def test_a_builder_without_money_collects_material_at_the_source_before_returning():
    world = living_world()
    builder = next(person for person in world.npcs if life_of(person).profession == "builder")
    builder.region_id = "forest"
    life_of(builder).coins = 0
    reset_opening_ledger(world)
    forest = next(region for region in world.regions if region.id == "forest")
    before = forest.reserves.wood
    assert _repair(world, builder)
    assert life_of(builder).inventory.wood == 4
    assert forest.reserves.wood == before - 4
    assert life_of(builder).journey is None
    WorldState.model_validate(world.model_dump())


def test_a_farmer_does_not_change_the_same_unworkable_plan_twice_every_day():
    world = living_world()
    farmer = world.npcs[0]
    world.npcs = [farmer]
    life_of(farmer).inventory.food = 15
    farm = next(region for region in world.regions if region.id == "farm")
    farm.market.coins = 0
    reset_opening_ledger(world)
    resting = advance_world(world)
    continued = advance_world(resting)
    assert life_of(continued.npcs[0]).plan.kind == "rest"
    assert not any(
        event.kind == "decision" and event.npc_id == farmer.id
        for event in continued.pending_events
    )


def test_a_distant_budget_change_is_not_immediately_known_to_a_builder():
    world = living_world()
    builder = next(person for person in world.npcs if life_of(person).profession == "builder")
    builder.region_id = "forest"
    bridge = next(road for road in world.roads if road.id == BRIDGE_ID)
    world.factions[0].wealth += bridge.repair_budget
    bridge.repair_budget = 0
    assert _repair(world, builder)
    assert life_of(builder).inventory.wood > 0
    assert bridge.repair_budget == 0
    WorldState.model_validate(world.model_dump())


def test_a_destroyed_crossing_forces_a_timed_return_not_an_instant_arrival():
    world = living_world()
    builder = next(person for person in world.npcs if life_of(person).profession == "builder")
    builder.region_id = "city"
    bridge = next(road for road in world.roads if road.id == BRIDGE_ID)
    bridge.integrity = 100
    life_of(builder).known_roads[BRIDGE_ID] = WorldRoadKnowledge(passable=True, day=1)
    assert _move(world, builder, "ferry")
    flooded = intervene_world(world, WorldIntervention(kind="flood", region_id="city"))
    changed = advance_world(flooded)
    person = next(person for person in changed.npcs if person.id == builder.id)
    assert person.region_id == "city"
    assert life_of(person).journey.returning
    assert life_of(person).journey.remaining_days == 1
    assert any(memory.kind == "flood" for memory in life_of(person).memories)


def test_channeling_consumes_real_material_and_changes_crossing_rules():
    world = living_world()
    npc = next(person for person in world.npcs if life_of(person).profession == "scholar")
    world.npcs = [npc]
    npc.region_id = "ferry"
    life = life_of(npc)
    life.ability = "watercourse"
    life.inventory.food = 10
    life.inventory.ore = 2
    life.known_roads[BRIDGE_ID] = WorldRoadKnowledge(passable=False, day=1)
    npc.energy = 90
    reset_opening_ledger(world)
    changed = advance_world(world)
    person = changed.npcs[0]
    bridge = next(road for road in changed.roads if road.id == BRIDGE_ID)
    assert life_of(person).inventory.ore == 0
    assert changed.ledger.consumed.ore == 2
    assert person.energy == 59
    assert bridge.integrity == 0
    assert bridge.ford_until_day == changed.day + 3
    assert any(event.kind == "power" for event in changed.pending_events)


def test_death_stops_actions_without_deleting_the_person_or_their_property():
    world = living_world()
    npc = world.npcs[0]
    life_of(npc).lifespan_days = life_of(npc).age_days + 1
    original_inventory = life_of(npc).inventory.model_copy(deep=True)
    changed = advance_world(world)
    dead = next(person for person in changed.npcs if person.id == npc.id)
    assert life_of(dead).health == 0
    assert life_of(dead).inventory == original_inventory
    assert life_of(dead).died_on == changed.day
    after = advance_world(changed)
    assert not any(event.npc_id == npc.id for event in after.pending_events)


def test_living_interventions_transfer_existing_budget_and_reject_free_stat_bonuses():
    world = living_world()
    changed = intervene_world(
        world, WorldIntervention(kind="repair_contract", region_id="city")
    )
    assert changed.factions[0].wealth == world.factions[0].wealth - 40
    assert changed.roads[0].repair_budget == world.roads[0].repair_budget + 40
    assert changed.ledger.initial_money == world.ledger.initial_money
    for kind in ("rain", "market", "enlightenment"):
        with pytest.raises(ValueError, match="直接增加"):
            intervene_world(world, WorldIntervention(kind=kind, region_id="city"))
    classic = create_world(WorldConfig(seed=42))
    with pytest.raises(ValueError, match="因果世界"):
        intervene_world(classic, WorldIntervention(kind="flood", region_id="qinglan"))
