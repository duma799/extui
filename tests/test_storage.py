from __future__ import annotations

import json
import os
import stat

import pytest

from extui.config import Configuration, ConfigurationStore
from extui.credentials import ENV_VAR, CredentialStore
from extui.minecraft.waypoints import Waypoint, WaypointStore


def test_config_round_trip(tmp_path) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    assert store.load() == Configuration()
    config = Configuration(selected_server_id="abc123", refresh_interval_seconds=15.0,
                           player_aliases={"uuid-1": "duma_n1"}, theme="gruvbox")
    store.save(config)
    assert store.load() == config


def test_config_is_compatible_with_the_swift_layout(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "selectedServerID": "7ZxtjLTBLh9yqPKr",
        "refreshIntervalSeconds": 10,
        "playerAliases": {"069a79f4": "duma_n1"},
    }))
    config = ConfigurationStore(path).load()
    assert config.selected_server_id == "7ZxtjLTBLh9yqPKr"
    assert config.player_aliases == {"069a79f4": "duma_n1"}
    assert json.loads(path.read_text())["selectedServerID"] == "7ZxtjLTBLh9yqPKr"


def test_config_clamps_refresh_interval_and_survives_junk(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"refreshIntervalSeconds": 1}))
    assert ConfigurationStore(path).load().refresh_interval_seconds == 5.0
    path.write_text(json.dumps({"refreshIntervalSeconds": "soon"}))
    assert ConfigurationStore(path).load().refresh_interval_seconds == 10.0
    path.write_text("not json at all")
    assert ConfigurationStore(path).load() == Configuration()
    path.write_text("[1,2,3]")
    assert ConfigurationStore(path).load() == Configuration()


def test_config_file_is_private(tmp_path) -> None:
    path = tmp_path / "config.json"
    ConfigurationStore(path).save(Configuration(selected_server_id="x"))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_token_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv(ENV_VAR, "  env-token  ")
    assert CredentialStore().read_token() == "env-token"
    monkeypatch.setenv(ENV_VAR, "   ")
    store = CredentialStore(service="dev.extui.test-nonexistent", account="none")
    assert store.read_token() is None


def test_waypoint_store_round_trip_and_filters(tmp_path) -> None:
    store = WaypointStore(tmp_path / "waypoints.json")
    first = Waypoint("Ice Spikes", "overworld", 1, 2, source="biome", target_id="minecraft:ice_spikes")
    second = Waypoint("Fortress", "the_nether", 3, 4, y=64, source="structure")
    store.add(first)
    store.add(second)
    assert len(store.all(dimension="overworld")) == 1
    assert store.all(source="structure")[0].name == "Fortress"
    assert store.get(first.id) is not None
    assert store.get("no-such-id") is None

    reloaded = WaypointStore(tmp_path / "waypoints.json")
    assert len(reloaded.all()) == 2
    assert reloaded.get(second.id).y == 64
    assert reloaded.get(second.id).coordinates == "3, 64, 4"
    assert reloaded.get(first.id).coordinates == "1, ~, 2"


def test_waypoint_rename_and_delete(tmp_path) -> None:
    store = WaypointStore(tmp_path / "waypoints.json")
    waypoint = Waypoint("Old", "overworld", 0, 0)
    store.add(waypoint)
    assert store.rename(waypoint.id, "New")
    assert not store.rename(waypoint.id, "   "), "blank names are rejected"
    assert not store.rename("missing", "x")
    assert WaypointStore(tmp_path / "waypoints.json").all()[0].name == "New"
    assert store.delete(waypoint.id)
    assert not store.delete(waypoint.id)
    assert WaypointStore(tmp_path / "waypoints.json").all() == []


def test_waypoint_file_is_private_and_survives_corruption(tmp_path) -> None:
    path = tmp_path / "waypoints.json"
    store = WaypointStore(path)
    store.add(Waypoint("A", "overworld", 1, 1))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    path.write_text("{ broken")
    assert WaypointStore(path).all() == []


@pytest.fixture
def no_keyring(monkeypatch):
    import keyring
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    monkeypatch.delenv(ENV_VAR, raising=False)
    yield
    keyring.set_keyring(previous)


def test_missing_keyring_reads_as_no_stored_token(no_keyring) -> None:
    assert CredentialStore().read_token() is None


def test_missing_keyring_explains_the_environment_variable(no_keyring) -> None:
    from extui.credentials import NoKeyringAvailable

    with pytest.raises(NoKeyringAvailable) as raised:
        CredentialStore().save_token("token")
    assert ENV_VAR in str(raised.value)
    assert "headless" in str(raised.value)


def test_environment_token_works_without_any_keyring(no_keyring, monkeypatch) -> None:
    monkeypatch.setenv(ENV_VAR, "env-token")
    assert CredentialStore().read_token() == "env-token"


def test_logout_without_a_keyring_does_not_raise(no_keyring) -> None:
    CredentialStore().delete_token()
