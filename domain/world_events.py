from datetime import datetime, timezone

from models.world import WorldEffect, WorldEvent, WorldState

MAX_WORLD_EVENTS = 200


def touch_world(world: WorldState) -> None:
    world.revision += 1
    world.updated_at = datetime.now(timezone.utc).isoformat()


def record_event(
    world: WorldState,
    kind: str,
    title: str,
    detail: str,
    region_id: str | None = None,
    npc_id: str | None = None,
    *,
    cause_ids: list[int] | None = None,
    effects: list[WorldEffect] | None = None,
) -> WorldEvent:
    causes = list(dict.fromkeys(cause_ids or []))
    if any(cause < 1 or cause >= world.next_event_id for cause in causes):
        raise ValueError("事件原因必须指向已经发生的事实")
    event = WorldEvent(
        id=world.next_event_id,
        day=world.day,
        kind=kind,
        title=title,
        detail=detail,
        region_id=region_id,
        npc_id=npc_id,
        cause_ids=causes,
        effects=effects or [],
    )
    world.events.append(event)
    # A busy day may produce more facts than the public recent-history window.
    world.pending_events.append(event)
    world.next_event_id += 1
    del world.events[:-MAX_WORLD_EVENTS]
    return event
