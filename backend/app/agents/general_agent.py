"""General Agent - catches anything that does not map cleanly to the four
major departments. Handles low-confidence routing, multi-turn clarification,
and hand-off to a human queue.

It also owns the "gentle" path for garbage input (pure symbols, repeated
junk): the LLM-layer guard in ``classify_with_fallback`` has already
attached a ``hint`` to the parent ticket meta; this agent surfaces it
instead of crashing.
"""
from __future__ import annotations

from ..core.llm import check_info_complete
from .base import BaseAgent


class GeneralAgent(BaseAgent):
    dept: str = "OTHER"
    name: str = "General Agent"

    def process(self, sub: dict) -> dict:
        """Two behaviours:

        1. When the parent confidence is high enough, simply acknowledge
           that the ticket has been accepted and queued for a human review.
        2. When confidence is low, build a clarification prompt for the
           submitter and park the sub-ticket in ``waiting_info``.
        """
        parent = sub.get("_parent", {})
        confidence = parent.get("confidence", 0.5)
        hint = (parent.get("meta") or {}).get("hint")
        text = f"{parent.get('title', '')} {parent.get('description', '')}".strip()

        # Garbage input: the guard has already set a hint. Park for follow-up
        # rather than auto-resolve.
        if hint or confidence < 0.4:
            return {
                "intent": "clarification_needed",
                "message": hint or "系统未能理解您的具体需求，请重新描述。",
                "needs_more_info": True,
                "clarification": hint or "请重新描述您的具体需求（例如：哪个部门、什么事、涉及什么金额/设备）。",
                "status_hint": "waiting_info",
                "actions": ["prompt_submitter", "resume_on_reply"],
            }

        if confidence < 0.6:
            check = check_info_complete("OTHER", text)
            return {
                "intent": "clarification_needed",
                "message": check["questions"][0] if check["questions"] else "请补充相关信息",
                "needs_more_info": True,
                "clarification": check["questions"][0] if check["questions"] else "请补充相关信息",
                "actions": ["prompt_submitter", "resume_on_reply"],
            }

        return {
            "intent": "general_ack",
            "message": "工单已进入通用处理队列，将尽快由人工专员复核",
            "actions": ["route_to_human_queue", "preserve_context"],
            "context_snapshot": {
                "title": parent.get("title"),
                "description": parent.get("description"),
                "confidence": confidence,
            },
        }
