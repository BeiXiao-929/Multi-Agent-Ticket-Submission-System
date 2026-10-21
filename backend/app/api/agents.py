"""Agent status + auth-token routes."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..agents.registry import get_registry
from ..middleware.jwt import issue_token

router = APIRouter()


class TokenRequest(BaseModel):
    sub: str
    roles: list[str] = ["employee"]


@router.get("/agents")
def list_agents() -> list[dict]:
    return get_registry().status()


@router.get("/agents/{type_}/status")
def agent_status(type_: str) -> dict:
    """Per-agent status. ``type_`` is the department code (IT, HR, ...)
    or ``ORCH`` for the orchestrator."""
    registry = get_registry()
    if type_.upper() == "ORCH":
        return {
            "type": "ORCH",
            "name": "Orchestrator Agent",
            "online": True,
            "watchdog": "running",
        }
    agent = registry.agent(type_.upper())
    if agent is None:
        return {"type": type_, "online": False, "error": "unknown agent"}
    return agent.status()


@router.post("/auth/token")
def issue_jwt(body: TokenRequest) -> dict:
    """Mint a JWT for the supplied subject + roles. In a real deployment
    this route would be gated by username/password or OIDC; it is exposed
    here for development convenience and demo purposes."""
    token = issue_token(body.sub, body.roles)
    return {"access_token": token, "token_type": "bearer"}
