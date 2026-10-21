"""Agent registry.

Holds one instance of each professional agent and dispatches sub-tickets to
the right one on a background thread. Also owns a watchdog thread that
calls ``Orchestrator.scan_sla_breaches`` every few seconds.

In a production deployment the in-process thread pool would be replaced by
RabbitMQ queues (one per department) and the watchdog would become a
delayed-message job. The registry keeps the same interface so swapping the
backend is a drop-in change.
"""
from __future__ import annotations

import logging
import threading

from .base import BaseAgent
from .finance_agent import FinanceAgent
from .general_agent import GeneralAgent
from .hr_agent import HRAgent
from .it_agent import ITAgent
from .orchestrator import Orchestrator
from .procurement_agent import ProcurementAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._orchestrator = Orchestrator()
        self._watchdog: threading.Thread | None = None
        self._stop_event = threading.Event()
        for agent in (ITAgent(), HRAgent(), ProcurementAgent(), FinanceAgent(), GeneralAgent()):
            self._agents[agent.dept] = agent
        logger.info("Agent registry started with %d agents: %s",
                    len(self._agents), ", ".join(self._agents.keys()))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start_all(self) -> None:
        if self._watchdog and self._watchdog.is_alive():
            return
        self._stop_event.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="agent-sla-watchdog", daemon=True)
        self._watchdog.start()

    def stop_all(self) -> None:
        self._stop_event.set()
        if self._watchdog:
            self._watchdog.join(timeout=2.0)

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._orchestrator.scan_sla_breaches()
            except Exception:
                logger.exception("SLA watchdog tick failed")
            self._stop_event.wait(5)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def dispatch(self, dept: str, sub: dict) -> None:
        agent = self._agents.get(dept)
        if agent is None:
            logger.warning("No agent for dept %s; routing to GeneralAgent", dept)
            agent = self._agents["OTHER"]
        # Attach a shallow parent snapshot so the agent can read context
        if not sub.get("_parent"):
            from ..state.store import TicketStore
            sub["_parent"] = TicketStore.get_ticket(sub["parent_id"]) or {}
        sub.setdefault("result_meta", sub.get("_parent", {}).get("meta", {}))
        threading.Thread(target=self._run, args=(agent, sub), name=f"agent-{dept}-{sub['id']}", daemon=True).start()

    def _run(self, agent: BaseAgent, sub: dict) -> None:
        logger.info("[%s] started sub-ticket %s", agent.name, sub["id"])
        agent.handle(sub)
        logger.info("[%s] finished sub-ticket %s (status=%s)", agent.name, sub["id"], sub.get("status"))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def orchestrator(self) -> Orchestrator:
        return self._orchestrator

    def agents(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def agent(self, dept: str) -> BaseAgent | None:
        return self._agents.get(dept)

    def status(self) -> list[dict]:
        return [a.status() for a in self.agents()]


# Singleton access
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
