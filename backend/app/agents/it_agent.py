"""IT Agent - handles account, hardware, network, and software sub-tickets.

Implements the ``waiting_info`` interception: when the user reports a
hardware failure without an asset identifier, the agent parks the
sub-ticket and asks the user for the missing context instead of
resolving it blindly.
"""
from __future__ import annotations

import time

from ..core.llm import build_clarification, check_info_complete
from .base import BaseAgent

# Second-level intent classifier: keyword driven, no ML required. Keeps the
# agent fully functional offline; swap in a small PyTorch model later if
# accuracy demand grows.
_SECOND_LEVEL_INTENTS: dict[str, list[str]] = {
    "account": ["权限", "账号", "登录", "密码", "SSO", "邮箱", "mail"],
    "hardware": ["硬件", "电脑", "笔记本", "打印机", "手机", "设备", "故障", "打不开", "蓝屏"],
    "network": ["网络", "WiFi", "wifi", "VPN", "IP", "路由", "网段"],
    "software": ["软件", "安装", "应用", "系统", "升级", "Office", "IDE"],
}


class ITAgent(BaseAgent):
    dept: str = "IT"
    name: str = "IT Agent"

    def process(self, sub: dict) -> dict:
        """Classify the IT request and return a structured result."""
        intent = self._second_level_classify(sub)
        device_id = sub.get("result_meta", {}).get("device_id", "") or ""
        user_id = sub.get("result_meta", {}).get("user_id", "user-1001")
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')} {sub.get('result_meta', {})}"

        # Hardware faults cannot be dispatched without an asset id.
        if intent == "hardware" and not device_id:
            check = check_info_complete("IT", text, sub.get("result_meta", {}))
            if not check["complete"]:
                return {
                    "intent": intent,
                    "needs_more_info": True,
                    "clarification": build_clarification("IT", text, check["missing"]),
                    "missing_fields": check["missing"],
                }

        device_id = device_id or "DEV-12345"  # fallback for non-hardware intents

        # Local demo data source.
        asset = self._query_asset(device_id)
        if intent == "account":
            resolution = {
                "intent": intent,
                "message": "已创建账号权限申请工单，IT 管理员将在 15 分钟内复核",
                "actions": ["create_permission_request", "notify_admin"],
                "reference": f"PERM-{user_id[:8]}",
            }
        elif intent == "hardware":
            resolution = {
                "intent": intent,
                "message": f"设备 {device_id} 已加入维修队列，预计 24h 内处理",
                "actions": ["open_hardware_ticket"],
                "reference": asset.get("ticket"),
            }
        elif intent == "network":
            resolution = {
                "intent": intent,
                "message": "网络诊断已启动，若 10 分钟内未恢复将自动升级",
                "actions": ["run_network_diagnose", "capture_packet_trace"],
            }
        else:  # software / unknown
            resolution = {
                "intent": intent,
                "message": "软件安装请求已入队，等待安全扫描",
                "actions": ["stage_software_install"],
            }
        resolution["asset_snapshot"] = asset
        return resolution

    # ------------------------------------------------------------------
    @staticmethod
    def _second_level_classify(sub: dict) -> str:
        text = f"{sub.get('intent_label', '')} {sub.get('_resumed_text', '')}"
        best, best_hits = "software", 0
        for intent, kws in _SECOND_LEVEL_INTENTS.items():
            hits = sum(1 for kw in kws if kw.lower() in text.lower())
            if hits > best_hits:
                best, best_hits = intent, hits
        return best

    @staticmethod
    def _query_asset(device_id: str) -> dict:
        # Local demo data source.
        return {
            "device_id": device_id,
            "owner": "user-1001",
            "status": "in_service",
            "ticket": f"HWT-{int(time.time())}",
        }
