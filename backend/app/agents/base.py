"""Base class for professional Agents.

Every agent in the system inherits from ``BaseAgent`` so the registry can
uniformly dispatch sub-tickets, collect their results, and report status.

The base ``handle`` method implements three lifecycle paths:

- normal: ``processing -> resolved``
- waiting_info: agent returns a result carrying ``needs_more_info=True``
  and a ``clarification`` string; the sub is parked in ``waiting_info``
  instead of being resolved, so the user can later append more context.
- exception: ``processing -> escalated`` (human handoff).
"""
from __future__ import annotations

import logging
import time
from typing import ClassVar

from ..state.store import TicketStore

logger = logging.getLogger(__name__)


class BaseAgent:
    """Abstract base for the professional agents."""

    #: Department code this agent handles
    dept: ClassVar[str] = "OTHER"
    #: Human readable agent name
    name: ClassVar[str] = "Agent"

    def __init__(self) -> None:
        self._handled: int = 0
        self._started_at = time.time()
        self._online: bool = True

    # Subclasses implement this
    def process(self, sub: dict) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Registry hooks
    # ------------------------------------------------------------------
    def handle(self, sub: dict) -> dict:
        """Run a sub-ticket end-to-end: process, persist result, and return
        a structured payload."""
        start = time.perf_counter()
        sub["status"] = "processing"
        TicketStore.update_sub_ticket(sub["id"], {"status": "processing"})
        try:
            result = self.process(sub)
            sub["result"] = result
            if result.get("needs_more_info"):
                # Park the sub-ticket for user follow-up. The clarification
                # text lives on the result so the frontend can render it.
                sub["status"] = "waiting_info"
                TicketStore.update_sub_ticket(sub["id"], {
                    "status": "waiting_info",
                    "result": result,
                })
                logger.info("[%s] sub %s parked in waiting_info: %s",
                            self.name, sub["id"], result.get("clarification"))
            else:
                sub["status"] = "resolved"
                TicketStore.update_sub_ticket(sub["id"], {"status": "resolved", "result": result})
                self._handled += 1
        except Exception as exc:  # pragma: no cover
            logger.exception("Agent %s failed on sub %s", self.name, sub["id"])
            sub["status"] = "escalated"
            fallback = {"error": str(exc), "handoff": "human", "note": "已转人工处理"}
            TicketStore.update_sub_ticket(sub["id"], {"status": "escalated", "result": fallback})
            sub["result"] = fallback
        elapsed = time.perf_counter() - start

        # Keep the parent in processing until every child has finished.
        parent = TicketStore.get_ticket(sub["parent_id"])
        if parent:
            siblings = TicketStore.list_sub_tickets(parent["id"])
            states = {item.get("status") for item in siblings}
            if states and states <= {"resolved", "closed"}:
                parent_status = "resolved"
            elif states and states <= {"resolved", "closed", "escalated", "failed"}:
                parent_status = "escalated"
            else:
                parent_status = "processing"
            if parent.get("status") != parent_status:
                TicketStore.update_ticket(parent["id"], {"status": parent_status})
        sub["processing_ms"] = int(elapsed * 1000)
        return sub

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "type": self.dept,
            "name": self.name,
            "online": self._online,
            "handled": self._handled,
            "uptime_s": int(time.time() - self._started_at),
        }

