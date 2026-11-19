import asyncio
import logging
import os
import sqlite3
import time
from contextlib import suppress

import httpx
from fastapi import HTTPException

from core.guardrails import get_guardrail_level, sanitize_input, scan_output
from core.llm_client import (
    BudgetExceededError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    create_client,
    validate_provider_config,
)
from core.world_store import WorldStore
from domain.world_simulation import advance_world, create_world, intervene_world, touch_world
from models.world import (
    PROFESSION_NAMES,
    REALM_NAMES,
    WorldAIEntry,
    WorldCapabilities,
    WorldChatRequest,
    WorldConfig,
    WorldControl,
    WorldEvent,
    WorldHistoryPage,
    WorldIntervention,
    WorldState,
    WorldSummary,
)

logger = logging.getLogger(__name__)


class WorldRuntime:
    def __init__(self, store: WorldStore | None = None):
        self.store = store if store is not None else WorldStore()
        self._worlds: dict[str, WorldState] = {}
        self._lock = asyncio.Lock()
        self._ai_lock = asyncio.Lock()
        self._next_ticks: dict[str, float] = {}
        self._clock: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.store.initialize()
        for world in self.store.load_all():
            if world.running and world.ruleset == "classic":
                world.running = False
                touch_world(world)
                self.store.save(world)
            self._worlds[world.id] = world
            if world.running:
                self._next_ticks[world.id] = time.monotonic() + world.interval_seconds
        self._clock = asyncio.create_task(self._run_clock())

    async def close(self) -> None:
        if self._clock is not None:
            self._clock.cancel()
            with suppress(asyncio.CancelledError):
                await self._clock
            self._clock = None
        async with self._lock:
            for world in list(self._worlds.values()):
                if world.running and world.ruleset == "classic":
                    paused = world.snapshot()
                    paused.running = False
                    touch_world(paused)
                    self._commit(paused)
            self._next_ticks.clear()

    @staticmethod
    def capabilities() -> WorldCapabilities:
        provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
        try:
            validate_provider_config()
        except EnvironmentError as exc:
            return WorldCapabilities(
                ai_configured=False,
                provider=provider,
                ai_message=f"{exc} 规则世界仍可正常演化。",
            )
        return WorldCapabilities(
            ai_configured=True,
            provider=provider,
            ai_message="AI 仅在你点击纪事或对话时调用；配置是否可用以实际请求为准。",
        )

    def list_worlds(self) -> list[WorldSummary]:
        return [
            WorldSummary(
                id=world.id,
                name=world.name,
                day=world.day,
                running=world.running,
                npc_count=len(world.npcs),
                updated_at=world.updated_at,
                ruleset=world.ruleset,
            )
            for world in sorted(
                self._worlds.values(), key=lambda item: item.updated_at, reverse=True
            )
        ]

    def get(self, world_id: str) -> WorldState:
        world = self._worlds.get(world_id)
        if world is None:
            raise HTTPException(status_code=404, detail="世界不存在，可能已被删除")
        return world.snapshot()

    def history(
        self, world_id: str, *, before: int | None = None, limit: int = 40,
        region_id: str | None = None, npc_id: str | None = None,
    ) -> WorldHistoryPage:
        self.get(world_id)
        return self.store.history(
            world_id, before=before, limit=limit, region_id=region_id, npc_id=npc_id
        )

    def event(self, world_id: str, event_id: int) -> WorldEvent:
        self.get(world_id)
        event = self.store.event(world_id, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="这条事实尚未归档或不存在")
        return event

    @staticmethod
    def _advance(world: WorldState) -> WorldState:
        try:
            return advance_world(world)
        except ValueError as exc:
            logger.exception("世界 %s 的规则校验失败", world.id)
            raise HTTPException(
                status_code=503,
                detail="世界规则校验失败，本次演化未提交；请检查服务日志后再继续",
            ) from exc

    def _commit(self, world: WorldState) -> None:
        try:
            self.store.save(world)
        except (sqlite3.Error, OSError) as exc:
            logger.exception("世界 %s 存档失败", world.id)
            raise HTTPException(
                status_code=503,
                detail="世界存档失败，请检查存储后重试；本次演化未提交",
            ) from exc
        self._worlds[world.id] = world

    async def create(self, config: WorldConfig) -> WorldState:
        async with self._lock:
            world = create_world(config)
            self._commit(world)
            return world.snapshot()

    async def control(self, world_id: str, command: WorldControl) -> WorldState:
        async with self._lock:
            world = self.get(world_id)
            if command.action == "step":
                if world.running:
                    raise HTTPException(status_code=409, detail="请先暂停世界，再手动推进")
                world = self._advance(world)
            else:
                world.running = command.action == "start"
                if command.interval_seconds is not None:
                    world.interval_seconds = command.interval_seconds
                world.last_error = ""
                touch_world(world)
            self._commit(world)
            if world.running:
                self._next_ticks[world_id] = time.monotonic() + world.interval_seconds
            else:
                self._next_ticks.pop(world_id, None)
            return world.snapshot()

    async def intervene(self, world_id: str, intervention: WorldIntervention) -> WorldState:
        async with self._lock:
            try:
                world = intervene_world(self.get(world_id), intervention)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            self._commit(world)
            return world.snapshot()

    async def delete(self, world_id: str) -> None:
        async with self._lock:
            self.get(world_id)
            try:
                self.store.delete(world_id)
            except (sqlite3.Error, OSError) as exc:
                logger.exception("删除世界 %s 失败", world_id)
                raise HTTPException(status_code=503, detail="删除世界存档失败，请稍后重试") from exc
            del self._worlds[world_id]
            self._next_ticks.pop(world_id, None)

    async def _run_clock(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            await self._tick_due(time.monotonic())

    async def _tick_due(self, now: float) -> None:
        async with self._lock:
            for world_id, due in list(self._next_ticks.items()):
                if now < due:
                    continue
                current = self._worlds[world_id]
                try:
                    self._commit(self._advance(current))
                except HTTPException as exc:
                    # 存储不可用时保留最后一次成功状态，并把暂停原因返回页面。
                    paused = current.snapshot()
                    paused.running = False
                    paused.last_error = str(exc.detail)
                    self._worlds[world_id] = paused
                    self._next_ticks.pop(world_id, None)
                    logger.error("世界 %s 自动演化已暂停：%s", world_id, exc.detail)
                else:
                    self._next_ticks[world_id] = now + current.interval_seconds

    async def ask_ai(
        self,
        world_id: str,
        chat: WorldChatRequest | None = None,
    ) -> WorldState:
        if self._ai_lock.locked():
            raise HTTPException(status_code=409, detail="已有 AI 请求正在进行，请稍后再试")
        async with self._ai_lock:
            snapshot = self.get(world_id)
            status = self.capabilities()
            if not status.ai_configured:
                raise HTTPException(status_code=503, detail=status.ai_message)
            question = chat.question if chat else ""
            if get_guardrail_level() != "none" and question:
                question, warnings = sanitize_input(question)
                if warnings:
                    raise HTTPException(
                        status_code=400, detail="输入检查未通过：" + "；".join(warnings)
                    )
            npc = None
            if chat:
                npc = next((person for person in snapshot.npcs if person.id == chat.npc_id), None)
                if npc is None:
                    raise HTTPException(status_code=404, detail="这位人物不在当前世界中")
                if npc.life is not None and npc.life.health == 0:
                    raise HTTPException(status_code=409, detail="这位人物已经逝去，请查阅其经历而非继续对话")
            facts = "\n".join(f"第{event.day}日：{event.detail}" for event in snapshot.events[-12:])
            if npc is not None:
                region = next(item for item in snapshot.regions if item.id == npc.region_id)
                if snapshot.ruleset == "living" and npc.life is not None:
                    life = npc.life
                    facts = "\n".join(
                        f"第{memory.day}日，{memory.detail}" for memory in life.memories[-10:]
                    )
                    known_markets = "\n".join(
                        f"{next(place.name for place in snapshot.regions if place.id == place_id)}："
                        f"第{knowledge.day}日得知粮价{knowledge.prices.food}，余粮{knowledge.stock.food}；可能过时。"
                        for place_id, knowledge in life.known_markets.items()
                    )
                    known_roads = "\n".join(
                        f"{next(road.name for road in snapshot.roads if road.id == road_id)}："
                        f"第{knowledge.day}日得知{'可通行' if knowledge.passable else '中断'}；可能过时。"
                        for road_id, knowledge in life.known_roads.items()
                    )
                    facts += f"\n已知市价：\n{known_markets}\n已知路况：\n{known_roads}"
                    instruction = (
                        f"扮演原创世界《{snapshot.name}》中的{npc.name}，职业{PROFESSION_NAMES[life.profession]}。"
                        f"最近停留地点：{region.name}；健康{life.health}，饥饿{life.hunger}，随身物资{life.inventory.model_dump()}。"
                        f"你的志向：{npc.goal}。最近行动：{npc.last_action}。"
                        f"当前计划：{life.plan.reason if life.plan else '尚在打算'}。"
                        "以下只有你已知的记忆，不代表全世界真相。不知道的事明确说不知道，"
                        "不得声称获得新物资、改变规则或替别人作决定。用80至150字回答。"
                        f"\n观察者问：{question}"
                    )
                else:
                    instruction = (
                        f"扮演原创仙侠世界《{snapshot.name}》中的{npc.name}。"
                        f"你在{region.name}，境界{REALM_NAMES[npc.realm]}，性情偏向{npc.trait}。"
                        f"你的志向：{npc.goal}。最近行动：{npc.last_action}。"
                        "只基于已知事实，用80至150字以角色口吻回答观察者，不虚构状态变化。"
                        f"\n观察者问：{question}"
                    )
            else:
                instruction = (
                    f"为原创世界《{snapshot.name}》第{snapshot.day}日写一则100至180字纪事。"
                    "把已发生的事件串成有画面感的短文，不发明新人物、结果或数值，不改变世界状态。"
                )
            prompt = f"{instruction}\n\n以下是规则引擎记录的事实：\n{facts}"

            from anthropic import APIError as AnthropicAPIError
            from openai import APIError as OpenAIAPIError

            try:
                client = create_client()
            except (ValueError, EnvironmentError) as exc:
                logger.warning("世界 AI 客户端配置错误：%s", type(exc).__name__)
                raise HTTPException(
                    status_code=503, detail="模型配置无效，请检查 .env 配置"
                ) from exc
            try:
                try:
                    text = await client.complete(
                        prompt,
                        max_tokens=600,
                        temperature=0.7,
                        agent_name="world_dialogue" if chat else "world_chronicle",
                    )
                finally:
                    await client.close()
            except BudgetExceededError as exc:
                raise HTTPException(
                    status_code=402,
                    detail="本次 AI 调用已达费用上限，可能已产生费用，请检查模型账单",
                ) from exc
            except (
                AnthropicAPIError,
                OpenAIAPIError,
                ProviderRateLimitError,
                ProviderUnavailableError,
                httpx.HTTPError,
                OSError,
            ) as exc:
                logger.warning("世界 AI 请求失败：%s", type(exc).__name__)
                raise HTTPException(
                    status_code=502,
                    detail="AI 请求失败，请检查模型配置和网络后重试；规则世界不受影响",
                ) from exc
            if not text.strip():
                logger.error("世界 %s 的 AI 返回空内容", world_id)
                raise HTTPException(status_code=502, detail="AI 返回了空内容，请重试")
            if get_guardrail_level() != "none":
                text, flags = scan_output(text)
                if flags:
                    logger.warning("世界 %s 的 AI 输出已由护栏处理", world_id)
            usage = client.get_cost_summary()
            async with self._lock:
                latest = self.get(world_id)
                latest.ai_entries.append(
                    WorldAIEntry(
                        kind="dialogue" if chat else "chronicle",
                        day=snapshot.day,
                        text=text.strip(),
                        npc_id=chat.npc_id if chat else None,
                        question=question,
                        tokens_in=usage["total_tokens_in"],
                        tokens_out=usage["total_tokens_out"],
                        cost_usd=usage["total_cost_usd"],
                    )
                )
                del latest.ai_entries[:-20]
                touch_world(latest)
                self._commit(latest)
                return latest.snapshot()
