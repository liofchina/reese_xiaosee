import heapq
import random
import secrets
import uuid
from datetime import datetime, timezone

from domain.world_events import record_event, touch_world
from models.world import (
    GOOD_NAMES,
    WORLD_GOODS,
    NPCTrait,
    WorldConfig,
    WorldEffect,
    WorldEvent,
    WorldFaction,
    WorldGood,
    WorldGoods,
    WorldIntervention,
    WorldJourney,
    WorldLedger,
    WorldLife,
    WorldMarket,
    WorldMarketKnowledge,
    WorldMemory,
    WorldNPC,
    WorldPlan,
    WorldPlanKind,
    WorldProfession,
    WorldRegion,
    WorldRoad,
    WorldRoadKnowledge,
    WorldState,
)

BRIDGE_ID = "river_bridge"
REPAIR_WOOD = 12
REPAIR_ORE = 4
REPAIR_WORK = 12


def life_of(npc: WorldNPC) -> WorldLife:
    if npc.life is None:
        raise ValueError(f"{npc.name} 缺少生活状态")
    return npc.life


def market_of(region: WorldRegion) -> WorldMarket:
    if region.market is None:
        raise ValueError(f"{region.name} 缺少市场")
    return region.market


def _ledger(world: WorldState) -> WorldLedger:
    if world.ledger is None:
        raise ValueError("因果世界缺少物资账本")
    return world.ledger


def _region(world: WorldState, region_id: str) -> WorldRegion:
    return next(region for region in world.regions if region.id == region_id)


def _bridge(world: WorldState) -> WorldRoad:
    return next(road for road in world.roads if road.id == BRIDGE_ID)


def road_passable(road: WorldRoad, day: int) -> bool:
    return road.integrity > 0 or day <= road.ford_until_day


def _road_days(road: WorldRoad) -> int:
    return road.travel_days + (1 if road.integrity == 0 else 0)


def _effect(subject: str, field: str, before: int | str, after: int | str) -> WorldEffect:
    return WorldEffect(subject_id=subject, field=field, before=before, after=after)


def _remember(
    npc: WorldNPC, event: WorldEvent, kind: str, subject: str, source: str | None = None
) -> None:
    life = life_of(npc)
    if any(memory.event_id == event.id for memory in life.memories):
        return
    life.memories.append(
        WorldMemory(
            event_id=event.id,
            day=event.day,
            kind=kind,
            subject_id=subject,
            detail=event.detail,
            source_id=source,
        )
    )
    del life.memories[:-16]


def _plan(
    world: WorldState,
    npc: WorldNPC,
    kind: WorldPlanKind,
    target: str,
    reason: str,
    causes: list[int] | None = None,
) -> None:
    life = life_of(npc)
    if (
        life.plan is not None
        and life.plan.kind == kind
        and life.plan.target_id == target
        and life.plan.reason == reason
        and life.plan.cause_ids == (causes or [])
    ):
        return
    life.plan = WorldPlan(
        kind=kind,
        target_id=target,
        reason=reason,
        since_day=world.day,
        cause_ids=causes or [],
    )
    event = record_event(
        world,
        "decision",
        f"{npc.name}重新安排打算",
        reason,
        npc.region_id,
        npc.id,
        cause_ids=causes,
    )
    npc.last_action = reason
    if causes:
        _remember(npc, event, "decision", target)


def _prices(world: WorldState) -> None:
    for region in world.regions:
        market = market_of(region)
        residents = sum(
            1
            for npc in world.npcs
            if life_of(npc).health > 0 and life_of(npc).home_region_id == region.id
        )
        target = max(12, residents * 5)
        food = market.stock.food
        market.prices.food = (
            9 if food < target // 3 else 5 if food < target else 3 if food < target * 2 else 1
        )
        market.prices.wood = 6 if market.stock.wood < 8 else 3 if market.stock.wood < 24 else 1
        market.prices.ore = 9 if market.stock.ore < 4 else 5 if market.stock.ore < 12 else 2
        region.prosperity = min(100, food * 100 // target)


def create_living_world(config: WorldConfig) -> WorldState:
    seed = config.seed if config.seed is not None else secrets.randbits(31)
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).isoformat()
    places = [
        ("city", "汀川城", "城镇", 34, 57, "council", 24, 18, 8, 320, WorldGoods()),
        ("farm", "东岸田庄", "农田", 77, 29, "commons", 100, 4, 0, 180, WorldGoods(food=180)),
        ("forest", "雾松林", "林地", 55, 17, "commons", 24, 12, 0, 120, WorldGoods(wood=180)),
        ("mine", "玄石矿", "矿山", 24, 25, "commons", 18, 2, 12, 120, WorldGoods(ore=240)),
        ("ruins", "旧观测所", "遗迹", 80, 68, "commons", 12, 2, 4, 80, WorldGoods()),
        ("ferry", "折潮渡", "河岸", 60, 46, "council", 24, 4, 2, 160, WorldGoods()),
        ("workshop", "南岭工坊", "工坊", 28, 81, "council", 26, 12, 8, 180, WorldGoods()),
    ]
    descriptions = {
        "city": "仓廪与街市聚于西岸。粮食、木材和矿石都要由真实的人沿道路运来。",
        "farm": "东岸的田地随季节生长。丰年需要储粮，冬季的产出远少于夏季。",
        "forest": "树木恢复缓慢，砍伐取得的木材可运往工坊与桥梁工地。",
        "mine": "可开采的矿石有限；它既是修桥材料，也是研究和引流术的消耗品。",
        "ruins": "残存的观测记录描述水流的规律。研究需要时间、矿石与持续的口粮。",
        "ferry": "断桥的东端。引流可以形成短暂浅滩，长久通行仍要依靠工程。",
        "workshop": "工匠在这里落脚。他们会在报酬、口粮与公共工程之间安排自己的计划。",
    }
    regions = [
        WorldRegion(
            id=rid,
            name=name,
            terrain=terrain,
            description=descriptions[rid],
            x=x,
            y=y,
            owner_id=owner,
            spirit=60,
            prosperity=50,
            danger=10,
            neighbors=[],
            market=WorldMarket(stock=WorldGoods(food=food, wood=wood, ore=ore), coins=coins),
            reserves=reserves,
        )
        for rid, name, terrain, x, y, owner, food, wood, ore, coins, reserves in places
    ]
    roads = [
        WorldRoad(
            id=BRIDGE_ID,
            name="汀川石桥",
            origin_id="city",
            destination_id="ferry",
            travel_days=1,
            bridge=True,
            integrity=0,
            repair_budget=100,
        ),
        WorldRoad(
            id="east_path", name="东岸田埂", origin_id="ferry", destination_id="farm", travel_days=1
        ),
        WorldRoad(
            id="forest_path",
            name="松林小径",
            origin_id="farm",
            destination_id="forest",
            travel_days=1,
        ),
        WorldRoad(
            id="north_ridge",
            name="北岭栈道",
            origin_id="forest",
            destination_id="mine",
            travel_days=2,
        ),
        WorldRoad(
            id="mine_road", name="运矿山路", origin_id="mine", destination_id="city", travel_days=3
        ),
        WorldRoad(
            id="ruins_path",
            name="旧观测道",
            origin_id="ferry",
            destination_id="ruins",
            travel_days=2,
        ),
        WorldRoad(
            id="workshop_road",
            name="南岭大道",
            origin_id="city",
            destination_id="workshop",
            travel_days=1,
        ),
        WorldRoad(
            id="south_detour",
            name="南岭远道",
            origin_id="workshop",
            destination_id="ruins",
            travel_days=3,
        ),
    ]
    by_id = {region.id: region for region in regions}
    for road in roads:
        by_id[road.origin_id].neighbors.append(road.destination_id)
        by_id[road.destination_id].neighbors.append(road.origin_id)
    factions = [
        WorldFaction(
            id="council",
            name="汀川议事会",
            color="#86cbb2",
            philosophy="征收交易税，以有限的公库承担守卫、救济与工程。",
            influence=100,
            wealth=300,
        ),
        WorldFaction(
            id="commons",
            name="渡川同盟",
            color="#e7bd73",
            philosophy="农人、矿工与行旅互通消息，依靠生产和交换维持生计。",
            influence=100,
            wealth=400,
        ),
    ]
    names = [
        "叶禾",
        "周粟",
        "林穗",
        "苏芩",
        "沈稻",
        "陆蓁",
        "许青",
        "江芜",
        "温桐",
        "顾栖",
        "陶谷",
        "宋苗",
        "秦樵",
        "唐松",
        "白榆",
        "柳梢",
        "石砚",
        "陈铸",
        "方朔",
        "梁衡",
        "何筑",
        "季安",
        "谢舟",
        "程渡",
        "孟遥",
        "邵行",
        "罗川",
        "韩宁",
        "闻溪",
        "晏知",
    ]
    role_groups: list[tuple[WorldProfession, str, NPCTrait, str, int]] = [
        ("farmer", "farm", "守护", "备足口粮，让田庄度过下一次冬季", 12),
        ("woodcutter", "forest", "探索", "把木材换成安稳的生活", 4),
        ("miner", "mine", "探索", "靠开矿积累可以自由选择去处的积蓄", 3),
        ("builder", "city", "守护", "修通汀川石桥，凭手艺维持生计", 2),
        ("builder", "workshop", "守护", "修通汀川石桥，凭手艺维持生计", 1),
        ("merchant", "farm", "经商", "沿真实的商路运送紧缺物资", 1),
        ("merchant", "city", "经商", "沿真实的商路运送紧缺物资", 1),
        ("merchant", "forest", "经商", "沿真实的商路运送紧缺物资", 1),
        ("merchant", "ferry", "经商", "沿真实的商路运送紧缺物资", 1),
        ("guard", "city", "守护", "守住聚落，也守住自己的口粮", 1),
        ("guard", "ferry", "守护", "守住聚落，也守住自己的口粮", 1),
        ("scholar", "ruins", "修炼", "弄懂旧观测所留下的水流规律", 2),
    ]
    roles: list[tuple[WorldProfession, str, NPCTrait, str]] = []
    for profession, home, trait, goal, count in role_groups:
        roles.extend([(profession, home, trait, goal)] * count)
    npcs = []
    for index, (profession, home, trait, goal) in enumerate(roles):
        life = WorldLife(
            profession=profession,
            home_region_id=home,
            age_days=rng.randint(18 * 365, 60 * 365),
            lifespan_days=rng.randint(70 * 365, 95 * 365),
            coins=rng.randint(28, 50),
            risk_tolerance=rng.randint(20, 85),
            inventory=WorldGoods(
                food=16 if profession == "merchant" else 4, ore=3 if profession == "scholar" else 0
            ),
            cargo_good="food" if profession == "merchant" else None,
            cargo_cost=1,
        )
        npcs.append(
            WorldNPC(
                id=f"person_{index + 1:02d}",
                name=names[index],
                faction_id=by_id[home].owner_id,
                region_id=home,
                trait=trait,
                goal=goal,
                realm=0,
                cultivation=0,
                energy=90,
                mood="平静",
                last_action="清点家当，准备今天的生活。",
                life=life,
            )
        )
    stocks = [region.reserves for region in regions]
    stocks.extend(market_of(region).stock for region in regions)
    stocks.extend(life_of(npc).inventory for npc in npcs)
    stocks.extend(road.materials for road in roads)
    money = (
        sum(faction.wealth for faction in factions)
        + sum(market_of(region).coins for region in regions)
        + sum(life_of(npc).coins for npc in npcs)
        + sum(road.repair_budget for road in roads)
    )
    world = WorldState(
        id=str(uuid.uuid4()),
        name=config.name,
        seed=seed,
        ruleset="living",
        interval_seconds=config.interval_seconds,
        created_at=now,
        updated_at=now,
        regions=regions,
        npcs=npcs,
        factions=factions,
        roads=roads,
        river_level=64,
        ledger=WorldLedger(initial_goods=WorldGoods.total(stocks), initial_money=money),
    )
    _prices(world)
    origin = record_event(
        world,
        "origin",
        "汀川的第一份清册",
        "三十个人带着各自的口粮与积蓄开始生活。自然生长、开采、交换和消耗分别记账，货币总量不凭空增加。",
    )
    bridge_event = record_event(
        world,
        "infrastructure",
        "旧桥还没有修好",
        "开局公示：旧洪水毁坏石桥，议事会预留100枚工程款。商队带有旧账簿，之后的新路况只能靠目击和同行传递。",
        "city",
        cause_ids=[origin.id],
    )
    bridge = _bridge(world)
    bridge.last_event_id = bridge_event.id
    for npc in npcs:
        life = life_of(npc)
        life.known_roads[BRIDGE_ID] = WorldRoadKnowledge(
            passable=False,
            day=0,
            event_id=bridge_event.id,
            integrity=0,
            repair_budget=bridge.repair_budget,
        )
        if life.profession == "merchant":
            for region in regions:
                market = market_of(region)
                life.known_markets[region.id] = WorldMarketKnowledge(
                    day=0,
                    prices=market.prices.model_copy(deep=True),
                    stock=market.stock.model_copy(deep=True),
                    source_id="开市前的商路账簿",
                    coins=market.coins,
                    capacity=_market_capacity(world, region),
                )
        _observe(world, npc)
    return world


def _observe(world: WorldState, npc: WorldNPC) -> None:
    life = life_of(npc)
    market = market_of(_region(world, npc.region_id))
    life.known_markets[npc.region_id] = WorldMarketKnowledge(
        day=world.day,
        prices=market.prices.model_copy(deep=True),
        stock=market.stock.model_copy(deep=True),
        source_id=npc.id,
        coins=market.coins,
        capacity=_market_capacity(world, _region(world, npc.region_id)),
    )
    for road in world.roads:
        if npc.region_id not in (road.origin_id, road.destination_id):
            continue
        passable = road_passable(road, world.day)
        previous = life.known_roads.get(road.id)
        if (previous is None and not passable) or (
            previous is not None and previous.passable != passable
        ):
            event = record_event(
                world,
                "observation",
                f"{npc.name}核实了{road.name}的路况",
                f"{npc.name}在现场看到：{road.name}{'可以通行' if passable else '无法通行'}。这条消息只进入在场者的认知。",
                npc.region_id,
                npc.id,
                cause_ids=[road.last_event_id] if road.last_event_id else [],
            )
            _remember(npc, event, "route", road.id)
        life.known_roads[road.id] = WorldRoadKnowledge(
            passable=passable,
            day=world.day,
            event_id=road.last_event_id,
            travel_days=_road_days(road),
            integrity=road.integrity,
            repair_budget=road.repair_budget,
            materials=road.materials.model_copy(deep=True),
        )
    for other in world.npcs:
        if other.id == npc.id or other.region_id != npc.region_id:
            continue
        source = life_of(other)
        if source.health == 0 or source.journey is not None:
            continue
        for region_id, knowledge in source.known_markets.items():
            known = life.known_markets.get(region_id)
            if known is None or knowledge.day > known.day:
                copy = knowledge.model_copy(deep=True)
                copy.source_id = other.id
                life.known_markets[region_id] = copy
        for road_id, road_knowledge in source.known_roads.items():
            known_road = life.known_roads.get(road_id)
            if known_road is None or road_knowledge.day > known_road.day:
                life.known_roads[road_id] = road_knowledge.model_copy(deep=True)


def route_for(world: WorldState, npc: WorldNPC, destination: str) -> list[WorldRoad] | None:
    if destination == npc.region_id:
        return []
    life = life_of(npc)
    queue: list[tuple[int, str, list[str]]] = [(0, npc.region_id, [])]
    best: dict[str, int] = {}
    roads = {road.id: road for road in world.roads}
    while queue:
        cost, here, path = heapq.heappop(queue)
        if here in best:
            continue
        best[here] = cost
        if here == destination:
            return [roads[road_id] for road_id in path]
        for road in world.roads:
            if here not in (road.origin_id, road.destination_id):
                continue
            knowledge = life.known_roads.get(road.id)
            if knowledge is not None and not knowledge.passable:
                continue
            neighbor = road.destination_id if here == road.origin_id else road.origin_id
            days = knowledge.travel_days if knowledge else road.travel_days
            fear = any(
                memory.kind == "flood"
                and memory.subject_id == road.id
                and world.day - memory.day <= 20
                for memory in life.memories
            )
            penalty = (100 - life.risk_tolerance) // 10 if fear else 0
            heapq.heappush(queue, (cost + days + penalty, neighbor, path + [road.id]))
    return None


def _move(world: WorldState, npc: WorldNPC, destination: str) -> bool:
    life = life_of(npc)
    path = route_for(world, npc, destination)
    if path is None or not path:
        npc.last_action = f"{npc.name}暂时找不到通往目标的已知路线，留在原地重新打算。"
        record_event(
            world, "blocked", f"{npc.name}暂缓出行", npc.last_action, npc.region_id, npc.id
        )
        return False
    road = path[0]
    if not road_passable(road, world.day):
        _observe(world, npc)
        npc.last_action = f"{npc.name}抵达{road.name}入口，发现道路中断，必须另找路线。"
        return False
    target = road.destination_id if road.origin_id == npc.region_id else road.origin_id
    days = _road_days(road)
    life.journey = WorldJourney(
        road_id=road.id, destination_id=target, remaining_days=days, total_days=days
    )
    npc.energy = max(0, npc.energy - 6)
    npc.last_action = (
        f"{npc.name}沿{road.name}前往{_region(world, target).name}，预计{days}日抵达。"
    )
    record_event(
        world,
        "travel",
        f"{npc.name}踏上{road.name}",
        npc.last_action,
        npc.region_id,
        npc.id,
        cause_ids=life.plan.cause_ids if life.plan else [],
    )
    return True


def _die(world: WorldState, npc: WorldNPC, reason: str, causes: list[int] | None = None) -> None:
    life = life_of(npc)
    if life.died_on is not None:
        return
    life.health = 0
    life.died_on = world.day
    life.journey = None
    life.plan = None
    npc.mood = "已逝"
    npc.last_action = f"{npc.name}{reason}。遗留物仍计入世界清册，不凭空消失。"
    event = record_event(
        world,
        "death",
        f"{npc.name}的生命结束",
        npc.last_action,
        npc.region_id,
        npc.id,
        cause_ids=causes,
    )
    for witness in world.npcs:
        if (
            witness.id != npc.id
            and witness.region_id == npc.region_id
            and life_of(witness).health > 0
        ):
            _remember(witness, event, "loss", npc.id)


def _journey(world: WorldState, npc: WorldNPC) -> bool:
    life = life_of(npc)
    journey = life.journey
    if journey is None:
        return False
    road = next(road for road in world.roads if road.id == journey.road_id)
    if not journey.returning and not road_passable(road, world.day):
        journey.returning = True
        journey.remaining_days = min(
            journey.total_days, journey.total_days - journey.remaining_days + 1
        )
        before = life.health
        warned = any(
            life_of(guard).profession == "guard"
            and life_of(guard).health > 0
            and life_of(guard).journey is None
            and guard.energy >= 20
            and guard.region_id in (road.origin_id, road.destination_id)
            for guard in world.npcs
        )
        damage = (2 if warned else 10) if world.river_level > 80 else 0
        life.health = max(0, life.health - damage)
        event = record_event(
            world,
            "danger",
            f"{npc.name}被迫折返",
            f"{road.name}已不能通过，{npc.name}开始返回出发地，损失{before - life.health}点健康。"
            + ("岸边守卫的示警减轻了损伤。" if warned and damage else ""),
            npc.region_id,
            npc.id,
            cause_ids=[road.last_event_id] if road.last_event_id else [],
            effects=[_effect(npc.id, "health", before, life.health)],
        )
        _remember(npc, event, "flood", road.id)
        life.known_roads[road.id] = WorldRoadKnowledge(
            passable=False,
            day=world.day,
            event_id=event.id,
            travel_days=_road_days(road),
            integrity=road.integrity,
        )
        if life.health == 0:
            _die(world, npc, "在断路的险情中身亡", [event.id])
        return True
    journey.remaining_days -= 1
    npc.energy = max(0, npc.energy - 3)
    if journey.remaining_days:
        npc.last_action = f"{npc.name}仍在{road.name}上{'折返' if journey.returning else '赶路'}，还需{journey.remaining_days}日。"
        return True
    if not journey.returning:
        npc.region_id = journey.destination_id
    returning = journey.returning
    life.journey = None
    record_event(
        world,
        "arrival",
        f"{npc.name}{'退回' if returning else '抵达'}{_region(world, npc.region_id).name}",
        f"{npc.name}走完了这一段实际行程，随身物资没有在途中自动补充。",
        npc.region_id,
        npc.id,
    )
    return False


def _buy(world: WorldState, npc: WorldNPC, good: WorldGood, requested: int) -> int:
    life = life_of(npc)
    market = market_of(_region(world, npc.region_id))
    price = market.prices.amount(good)
    quantity = min(requested, market.stock.amount(good), life.coins // price)
    if quantity <= 0:
        return 0
    before_coins, before_stock = life.coins, life.inventory.amount(good)
    market.stock.change(good, -quantity)
    life.inventory.change(good, quantity)
    cost = quantity * price
    life.coins -= cost
    market.coins += cost
    event = record_event(
        world,
        "trade",
        f"{npc.name}买入{quantity}份{GOOD_NAMES[good]}",
        f"{npc.name}向{_region(world, npc.region_id).name}公营货栈支付{cost}枚钱；货物从货栈转入随身行囊。",
        npc.region_id,
        npc.id,
        cause_ids=life.plan.cause_ids if life.plan else [],
        effects=[
            _effect(npc.id, f"inventory.{good}", before_stock, before_stock + quantity),
            _effect(npc.id, "coins", before_coins, life.coins),
        ],
    )
    npc.last_action = event.detail
    return quantity


def _target_stock(world: WorldState, region: WorldRegion, good: WorldGood) -> int:
    if good == "food":
        residents = sum(
            life_of(npc).health > 0 and life_of(npc).home_region_id == region.id
            for npc in world.npcs
        )
        return max(36, residents * 15)
    return 32 if good == "wood" else 16


def _market_capacity(world: WorldState, region: WorldRegion) -> WorldGoods:
    return WorldGoods(
        food=_target_stock(world, region, "food"),
        wood=_target_stock(world, region, "wood"),
        ore=_target_stock(world, region, "ore"),
    )


def _sale_quantity(world: WorldState, npc: WorldNPC, good: WorldGood, requested: int) -> int:
    life = life_of(npc)
    region = _region(world, npc.region_id)
    market = market_of(region)
    price = max(1, market.prices.amount(good) - 1)
    return min(
        requested,
        life.inventory.amount(good),
        market.coins // price,
        max(0, _target_stock(world, region, good) - market.stock.amount(good)),
    )


def _sell(world: WorldState, npc: WorldNPC, good: WorldGood, requested: int) -> int:
    life = life_of(npc)
    region = _region(world, npc.region_id)
    market = market_of(region)
    price = max(1, market.prices.amount(good) - 1)
    quantity = _sale_quantity(world, npc, good, requested)
    if quantity <= 0:
        return 0
    gross = quantity * price
    tax = gross // 10
    before_coins, before_stock = life.coins, life.inventory.amount(good)
    life.inventory.change(good, -quantity)
    market.stock.change(good, quantity)
    market.coins -= gross
    life.coins += gross - tax
    faction = next(faction for faction in world.factions if faction.id == region.owner_id)
    faction.wealth += tax
    event = record_event(
        world,
        "trade",
        f"{npc.name}售出{quantity}份{GOOD_NAMES[good]}",
        f"{region.name}货栈用{gross}枚钱收购，{npc.name}实得{gross - tax}枚，另有{tax}枚交易税进入{faction.name}公库。",
        npc.region_id,
        npc.id,
        cause_ids=life.plan.cause_ids if life.plan else [],
        effects=[
            _effect(npc.id, f"inventory.{good}", before_stock, before_stock - quantity),
            _effect(npc.id, "coins", before_coins, life.coins),
            _effect(faction.id, "wealth", faction.wealth - tax, faction.wealth),
        ],
    )
    npc.last_action = event.detail
    return quantity


def _produce(world: WorldState, npc: WorldNPC, good: WorldGood) -> bool:
    region = _region(world, npc.region_id)
    life = life_of(npc)
    quantity = min(region.reserves.amount(good), 6 if good == "food" else 4)
    if quantity == 0:
        return False
    before = region.reserves.amount(good)
    region.reserves.change(good, -quantity)
    life.inventory.change(good, quantity)
    npc.energy = max(0, npc.energy - 12)
    event = record_event(
        world,
        "production",
        f"{npc.name}收取{quantity}份{GOOD_NAMES[good]}",
        f"{npc.name}在{region.name}劳动，把当地可采资源转入行囊；采区现余{region.reserves.amount(good)}份{GOOD_NAMES[good]}。",
        region.id,
        npc.id,
        cause_ids=life.plan.cause_ids if life.plan else [],
        effects=[
            _effect(region.id, f"reserves.{good}", before, before - quantity),
            _effect(
                npc.id,
                f"inventory.{good}",
                life.inventory.amount(good) - quantity,
                life.inventory.amount(good),
            ),
        ],
    )
    npc.last_action = event.detail
    return True


def _rest(world: WorldState, npc: WorldNPC, reason: str) -> None:
    _plan(world, npc, "rest", npc.region_id, reason)
    npc.energy = min(100, npc.energy + 30)
    npc.last_action = f"{npc.name}留在{_region(world, npc.region_id).name}休息。{reason}"
    npc.mood = "疲惫" if life_of(npc).hunger >= 40 else "平静"


def _survive(world: WorldState, npc: WorldNPC) -> bool:
    life = life_of(npc)
    if life.inventory.food >= 2:
        return False
    _plan(world, npc, "eat", npc.region_id, "随身口粮不足两日，先解决生存问题。")
    if _buy(world, npc, "food", 5):
        return True
    region = _region(world, npc.region_id)
    if life.hunger >= 40 and market_of(region).stock.food:
        faction = next(faction for faction in world.factions if faction.id == region.owner_id)
        cost = market_of(region).prices.food
        if faction.wealth >= cost:
            faction.wealth -= cost
            market_of(region).coins += cost
            market_of(region).stock.food -= 1
            life.inventory.food += 1
            event = record_event(
                world,
                "aid",
                f"{npc.name}领取一日救济",
                f"{faction.name}从真实公库支出{cost}枚钱，向当地货栈购买一份口粮交给{npc.name}。",
                region.id,
                npc.id,
                effects=[_effect(faction.id, "wealth", faction.wealth + cost, faction.wealth)],
            )
            _remember(npc, event, "aid", faction.id)
            npc.last_action = event.detail
            return True
    for salvage_good in WORLD_GOODS[1:]:
        if _sell(world, npc, salvage_good, life.inventory.amount(salvage_good)):
            return True
    if region.reserves.food and _produce(world, npc, "food"):
        return True
    if life.hunger < 60:
        good: WorldGood | None = (
            "wood"
            if life.profession == "woodcutter"
            else "ore"
            if life.profession == "miner"
            else None
        )
        if good is not None and _produce(world, npc, good):
            return True
    _plan(world, npc, "eat", "farm", "买不到足够口粮，前往有田地的东岸谋生。")
    if npc.region_id != "farm":
        _move(world, npc, "farm")
        return True
    _rest(world, npc, "田间也暂无可收口粮，只能等待生长；饥饿不会因休息消失。")
    return True


def _pay(world: WorldState, npc: WorldNPC, amount: int) -> None:
    life = life_of(npc)
    faction = next(faction for faction in world.factions if faction.id == npc.faction_id)
    paid = min(amount, faction.wealth)
    if paid:
        faction.wealth -= paid
        life.coins += paid
        record_event(
            world,
            "payroll",
            f"{npc.name}取得公职报酬",
            f"{faction.name}从公库向{npc.name}支付{paid}枚钱，公库现余{faction.wealth}枚。",
            npc.region_id,
            npc.id,
        )


def _repair(world: WorldState, npc: WorldNPC) -> bool:
    life = life_of(npc)
    road = _bridge(world)
    requirements: tuple[tuple[WorldGood, int], ...] = (("wood", REPAIR_WOOD), ("ore", REPAIR_ORE))
    knowledge = life.known_roads.get(road.id)
    if knowledge is None or knowledge.integrity >= 60 or knowledge.repair_budget <= 0:
        return False
    causes = [knowledge.event_id] if knowledge.event_id else []
    _plan(
        world,
        npc,
        "repair",
        road.id,
        "已知石桥受损且仍有工程款，先补材料，再投入实际工日。",
        causes,
    )
    if npc.region_id not in (road.origin_id, road.destination_id):
        for needed_good, required in requirements:
            if (
                knowledge.materials.amount(needed_good) < required
                and life.inventory.amount(needed_good) == 0
            ):
                if _buy(world, npc, needed_good, min(4, required)):
                    return True
                if _produce(world, npc, needed_good):
                    return True
        endpoints = [
            (sum(step.travel_days for step in path), endpoint)
            for endpoint in (road.origin_id, road.destination_id)
            if (path := route_for(world, npc, endpoint)) is not None
        ]
        if endpoints:
            _move(world, npc, min(endpoints)[1])
        else:
            _rest(world, npc, "目前没有可到达的工地入口，等待新路况。")
        return True
    delivered = False
    for good, required in requirements:
        needed = required - road.materials.amount(good)
        if needed <= 0:
            continue
        if life.inventory.amount(good) == 0:
            _buy(world, npc, good, min(needed, 4))
        quantity = min(needed, life.inventory.amount(good))
        if quantity:
            before = road.materials.amount(good)
            life.inventory.change(good, -quantity)
            road.materials.change(good, quantity)
            compensation = min(
                road.repair_budget,
                quantity * market_of(_region(world, npc.region_id)).prices.amount(good),
            )
            road.repair_budget -= compensation
            life.coins += compensation
            event = record_event(
                world,
                "construction",
                f"{npc.name}运来修桥材料",
                f"{quantity}份{GOOD_NAMES[good]}从{npc.name}行囊转入桥梁工地，工程款报销{compensation}枚钱。",
                npc.region_id,
                npc.id,
                cause_ids=causes,
                effects=[_effect(road.id, f"materials.{good}", before, before + quantity)],
            )
            npc.last_action = event.detail
            delivered = True
    if delivered:
        return True
    if road.materials.wood < REPAIR_WOOD or road.materials.ore < REPAIR_ORE:
        missing_good: WorldGood = "wood" if road.materials.wood < REPAIR_WOOD else "ore"
        source = "forest" if missing_good == "wood" else "mine"
        _plan(
            world,
            npc,
            "repair",
            source,
            f"工地缺少{GOOD_NAMES[missing_good]}，到产地寻找材料。",
            causes,
        )
        _move(world, npc, source)
        return True
    before = road.repair_work
    road.repair_work = min(REPAIR_WORK, before + 1)
    npc.energy = max(0, npc.energy - 15)
    paid = min(3, road.repair_budget)
    road.repair_budget -= paid
    life.coins += paid
    event = record_event(
        world,
        "construction",
        f"{npc.name}在石桥上施工",
        f"工程从{before}/{REPAIR_WORK}推进至{road.repair_work}/{REPAIR_WORK}工日，工匠取得{paid}枚钱。",
        npc.region_id,
        npc.id,
        cause_ids=causes,
        effects=[_effect(road.id, "repair_work", before, road.repair_work)],
    )
    npc.last_action = event.detail
    if road.repair_work == REPAIR_WORK:
        ledger = _ledger(world)
        road.materials.wood -= REPAIR_WOOD
        road.materials.ore -= REPAIR_ORE
        ledger.consumed.wood += REPAIR_WOOD
        ledger.consumed.ore += REPAIR_ORE
        before_integrity = road.integrity
        road.integrity = 100
        road.repair_work = 0
        owner = next(
            faction
            for faction in world.factions
            if faction.id == _region(world, road.origin_id).owner_id
        )
        owner.wealth += road.repair_budget
        road.repair_budget = 0
        complete = record_event(
            world,
            "infrastructure",
            "汀川石桥重新通行",
            "12份木材、4份矿石与12个工日成为真实桥梁。剩余工程款退回公库，商队可重新选择更短路线。",
            npc.region_id,
            npc.id,
            cause_ids=[event.id],
            effects=[_effect(road.id, "integrity", before_integrity, 100)],
        )
        road.last_event_id = complete.id
        _witness_aid(world, npc, complete, road.id)
    return True


def _witness_aid(world: WorldState, actor: WorldNPC, event: WorldEvent, subject: str) -> None:
    road = _bridge(world)
    for npc in world.npcs:
        life = life_of(npc)
        if (
            life.health > 0
            and npc.region_id in (road.origin_id, road.destination_id)
            and life.journey is None
        ):
            _remember(npc, event, "aid", subject, actor.id)
            if npc.id != actor.id:
                life.relationships[actor.id] = min(100, life.relationships.get(actor.id, 0) + 10)


def _scholar(world: WorldState, npc: WorldNPC) -> bool:
    life = life_of(npc)
    road = _bridge(world)
    if life.ability is not None:
        knowledge = life.known_roads.get(road.id)
        if knowledge is None or knowledge.passable:
            return False
        causes = [memory.event_id for memory in life.memories if memory.subject_id == road.id][-2:]
        _plan(
            world, npc, "channel", road.id, "已知旧桥仍无法通行，尝试用所学暂时改变水路。", causes
        )
        if npc.region_id not in (road.origin_id, road.destination_id):
            _move(world, npc, "ferry")
            return True
        if road_passable(road, world.day):
            return False
        if life.inventory.ore < 2:
            _buy(world, npc, "ore", 2 - life.inventory.ore)
        if life.inventory.ore < 2:
            npc.last_action = "引流需要两份真实矿石，材料不足，无法发动。"
            record_event(
                world, "blocked", f"{npc.name}缺少引流材料", npc.last_action, npc.region_id, npc.id
            )
            return False
        if npc.energy < 35:
            _rest(world, npc, "引流至少需要35点精力，不能凭空施术。")
            return True
        life.inventory.ore -= 2
        _ledger(world).consumed.ore += 2
        npc.energy -= 35
        before_level, before_ford = world.river_level, road.ford_until_day
        world.river_level = max(0, world.river_level - 25)
        road.ford_until_day = world.day + 3
        event = record_event(
            world,
            "power",
            f"{npc.name}引出一段浅滩",
            f"消耗2份矿石与35点精力，水位从{before_level}降至{world.river_level}。石桥仍未修复，但浅滩可用至第{road.ford_until_day}日，渡涉比桥面慢一日。",
            npc.region_id,
            npc.id,
            cause_ids=causes,
            effects=[
                _effect("river", "level", before_level, world.river_level),
                _effect(road.id, "ford_until_day", before_ford, road.ford_until_day),
            ],
        )
        road.last_event_id = event.id
        npc.last_action = event.detail
        _witness_aid(world, npc, event, road.id)
        return True
    _plan(
        world, npc, "study", "ruins", "记录需要三日独立研究，每次消耗一份矿石；研究不能替代口粮。"
    )
    if npc.region_id != "ruins":
        _move(world, npc, "ruins")
        return True
    if life.inventory.ore == 0:
        _buy(world, npc, "ore", 1)
    if life.inventory.ore == 0:
        return False
    life.inventory.ore -= 1
    _ledger(world).consumed.ore += 1
    life.research += 1
    npc.energy = max(0, npc.energy - 18)
    _pay(world, npc, 2)
    event = record_event(
        world,
        "discovery",
        f"{npc.name}解读水流记录",
        f"消耗一份矿石，研究推进至{life.research}/3。知识只属于亲历研究者，不会让所有人同时升级。",
        npc.region_id,
        npc.id,
        effects=[_effect(npc.id, "research", life.research - 1, life.research)],
    )
    npc.last_action = event.detail
    _remember(npc, event, "discovery", "watercourse")
    if life.research == 3:
        life.ability = "watercourse"
        learned = record_event(
            world,
            "discovery",
            f"{npc.name}掌握引流",
            "此人现在可以在断桥河岸消耗矿石和精力，开出短暂浅滩；这改变通行能力，不增加任意财富或境界。",
            npc.region_id,
            npc.id,
            cause_ids=[event.id],
        )
        _remember(npc, learned, "discovery", "watercourse")
    return True


def _trade(world: WorldState, npc: WorldNPC) -> bool:
    life = life_of(npc)
    here = _region(world, npc.region_id)
    market = market_of(here)
    cargo = life.cargo_good
    if cargo is not None:
        quantity = max(0, life.inventory.amount(cargo) - (4 if cargo == "food" else 0))
        if quantity:
            offers = []
            for region_id, knowledge in life.known_markets.items():
                path = route_for(world, npc, region_id)
                if path is None:
                    continue
                distance = sum(road.travel_days for road in path)
                bid = max(1, knowledge.prices.amount(cargo) - 1)
                if knowledge.coins < bid or knowledge.stock.amount(
                    cargo
                ) >= knowledge.capacity.amount(cargo):
                    continue
                profit = quantity * (bid - life.cargo_cost) - distance * 2
                offers.append((profit, region_id))
            if offers:
                _, target = max(offers)
                _plan(
                    world,
                    npc,
                    "trade",
                    target,
                    f"依据已知货价与行程，把随身{GOOD_NAMES[cargo]}运往{_region(world, target).name}；旧消息可能过时。",
                )
                if target != npc.region_id:
                    _move(world, npc, target)
                    return True
                if _sell(world, npc, cargo, quantity):
                    if life.inventory.amount(cargo) <= (4 if cargo == "food" else 0):
                        if quantity:
                            _rest(world, npc, "随身货物暂时没有可信的买家，等待需求或消息变化。")
                            return True
                        life.cargo_good = None
                    return True
        life.cargo_good = None
    opportunities: list[tuple[int, WorldGood, str, int]] = []
    for good in WORLD_GOODS:
        quantity = min(
            10, market.stock.amount(good), max(0, life.coins - 8) // market.prices.amount(good)
        )
        if quantity == 0:
            continue
        for region_id, knowledge in life.known_markets.items():
            if region_id == npc.region_id:
                continue
            path = route_for(world, npc, region_id)
            if path is None:
                continue
            if knowledge.coins < 1 or knowledge.stock.amount(good) >= knowledge.capacity.amount(
                good
            ):
                continue
            days = sum(road.travel_days for road in path)
            margin = max(1, knowledge.prices.amount(good) - 1) - market.prices.amount(good)
            profit = quantity * margin - days * 2
            if profit > 0:
                opportunities.append((profit, good, region_id, quantity))
    if opportunities:
        _, good, target, quantity = max(opportunities)
        _plan(
            world,
            npc,
            "trade",
            target,
            f"已知{_region(world, target).name}的{GOOD_NAMES[good]}较紧缺，尝试承担运输风险赚取差价。",
        )
        price = market.prices.amount(good)
        if _buy(world, npc, good, quantity):
            life.cargo_good = good
            life.cargo_cost = price
            return True
    if npc.region_id != "farm" and life.inventory.food < 6:
        _plan(world, npc, "trade", "farm", "暂时没有可信的获利机会，先到产粮地补给并打听消息。")
        _move(world, npc, "farm")
        return True
    return False


def _act(world: WorldState, npc: WorldNPC) -> None:
    life = life_of(npc)
    if life.health == 0 or _journey(world, npc):
        return
    _observe(world, npc)
    if _survive(world, npc):
        return
    if npc.energy < 20:
        _rest(world, npc, "精力不足，先休息再执行原来的打算。")
        return
    if life.profession == "builder" and _repair(world, npc):
        return
    if life.profession == "scholar" and _scholar(world, npc):
        return
    if life.profession == "merchant" and _trade(world, npc):
        return
    if life.profession == "guard":
        _plan(world, npc, "patrol", life.home_region_id, "在领薪前先回到自己负责的聚落。")
        if npc.region_id != life.home_region_id:
            _move(world, npc, life.home_region_id)
            return
        _pay(world, npc, 2)
        npc.energy = max(0, npc.energy - 8)
        npc.last_action = f"{npc.name}在{_region(world, npc.region_id).name}值守，查看渡口与仓廪。"
        return
    resource: WorldGood = (
        "wood"
        if life.profession == "woodcutter"
        else "ore"
        if life.profession == "miner"
        else "food"
    )
    home = life.home_region_id if life.profession in ("farmer", "woodcutter", "miner") else "farm"
    stock = life.inventory.amount(resource)
    reserve = 4 if resource == "food" else 0
    if stock > reserve and _sale_quantity(world, npc, resource, stock - reserve) > 0:
        _plan(
            world,
            npc,
            "sell",
            npc.region_id,
            f"把多余的{GOOD_NAMES[resource]}换成下一次生活所需的钱。",
        )
        if _sell(world, npc, resource, stock - reserve):
            return
    if stock < 10:
        _plan(
            world,
            npc,
            "produce",
            home,
            f"依靠劳动取得真实{GOOD_NAMES[resource]}，不是直接增加财富。",
        )
        if npc.region_id != home:
            _move(world, npc, home)
            return
        if _produce(world, npc, resource):
            return
        if resource != "food" and life.inventory.amount(resource) == 0:
            previous = life.profession
            life.profession = "farmer"
            life.home_region_id = "farm"
            event = record_event(
                world,
                "career",
                f"{npc.name}离开耗尽的采区",
                f"原来的{GOOD_NAMES[resource]}已无从采收，{npc.name}不再原地等待资源凭空恢复，决定去东岸务农。",
                npc.region_id,
                npc.id,
                effects=[_effect(npc.id, "profession", previous, "farmer")],
            )
            _remember(npc, event, "hardship", npc.region_id)
            _plan(world, npc, "produce", "farm", "原有采区耗尽，转向能维持生活的工作。", [event.id])
            _move(world, npc, "farm")
            return
    _rest(world, npc, "已有口粮，眼下也没有可完成的生产或买卖，等待需求与环境变化。")


def _institutions(world: WorldState) -> None:
    if world.day % 7 == 0:
        for region in world.regions:
            market = market_of(region)
            surplus = max(0, market.coins - 160) // 2
            if surplus == 0:
                continue
            faction = next(faction for faction in world.factions if faction.id == region.owner_id)
            market.coins -= surplus
            faction.wealth += surplus
            record_event(
                world,
                "finance",
                f"{region.name}货栈结算公共收益",
                f"货栈保留周转金后，把{surplus}枚现有钱交入{faction.name}公库，用于公职、救济和工程；没有增发货币。",
                region.id,
                effects=[
                    _effect(f"market:{region.id}", "coins", market.coins + surplus, market.coins),
                    _effect(faction.id, "wealth", faction.wealth - surplus, faction.wealth),
                ],
            )
    road = _bridge(world)
    observers = [
        npc
        for npc in world.npcs
        if npc.faction_id == "council"
        and life_of(npc).health > 0
        and life_of(npc).journey is None
        and npc.region_id in (road.origin_id, road.destination_id)
    ]
    if not observers or road.integrity >= 60:
        return
    market = market_of(_region(world, "city"))
    estimate = (
        max(0, REPAIR_WOOD - road.materials.wood) * market.prices.wood
        + max(0, REPAIR_ORE - road.materials.ore) * market.prices.ore
        + (REPAIR_WORK - road.repair_work) * 3
    )
    needed = max(0, estimate - road.repair_budget)
    faction = next(faction for faction in world.factions if faction.id == "council")
    contribution = min(needed, max(0, faction.wealth - 30))
    if contribution:
        faction.wealth -= contribution
        road.repair_budget += contribution
        event = record_event(
            world,
            "policy",
            "议事会追加石桥工程款",
            f"驻岸成员报告桥损后，议事会按材料与剩余工日估算，从公库划拨{contribution}枚现有钱；保留30枚应急金。",
            "city",
            cause_ids=[road.last_event_id] if road.last_event_id else [],
            effects=[
                _effect(faction.id, "wealth", faction.wealth + contribution, faction.wealth),
                _effect(
                    road.id, "repair_budget", road.repair_budget - contribution, road.repair_budget
                ),
            ],
        )
        road.last_event_id = event.id


def _flood(world: WorldState, observer: bool, causes: list[int] | None = None) -> WorldEvent:
    road = _bridge(world)
    before = road.integrity
    before_level = world.river_level
    if observer:
        world.river_level = 95
    road.integrity = max(0, road.integrity - (100 if observer else 30))
    road.ford_until_day = 0
    if road.integrity == 0:
        road.repair_work = 0
    event = record_event(
        world,
        "intervention" if observer else "disaster",
        "观察实验：洪水冲击石桥" if observer else "洪峰冲击汀川石桥",
        f"河水冲击使桥梁完好度从{before}降至{road.integrity}，临时浅滩失效。"
        + (
            "这是观察者主动施加的扰动，不伪装成自然事件。"
            if observer
            else "不能通行者必须改道或等待。"
        ),
        "city",
        cause_ids=(causes or []) + ([road.last_event_id] if road.last_event_id else []),
        effects=[
            _effect(road.id, "integrity", before, road.integrity),
            _effect("river", "level", before_level, world.river_level),
        ],
    )
    road.last_event_id = event.id
    for npc in world.npcs:
        life = life_of(npc)
        if (
            life.health > 0
            and npc.region_id in (road.origin_id, road.destination_id)
            and (life.journey is None or life.journey.road_id == road.id)
        ):
            _remember(npc, event, "flood", road.id)
    return event


def _environment(world: WorldState, rng: random.Random) -> None:
    world.weather = rng.choices(["晴", "细雨", "暴雨"], weights=[6, 3, 1])[0]
    before_level = world.river_level
    world.river_level = min(
        100, max(0, world.river_level + {"晴": -5, "细雨": 4, "暴雨": 18}[world.weather])
    )
    climate = record_event(
        world,
        "weather",
        f"{world.weather}中的汀川",
        f"降雨与蒸发使水位从{before_level}变为{world.river_level}；作物生长与桥梁风险受实际水位影响。",
        effects=[_effect("river", "level", before_level, world.river_level)],
    )
    ledger = _ledger(world)
    farm = _region(world, "farm")
    season = ((world.day - 1) // 30) % 4
    growth = [38, 52, 36, 14][season]
    if world.river_level < 20:
        growth //= 2
    growth = min(growth, 320 - farm.reserves.food)
    farm.reserves.food += growth
    ledger.produced.food += growth
    if growth:
        record_event(
            world,
            "ecology",
            "田间作物生长",
            f"季节与水位使田间增加{growth}份可收粮食；这是自然产出的记账来源，还需要有人收取与运输。",
            farm.id,
            cause_ids=[climate.id],
            effects=[
                _effect(farm.id, "reserves.food", farm.reserves.food - growth, farm.reserves.food)
            ],
        )
    if world.day % 7 == 0:
        forest = _region(world, "forest")
        growth_wood = min(2, 200 - forest.reserves.wood)
        forest.reserves.wood += growth_wood
        ledger.produced.wood += growth_wood
        if growth_wood:
            record_event(
                world,
                "ecology",
                "雾松林缓慢恢复",
                f"自然生长增加{growth_wood}份可采木材，矿石则不会自然补充。",
                forest.id,
                effects=[
                    _effect(
                        forest.id,
                        "reserves.wood",
                        forest.reserves.wood - growth_wood,
                        forest.reserves.wood,
                    )
                ],
            )
    road = _bridge(world)
    if world.weather == "暴雨" and world.river_level > 75:
        _flood(world, observer=False, causes=[climate.id])
    elif road.ford_until_day == world.day - 1:
        event = record_event(
            world,
            "infrastructure",
            "引流浅滩已经消退",
            "法术维持期结束，渡涉不再可用；是否能过河重新取决于桥梁和其他真实道路。",
            "ferry",
            cause_ids=[road.last_event_id] if road.last_event_id else [],
        )
        road.last_event_id = event.id


def _bodies(world: WorldState) -> None:
    consumed = 0
    effects = []
    for npc in world.npcs:
        life = life_of(npc)
        if life.health == 0:
            continue
        life.age_days += 1
        if life.age_days >= life.lifespan_days:
            _die(world, npc, "寿命已尽")
            continue
        npc.energy = min(100, npc.energy + 4)
        life.hunger = min(100, life.hunger + 20)
        if life.inventory.food:
            before = life.inventory.food
            life.inventory.food -= 1
            _ledger(world).consumed.food += 1
            consumed += 1
            effects.append(_effect(npc.id, "inventory.food", before, life.inventory.food))
            life.hunger = max(0, life.hunger - 35)
            if life.hunger < 40:
                life.health = min(100, life.health + 2)
        elif life.hunger >= 60:
            before_health = life.health
            life.health = max(0, life.health - 12)
            event = record_event(
                world,
                "hardship",
                f"{npc.name}正在挨饿",
                f"没有吃到实际口粮，健康从{before_health}降至{life.health}。休息和头衔不能代替食物。",
                npc.region_id,
                npc.id,
                effects=[_effect(npc.id, "health", before_health, life.health)],
            )
            _remember(npc, event, "hardship", npc.region_id)
            if life.health == 0:
                _die(world, npc, "在持续饥饿中死去", [event.id])
    if consumed:
        record_event(
            world,
            "consumption",
            f"居民用去{consumed}份口粮",
            "口粮从每个人的行囊实际扣除，计入消耗账；在途者同样需要自己的粮食。",
            effects=effects,
        )


def advance_living_world(current: WorldState) -> WorldState:
    world = current.snapshot()
    world.day += 1
    rng = random.Random((world.seed << 16) + world.day * 7919)
    _environment(world, rng)
    _bodies(world)
    _prices(world)
    offset = world.day % len(world.npcs) if world.npcs else 0
    for npc in world.npcs[offset:] + world.npcs[:offset]:
        _act(world, npc)
    _prices(world)
    _institutions(world)
    for faction in world.factions:
        members = [
            npc for npc in world.npcs if npc.faction_id == faction.id and life_of(npc).health > 0
        ]
        faction.influence = (
            sum(100 - life_of(npc).hunger for npc in members) // len(members) if members else 0
        )
    world.last_error = ""
    touch_world(world)
    WorldState.model_validate(world.model_dump())
    return world


def intervene_living_world(current: WorldState, intervention: WorldIntervention) -> WorldState:
    if intervention.kind not in ("flood", "repair_contract"):
        raise ValueError("因果世界不接受直接增加财富、灵气或修行的旧版干预")
    world = current.snapshot()
    road = _bridge(world)
    if intervention.region_id not in (road.origin_id, road.destination_id):
        raise ValueError("请先选择汀川石桥任意一端：汀川城或折潮渡")
    if intervention.kind == "flood":
        _flood(world, observer=True)
    else:
        if road.integrity >= 60:
            raise ValueError("石桥目前无需重建，不能重复划拨工程款")
        faction = next(faction for faction in world.factions if faction.id == "council")
        if faction.wealth < 40:
            raise ValueError("议事会公库不足40枚钱，无法发布修桥委托")
        faction.wealth -= 40
        road.repair_budget += 40
        event = record_event(
            world,
            "intervention",
            "观察实验：追加修桥委托",
            "从议事会现有公库划出40枚钱进入石桥工程款，不增加货币；工匠仍需自己决定并运来材料。",
            intervention.region_id,
            cause_ids=[road.last_event_id] if road.last_event_id else [],
            effects=[
                _effect(faction.id, "wealth", faction.wealth + 40, faction.wealth),
                _effect(road.id, "repair_budget", road.repair_budget - 40, road.repair_budget),
            ],
        )
        road.last_event_id = event.id
    world.last_error = ""
    touch_world(world)
    WorldState.model_validate(world.model_dump())
    return world
