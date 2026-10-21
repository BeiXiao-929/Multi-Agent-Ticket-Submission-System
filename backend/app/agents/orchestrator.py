"""Ticket classification, routing, lifecycle, SLA, and result aggregation."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from ..config import settings
from ..core.llm import classify_with_fallback
from ..state.store import TicketStore

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates the whole ticket lifecycle.

    Thread model
    ------------
    Each sub-ticket is handed to a background thread in the agent
    registry. The orchestrator owns an SLA watchdog that periodically
    checks every open sub-ticket and escalates when its SLA expires.
    """

    def __init__(self) -> None:
        self._escalation_lock = threading.Lock()
        self._last_escalated: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def handle_submission(self, payload: dict) -> dict:
        """Accept a raw ticket, classify it, split into sub-tickets,
        dispatch them, and return the primary routing decision."""
        from .registry import get_registry

        ticket_id = str(uuid.uuid4())
        now_iso = _now_iso()

        text = f"{payload.get('title', '')} {payload.get('content', '')}".strip()
        cls = classify_with_fallback(text)
        logger.info(
            "Ticket %s -> %s (confidence=%.2f, multi=%s, source=%s)",
            ticket_id, cls["primary_dept"], cls["confidence"],
            cls["multi_intent"], cls.get("source", "?"),
        )

        ticket = {
            "id": ticket_id,
            "title": payload.get("title", "(untitled)"),
            "description": payload.get("content", text),
            "submitter": payload.get("submitter", "anonymous"),
            "priority": payload.get("priority", "normal"),
            "status": "created",
            "primary_dept": cls["primary_dept"],
            "confidence": cls["confidence"],
            "multi_intent": cls["multi_intent"],
            "created_at": now_iso,
            "meta": {
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "hint": cls.get("hint"),
            },
        }
        TicketStore.save_ticket(ticket)
        TicketStore.update_ticket(ticket_id, {"status": "routed"}, expected_version=1)

        registry = get_registry()
        sub_tickets = self._build_sub_tickets(ticket, cls)
        for st in sub_tickets:
            registry.dispatch(st["dept"], st)

        return {
            "ticket_id": ticket_id,
            "primary_dept": cls["primary_dept"],
            "confidence": cls["confidence"],
            "multi_intent": cls["multi_intent"],
            "sub_intents": cls["sub_intents"],
            "sub_ticket_ids": [s["id"] for s in sub_tickets],
            "hint": cls.get("hint"),
        }

    # ------------------------------------------------------------------
    # Multi-intent splitting
    # ------------------------------------------------------------------
    def _build_sub_tickets(self, ticket: dict, cls: dict) -> list[dict]:
        """Fan one parent ticket out to one sub-ticket per intent.

        - Every dept in ``cls["sub_intents"]`` becomes its own sub-ticket
          (this is what makes the "one parent -> N agents" collaboration
          visible in the UI).
        - The primary intent always appears, even when the LLM reports a
          single intent.
        - A sub's SLA is the department SLA.
        """
        base_id = ticket["id"]
        now_iso = _now_iso()
        sla_map = settings.sla_seconds

        subs: list[dict] = []
        intents = cls["sub_intents"]
        if not intents:
            intents = [{"dept": cls["primary_dept"], "confidence": cls["confidence"], "span": ""}]

        # de-dup departments while preserving order
        ordered: list[dict] = []
        seen: set[str] = set()
        for it in intents:
            dept = it.get("dept")
            if dept in seen:
                continue
            seen.add(dept)
            ordered.append(it)
        # ensure primary is present
        if cls["primary_dept"] not in seen:
            ordered.insert(0, {"dept": cls["primary_dept"], "confidence": cls["confidence"], "span": ""})

        for idx, intent in enumerate(ordered):
            subs.append(self._make_sub(
                base_id, idx + 1,
                intent.get("dept", cls["primary_dept"]),
                intent.get("confidence", 0.5),
                now_iso, sla_map,
                intent_label=intent.get("span", ""),
            ))
        for s in subs:
            TicketStore.save_sub_ticket(s)
        return subs

    @staticmethod
    def _make_sub(parent_id: str, idx: int, dept: str, confidence: float,
                  now_iso: str, sla_map: dict, intent_label: str = "") -> dict:
        return {
            "id": f"{parent_id}-{idx}",
            "parent_id": parent_id,
            "dept": dept,
            "intent_label": intent_label or dept,
            "confidence": confidence,
            "status": "created",
            "created_at": now_iso,
            "sla_seconds": sla_map.get(dept, 120),
            "result": None,
        }

    # ------------------------------------------------------------------
    # SLA watchdog
    # ------------------------------------------------------------------
    def scan_sla_breaches(self) -> None:
        """Periodically called by a watchdog thread. Escalates any sub-
        ticket that has been open longer than its SLA without reaching
        ``resolved``. Also re-escalates parked ``waiting_info`` subs that
        sit idle for too long (a user-supplied follow-up should arrive)."""
        now = time.time()
        with self._escalation_lock:
            for sub in _open_sub_tickets():
                created = sub.get("created_at")
                if not created:
                    continue
                age = now - _parse_iso(created)
                sla = sub.get("sla_seconds", 120)
                if sub.get("status") == "waiting_info":
                    grace = max(sla, 120)
                    if age <= grace:
                        continue
                elif age <= sla:
                    continue
                last = self._last_escalated.get(sub["id"], 0.0)
                if now - last < 30:  # don't spam escalations every second
                    continue
                self._last_escalated[sub["id"]] = now
                reason = "SLA breach" if sub.get("status") != "waiting_info" else "waiting_info 超时未补充"
                logger.warning(
                    "SLA breach: sub-ticket %s (%s, status=%s) open for %.0fs (%s); escalating",
                    sub["id"], sub["dept"], sub.get("status"), age, reason,
                )
                TicketStore.update_sub_ticket(sub["id"], {"status": "escalated"})
                self._escalate_parent(sub["parent_id"])

    def _escalate_parent(self, parent_id: str) -> None:
        """Escalate the parent only when every sub is in a hard terminal
        state; otherwise keep the parent at its current state."""
        subs = TicketStore.list_sub_tickets(parent_id)
        if subs and all(s["status"] in {"escalated", "failed"} for s in subs):
            TicketStore.update_ticket(parent_id, {"status": "escalated"})

    # ------------------------------------------------------------------
    # waiting_info lifecycle
    # ------------------------------------------------------------------
    def append_info(self, sub_id: str, text: str) -> dict:
        """Accept user-supplied follow-up for a parked sub-ticket, then
        re-dispatch the sub to its owning agent. Returns the updated sub."""
        sub = TicketStore.get_sub_ticket(sub_id)
        if sub is None:
            raise KeyError(sub_id)
        if sub.get("status") != "waiting_info":
            raise ValueError(f"sub-ticket {sub_id} is not in waiting_info state")

        # Merge new text with the parent's description so the agent can
        # re-run its info check with the full context.
        parent = TicketStore.get_ticket(sub["parent_id"]) or {}
        combined = f"{parent.get('description', '')}\n[追加信息] {text}"
        TicketStore.update_sub_ticket(sub_id, {
            "status": "processing",
            "intent_label": f"{sub.get('intent_label') or ''} | 补充: {text[:30]}",
        })

        # Re-dispatch
        from .registry import get_registry
        resumed = {
            **sub,
            "status": "processing",
            "_resumed_text": combined,
            "_resumed_at": _now_iso(),
            "result": None,
            "result_meta": sub.get("result_meta") or {},
        }
        resumed.pop("_parent", None)  # agent will re-fetch a fresh parent
        registry = get_registry()
        registry.dispatch(resumed["dept"], resumed)
        TicketStore.update_ticket(sub["parent_id"], {"status": "processing"})
        return TicketStore.get_sub_ticket(sub_id) or {}

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------
    def aggregate_results(self, parent_id: str) -> dict:
        """Read all sub-tickets for a parent and build a unified reply."""
        subs = TicketStore.list_sub_tickets(parent_id)
        parent = TicketStore.get_ticket(parent_id) or {}
        resolved = [s for s in subs if s.get("status") == "resolved"]
        open_subs = [s for s in subs if s.get("status") not in {"resolved", "escalated", "failed", "closed"}]
        waiting = [s for s in subs if s.get("status") == "waiting_info"]
        escalated = [s for s in subs if s.get("status") == "escalated"]
        hint = (parent.get("meta") or {}).get("hint")
        reply: dict = {
            "ticket_id": parent_id,
            "title": parent.get("title", ""),
            "primary_dept": parent.get("primary_dept"),
            "status": parent.get("status"),
            "hint": hint,
            "sub_results": [
                {
                    "id": s["id"],
                    "dept": s["dept"],
                    "intent_label": s.get("intent_label"),
                    "status": s.get("status"),
                    "result": s.get("result"),
                }
                for s in subs
            ],
            "summary": _compose_summary(parent, subs, resolved, open_subs, waiting, escalated),
        }
        return reply


def _compose_summary(
    parent: dict, subs: list[dict], resolved: list[dict],
    open_subs: list[dict], waiting: list[dict], escalated: list[dict],
) -> str:
    """Build a short human-readable summary for the submitter."""
    lines: list[str] = []
    hint = (parent.get("meta") or {}).get("hint")
    if hint:
        lines.append(hint)
    if parent.get("multi_intent"):
        lines.append(f"您的工单被拆分为 {len(subs)} 个子任务，已分发给相应部门。")
    if resolved:
        lines.append(f"其中 {len(resolved)} 项已完成：")
        for s in resolved:
            result = s.get("result") or {}
            note = result.get("message") or result.get("note") or ""
            lines.append(f"  - {s['dept']} / {s.get('intent_label')} : {note or '已处理'}")
    if waiting:
        lines.append(f"还有 {len(waiting)} 项等待您补充信息：")
        for s in waiting:
            q = (s.get("result") or {}).get("clarification") or "请补充相关信息"
            lines.append(f"  - {s['dept']} / {s.get('intent_label')} : {q}")
    if escalated:
        lines.append(f"{len(escalated)} 项已升级至人工处理：")
        for s in escalated:
            lines.append(f"  - {s['dept']} / {s.get('intent_label')} : 已转人工")
    if open_subs:
        others = [s for s in open_subs if s.get("status") != "waiting_info"]
        if others:
            lines.append(f"还有 {len(others)} 项正在处理中：")
            for s in others:
                lines.append(f"  - {s['dept']} / {s.get('intent_label')} : {s.get('status')}")
    return "\n".join(lines).strip() or "已收到工单，正在处理。"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(ts: str) -> float:
    try:
        parsed = datetime.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        return parsed.replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return time.time()


def _open_sub_tickets() -> list[dict]:
    """Return every sub-ticket that is not in a terminal state."""
    cols = [c[0] for c in TicketStore.conn().execute("SELECT * FROM sub_tickets").description]
    rows = TicketStore.conn().execute(
        "SELECT * FROM sub_tickets WHERE status NOT IN ('resolved','closed','escalated','failed')"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        d["result"] = json.loads(d.get("result") or "null")
        out.append(d)
    return out
