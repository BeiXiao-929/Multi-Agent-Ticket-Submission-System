"""WebSocket routes for per-ticket real-time status stream."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..middleware.jwt import verify_token
from ..state.store import TicketStore

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/tickets/{ticket_id}/stream")
async def ticket_stream(
    ws: WebSocket,
    ticket_id: str,
    token: str = Query(default=""),
):
    """Push a new JSON message to the socket every time the parent ticket
    or any of its sub-tickets changes state.

    The browser connects with a short-lived JWT query parameter. On every
    push the payload is:

        {
          "type": "ticket_state",
          "ticket": {...parent...},
          "subs": [ {...sub1...}, {...sub2...} ],
        }

    The stream terminates when every sub-ticket reaches a terminal state
    (resolved / escalated / closed).
    """
    await ws.accept()
    if not token or verify_token(token) is None:
        await ws.send_json({"type": "error", "message": "unauthorized"})
        await ws.close(code=1008)
        return
    terminal = {"resolved", "escalated", "closed", "failed"}
    last_seen: dict[str, str] = {}
    try:
        while True:
            parent = TicketStore.get_ticket(ticket_id)
            if parent is None:
                await ws.send_json({"type": "error", "message": "ticket not found"})
                break
            subs = TicketStore.list_sub_tickets(ticket_id)
            done = len(subs) > 0 and all(s["status"] in terminal for s in subs)
            # Detect real state transitions so we can surface escalation /
            # waiting_info events in the frontend log stream.
            events = []
            for s in subs:
                prev = last_seen.get(s["id"])
                if prev and prev != s["status"]:
                    events.append({"from": prev, "to": s["status"], "sub_id": s["id"], "dept": s["dept"]})
                last_seen[s["id"]] = s["status"]
            await ws.send_json({
                "type": "ticket_state",
                "ticket": {k: v for k, v in parent.items() if k != "meta"},
                "subs": subs,
                "events": events,
            })
            if done:
                break
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from ticket %s", ticket_id)
