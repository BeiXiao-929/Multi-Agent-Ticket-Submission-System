from __future__ import annotations

import time

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agents.it_agent import ITAgent
from app.agents.orchestrator import _now_iso, _parse_iso
from app.agents.procurement_agent import ProcurementAgent
from app.main import app


def test_supplier_request_is_not_blocked_by_device_keyword() -> None:
    result = ProcurementAgent().process({
        "intent_label": "供应商设备资料更新",
        "result_meta": {},
        "_resumed_text": "",
    })

    assert result["intent"] == "supplier"
    assert "needs_more_info" not in result


def test_it_agent_uses_user_id_from_metadata() -> None:
    result = ITAgent().process({
        "parent_id": "ticket-123",
        "intent_label": "账号权限申请",
        "result_meta": {"user_id": "employee-42"},
        "_resumed_text": "",
    })

    assert result["reference"] == "PERM-employee"


def test_sla_timestamp_is_interpreted_as_utc() -> None:
    assert abs(time.time() - _parse_iso(_now_iso())) < 2


def test_ticket_stream_rejects_missing_token() -> None:
    client = TestClient(app)
    with client.websocket_connect("/api/v1/tickets/missing/stream") as websocket:
        assert websocket.receive_json() == {"type": "error", "message": "unauthorized"}
        try:
            websocket.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        else:
            raise AssertionError("WebSocket should close after an authentication failure")
