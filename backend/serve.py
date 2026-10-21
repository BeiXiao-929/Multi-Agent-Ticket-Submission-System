"""serve.py - one-process launcher.

Runs the FastAPI multi-agent backend AND serves the frontend dashboard
from a single port so the browser can reach both without CORS.

Usage:
    python serve.py            # starts on http://127.0.0.1:8000
    python serve.py --port 9000
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser


def _ensure_hidden_log_streams() -> None:
    """Give Uvicorn usable streams when Windows starts Python without a console."""
    hidden = os.environ.get("AGENT_HIDDEN_LOG") == "1"
    if not hidden and sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(os.path.dirname(__file__), "server.runtime.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if hidden or sys.stdout is None:
        sys.stdout = stream
    if hidden or sys.stderr is None:
        sys.stderr = stream


_ensure_hidden_log_streams()

# Make sure the local config data dir exists
os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)

from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

# Pull in the already-built app (routers + middleware + lifecycle)
from app.main import app as api_app


def _mount_dashboard() -> None:
    dashboard_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    index = os.path.join(dashboard_dir, "index.html")

    # Serve the dashboard at the site root.
    @api_app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        # If a real static file exists (e.g. api.js), serve it; otherwise index.html
        target = os.path.join(dashboard_dir, full_path)
        if full_path and os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(index)


_mount_dashboard()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the multi-agent ticket system.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    import uvicorn

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()

    print(f"Starting multi-agent ticket system at http://{args.host}:{args.port}")
    uvicorn.run(api_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
