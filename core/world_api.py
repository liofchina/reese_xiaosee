from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from core.world_runtime import WorldRuntime
from models.world import (
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

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


def _runtime(request: Request) -> WorldRuntime:
    runtime = getattr(request.app.state, "world_runtime", None)
    if not isinstance(runtime, WorldRuntime):
        raise HTTPException(status_code=503, detail="世界服务尚未启动")
    return runtime


@router.get("/capabilities")
async def capabilities() -> WorldCapabilities:
    return WorldRuntime.capabilities()


@router.get("")
async def list_worlds(request: Request) -> list[WorldSummary]:
    return _runtime(request).list_worlds()


@router.post("", status_code=201)
async def create_world(request: Request, config: WorldConfig) -> WorldState:
    return await _runtime(request).create(config)


@router.get("/{world_id}")
async def get_world(request: Request, world_id: UUID) -> WorldState:
    return _runtime(request).get(str(world_id))


@router.get("/{world_id}/events")
async def world_history(
    request: Request,
    world_id: UUID,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=40, ge=1, le=100),
    region_id: str | None = Query(default=None, max_length=40),
    npc_id: str | None = Query(default=None, max_length=40),
) -> WorldHistoryPage:
    return _runtime(request).history(
        str(world_id), before=before, limit=limit, region_id=region_id, npc_id=npc_id
    )


@router.get("/{world_id}/events/{event_id}")
async def world_fact(request: Request, world_id: UUID, event_id: int) -> WorldEvent:
    if event_id < 1:
        raise HTTPException(status_code=422, detail="事实编号必须大于0")
    return _runtime(request).event(str(world_id), event_id)


@router.post("/{world_id}/control")
async def control_world(request: Request, world_id: UUID, command: WorldControl) -> WorldState:
    return await _runtime(request).control(str(world_id), command)


@router.post("/{world_id}/intervene")
async def intervene_world(
    request: Request,
    world_id: UUID,
    intervention: WorldIntervention,
) -> WorldState:
    return await _runtime(request).intervene(str(world_id), intervention)


@router.post("/{world_id}/chronicle")
async def world_chronicle(request: Request, world_id: UUID) -> WorldState:
    return await _runtime(request).ask_ai(str(world_id))


@router.post("/{world_id}/chat")
async def world_chat(request: Request, world_id: UUID, chat: WorldChatRequest) -> WorldState:
    return await _runtime(request).ask_ai(str(world_id), chat)


@router.delete("/{world_id}", status_code=204)
async def delete_world(request: Request, world_id: UUID) -> Response:
    await _runtime(request).delete(str(world_id))
    return Response(status_code=204)
