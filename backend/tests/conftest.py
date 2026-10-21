import os

import pytest

# Use a temp SQLite file and disable the LLM so the suite is hermetic
os.environ["AGENT_SQLITE_PATH"] = "data/test.sqlite3"
os.environ["AGENT_LLM_ENABLED"] = "0"


@pytest.fixture(scope="module")
def client():
    """Create a TestClient and keep the registry alive only for the module."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
