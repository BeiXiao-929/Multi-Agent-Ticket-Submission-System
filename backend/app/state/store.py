"""Shared state layer: SQLite for durable ticket records, optional Redis for
caching and distributed locks.

Design notes
------------
- SQLite runs in WAL mode for concurrent reader/writer.
- A per-ticket snapshot row is written whenever editable ticket data changes,
  providing a local change history for auditing and diagnostics.
- A `version` integer field provides optimistic locking; writers must pass the
  version they read when updating.
- When REDIS_URL is configured, a mirror copy of ticket state is written to
  Redis with a short TTL so read-heavy consumers (dashboards, websockets)
  can avoid SQLite round-trips.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from ..config import settings

logger = logging.getLogger(__name__)


class TicketStore:
    """Thin synchronous SQLite store (thread-safe via a single lock)."""

    _lock = threading.Lock()
    _conn: sqlite3.Connection | None = None
    _redis: object | None = None
    # Set to True (outside the lock) once the connection has been created,
    # so that conn() never re-enters create_schema() while the lock is held.
    _init_lock = threading.Lock()

    @classmethod
    def create_schema(cls) -> None:
        """Create the SQLite schema and connection exactly once.

        Safe to call from any thread at any time. Internally guards with a
        dedicated ``_init_lock`` (distinct from the I/O ``_lock``) so that it
        can be invoked from within a ``with cls._lock`` block without
        deadlocking.
        """
        with cls._init_lock:
            if cls._conn is not None:
                return
            conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    submitter TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'created',
                    primary_dept TEXT,
                    confidence REAL,
                    multi_intent INTEGER DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
                CREATE INDEX IF NOT EXISTS idx_tickets_dept ON tickets(primary_dept);

                CREATE TABLE IF NOT EXISTS sub_tickets (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    dept TEXT NOT NULL,
                    intent_label TEXT,
                    status TEXT NOT NULL DEFAULT 'created',
                    confidence REAL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sub_parent ON sub_tickets(parent_id);

                CREATE TABLE IF NOT EXISTS snapshots (
                    ticket_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY (ticket_id, seq)
                );
                """
            )
            conn.commit()
            cls._conn = conn

            if settings.use_redis:
                try:
                    import redis  # type: ignore
                    cls._redis = redis.from_url(settings.redis_url, decode_responses=True)
                    cls._redis.ping()
                    logger.info("Redis connection established: %s", settings.redis_url)
                except Exception as exc:  # pragma: no cover
                    logger.warning("Redis unavailable (%s); falling back to SQLite only", exc)
                    cls._redis = None

    @classmethod
    def conn(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls.create_schema()
        assert cls._conn is not None
        return cls._conn

    @classmethod
    def _now(cls) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"

    @classmethod
    def save_ticket(cls, ticket: dict) -> None:
        with cls._lock:
            conn = cls.conn()
            now = cls._now()
            conn.execute(
                """
                INSERT INTO tickets
                  (id, title, description, submitter, priority, status,
                   primary_dept, confidence, multi_intent, version,
                   created_at, updated_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ticket["id"], ticket["title"], ticket["description"],
                    ticket["submitter"], ticket.get("priority", "normal"),
                    ticket.get("status", "created"),
                    ticket.get("primary_dept"), ticket.get("confidence"),
                    1 if ticket.get("multi_intent") else 0,
                    ticket.get("version", 1),
                    ticket.get("created_at", now), now,
                    json.dumps(ticket.get("meta", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
            cls._mirror_to_redis(ticket, sub=None)

    @classmethod
    def update_ticket(cls, ticket_id: str, patch: dict, expected_version: int | None = None) -> bool:
        with cls._lock:
            conn = cls.conn()
            now = cls._now()
            set_clause = ["version = version + 1", "updated_at = ?"]
            values: list = [now]
            for k in (
                "title", "description", "submitter", "priority",
                "status", "primary_dept", "confidence", "meta",
            ):
                if k in patch:
                    set_clause.append(f"{k} = ?")
                    values.append(patch[k] if k != "meta" else json.dumps(patch[k], ensure_ascii=False))
            sql = f"UPDATE tickets SET {', '.join(set_clause)} WHERE id = ?"
            values.append(ticket_id)
            if expected_version is not None:
                values.append(expected_version)
                sql += " AND version = ?"
            cur = conn.execute(sql, values)
            conn.commit()
            if cur.rowcount == 0:
                if expected_version is not None:
                    logger.warning("Optimistic lock failed for ticket %s", ticket_id)
                else:
                    logger.warning("Ticket not found while updating: %s", ticket_id)
                return False
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            cls._write_snapshot(ticket_id, row)
            cls._mirror_to_redis(row, sub=None)
            return True

    @classmethod
    def get_ticket(cls, ticket_id: str) -> dict | None:
        with cls._lock:
            conn = cls.conn()
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return cls._row_to_ticket(row)

    @classmethod
    def delete_ticket(cls, ticket_id: str) -> bool:
        """Delete a parent ticket and all dependent local records."""
        with cls._lock:
            conn = cls.conn()
            row = conn.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if row is None:
                return False
            try:
                conn.execute("DELETE FROM snapshots WHERE ticket_id = ?", (ticket_id,))
                conn.execute("DELETE FROM sub_tickets WHERE parent_id = ?", (ticket_id,))
                conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if cls._redis is not None:
            try:
                cls._redis.delete(f"ticket:{ticket_id}")
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis mirror delete failed: %s", exc)
        return True

    @classmethod
    def list_tickets(cls, limit: int = 50, offset: int = 0) -> list[dict]:
        with cls._lock:
            conn = cls.conn()
            rows = conn.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [cls._row_to_ticket(r) for r in rows]

    @classmethod
    def save_sub_ticket(cls, sub: dict) -> None:
        with cls._lock:
            conn = cls.conn()
            now = cls._now()
            conn.execute(
                """
                INSERT INTO sub_tickets
                  (id, parent_id, dept, intent_label, status, confidence,
                   version, created_at, updated_at, result)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sub["id"], sub["parent_id"], sub["dept"],
                    sub.get("intent_label"), sub.get("status", "created"),
                    sub.get("confidence"), sub.get("version", 1),
                    sub.get("created_at", now), now,
                    json.dumps(sub.get("result"), ensure_ascii=False),
                ),
            )
            conn.commit()

    @classmethod
    def get_sub_ticket(cls, sub_id: str) -> dict | None:
        """Fetch one sub-ticket by primary key (used by the waiting_info
        append flow and the orchestrator's SLA watchdog)."""
        with cls._lock:
            conn = cls.conn()
            row = conn.execute("SELECT * FROM sub_tickets WHERE id = ?", (sub_id,)).fetchone()
            return cls._row_to_sub(row)

    @classmethod
    def update_sub_ticket(cls, sub_id: str, patch: dict) -> None:
        with cls._lock:
            conn = cls.conn()
            now = cls._now()
            set_clause = ["version = version + 1", "updated_at = ?"]
            values: list = [now]
            for k in ("dept", "intent_label", "status", "confidence", "result"):
                if k in patch:
                    set_clause.append(f"{k} = ?")
                    values.append(patch[k] if k != "result" else json.dumps(patch[k], ensure_ascii=False))
            values.append(sub_id)
            conn.execute(
                f"UPDATE sub_tickets SET {', '.join(set_clause)} WHERE id = ?",
                values,
            )
            conn.commit()

    @classmethod
    def list_sub_tickets(cls, parent_id: str) -> list[dict]:
        with cls._lock:
            conn = cls.conn()
            rows = conn.execute(
                "SELECT * FROM sub_tickets WHERE parent_id = ? ORDER BY created_at",
                (parent_id,),
            ).fetchall()
            return [cls._row_to_sub(r) for r in rows]

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    @classmethod
    def _write_snapshot(cls, ticket_id: str, row) -> None:
        conn = cls.conn()
        row_dict = cls._row_to_ticket(row); seq = row_dict.get("version", 0) + 1
        payload = json.dumps(cls._row_to_ticket(row), ensure_ascii=False, default=str)
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (ticket_id, seq, payload, captured_at) VALUES (?,?,?,?)",
            (ticket_id, seq, payload, cls._now()),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Redis mirror (best effort)
    # ------------------------------------------------------------------
    @classmethod
    def _mirror_to_redis(cls, ticket: dict, sub: dict | None) -> None:
        if cls._redis is None:
            return
        try:
            key = f"ticket:{ticket['id']}" if sub is None else f"ticket:sub:{sub['id']}"
            payload = json.dumps(sub or ticket, ensure_ascii=False, default=str)
            cls._redis.set(key, payload, ex=3600)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis mirror write failed: %s", exc)

    @classmethod
    def _row_to_ticket(cls, row) -> dict | None:
        if row is None:
            return None
        cols = [c[0] for c in cls.conn().execute("SELECT * FROM tickets").description]
        d = dict(zip(cols, row, strict=True))
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["multi_intent"] = bool(d.get("multi_intent"))
        return d

    @classmethod
    def _row_to_sub(cls, row) -> dict | None:
        if row is None:
            return None
        cols = [c[0] for c in cls.conn().execute("SELECT * FROM sub_tickets").description]
        d = dict(zip(cols, row, strict=True))
        d["result"] = json.loads(d.get("result") or "null")
        return d
