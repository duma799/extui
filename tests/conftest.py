from __future__ import annotations

import pytest

from extui.api.models import ServerStatus
from extui.config import ConfigurationStore
from extui.fake import FakeExarotonService
from extui.minecraft.waypoints import WaypointStore


@pytest.fixture
def service() -> FakeExarotonService:
    return FakeExarotonService(status=ServerStatus.ONLINE, transition_delay=0.2)


@pytest.fixture
def make_app(tmp_path):
    from extui.tui.app import ExtuiApp

    counter = {"n": 0}

    def factory(svc: FakeExarotonService | None = None) -> "ExtuiApp":
        counter["n"] += 1
        suffix = counter["n"]
        return ExtuiApp(
            service=svc or FakeExarotonService(status=ServerStatus.ONLINE, transition_delay=0.2),
            server_id="demo-server",
            config_store=ConfigurationStore(tmp_path / f"config-{suffix}.json"),
            waypoint_store=WaypointStore(tmp_path / f"waypoints-{suffix}.json"),
            demo=True,
        )

    return factory


@pytest.fixture
def app(tmp_path, service):
    from extui.tui.app import ExtuiApp

    return ExtuiApp(
        service=service,
        server_id="demo-server",
        config_store=ConfigurationStore(tmp_path / "config.json"),
        waypoint_store=WaypointStore(tmp_path / "waypoints.json"),
        demo=True,
    )
