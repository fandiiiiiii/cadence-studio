"""SQLite persistence. Short-lived connections + WAL keep worker writes safe."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  mode TEXT NOT NULL DEFAULT 'live',
  spec_json TEXT NOT NULL,
  route_snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  file_name TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  inference_path TEXT NOT NULL DEFAULT '',
  mime TEXT NOT NULL DEFAULT '',
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL DEFAULT '',
  duration_sec REAL,
  sample_rate INTEGER,
  channels INTEGER,
  bitrate INTEGER,
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0,
  raw_text TEXT NOT NULL DEFAULT '',
  llm_raw_text TEXT NOT NULL DEFAULT '',
  normalized_json TEXT,
  summary_json TEXT,
  error_code TEXT NOT NULL DEFAULT '',
  error_message TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  inference_route_id TEXT NOT NULL DEFAULT '',
  inference_model TEXT NOT NULL DEFAULT '',
  llm_route_id TEXT NOT NULL DEFAULT '',
  llm_model TEXT NOT NULL DEFAULT '',
  timings_json TEXT NOT NULL DEFAULT '{}',
  review_status TEXT NOT NULL DEFAULT 'unreviewed',
  review_note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_batch_position ON items(batch_id, position);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_batch_status ON items(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_batches_created ON batches(created_at DESC);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT,
  item_id TEXT,
  kind TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_batch ON events(batch_id, id);

CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT,
  item_id TEXT,
  stage TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  input_units INTEGER NOT NULL DEFAULT 0,
  output_units INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self._lock, self.connection() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '1')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('created_at', ?)", (utc_now(),)
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    @staticmethod
    def _json_load(value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    # ------------------------------------------------------------------ batches
    def create_batch(
        self,
        name: str,
        spec: dict[str, Any],
        route_snapshot: dict[str, Any],
        *,
        note: str = "",
        mode: str = "live",
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        batch_id = batch_id or new_id("bat")
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO batches(id,name,note,status,mode,spec_json,route_snapshot_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    batch_id,
                    name,
                    note,
                    "draft",
                    mode,
                    json.dumps(spec, ensure_ascii=False),
                    json.dumps(route_snapshot, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_batch(batch_id) or {}

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                return None
            batch = dict(row)
            counts = conn.execute(
                "SELECT status, COUNT(*) AS n FROM items WHERE batch_id=? GROUP BY status", (batch_id,)
            ).fetchall()
        batch["spec"] = self._json_load(batch.pop("spec_json"), {})
        batch["route_snapshot"] = self._json_load(batch.pop("route_snapshot_json"), {})
        counts_map = {row["status"]: row["n"] for row in counts}
        total = sum(counts_map.values())
        completed = counts_map.get("completed", 0)
        failed = counts_map.get("failed", 0)
        batch["counts"] = {
            "total": total,
            "queued": counts_map.get("queued", 0),
            "running": sum(
                counts_map.get(status, 0)
                for status in ("preprocessing", "inferencing", "normalizing", "saving")
            ),
            "completed": completed,
            "failed": failed,
            "canceled": counts_map.get("canceled", 0),
        }
        batch["progress"] = round(100 * (completed + failed) / total, 1) if total else 0.0
        batch["success_rate"] = round(100 * completed / total, 1) if total else 0.0
        return batch

    def list_batches(
        self,
        *,
        query: str = "",
        status: str = "",
        mode: str = "",
        limit: int = 50,
        offset: int = 0,
        archived: bool = False,
    ) -> dict[str, Any]:
        where = ["archived=?"]
        params: list[Any] = [1 if archived else 0]
        if query.strip():
            where.append("(name LIKE ? OR note LIKE ? OR id LIKE ?)")
            term = f"%{query.strip()}%"
            params.extend([term, term, term])
        if status:
            where.append("status=?")
            params.append(status)
        if mode:
            where.append("mode=?")
            params.append(mode)
        clause = " AND ".join(where)
        with self.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM batches WHERE {clause}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM batches WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            items = [dict(row) for row in rows]
            for batch in items:
                batch["spec"] = self._json_load(batch.pop("spec_json"), {})
                batch["route_snapshot"] = self._json_load(batch.pop("route_snapshot_json"), {})
                counts = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM items WHERE batch_id=? GROUP BY status", (batch["id"],)
                ).fetchall()
                counts_map = {row["status"]: row["n"] for row in counts}
                batch_total = sum(counts_map.values())
                batch["counts"] = {
                    "total": batch_total,
                    "completed": counts_map.get("completed", 0),
                    "failed": counts_map.get("failed", 0),
                    "queued": counts_map.get("queued", 0),
                    "running": sum(
                        counts_map.get(s, 0)
                        for s in ("preprocessing", "inferencing", "normalizing", "saving")
                    ),
                }
                batch["progress"] = (
                    round(100 * (batch["counts"]["completed"] + batch["counts"]["failed"]) / batch_total, 1)
                    if batch_total
                    else 0.0
                )
        return {"total": total, "items": items, "limit": limit, "offset": offset}

    def update_batch(self, batch_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"name", "note", "status", "archived", "started_at", "finished_at", "route_snapshot_json"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_batch(batch_id)
        updates["updated_at"] = utc_now()
        if "route_snapshot" in updates:
            updates["route_snapshot_json"] = json.dumps(updates.pop("route_snapshot"), ensure_ascii=False)
        set_clause = ", ".join(f"{key}=?" for key in updates)
        with self.connection() as conn:
            conn.execute(f"UPDATE batches SET {set_clause} WHERE id=?", [*updates.values(), batch_id])
        return self.get_batch(batch_id)

    def delete_batch(self, batch_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
            conn.execute("DELETE FROM events WHERE batch_id=?", (batch_id,))
            return cursor.rowcount > 0

    # -------------------------------------------------------------------- items
    def add_items(self, batch_id: str, items: list[dict[str, Any]]) -> int:
        now = utc_now()
        with self.connection() as conn:
            for item in items:
                conn.execute(
                    """INSERT INTO items(
                         id,batch_id,position,file_name,stored_path,inference_path,mime,size_bytes,sha256,
                         duration_sec,sample_rate,channels,bitrate,status,stage,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item["id"],
                        batch_id,
                        item["position"],
                        item["file_name"],
                        item["stored_path"],
                        item.get("inference_path", ""),
                        item.get("mime", ""),
                        item.get("size_bytes", 0),
                        item.get("sha256", ""),
                        item.get("duration_sec"),
                        item.get("sample_rate"),
                        item.get("channels"),
                        item.get("bitrate"),
                        "queued",
                        "queued",
                        now,
                        now,
                    ),
                )
        return len(items)

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._decorate_item(row)

    def _decorate_item(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["normalized"] = self._json_load(item.pop("normalized_json", None), None)
        item["summary"] = self._json_load(item.pop("summary_json", None), {})
        item["timings"] = self._json_load(item.pop("timings_json", None), {})
        return item

    def list_items(
        self,
        batch_id: str,
        *,
        query: str = "",
        status: str = "",
        limit: int = 200,
        offset: int = 0,
        sort: str = "position",
        full: bool = False,
    ) -> dict[str, Any]:
        where = ["batch_id=?"]
        params: list[Any] = [batch_id]
        if query.strip():
            term = f"%{query.strip()}%"
            where.append(
                "(file_name LIKE ? OR raw_text LIKE ? OR normalized_json LIKE ? OR error_message LIKE ?)"
            )
            params.extend([term, term, term, term])
        if status:
            where.append("status=?")
            params.append(status)
        clause = " AND ".join(where)
        order = {
            "position": "position ASC",
            "newest": "created_at DESC",
            "duration": "duration_sec DESC",
            "updated": "updated_at DESC",
        }.get(sort, "position ASC")
        columns = (
            "id,batch_id,position,file_name,mime,size_bytes,sha256,duration_sec,sample_rate,channels,bitrate,"
            "status,stage,progress,error_code,error_message,attempts,next_retry_at,inference_route_id,"
            "inference_model,llm_route_id,llm_model,review_status,review_note,created_at,updated_at,"
            "started_at,finished_at,summary_json"
        )
        if full:
            columns = "*"
        with self.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM items WHERE {clause}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT {columns} FROM items WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "items": [self._decorate_item(row) for row in rows], "limit": limit, "offset": offset}

    def claim_item(self, item_id: str, stage: str = "preprocessing") -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as conn:
            cur = conn.execute(
                """UPDATE items SET status=?, stage=?, progress=5, updated_at=?, started_at=COALESCE(started_at,?),
                     next_retry_at=NULL, error_code='', error_message=''
                   WHERE id=? AND status='queued'""",
                (stage, stage, now, now, item_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._decorate_item(row)

    def queued_items(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT i.* FROM items i JOIN batches b ON b.id=i.batch_id
                   WHERE i.status='queued' AND b.status IN ('queued','running') AND b.archived=0
                     AND (i.next_retry_at IS NULL OR i.next_retry_at <= ?)
                   ORDER BY b.created_at ASC, i.position ASC LIMIT ?""",
                (utc_now(), limit),
            ).fetchall()
        return [self._decorate_item(row) for row in rows if row is not None]

    def queued_item(self) -> dict[str, Any] | None:
        items = self.queued_items(1)
        return items[0] if items else None

    def update_item(self, item_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "stage",
            "progress",
            "raw_text",
            "llm_raw_text",
            "normalized_json",
            "summary_json",
            "error_code",
            "error_message",
            "attempts",
            "next_retry_at",
            "inference_route_id",
            "inference_model",
            "llm_route_id",
            "llm_model",
            "timings_json",
            "review_status",
            "review_note",
            "finished_at",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"normalized_json", "summary_json", "timings_json"} and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False) if value is not None else None
            updates[key] = value
        if not updates:
            return self.get_item(item_id)
        updates["updated_at"] = utc_now()
        set_clause = ", ".join(f"{key}=?" for key in updates)
        with self.connection() as conn:
            conn.execute(f"UPDATE items SET {set_clause} WHERE id=?", [*updates.values(), item_id])
        return self.get_item(item_id)

    def set_item_state(
        self,
        item_id: str,
        status: str,
        stage: str,
        progress: int,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any] | None:
        fields: dict[str, Any] = {
            "status": status,
            "stage": stage,
            "progress": progress,
            "error_code": error_code,
            "error_message": error_message,
        }
        if status in {"completed", "failed", "canceled"}:
            fields["finished_at"] = utc_now()
        return self.update_item(item_id, **fields)

    def reset_interrupted(self) -> int:
        now = utc_now()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id,status,raw_text FROM items WHERE status IN ('preprocessing','inferencing','normalizing','saving')"
            ).fetchall()
            for row in rows:
                stage = "resume_normalize" if row["status"] == "normalizing" and row["raw_text"] else "queued"
                conn.execute(
                    "UPDATE items SET status='queued', stage=?, progress=0, error_message=?, updated_at=? WHERE id=?",
                    (stage, "工作台重启，已重新入队", now, row["id"]),
                )
            conn.execute(
                "UPDATE batches SET status='queued', updated_at=? WHERE status='running'", (now,)
            )
        return len(rows)

    def batch_counts(self, batch_id: str) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM items WHERE batch_id=? GROUP BY status", (batch_id,)
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def refresh_batch_status(self, batch_id: str) -> dict[str, Any] | None:
        batch = self.get_batch(batch_id)
        if not batch or batch["status"] in {"paused", "canceled", "draft"}:
            return batch
        counts = batch["counts"]
        total = counts["total"]
        if total == 0:
            return batch
        running = counts["running"]
        queued = counts["queued"]
        done = counts["completed"] + counts["failed"] + counts["canceled"]
        if done >= total:
            status = "completed" if counts["failed"] == 0 and counts["canceled"] == 0 else "completed_with_errors"
            return self.update_batch(batch_id, status=status, finished_at=utc_now())
        if running > 0:
            return self.update_batch(batch_id, status="running", started_at=batch.get("started_at") or utc_now())
        if queued > 0:
            return self.update_batch(batch_id, status="queued")
        return batch

    def set_batch_items_status(self, batch_id: str, from_statuses: tuple[str, ...], to_status: str) -> int:
        if not from_statuses:
            return 0
        placeholders = ",".join("?" for _ in from_statuses)
        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE items SET status=?, stage=?, updated_at=? WHERE batch_id=? AND status IN ({placeholders})",
                (to_status, to_status, utc_now(), batch_id, *from_statuses),
            )
            return cursor.rowcount

    def retry_item(self, item_id: str, *, normalize_only: bool = False) -> dict[str, Any] | None:
        item = self.get_item(item_id)
        if not item:
            return None
        fields: dict[str, Any] = {
            "status": "queued",
            "stage": "resume_normalize" if normalize_only and item.get("raw_text") else "queued",
            "progress": 0,
            "error_code": "",
            "error_message": "",
            "finished_at": None,
            "next_retry_at": None,
        }
        if not normalize_only:
            fields["raw_text"] = ""
            fields["normalized_json"] = None
            fields["summary_json"] = None
            fields["llm_raw_text"] = ""
            fields["attempts"] = 0
        self.update_item(item_id, **fields)
        self.update_batch(item["batch_id"], status="queued", finished_at=None)
        return self.get_item(item_id)

    # ------------------------------------------------------------------- events
    def add_event(
        self,
        kind: str,
        message: str,
        *,
        batch_id: str | None = None,
        item_id: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO events(batch_id,item_id,kind,level,message,data_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    batch_id,
                    item_id,
                    kind,
                    level,
                    message,
                    json.dumps(data or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def recent_events(self, *, limit: int = 100, level: str = "") -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if level:
            where.append("level=?")
            params.append(level)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        result = [dict(row) for row in rows]
        for event in result:
            event["data"] = self._json_load(event.pop("data_json"), {})
        return result

    def list_events(
        self, *, since_id: int = 0, batch_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        where = ["id>?"]
        params: list[Any] = [since_id]
        if batch_id:
            where.append("batch_id=?")
            params.append(batch_id)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id ASC LIMIT ?",
                [*params, limit],
            ).fetchall()
        result = [dict(row) for row in rows]
        for event in result:
            event["data"] = self._json_load(event.pop("data_json"), {})
        return result

    # -------------------------------------------------------------------- usage
    def add_usage(
        self,
        *,
        stage: str,
        provider: str = "",
        model: str = "",
        latency_ms: int = 0,
        input_units: int = 0,
        output_units: int = 0,
        batch_id: str | None = None,
        item_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO usage(batch_id,item_id,stage,provider,model,latency_ms,input_units,output_units,meta_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    batch_id,
                    item_id,
                    stage,
                    provider,
                    model,
                    latency_ms,
                    input_units,
                    output_units,
                    json.dumps(meta or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )

    # -------------------------------------------------------------------- stats
    def overview(self) -> dict[str, Any]:
        today = datetime.now(UTC).date().isoformat()
        with self.connection() as conn:
            counts = conn.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status").fetchall()
            total_batches = conn.execute("SELECT COUNT(*) AS n FROM batches WHERE archived=0").fetchone()["n"]
            today_items = conn.execute(
                "SELECT COUNT(*) AS n FROM items WHERE status='completed' AND finished_at LIKE ?",
                (f"{today}%",),
            ).fetchone()["n"]
            today_duration = conn.execute(
                "SELECT COALESCE(SUM(duration_sec),0) AS n FROM items WHERE status='completed' AND finished_at LIKE ?",
                (f"{today}%",),
            ).fetchone()["n"]
            total_duration = conn.execute(
                "SELECT COALESCE(SUM(duration_sec),0) AS n FROM items WHERE status='completed'"
            ).fetchone()["n"]
            active = conn.execute(
                "SELECT COUNT(*) AS n FROM batches WHERE status IN ('queued','running') AND archived=0"
            ).fetchone()["n"]
            recent = conn.execute(
                "SELECT id,name,status,mode,created_at,updated_at FROM batches WHERE archived=0 ORDER BY updated_at DESC LIMIT 5"
            ).fetchall()
            recent_items = []
            for row in recent:
                batch = dict(row)
                batch_counts = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM items WHERE batch_id=? GROUP BY status", (batch["id"],)
                ).fetchall()
                count_map = {entry["status"]: entry["n"] for entry in batch_counts}
                total = sum(count_map.values())
                batch["counts"] = {
                    "total": total,
                    "completed": count_map.get("completed", 0),
                    "failed": count_map.get("failed", 0),
                    "queued": count_map.get("queued", 0),
                    "running": sum(count_map.get(s, 0) for s in ("preprocessing", "inferencing", "normalizing", "saving")),
                }
                batch["progress"] = (
                    round(100 * (batch["counts"]["completed"] + batch["counts"]["failed"]) / total, 1) if total else 0
                )
                recent_items.append(batch)
        status_map = {row["status"]: row["n"] for row in counts}
        return {
            "total_batches": total_batches,
            "active_batches": active,
            "today_completed": today_items,
            "today_completed_minutes": round(float(today_duration or 0) / 60, 1),
            "total_completed": status_map.get("completed", 0),
            "total_items": sum(status_map.values()),
            "completed": status_map.get("completed", 0),
            "failed": status_map.get("failed", 0),
            "queued": status_map.get("queued", 0),
            "running": sum(status_map.get(s, 0) for s in ("preprocessing", "inferencing", "normalizing", "saving")),
            "total_audio_minutes": round(float(total_duration or 0) / 60, 1),
            "recent_batches": recent_items,
        }


DB = Database()
