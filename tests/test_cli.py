from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from extui import cli
from extui.api.models import ServerStatus
from extui.config import Configuration, ConfigurationStore
from extui.fake import FakeExarotonService


@contextmanager
def wired(monkeypatch, tmp_path, service: FakeExarotonService, *, token: str = "tok",
          selected: str | None = "demo-server"):
    store = ConfigurationStore(tmp_path / "config.json")
    store.save(Configuration(selected_server_id=selected))
    monkeypatch.setattr(cli, "ConfigurationStore", lambda *a, **k: store)

    class FakeCredentials:
        def __init__(self, *a, **k) -> None:
            self.saved: str | None = None

        def read_token(self) -> str | None:
            return token

        def save_token(self, value: str) -> None:
            self.saved = value

        def delete_token(self) -> None:
            pass

    monkeypatch.setattr(cli, "CredentialStore", FakeCredentials)

    class Ctx:
        async def __aenter__(self_inner):
            return service

        async def __aexit__(self_inner, *a):
            return False

    monkeypatch.setattr(cli, "_client", lambda credentials: Ctx())
    monkeypatch.setattr(cli, "WaypointStore", lambda *a, **k: cli.WaypointStore.__mro__[0](tmp_path / "waypoints.json"))
    yield store


@pytest.fixture
def service() -> FakeExarotonService:
    return FakeExarotonService(status=ServerStatus.ONLINE, transition_delay=0.01)


def test_help_and_version_exit_cleanly(capsys) -> None:
    for flag in ("--help", "--version"):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([flag])
        assert exit_info.value.code == 0


def test_servers_lists_the_account(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["servers"]) == 0
    out = capsys.readouterr().out
    assert "demo-server" in out and "ONLINE" in out


def test_status_shows_the_selected_server(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Duma's Survival" in out and "ONLINE" in out
    assert "duma.exaroton.me" in out
    assert "Welcome to the server" in out, "the MOTD is rendered without section codes"
    assert "§" not in out


def test_select_persists_the_server(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service, selected=None) as store:
        assert cli.main(["select", "demo-server"]) == 0
        assert store.load().selected_server_id == "demo-server"


def test_balance_reports_credits(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["balance"]) == 0
    assert "Credits" in capsys.readouterr().out


def test_commands_require_a_selected_server(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service, selected=None):
        assert cli.main(["status"]) == 1
    assert "No server selected" in capsys.readouterr().err


def test_missing_token_is_explained(monkeypatch, tmp_path, capsys) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    store.save(Configuration(selected_server_id="demo-server"))
    monkeypatch.setattr(cli, "ConfigurationStore", lambda *a, **k: store)
    monkeypatch.delenv("EXAROTON_TOKEN", raising=False)

    class NoToken:
        def __init__(self, *a, **k) -> None: ...
        def read_token(self) -> None:
            return None

    monkeypatch.setattr(cli, "CredentialStore", NoToken)
    assert cli.main(["status"]) == 1
    assert "extui login" in capsys.readouterr().err


def test_lifecycle_prints_the_transition_trail(monkeypatch, tmp_path, service, capsys) -> None:
    service.status = ServerStatus.OFFLINE
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["start"]) == 0
    out = capsys.readouterr().out
    assert "OFFLINE" in out and "ONLINE" in out and "→" in out
    assert service.actions == ["start"]


def test_lifecycle_rejects_an_impossible_action(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["start"]) == 1
    assert "Cannot start" in capsys.readouterr().err


def test_console_sends_a_one_shot_command(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["console", "time", "set", "day"]) == 0
    assert service.commands == ["time set day"]
    assert "Command sent." in capsys.readouterr().out


def test_chunky_start_reports_the_estimate(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["chunky", "start", "--dimension", "world",
                         "--center-x", "-3000", "--center-z", "-2700", "--radius", "10000"]) == 0
    out = capsys.readouterr().out
    assert "Estimated square chunks" in out
    assert service.commands == ["chunky start world square -3000 -2700 10000"]


def test_chunky_start_rejects_a_bad_radius(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["chunky", "start", "--center-x", "0", "--center-z", "0", "--radius", "0"]) == 1
    assert "Radius" in capsys.readouterr().err
    assert service.commands == []


@pytest.mark.parametrize("action,expected", [
    ("status", "chunky progress"), ("pause", "chunky pause"),
    ("resume", "chunky continue"), ("cancel", "chunky cancel"),
])
def test_chunky_control_verbs(monkeypatch, tmp_path, service, action, expected, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["chunky", action]) == 0
    assert service.commands == [expected]


def test_locate_sends_a_validated_command(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["locate", "biome", "minecraft:ice_spikes"]) == 0
    assert service.commands == ["locate biome minecraft:ice_spikes"]


def test_locate_rejects_an_injected_identifier(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["locate", "biome", "spikes; op @a"]) == 1
    assert service.commands == []


def test_advancements_and_biomes(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service):
        assert cli.main(["advancements"]) == 0
        out = capsys.readouterr().out
        assert "minecraft:story/root" in out
        assert cli.main(["biomes"]) == 0
        biomes = capsys.readouterr().out
        assert "Adventuring Time: 10/53" in biomes
        assert "minecraft:ice_spikes" in biomes


def test_waypoint_lifecycle(monkeypatch, tmp_path, service, capsys) -> None:
    path = tmp_path / "waypoints.json"
    monkeypatch.setattr(cli, "WaypointStore", lambda *a, **k: __import__(
        "extui.minecraft.waypoints", fromlist=["WaypointStore"]).WaypointStore(path))
    assert cli.main(["waypoint", "add", "Ice Spikes", "overworld", "18240", "~", "-5312"]) == 0
    assert cli.main(["waypoint", "list"]) == 0
    out = capsys.readouterr().out
    assert "Ice Spikes" in out and "18240, ~, -5312" in out
    stored = json.loads(path.read_text())
    identifier = stored[0]["id"]
    assert cli.main(["waypoint", "rename", identifier, "Cold Place"]) == 0
    assert "Cold Place" in json.loads(path.read_text())[0]["name"]
    assert cli.main(["waypoint", "delete", identifier]) == 0
    assert json.loads(path.read_text()) == []
    assert cli.main(["waypoint", "delete", identifier]) == 0
    assert "not found" in capsys.readouterr().out


def test_player_association_is_saved(monkeypatch, tmp_path, service, capsys) -> None:
    with wired(monkeypatch, tmp_path, service) as store:
        assert cli.main(["player", "associate", "duma_n1", "069a79f4"]) == 0
        assert store.load().player_aliases == {"069a79f4": "duma_n1"}


def test_login_stores_the_pasted_token(monkeypatch, tmp_path, capsys) -> None:
    saved: dict = {}

    class Recorder:
        def __init__(self, *a, **k) -> None: ...
        def save_token(self, value: str) -> None:
            saved["token"] = value

    monkeypatch.setattr(cli, "CredentialStore", Recorder)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "secret-token")
    assert cli.main(["login"]) == 0
    assert saved["token"] == "secret-token"
    assert "secret-token" not in capsys.readouterr().out, "the token must never be echoed"
