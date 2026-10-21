"""HR Agent - leave, attendance, certificate, and policy sub-tickets.

HR answers every request from the stub data store, so no waiting_info
interception is needed here; the agent always resolves its sub-ticket.
"""
from __future__ import annotations

from .base import BaseAgent

_SECOND_LEVEL_INTENTS: dict[str, list[str]] = {
    "leave": ["假期", "年假", "请假", "调休", "假期余额", "leave"],
    "attendance": ["考勤", "打卡", "迟到", "早退", "attendance"],
    "certificate": ["证明", "在职", "收入证明", "certificate"],
    "policy": ["政策", "制度", "规则", "policy"],
}


class HRAgent(BaseAgent):
    dept: str = "HR"
    name: str = "HR Agent"

    def process(self, sub: dict) -> dict:
        intent = self._second_level_classify(sub)
        user_id = sub.get("result_meta", {}).get("user_id", "user-1001")
        if intent == "leave":
            return {
                "intent": intent,
                "message": f"用户 {user_id} 的假期余额：年假 12 天，病假 5 天",
                "leave_balance": {"annual": 12, "sick": 5},
            }
        if intent == "attendance":
            return {
                "intent": intent,
                "message": "考勤记录已导出，最近 30 天迟到 0 次",
                "attendance_summary": {"late_30d": 0, "absent_30d": 0},
            }
        if intent == "certificate":
            return {
                "intent": intent,
                "message": "在职证明已生成，下载链接将在邮件中发送",
                "async_task_id": f"HR-CERT-{user_id}",
                "note": "异步生成中，预计 5 分钟内完成",
            }
        return {
            "intent": intent,
            "message": "已记录 HR 政策查询，请咨询 HRBP 获取细则",
            "actions": ["route_to_hr_business_partner"],
        }

    @staticmethod
    def _second_level_classify(sub: dict) -> str:
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"
        best, best_hits = "policy", 0
        for intent, kws in _SECOND_LEVEL_INTENTS.items():
            hits = sum(1 for kw in kws if kw.lower() in text.lower())
            if hits > best_hits:
                best, best_hits = intent, hits
        return best
