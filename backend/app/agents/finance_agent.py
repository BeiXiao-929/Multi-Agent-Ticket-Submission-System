"""Finance Agent - reimbursement, budget, and invoice sub-tickets.

Implements the ``waiting_info`` interception: a reimbursement request
without an amount cannot enter the finance review queue, so the agent
parks the sub-ticket and asks the user for the missing numbers.
"""
from __future__ import annotations

import time

from ..core.llm import build_clarification, check_info_complete
from .base import BaseAgent

_SECOND_LEVEL_INTENTS: dict[str, list[str]] = {
    "reimbursement": ["报销", "费用", "reimbursement"],
    "budget": ["预算", "budget"],
    "invoice": ["发票", "报销发票", "invoice"],
}


class FinanceAgent(BaseAgent):
    dept: str = "FINANCE"
    name: str = "Finance Agent"

    def process(self, sub: dict) -> dict:
        intent = self._second_level_classify(sub)
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"

        # Do not resolve a reimbursement without an amount.
        if intent == "reimbursement":
            check = check_info_complete("FINANCE", text, sub.get("result_meta", {}))
            if not check["complete"]:
                return {
                    "intent": intent,
                    "needs_more_info": True,
                    "clarification": build_clarification("FINANCE", text, check["missing"]),
                    "missing_fields": check["missing"],
                }

        if intent == "reimbursement":
            return {
                "intent": intent,
                "message": "报销单已进入财务复核，预计 2 个工作日内打款",
                "expected_days": 2,
                "actions": ["queue_for_review", "notify_finance_clerk"],
            }
        if intent == "budget":
            return {
                "intent": intent,
                "message": "预算查询结果已缓存（TTL 5 分钟），请查看下方余额",
                "budget": {
                    "department": sub.get("result_meta", {}).get("dept", "R&D"),
                    "remaining_pct": 64.0,
                    "cached_at": int(time.time()),
                    "ttl_seconds": 300,
                },
            }
        # invoice
        return {
            "intent": intent,
            "message": "发票验真已排队，失败将自动转人工复核",
            "actions": ["run_invoice_verification", "ocr_extract"],
            "async_task_id": f"FIN-INV-{int(time.time())}",
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _second_level_classify(sub: dict) -> str:
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"
        best, best_hits = "reimbursement", 0
        for intent, kws in _SECOND_LEVEL_INTENTS.items():
            hits = sum(1 for kw in kws if kw.lower() in text.lower())
            if hits > best_hits:
                best, best_hits = intent, hits
        return best
