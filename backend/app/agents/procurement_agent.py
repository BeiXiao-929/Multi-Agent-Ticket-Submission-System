"""Procurement Agent - office supply, supplier, and invoice sub-tickets.

Implements the ``waiting_info`` interception for procurement: a purchase
request without a model/spec and a budget amount cannot be routed
through the approval flow, so the agent parks the sub-ticket and asks
the user for the missing numbers.
"""
from __future__ import annotations

from ..core.llm import build_clarification, check_info_complete
from .base import BaseAgent

_SECOND_LEVEL_INTENTS: dict[str, list[str]] = {
    "office_supply": ["办公用品", "采购", "打印纸", "笔记本", "office"],
    "supplier": ["供应商", "厂家", "supplier"],
    "invoice": ["发票", "采购发票", "invoice"],
}

# Approval-flow thresholds (RMB)
_THRESHOLD_AUTO = 500
_THRESHOLD_MANAGER = 5_000


class ProcurementAgent(BaseAgent):
    dept: str = "PROCUREMENT"
    name: str = "Procurement Agent"

    def process(self, sub: dict) -> dict:
        intent = self._second_level_classify(sub)
        amount = float(sub.get("result_meta", {}).get("amount", 0) or 0)
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"

        # Equipment purchases need both a specification and a budget.
        if intent == "office_supply" and ("服务器" in text or "设备" in text):
            check = check_info_complete("PROCUREMENT", text, sub.get("result_meta", {}))
            if not check["complete"]:
                return {
                    "intent": intent,
                    "needs_more_info": True,
                    "clarification": build_clarification("PROCUREMENT", text, check["missing"]),
                    "missing_fields": check["missing"],
                }

        approval_state = self._decide_approval(amount)
        stock = self._check_stock(intent)
        result: dict = {
            "intent": intent,
            "approval_state": approval_state["state"],
            "approval_flow": approval_state["flow"],
            "stock": stock,
        }
        if stock.get("available") == 0:
            result["substitute_suggestion"] = stock.get("substitute", "请联系采购员")
        result["message"] = self._compose_message(intent, approval_state, stock)
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _second_level_classify(sub: dict) -> str:
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"
        best, best_hits = "office_supply", 0
        for intent, kws in _SECOND_LEVEL_INTENTS.items():
            hits = sum(1 for kw in kws if kw.lower() in text.lower())
            if hits > best_hits:
                best, best_hits = intent, hits
        return best

    @staticmethod
    def _decide_approval(amount: float) -> dict:
        if amount <= _THRESHOLD_AUTO:
            return {"state": "auto_approved", "flow": ["auto"]}
        if amount <= _THRESHOLD_MANAGER:
            return {"state": "manager_approval", "flow": ["submitter", "manager"]}
        return {
            "state": "multi_level_approval",
            "flow": ["submitter", "manager", "director", "finance"],
        }

    @staticmethod
    def _check_stock(intent: str) -> dict:
        # Local demo inventory data.
        available = 42 if intent == "office_supply" else 0
        substitute = "可选 A4 复印纸（同规格）或 替牌笔记本" if available == 0 else ""
        return {"available": available, "substitute": substitute}

    @staticmethod
    def _compose_message(intent: str, approval: dict, stock: dict) -> str:
        base = {
            "office_supply": "办公用品下单",
            "supplier": "供应商管理",
            "invoice": "采购发票处理",
        }.get(intent, "采购工单")
        if approval["state"] == "auto_approved":
            return f"{base}已自动通过审批（金额 <= {_THRESHOLD_AUTO} 元）"
        if approval["state"] == "manager_approval":
            return f"{base}待主管审批（{_THRESHOLD_AUTO} < 金额 <= {_THRESHOLD_MANAGER} 元）"
        return f"{base}进入多级审批流程（金额 > {_THRESHOLD_MANAGER} 元）"
