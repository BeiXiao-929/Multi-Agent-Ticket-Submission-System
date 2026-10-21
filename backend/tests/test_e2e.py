"""End-to-end tests that run the real FastAPI app with TestClient."""
from __future__ import annotations

import os

# Point SQLite at a temp file so the test run doesn't touch production data
os.environ["AGENT_SQLITE_PATH"] = "data/test_tickets.sqlite3"
os.environ["AGENT_LLM_ENABLED"] = "0"  # keyword fallback only, no network

from fastapi.testclient import TestClient

from app.main import app
from app.state.store import TicketStore


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_submit_and_query_ticket() -> None:
    client = TestClient(app)
    # Mint a token first
    token = client.post(
        "/api/v1/auth/token",
        json={"sub": "tester", "roles": ["employee"]},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/tickets/submit",
        headers=headers,
        json={
            "title": "申请开通数据平台权限",
            "content": "我需要数据平台的查询权限，同时笔记本也坏了需要维修",
            "priority": "high",
            "result_meta": {"device_id": "DEV-900"},
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ticket_id"]
    assert data["primary_dept"] in {"IT", "HR", "PROCUREMENT", "FINANCE", "OTHER"}

    # Query it back
    r2 = client.get(f"/api/v1/tickets/{data['ticket_id']}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == data["ticket_id"]

    # Sub-tickets
    r3 = client.get(f"/api/v1/tickets/{data['ticket_id']}/sub-tickets", headers=headers)
    assert r3.status_code == 200
    assert isinstance(r3.json(), list)

    # Aggregated result
    r4 = client.get(f"/api/v1/tickets/{data['ticket_id']}/result", headers=headers)
    assert r4.status_code == 200
    assert "summary" in r4.json()


def test_agent_status() -> None:
    client = TestClient(app)
    # /agents is behind JWT; mint a token first (matches the frontend contract).
    token = client.post(
        "/api/v1/auth/token",
        json={"sub": "tester", "roles": ["employee"]},
    ).json()["access_token"]
    r = client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert any(a["type"] == "IT" for a in r.json())


def test_update_and_delete_ticket() -> None:
    client = TestClient(app)
    token = client.post(
        "/api/v1/auth/token",
        json={"sub": "crud-tester", "roles": ["employee"]},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/v1/tickets/submit",
        headers=headers,
        json={
            "title": "CRUD test ticket",
            "content": "Please check the office network connection.",
            "priority": "normal",
            "submitter": "tester",
        },
    )
    assert created.status_code == 200, created.text
    ticket_id = created.json()["ticket_id"]

    updated = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=headers,
        json={
            "title": "CRUD test ticket updated",
            "description": "Updated office network details.",
            "submitter": "crud-tester",
            "priority": "high",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["title"] == "CRUD test ticket updated"
    assert body["description"] == "Updated office network details."
    assert body["submitter"] == "crud-tester"
    assert body["priority"] == "high"

    invalid = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=headers,
        json={"title": None},
    )
    assert invalid.status_code == 422

    deleted = client.delete(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert TicketStore.list_sub_tickets(ticket_id) == []
    snapshot_count = TicketStore.conn().execute(
        "SELECT COUNT(*) FROM snapshots WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()[0]
    assert snapshot_count == 0

    missing = client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert missing.status_code == 404

    missing_delete = client.delete(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert missing_delete.status_code == 404


def test_unauthorized_without_token() -> None:
    client = TestClient(app)
    r = client.get("/api/v1/tickets")
    assert r.status_code in {401, 403}
