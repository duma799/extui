from __future__ import annotations

import pytest

from extui.api.models import (
    Account,
    ConsoleLine,
    FileInfo,
    Server,
    ServerAction,
    ServerActionError,
    ServerStatus,
)

SERVER_JSON = {
    "id": "7ZxtjLTBLh9yqPKr",
    "name": "Duma's Survival",
    "address": "duma.exaroton.me",
    "motd": "§7Welcome!",
    "status": 1,
    "host": "node1.exaroton.com",
    "port": 25565,
    "players": {"max": 20, "count": 2, "list": ["duma_n1", "Havar887"]},
    "software": {"id": "fabric", "name": "Fabric", "version": "1.21.4"},
    "shared": False,
}


def test_parses_documented_server() -> None:
    server = Server.from_dict(SERVER_JSON)
    assert server.status is ServerStatus.ONLINE
    assert server.players.count == 2
    assert server.players.list == ("duma_n1", "Havar887")
    assert server.software_label == "Fabric 1.21.4"
    assert server.port == 25565


def test_tolerates_missing_optional_fields() -> None:
    server = Server.from_dict({"id": "x", "name": "x", "address": "x", "status": 0})
    assert server.software is None
    assert server.port is None
    assert server.players.count == 0
    assert server.software_label == "—"


def test_every_documented_status_code_round_trips() -> None:
    for code in range(11):
        assert ServerStatus.parse(code).value == code
    assert ServerStatus.parse(10) is ServerStatus.PREPARING
    assert ServerStatus.parse("nonsense") is ServerStatus.OFFLINE


def test_status_classification() -> None:
    assert ServerStatus.ONLINE.is_transitional is False
    assert ServerStatus.OFFLINE.is_transitional is False
    assert ServerStatus.CRASHED.is_transitional is False
    assert ServerStatus.STARTING.is_transitional is True
    assert ServerStatus.OFFLINE.can_start and ServerStatus.CRASHED.can_start
    assert not ServerStatus.ONLINE.can_start


@pytest.mark.parametrize(
    "action,status",
    [("start", ServerStatus.OFFLINE), ("start", ServerStatus.CRASHED),
     ("stop", ServerStatus.ONLINE), ("restart", ServerStatus.ONLINE)],
)
def test_allowed_actions(action: str, status: ServerStatus) -> None:
    ServerAction.validate(action, status)


@pytest.mark.parametrize(
    "action,status",
    [("start", ServerStatus.ONLINE), ("restart", ServerStatus.LOADING),
     ("stop", ServerStatus.OFFLINE), ("restart", ServerStatus.OFFLINE)],
)
def test_rejected_actions(action: str, status: ServerStatus) -> None:
    with pytest.raises(ServerActionError):
        ServerAction.validate(action, status)


def test_action_targets() -> None:
    assert ServerAction.target("stop") is ServerStatus.OFFLINE
    assert ServerAction.target("start") is ServerStatus.ONLINE
    assert ServerAction.target("restart") is ServerStatus.ONLINE


def test_console_line_extracts_timestamp_and_level() -> None:
    line = ConsoleLine("[12:34:56] [Server thread/WARN]: Can't keep up!")
    assert line.timestamp == "12:34:56"
    assert line.level == "WARN"
    assert line.text.endswith("Can't keep up!")


def test_console_line_sanitizes_and_survives_plain_text() -> None:
    line = ConsoleLine("\x1b[31m[12:34:56] danger\x1b[0m\x07")
    assert line.text == "[12:34:56] danger"
    assert ConsoleLine("no timestamp here").timestamp is None
    assert ConsoleLine("no timestamp here").level is None


def test_file_info_sorts_directories_first() -> None:
    info = FileInfo.from_dict({
        "path": "", "name": "", "isDirectory": True, "isReadable": True,
        "isTextFile": False, "isConfigFile": False, "isLog": False, "isWritable": False, "size": 0,
        "children": [
            {"path": "b.txt", "name": "b.txt", "isDirectory": False, "isTextFile": True, "isConfigFile": False, "isLog": False, "isReadable": True, "isWritable": False, "size": 10, "children": None},
            {"path": "world", "name": "world", "isDirectory": True, "isTextFile": False, "isConfigFile": False, "isLog": False, "isReadable": False, "isWritable": False, "size": 0, "children": None},
            {"path": "a.txt", "name": "a.txt", "isDirectory": False, "isTextFile": True, "isConfigFile": False, "isLog": False, "isReadable": True, "isWritable": False, "size": 10, "children": None},
        ],
    })
    assert [c.name for c in info.sorted_children] == ["world", "a.txt", "b.txt"]


def test_account_parsing() -> None:
    account = Account.from_dict({"name": "duma", "email": "d@example.com", "verified": True, "credits": 1234.5})
    assert account.credits == 1234.5 and account.verified
