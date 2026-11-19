import random
import secrets
import uuid
from datetime import datetime, timezone

from domain.living_world import (
    advance_living_world,
    create_living_world,
    intervene_living_world,
)
from domain.world_events import MAX_WORLD_EVENTS as MAX_WORLD_EVENTS
from domain.world_events import record_event, touch_world
from models.world import (
    REALM_NAMES,
    NPCTrait,
    WorldConfig,
    WorldFaction,
    WorldIntervention,
    WorldNPC,
    WorldRegion,
    WorldState,
)

_REGIONS = [
    (
        "qinglan",
        "青岚山",
        "山岳",
        "云气沿石阶上行，山门收留远道而来的求学者。",
        24,
        27,
        "lingxiao",
        ["yundu", "jinghu"],
    ),
    (
        "yundu",
        "云舟渡",
        "渡口",
        "商舟在两岸往返，消息常比灵石更早抵达。",
        52,
        20,
        "yunshang",
        ["qinglan", "chiyuan", "bailu"],
    ),
    (
        "chiyuan",
        "赤原",
        "旷野",
        "开阔的赤色原野，散修在旧驿道旁交换见闻。",
        79,
        35,
        "xingye",
        ["yundu", "bailu"],
    ),
    (
        "jinghu",
        "镜湖",
        "湖泊",
        "平静湖面映着远山，水畔适合静修与采集。",
        40,
        52,
        "lingxiao",
        ["qinglan", "bailu", "wumeng"],
    ),
    (
        "bailu",
        "白鹿城",
        "城镇",
        "灯火与摊位聚成市集，各方在这里维持脆弱的默契。",
        67,
        69,
        "yunshang",
        ["yundu", "chiyuan", "jinghu", "wumeng"],
    ),
    (
        "wumeng",
        "雾梦谷",
        "幽谷",
        "谷中灵植随雾舒展，蜿蜒的小径还没有被完全标记。",
        23,
        79,
        "xingye",
        ["jinghu", "bailu"],
    ),
]

_PEOPLE: list[tuple[str, str, str, str, NPCTrait, str]] = [
    ("shenzhao", "沈照微", "lingxiao", "qinglan", "修炼", "在山门中寻得自己的道"),
    ("luqing", "陆清和", "lingxiao", "jinghu", "守护", "守住湖畔的安宁"),
    ("wenxi", "温溪", "lingxiao", "qinglan", "探索", "绘完六地之间的行路图"),
    ("gutang", "顾棠", "yunshang", "yundu", "经商", "让每一条商路重新热闹起来"),
    ("suting", "苏听澜", "yunshang", "bailu", "探索", "记下各地不为人知的故事"),
    ("linqiao", "林乔", "yunshang", "yundu", "守护", "护送每一艘商舟平安靠岸"),
    ("yanzhou", "晏舟", "xingye", "chiyuan", "探索", "找到能让散修安居的地方"),
    ("jiangli", "江离", "xingye", "wumeng", "修炼", "从灵植中悟出新的修行方法"),
    ("xuning", "许宁", "xingye", "chiyuan", "经商", "为同道攒下一座共同的书楼"),
]

_ACTIONS = {
    "探索": ["travel", "travel", "gather", "cultivate"],
    "修炼": ["cultivate", "cultivate", "cultivate", "gather", "travel"],
    "经商": ["trade", "trade", "trade", "travel", "gather", "cultivate"],
    "守护": ["patrol", "patrol", "patrol", "cultivate", "travel"],
}


def create_world(config: WorldConfig) -> WorldState:
    if config.ruleset == "living":
        return create_living_world(config)
    seed = config.seed if config.seed is not None else secrets.randbits(31)
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).isoformat()
    regions = [
        WorldRegion(
            id=rid,
            name=name,
            terrain=terrain,
            description=description,
            x=x,
            y=y,
            owner_id=owner,
            spirit=rng.randint(48, 82),
            prosperity=rng.randint(35, 68),
            danger=rng.randint(8, 30),
            neighbors=neighbors,
        )
        for rid, name, terrain, description, x, y, owner, neighbors in _REGIONS
    ]
    factions = [
        WorldFaction(
            id="lingxiao",
            name="灵霄宗",
            color="#86cbb2",
            philosophy="循序修行，守望山水",
            influence=54,
            wealth=160,
        ),
        WorldFaction(
            id="yunshang",
            name="云商会",
            color="#e7bd73",
            philosophy="以商通路，以信结缘",
            influence=49,
            wealth=220,
        ),
        WorldFaction(
            id="xingye",
            name="行野盟",
            color="#b4a1d9",
            philosophy="行遍旷野，自寻归处",
            influence=46,
            wealth=140,
        ),
    ]
    npcs = [
        WorldNPC(
            id=nid,
            name=name,
            faction_id=faction,
            region_id=region,
            trait=trait,
            goal=goal,
            realm=rng.randint(0, 2),
            cultivation=rng.randint(5, 65),
            energy=rng.randint(65, 95),
            mood="平静",
            last_action="安顿行装，等待新的一日。",
        )
        for nid, name, faction, region, trait, goal in _PEOPLE
    ]
    world = WorldState(
        id=str(uuid.uuid4()),
        name=config.name,
        seed=seed,
        interval_seconds=config.interval_seconds,
        created_at=now,
        updated_at=now,
        regions=regions,
        factions=factions,
        npcs=npcs,
    )
    record_event(
        world, "origin", "雾海初开", "六处山川、三方势力与九位修行者，共同开始这段世界的历史。"
    )
    return world


def _gain_cultivation(npc: WorldNPC, amount: int) -> bool:
    total = npc.cultivation + amount
    if npc.realm < len(REALM_NAMES) - 1 and total >= 100:
        npc.realm += 1
        npc.cultivation = total - 100
        return True
    npc.cultivation = min(99, total)
    return False


def _act(world: WorldState, npc: WorldNPC, rng: random.Random) -> None:
    regions = {region.id: region for region in world.regions}
    factions = {faction.id: faction for faction in world.factions}
    region = regions[npc.region_id]
    faction = factions[npc.faction_id]
    kind = "daily"
    if npc.energy < 25:
        npc.energy = min(100, npc.energy + 30)
        npc.mood = "平静"
        detail = f"{npc.name}留在{region.name}休整，为下一段旅程恢复精力。"
        title = f"{npc.name}暂歇"
    else:
        action = rng.choice(_ACTIONS[npc.trait])
        npc.mood = "平静"
        if action == "travel":
            destination = regions[rng.choice(region.neighbors)]
            npc.region_id = destination.id
            npc.energy = max(0, npc.energy - 10 - region.danger // 10)
            npc.mood = "好奇"
            detail = f"{npc.name}从{region.name}沿旧道前往{destination.name}，继续{npc.goal}。"
            title = f"{npc.name}抵达{destination.name}"
            region = destination
            kind = "travel"
        elif action == "cultivate" and region.spirit >= 3:
            region.spirit -= 3
            npc.energy = max(0, npc.energy - 12)
            advanced = _gain_cultivation(npc, rng.randint(9, 18))
            if advanced:
                npc.mood = "振奋"
                title = f"{npc.name}突破至{REALM_NAMES[npc.realm]}"
                detail = f"借{region.name}的灵气与日积月累的感悟，{npc.name}迈入了新的境界。"
                kind = "breakthrough"
                faction.influence = min(100, faction.influence + 3)
            else:
                title = f"{npc.name}静心修行"
                detail = f"{npc.name}在{region.name}吐纳修行，功行渐长，仍记着「{npc.goal}」。"
        elif action == "trade":
            income = rng.randint(5, 12)
            faction.wealth = min(1000, faction.wealth + income)
            region.prosperity = min(100, region.prosperity + 2)
            npc.energy = max(0, npc.energy - 8)
            title = f"{region.name}商路有声"
            detail = (
                f"{npc.name}在{region.name}促成一笔交易，为{faction.name}积累了{income}份资财。"
            )
            kind = "trade"
        elif action == "patrol":
            region.danger = max(0, region.danger - rng.randint(3, 8))
            faction.influence = min(100, faction.influence + 1)
            npc.energy = max(0, npc.energy - 10)
            title = f"{npc.name}巡守{region.name}"
            detail = f"{npc.name}疏通山道、照看行人，{region.name}的路途变得更安稳。"
        elif region.spirit:
            gathered = min(region.spirit, rng.randint(2, 6))
            region.spirit -= gathered
            faction.wealth = min(1000, faction.wealth + gathered * 2)
            npc.energy = max(0, npc.energy - 8)
            title = f"{npc.name}采集灵材"
            detail = f"{npc.name}在{region.name}采得{gathered}份灵材，交由{faction.name}共同使用。"
        else:
            npc.energy = min(100, npc.energy + 12)
            title = f"{npc.name}另寻机缘"
            detail = f"{region.name}灵气暂薄，{npc.name}停下采修，整理见闻与行装。"
    npc.last_action = detail
    record_event(world, kind, title, detail, region.id, npc.id)


def _faction_actions(world: WorldState, rng: random.Random) -> None:
    if world.day % 3 == 0:
        for faction in world.factions:
            owned = [region for region in world.regions if region.owner_id == faction.id]
            if owned and faction.wealth >= 12:
                region = min(owned, key=lambda item: item.prosperity)
                faction.wealth -= 12
                region.prosperity = min(100, region.prosperity + 5)
                record_event(
                    world,
                    "faction",
                    f"{faction.name}修缮{region.name}",
                    f"{faction.name}支出12份资财，修复道路与公共设施，让往来的人多一分便利。",
                    region.id,
                )
    if world.day % 4:
        return
    region = rng.choice(world.regions)
    presence = {
        faction.id: sum(
            1 for npc in world.npcs if npc.region_id == region.id and npc.faction_id == faction.id
        )
        for faction in world.factions
    }
    leader = max(world.factions, key=lambda faction: presence[faction.id])
    if leader.id != region.owner_id and presence[leader.id] >= 2:
        previous = next(faction for faction in world.factions if faction.id == region.owner_id)
        if presence[leader.id] > presence[previous.id]:
            region.owner_id = leader.id
            leader.influence = min(100, leader.influence + 4)
            previous.influence = max(0, previous.influence - 3)
            record_event(
                world,
                "faction",
                f"{region.name}迎来新的守望者",
                f"随着驻地修行者增多，{leader.name}接手了{region.name}的日常事务。",
                region.id,
            )


def advance_world(current: WorldState) -> WorldState:
    if current.ruleset == "living":
        return advance_living_world(current)
    world = current.snapshot()
    world.day += 1
    rng = random.Random((world.seed << 16) + world.day * 7919)
    world.weather = rng.choice(["晴和", "山雾", "灵雨", "流云"])
    for region in world.regions:
        recovery = 6 if world.weather == "灵雨" else 2
        region.spirit = min(100, region.spirit + recovery + rng.randint(0, 2))
        upkeep = rng.randint(0, 1) + region.prosperity // 50
        region.prosperity = max(0, region.prosperity - upkeep)
        region.danger = min(100, max(0, region.danger + rng.randint(-1, 2)))
    if world.weather == "灵雨":
        record_event(world, "weather", "灵雨润山川", "细雨携着灵气落遍六地，各处灵脉正缓缓恢复。")
    for npc in world.npcs:
        _act(world, npc, rng)
    _faction_actions(world, rng)
    world.last_error = ""
    touch_world(world)
    return world


def intervene_world(current: WorldState, intervention: WorldIntervention) -> WorldState:
    if current.ruleset == "living":
        return intervene_living_world(current, intervention)
    if intervention.kind not in ("rain", "market", "enlightenment"):
        raise ValueError("这项干预只适用于因果世界")
    world = current.snapshot()
    region = next((item for item in world.regions if item.id == intervention.region_id), None)
    if intervention.kind in ("rain", "market") and region is None:
        raise ValueError("请选择一个有效地点后再施加干预")
    if intervention.kind == "rain" and region is not None:
        region.spirit = min(100, region.spirit + 20)
        title, detail = "天降灵雨", f"一场特别的灵雨落在{region.name}，此地灵气增加20，最高为100。"
    elif intervention.kind == "market" and region is not None:
        region.prosperity = min(100, region.prosperity + 15)
        for npc in world.npcs:
            if npc.region_id == region.id:
                npc.energy = min(100, npc.energy + 15)
        title, detail = (
            "山海集市开张",
            f"{region.name}开设集市，繁荣增加15，在此停留的人恢复了精力。",
        )
    else:
        for npc in world.npcs:
            advanced = _gain_cultivation(npc, 8)
            if advanced:
                record_event(
                    world,
                    "breakthrough",
                    f"{npc.name}感悟破境",
                    f"一场共同的顿悟让{npc.name}迈入{REALM_NAMES[npc.realm]}。",
                    npc.region_id,
                    npc.id,
                )
        title, detail = "一念照山海", "修行者各得一缕感悟，所有人的修行进度增加8。"
    record_event(world, "intervention", title, detail, region.id if region else None)
    world.last_error = ""
    touch_world(world)
    return world
