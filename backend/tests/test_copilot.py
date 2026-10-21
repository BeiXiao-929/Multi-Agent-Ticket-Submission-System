"""Regression tests for the embedded ticket assistant."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.state.store import TicketStore


def _headers(client: TestClient) -> dict[str, str]:
    token = client.post(
        "/api/v1/auth/token",
        json={"sub": "copilot-tester", "roles": ["employee"]},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _ticket_count() -> int:
    return TicketStore.conn().execute("SELECT COUNT(*) FROM tickets").fetchone()[0]


def test_runtime_info_supports_copilotkit_v2() -> None:
    client = TestClient(app)
    expected = {
        "ticket_assistant": {
            "description": "Draft and pre-check tickets; never submit without human approval.",
            "capabilities": {},
        }
    }

    get_response = client.get("/api/v1/copilotkit/info")
    assert get_response.status_code == 200
    assert get_response.json()["mode"] == "sse"
    assert get_response.json()["agents"] == expected

    post_response = client.post(
        "/api/v1/copilotkit/info",
        json={"method": "info"},
    )
    assert post_response.status_code == 200
    assert post_response.json()["agents"] == expected


def test_analyze_returns_draft_without_persisting() -> None:
    client = TestClient(app)
    headers = _headers(client)
    before = _ticket_count()

    response = client.post(
        "/api/v1/copilot/analyze",
        headers=headers,
        json={
            "title": "",
            "description": "电脑蓝屏无法开机，资产编号 LAPTOP-TEST-001，请尽快处理",
            "submitter": "tester",
            "priority": "high",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["confirmation_required"] is True
    assert body["draft"]["department"] == "IT"
    assert body["draft"]["priority"] == "high"
    assert body["draft"]["title"]
    assert "LAPTOP-TEST-001" in body["draft"]["description"]
    assert body["assistant_message"]
    assert _ticket_count() == before


def test_skills_are_discovered_with_local_to_tickets_fallback() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/copilot/skills", headers=_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 16
    names = {skill["name"] for skill in body["skills"]}
    assert "to-tickets" in names
    assert "systematic-debugging" in names
    assert body["to_tickets_upstream"].startswith("unavailable")


def test_copilot_agent_returns_fill_ticket_tool_call() -> None:
    client = TestClient(app)
    headers = {
        **_headers(client),
        "Accept": "text/event-stream",
    }
    response = client.post(
        "/api/v1/copilotkit/agent/ticket_assistant/run",
        headers=headers,
        json={
            "threadId": "test-thread",
            "runId": "test-run",
            "state": {},
            "messages": [
                {
                    "id": "message-1",
                    "role": "user",
                    "content": "Laptop blue screen and will not start. Asset LAPTOP-TEST-002.",
                }
            ],
            "tools": [
                {
                    "name": "fillTicketForm",
                    "description": "Fill the visible ticket form.",
                    "parameters": {"type": "object"},
                }
            ],
            "context": [],
        },
    )

    assert response.status_code == 200, response.text
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text
    assert '"name":"fillTicketForm"' in response.text
    assert "LAPTOP-TEST-002" in response.text
