from collections.abc import Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

REALM_NAMES = ["凡人", "炼气", "筑基", "金丹", "元婴", "化神"]
NPCTrait = Literal["探索", "修炼", "经商", "守护"]
WorldRuleset = Literal["classic", "living"]
WORLD_RULESETS: tuple[WorldRuleset, ...] = ("classic", "living")
WorldGood = Literal["food", "wood", "ore"]
WORLD_GOODS: tuple[WorldGood, ...] = ("food", "wood", "ore")
GOOD_NAMES: dict[WorldGood, str] = {"food": "粮食", "wood": "木材", "ore": "矿石"}
WorldProfession = Literal[
    "farmer", "woodcutter", "miner", "builder", "merchant", "guard", "scholar"
]
PROFESSION_NAMES: dict[WorldProfession, str] = {
    "farmer": "农人",
    "woodcutter": "伐木人",
    "miner": "矿工",
    "builder": "工匠",
    "merchant": "行商",
    "guard": "守卫",
    "scholar": "研究者",
}


class WorldConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(default="雾海九州", min_length=1, max_length=40)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    interval_seconds: int = Field(default=15, ge=3, le=120)
    ruleset: WorldRuleset = "classic"


class WorldControl(BaseModel):
    action: Literal["start", "pause", "step"]
    interval_seconds: int | None = Field(default=None, ge=3, le=120)


class WorldIntervention(BaseModel):
    kind: Literal["rain", "market", "enlightenment", "flood", "repair_contract"]
    region_id: str | None = Field(default=None, max_length=40)


class WorldChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    npc_id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=500)


class WorldGoods(BaseModel):
    food: int = Field(default=0, ge=0)
    wood: int = Field(default=0, ge=0)
    ore: int = Field(default=0, ge=0)

    def amount(self, good: WorldGood) -> int:
        return {"food": self.food, "wood": self.wood, "ore": self.ore}[good]

    def change(self, good: WorldGood, delta: int) -> None:
        value = self.amount(good) + delta
        if value < 0:
            raise ValueError(f"{good} 库存不足，无法变动 {delta}")
        setattr(self, good, value)

    @classmethod
    def total(cls, stocks: Iterable["WorldGoods"]) -> "WorldGoods":
        result = cls()
        for stock in stocks:
            for good in WORLD_GOODS:
                result.change(good, stock.amount(good))
        return result


class WorldPrices(BaseModel):
    food: int = Field(default=3, ge=1)
    wood: int = Field(default=3, ge=1)
    ore: int = Field(default=5, ge=1)

    def amount(self, good: WorldGood) -> int:
        return {"food": self.food, "wood": self.wood, "ore": self.ore}[good]


class WorldMarket(BaseModel):
    stock: WorldGoods = Field(default_factory=WorldGoods)
    coins: int = Field(ge=0)
    prices: WorldPrices = Field(default_factory=WorldPrices)


class WorldRoad(BaseModel):
    id: str
    name: str
    origin_id: str
    destination_id: str
    travel_days: int = Field(ge=1)
    bridge: bool = False
    integrity: int = Field(default=100, ge=0, le=100)
    ford_until_day: int = Field(default=0, ge=0)
    repair_work: int = Field(default=0, ge=0, le=12)
    materials: WorldGoods = Field(default_factory=WorldGoods)
    repair_budget: int = Field(default=0, ge=0)
    last_event_id: int | None = None


class WorldMemory(BaseModel):
    event_id: int = Field(ge=1)
    day: int = Field(ge=1)
    kind: str
    subject_id: str
    detail: str
    source_id: str | None = None


class WorldRoadKnowledge(BaseModel):
    passable: bool
    day: int = Field(ge=0)
    event_id: int | None = None
    travel_days: int = Field(default=1, ge=1)
    integrity: int = Field(default=100, ge=0, le=100)
    repair_budget: int = Field(default=0, ge=0)
    materials: WorldGoods = Field(default_factory=WorldGoods)


class WorldMarketKnowledge(BaseModel):
    day: int = Field(ge=0)
    prices: WorldPrices
    stock: WorldGoods
    coins: int = Field(ge=0)
    capacity: WorldGoods
    source_id: str | None = None


WorldPlanKind = Literal[
    "eat", "produce", "sell", "trade", "repair", "study", "channel", "rest", "patrol"
]


class WorldPlan(BaseModel):
    kind: WorldPlanKind
    target_id: str
    reason: str
    since_day: int = Field(ge=1)
    cause_ids: list[int] = Field(default_factory=list)


class WorldJourney(BaseModel):
    road_id: str
    destination_id: str
    remaining_days: int = Field(ge=0)
    total_days: int = Field(ge=1)
    returning: bool = False


class WorldLife(BaseModel):
    profession: WorldProfession
    home_region_id: str
    age_days: int = Field(ge=0)
    lifespan_days: int = Field(ge=1)
    health: int = Field(default=100, ge=0, le=100)
    hunger: int = Field(default=0, ge=0, le=100)
    died_on: int | None = None
    coins: int = Field(ge=0)
    inventory: WorldGoods = Field(default_factory=WorldGoods)
    risk_tolerance: int = Field(ge=0, le=100)
    ability: Literal["watercourse"] | None = None
    research: int = Field(default=0, ge=0, le=3)
    plan: WorldPlan | None = None
    journey: WorldJourney | None = None
    memories: list[WorldMemory] = Field(default_factory=list)
    known_roads: dict[str, WorldRoadKnowledge] = Field(default_factory=dict)
    known_markets: dict[str, WorldMarketKnowledge] = Field(default_factory=dict)
    relationships: dict[str, int] = Field(default_factory=dict)
    cargo_good: WorldGood | None = None
    cargo_cost: int = Field(default=0, ge=0)


class WorldLedger(BaseModel):
    initial_goods: WorldGoods
    produced: WorldGoods = Field(default_factory=WorldGoods)
    consumed: WorldGoods = Field(default_factory=WorldGoods)
    initial_money: int = Field(ge=0)


class WorldRegion(BaseModel):
    id: str
    name: str
    terrain: str
    description: str
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    owner_id: str
    spirit: int = Field(ge=0, le=100)
    prosperity: int = Field(ge=0, le=100)
    danger: int = Field(ge=0, le=100)
    neighbors: list[str]
    market: WorldMarket | None = None
    reserves: WorldGoods = Field(default_factory=WorldGoods)


class WorldFaction(BaseModel):
    id: str
    name: str
    color: str
    philosophy: str
    influence: int = Field(ge=0, le=100)
    wealth: int = Field(ge=0)


class WorldNPC(BaseModel):
    id: str
    name: str
    faction_id: str
    region_id: str
    trait: NPCTrait
    goal: str
    realm: int = Field(ge=0, lt=len(REALM_NAMES))
    cultivation: int = Field(ge=0, le=99)
    energy: int = Field(ge=0, le=100)
    mood: str
    last_action: str
    life: WorldLife | None = None


class WorldEffect(BaseModel):
    subject_id: str
    field: str
    before: int | str
    after: int | str


class WorldEvent(BaseModel):
    id: int
    day: int
    kind: str
    title: str
    detail: str
    region_id: str | None = None
    npc_id: str | None = None
    cause_ids: list[int] = Field(default_factory=list)
    effects: list[WorldEffect] = Field(default_factory=list)


class WorldAIEntry(BaseModel):
    kind: Literal["chronicle", "dialogue"]
    day: int
    text: str
    npc_id: str | None = None
    question: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0


class WorldState(BaseModel):
    id: str
    name: str
    seed: int
    ruleset: WorldRuleset = "classic"
    day: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    running: bool = False
    interval_seconds: int = Field(default=15, ge=3, le=120)
    weather: str = "晴和"
    created_at: str
    updated_at: str
    regions: list[WorldRegion]
    factions: list[WorldFaction]
    npcs: list[WorldNPC]
    events: list[WorldEvent] = Field(default_factory=list)
    ai_entries: list[WorldAIEntry] = Field(default_factory=list)
    next_event_id: int = 1
    last_error: str = ""
    roads: list[WorldRoad] = Field(default_factory=list)
    river_level: int = Field(default=50, ge=0, le=100)
    ledger: WorldLedger | None = None
    pending_events: list[WorldEvent] = Field(default_factory=list, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_living_world(self) -> Self:
        if self.ruleset != "living":
            return self
        if self.ledger is None or any(region.market is None for region in self.regions):
            raise ValueError("因果世界缺少物资账本或市场")
        region_ids = {region.id for region in self.regions}
        faction_ids = {faction.id for faction in self.factions}
        road_ids = {road.id for road in self.roads}
        if (
            len(region_ids) != len(self.regions)
            or len(faction_ids) != len(self.factions)
            or len(road_ids) != len(self.roads)
            or len({npc.id for npc in self.npcs}) != len(self.npcs)
        ):
            raise ValueError("世界实体标识重复")
        roads = {road.id: road for road in self.roads}
        for region in self.regions:
            if region.owner_id not in faction_ids or not set(region.neighbors) <= region_ids:
                raise ValueError("地点引用了不存在的势力或邻地")
        for road in self.roads:
            if (
                road.origin_id not in region_ids
                or road.destination_id not in region_ids
                or road.origin_id == road.destination_id
            ):
                raise ValueError("道路端点无效")
        for npc in self.npcs:
            life = npc.life
            if (
                life is None
                or npc.region_id not in region_ids
                or npc.faction_id not in faction_ids
                or life.home_region_id not in region_ids
            ):
                raise ValueError("人物缺少有效的生活状态、地点或势力")
            journey = life.journey
            if journey is not None:
                journey_road = roads.get(journey.road_id)
                if (
                    journey_road is None
                    or {npc.region_id, journey.destination_id}
                    != {journey_road.origin_id, journey_road.destination_id}
                    or journey.remaining_days > journey.total_days
                ):
                    raise ValueError("人物行程与道路不一致")
        stocks = [region.reserves for region in self.regions]
        stocks.extend(region.market.stock for region in self.regions if region.market is not None)
        stocks.extend(npc.life.inventory for npc in self.npcs if npc.life is not None)
        stocks.extend(road.materials for road in self.roads)
        actual = WorldGoods.total(stocks)
        for good in WORLD_GOODS:
            expected = (
                self.ledger.initial_goods.amount(good)
                + self.ledger.produced.amount(good)
                - self.ledger.consumed.amount(good)
            )
            if actual.amount(good) != expected:
                raise ValueError(f"{good} 物资账不平：现存 {actual.amount(good)}，应为 {expected}")
        money = (
            sum(faction.wealth for faction in self.factions)
            + sum(region.market.coins for region in self.regions if region.market is not None)
            + sum(npc.life.coins for npc in self.npcs if npc.life is not None)
            + sum(road.repair_budget for road in self.roads)
        )
        if money != self.ledger.initial_money:
            raise ValueError(f"货币账不平：现存 {money}，初始 {self.ledger.initial_money}")
        return self

    def snapshot(self) -> Self:
        """Rebuild validated fields without recursively deep-copying model internals."""
        return type(self).model_validate(self.model_dump())


class WorldSummary(BaseModel):
    id: str
    name: str
    day: int
    running: bool
    npc_count: int
    updated_at: str
    ruleset: WorldRuleset = "classic"


class WorldCapabilities(BaseModel):
    ai_configured: bool
    provider: str
    ai_message: str
    realm_names: list[str] = Field(default_factory=lambda: list(REALM_NAMES))
    rulesets: list[WorldRuleset] = Field(default_factory=lambda: list(WORLD_RULESETS))
    persistent_history: bool = True
    profession_names: dict[WorldProfession, str] = Field(
        default_factory=lambda: dict(PROFESSION_NAMES)
    )
    good_names: dict[WorldGood, str] = Field(default_factory=lambda: dict(GOOD_NAMES))


class WorldHistoryPage(BaseModel):
    events: list[WorldEvent]
    next_before: int | None
    has_more: bool
