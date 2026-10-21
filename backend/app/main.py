"""FastAPI application factory and route registration."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from ag_ui_langgraph import LangGraphAgent, add_langgraph_fastapi_endpoint
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import agents, copilot, tickets, tickets_ws
from .assistant.workflow import build_copilot_graph
from .config import settings
from .middleware import (
    JWTAuthMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from .state.store import TicketStore

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory exists
    os.makedirs(os.path.dirname(settings.sqlite_path) or ".", exist_ok=True)
    TicketStore.create_schema()

    # Bring up each agent's in-process task registry + SLA watchdog
    from .agents.registry import get_registry
    registry = get_registry()
    registry.start_all()
    app.state.registry = registry

    yield

    # Ensure the watchdog thread is cleanly stopped
    registry.stop_all()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Order matters: the first added is the outermost layer in FastAPI
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        JWTAuthMiddleware,
        exempt_paths=(
            "/health",
            "/openapi.json",
            "/docs",
            "/api/v1/auth/token",
            f"{settings.api_v1_prefix}/copilotkit/info",
        ),
    )

    # Include routers
    app.include_router(tickets.router, prefix=settings.api_v1_prefix, tags=["tickets"])
    app.include_router(agents.router, prefix=settings.api_v1_prefix, tags=["agents"])
    app.include_router(tickets_ws.router, prefix=settings.api_v1_prefix, tags=["tickets-ws"])
    app.include_router(copilot.router, prefix=settings.api_v1_prefix, tags=["copilot"])

    agent_description = "Draft and pre-check tickets; never submit without human approval."
    copilot_agent = LangGraphAgent(
        name="ticket_assistant",
        description=agent_description,
        graph=build_copilot_graph(),
        emit_raw_events=False,
    )
    add_langgraph_fastapi_endpoint(
        app,
        copilot_agent,
        path=f"{settings.api_v1_prefix}/copilotkit/agent/ticket_assistant/run",
        include_in_schema=False,
    )

    @app.api_route(
        f"{settings.api_v1_prefix}/copilotkit/info",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    def copilotkit_info() -> dict:
        """Report the v2 runtime contract consumed by CopilotKit React."""
        return {
            "version": "1.0.0",
            "mode": "sse",
            "agents": {
                "ticket_assistant": {
                    "description": agent_description,
                    "capabilities": {},
                }
            },
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
