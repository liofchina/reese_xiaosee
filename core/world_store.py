import sqlite3
from contextlib import closing
from pathlib import Path

from models.world import WorldEvent, WorldHistoryPage, WorldState


class WorldStore:
    def __init__(self, path: Path = Path("data/worlds.db")):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS worlds (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS world_events (
                    world_id TEXT NOT NULL,
                    event_id INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    region_id TEXT,
                    npc_id TEXT,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (world_id, event_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS world_events_region "
                "ON world_events (world_id, region_id, event_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS world_events_npc "
                "ON world_events (world_id, npc_id, event_id)"
            )
            conn.commit()

    def load_all(self) -> list[WorldState]:
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute("SELECT state FROM worlds ORDER BY rowid DESC").fetchall()
        return [WorldState.model_validate_json(row[0]) for row in rows]

    def save(self, world: WorldState) -> None:
        events = {event.id: event for event in [*world.events, *world.pending_events]}
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO worlds (id, state) VALUES (?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET state = excluded.state",
                    (world.id, world.model_dump_json()),
                )
                conn.executemany(
                    "INSERT INTO world_events "
                    "(world_id, event_id, day, region_id, npc_id, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(world_id, event_id) DO NOTHING",
                    [
                        (
                            world.id,
                            event.id,
                            event.day,
                            event.region_id,
                            event.npc_id,
                            event.model_dump_json(),
                        )
                        for event in events.values()
                    ],
                )
        world.pending_events.clear()

    def history(
        self,
        world_id: str,
        *,
        before: int | None = None,
        limit: int = 40,
        region_id: str | None = None,
        npc_id: str | None = None,
    ) -> WorldHistoryPage:
        clauses = ["world_id = ?"]
        params: list[str | int] = [world_id]
        for field, value in (("event_id", before), ("region_id", region_id), ("npc_id", npc_id)):
            if value is not None:
                clauses.append(f"{field} {'<' if field == 'event_id' else '='} ?")
                params.append(value)
        params.append(limit + 1)
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute(
                "SELECT payload FROM world_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY event_id DESC LIMIT ?",
                params,
            ).fetchall()
        has_more = len(rows) > limit
        events = [WorldEvent.model_validate_json(row[0]) for row in rows[:limit]]
        return WorldHistoryPage(
            events=events,
            has_more=has_more,
            next_before=events[-1].id if has_more else None,
        )

    def event(self, world_id: str, event_id: int) -> WorldEvent | None:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT payload FROM world_events WHERE world_id = ? AND event_id = ?",
                (world_id, event_id),
            ).fetchone()
        return WorldEvent.model_validate_json(row[0]) if row else None

    def delete(self, world_id: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute("DELETE FROM world_events WHERE world_id = ?", (world_id,))
                conn.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
