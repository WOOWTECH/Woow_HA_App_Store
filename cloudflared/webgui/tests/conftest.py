import os

# Must be set before backend modules are imported (read at import time).
os.environ["WEBGUI_DEV"] = "1"

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.instances import supervisor


class FakeSupervisor:
    """In-memory stand-in for the Supervisor API used by the routers."""

    def __init__(self):
        self.options = {"external_hostname": "", "additional_hosts": []}
        self.restarted = False

    async def self_info(self):
        return {"version": "1.0.0", "state": "started", "options": self.options}

    async def get_options(self):
        return dict(self.options)

    async def set_options(self, options):
        self.options = options

    async def restart_self(self):
        self.restarted = True

    async def ping(self):
        return True


@pytest.fixture()
def fake_supervisor(monkeypatch):
    fake = FakeSupervisor()
    for name in (
        "self_info",
        "get_options",
        "set_options",
        "restart_self",
        "ping",
    ):
        monkeypatch.setattr(supervisor, name, getattr(fake, name))
    return fake


@pytest.fixture()
def client(fake_supervisor):
    # Lifespan (log watcher) is intentionally not started — TestClient
    # without a context manager skips lifespan events.
    return TestClient(app)
