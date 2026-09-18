from __future__ import annotations

import json

import httpx
import pytest

from extui.api.client import (
    DEFAULT_BASE_URL,
    ExarotonClient,
    ExarotonError,
    ServerStream,
    perform_and_follow,
    safe_file_path,
    safe_id,
)
from extui.api.models import (
    ConnectionEvent,
    ConsoleEvent,
    HeapEvent,
    ServerActionError,
    ServerStatus,
    StatsEvent,
    StatusEvent,
    TickEvent,
)

SERVER = {
    "id": "abc", "name": "S", "address": "s.exaroton.me", "motd": "", "status": 1,
    "players": {"max": 20, "count": 0, "list": []}, "software": None, "shared": False,
}


def client_with(handler) -> ExarotonClient:
    client = ExarotonClient("token")
    client._http = httpx.AsyncClient(base_url=DEFAULT_BASE_URL, transport=httpx.MockTransport(handler),
                                     headers={"Authorization": "Bearer token"})
    return client


def test_identifier_validation_blocks_traversal_and_injection() -> None:
    assert safe_id("7ZxtjLTBLh9yqPKr") == "7ZxtjLTBLh9yqPKr"
    assert safe_id("banned-players") == "banned-players"
    for bad in ("", "../account", "a/b", "a b", "a?x=1", "a#f", "a%2f"):
        with pytest.raises(ExarotonError):
            safe_id(bad)


def test_file_paths_are_escaped_and_traversal_is_rejected() -> None:
    assert safe_file_path("world/server.properties") == "world/server.properties"
    assert safe_file_path("/world//logs/") == "world/logs"
    assert safe_file_path("my folder/a b.txt") == "my%20folder/a%20b.txt"
    assert safe_file_path("") == ""
    for bad in ("../secrets", "world/../../etc/passwd", "world/./x"):
        with pytest.raises(ExarotonError):
            safe_file_path(bad)


async def test_unwraps_the_success_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"success": True, "error": None, "data": SERVER})

    server = await client_with(handler).server("abc")
    assert server.status is ServerStatus.ONLINE and server.id == "abc"


async def test_surfaces_api_level_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": "Server not found.", "data": None})

    with pytest.raises(ExarotonError, match="Server not found."):
        await client_with(handler).server("abc")


@pytest.mark.parametrize("code,fragment", [(401, "token"), (429, "rate limit")])
async def test_explains_auth_and_rate_limit_failures(code: int, fragment: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"success": False, "error": "x"})

    with pytest.raises(ExarotonError, match=fragment):
        await client_with(handler).account()


async def test_non_json_response_is_reported_clearly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(ExarotonError, match="non-JSON"):
        await client_with(handler).account()


async def test_network_failures_are_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ExarotonError, match="Network error"):
        await client_with(handler).account()


async def test_command_endpoint_posts_documented_body() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True, "data": None})

    await client_with(handler).send_command("abc", "  say hello  ")
    assert seen["url"].endswith("/servers/abc/command/")
    assert seen["body"] == {"command": "say hello"}


async def test_empty_command_is_refused_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent")

    with pytest.raises(ExarotonError, match="cannot be empty"):
        await client_with(handler).send_command("abc", "   ")


async def test_shared_server_start_uses_post_with_own_credits() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(200, json={"success": True, "data": None})

    await client_with(handler).perform("start", "abc", use_own_credits=True)
    assert seen["method"] == "POST" and seen["body"] == {"useOwnCredits": True}


async def test_plain_start_uses_get() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        return httpx.Response(200, json={"success": True, "data": None})

    await client_with(handler).perform("start", "abc")
    assert seen["method"] == "GET"


async def test_unknown_action_is_rejected() -> None:
    with pytest.raises(ServerActionError):
        await client_with(lambda r: httpx.Response(200, json={"success": True})).perform("nuke", "abc")


async def test_file_data_returns_raw_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/files/data/world/server.properties" in str(request.url)
        return httpx.Response(200, content=b"motd=hi\n")

    assert await client_with(handler).file_data("abc", "world/server.properties") == b"motd=hi\n"


async def test_perform_and_follow_reports_each_transition() -> None:
    statuses = iter([ServerStatus.OFFLINE, ServerStatus.LOADING, ServerStatus.STARTING, ServerStatus.ONLINE])
    current = {"value": ServerStatus.OFFLINE}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start/"):
            return httpx.Response(200, json={"success": True, "data": None})
        current["value"] = next(statuses, current["value"])
        return httpx.Response(200, json={"success": True, "data": {**SERVER, "status": int(current["value"])}})

    seen: list[ServerStatus] = []

    async def observe(server, _at):
        seen.append(server.status)

    final = await perform_and_follow(client_with(handler), "start", "abc", on_observation=observe, poll_interval=0.01)
    assert final.status is ServerStatus.ONLINE
    assert seen == [ServerStatus.OFFLINE, ServerStatus.LOADING, ServerStatus.STARTING, ServerStatus.ONLINE]


async def test_perform_and_follow_validates_before_acting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start/"):
            raise AssertionError("start must not be requested for an online server")
        return httpx.Response(200, json={"success": True, "data": SERVER})

    with pytest.raises(ServerActionError, match="Cannot start"):
        await perform_and_follow(client_with(handler), "start", "abc", poll_interval=0.01)


async def test_perform_and_follow_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stop/"):
            return httpx.Response(200, json={"success": True, "data": None})
        return httpx.Response(200, json={"success": True, "data": SERVER})

    with pytest.raises(ServerActionError, match="Timed out"):
        await perform_and_follow(client_with(handler), "stop", "abc", poll_interval=0.01, timeout=0.05)


async def test_perform_and_follow_returns_early_on_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start/"):
            return httpx.Response(200, json={"success": True, "data": None})
        status = ServerStatus.OFFLINE if not handler.started else ServerStatus.CRASHED
        handler.started = True
        return httpx.Response(200, json={"success": True, "data": {**SERVER, "status": int(status)}})

    handler.started = False
    final = await perform_and_follow(client_with(handler), "start", "abc", poll_interval=0.01)
    assert final.status is ServerStatus.CRASHED


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def stream(status: ServerStatus | None = ServerStatus.ONLINE) -> ServerStream:
    return ServerStream("token", DEFAULT_BASE_URL, "abc", tail=50, initial_status=status)


def test_stream_url_is_derived_from_the_rest_base() -> None:
    assert stream()._url == "wss://api.exaroton.com/v1/servers/abc/websocket"
    assert ServerStream("t", "http://localhost:8080/v1/", "abc")._url == "ws://localhost:8080/v1/servers/abc/websocket"


async def test_ready_subscribes_to_every_stream_when_online() -> None:
    s, socket = stream(), FakeSocket()
    events = await s._handle(socket, json.dumps({"type": "ready", "data": "abc"}))
    assert isinstance(events[0], ConnectionEvent) and events[0].state == "connected"
    assert [m["stream"] for m in socket.sent] == ["console", "tick", "stats", "heap"]
    assert socket.sent[0]["data"] == {"tail": 50}


async def test_offline_server_does_not_subscribe_until_it_starts() -> None:
    s, socket = stream(ServerStatus.OFFLINE), FakeSocket()
    await s._handle(socket, json.dumps({"type": "ready"}))
    assert socket.sent == [], "exaroton drops optional streams while the server is offline"

    events = await s._handle(socket, json.dumps({"type": "status", "data": {**SERVER, "status": 1}}))
    assert any(isinstance(e, StatusEvent) for e in events)
    assert [m["stream"] for m in socket.sent] == ["console", "tick", "stats", "heap"]


async def test_going_offline_clears_subscriptions() -> None:
    s, socket = stream(), FakeSocket()
    await s._handle(socket, json.dumps({"type": "ready"}))
    await s._handle(socket, json.dumps({"stream": "console", "type": "started"}))
    assert "console" in s._started
    await s._handle(socket, json.dumps({"type": "status", "data": {**SERVER, "status": 0}}))
    assert s._started == set()


async def test_decodes_console_tick_stats_and_heap_frames() -> None:
    s, socket = stream(), FakeSocket()

    started = await s._handle(socket, json.dumps({"stream": "console", "type": "started"}))
    assert isinstance(started[0], ConnectionEvent) and started[0].state == "live"

    line = await s._handle(socket, json.dumps(
        {"stream": "console", "type": "line", "data": "[12:00:00] [Server thread/INFO]: hi"}))
    assert isinstance(line[0], ConsoleEvent) and line[0].line.timestamp == "12:00:00"

    tick = await s._handle(socket, json.dumps({"stream": "tick", "type": "tick", "data": {"averageTickTime": 50.0}}))
    assert isinstance(tick[0], TickEvent) and tick[0].tps == 20.0

    slow = await s._handle(socket, json.dumps({"stream": "tick", "type": "tick", "data": {"averageTickTime": 100.0}}))
    assert slow[0].tps == 10.0

    stats = await s._handle(socket, json.dumps(
        {"stream": "stats", "type": "stats", "data": {"memory": {"percent": 42.5, "usage": 1_800_000_000}}}))
    assert isinstance(stats[0], StatsEvent) and stats[0].memory_percent == 42.5

    heap = await s._handle(socket, json.dumps({"stream": "heap", "type": "heap", "data": {"usage": 900_000_000}}))
    assert isinstance(heap[0], HeapEvent) and heap[0].usage_bytes == 900_000_000


async def test_tick_never_reports_more_than_twenty_tps() -> None:
    s = stream()
    fast = await s._handle(FakeSocket(), json.dumps({"stream": "tick", "type": "tick", "data": {"averageTickTime": 5.0}}))
    assert fast[0].tps == 20.0
    zero = await s._handle(FakeSocket(), json.dumps({"stream": "tick", "type": "tick", "data": {"averageTickTime": 0}}))
    assert zero[0].tps == 20.0


async def test_keep_alive_and_unknown_frames_are_ignored() -> None:
    s, socket = stream(), FakeSocket()
    assert await s._handle(socket, json.dumps({"type": "keep-alive"})) == []
    assert await s._handle(socket, json.dumps({"stream": "future", "type": "unknown"})) == []
    assert await s._handle(socket, "not json at all") == []
    assert await s._handle(socket, json.dumps(["a", "list"])) == []


async def test_server_initiated_disconnect_raises_for_reconnect() -> None:
    s = stream()
    with pytest.raises(ExarotonError, match="closed the stream"):
        await s._handle(FakeSocket(), json.dumps({"type": "disconnected", "data": "invalid-status"}))


async def test_console_command_can_be_sent_over_the_socket() -> None:
    s, socket = stream(), FakeSocket()
    assert await s.send_command("say hi") is False, "not sendable before the console stream starts"
    s._socket = socket
    await s._handle(socket, json.dumps({"stream": "console", "type": "started"}))
    assert await s.send_command("say hi") is True
    assert socket.sent[-1] == {"stream": "console", "type": "command", "data": "say hi"}


async def test_ready_frame_carries_the_server_id_as_a_string() -> None:
    s, socket = stream(ServerStatus.OFFLINE), FakeSocket()
    events = await s._handle(socket, json.dumps({"type": "ready", "data": "GBT3RzTLXHqeEUEE"}))
    assert isinstance(events[0], ConnectionEvent) and events[0].state == "connected"


async def test_premature_subscription_is_never_attempted_while_offline() -> None:
    s, socket = stream(ServerStatus.OFFLINE), FakeSocket()
    await s._handle(socket, json.dumps({"type": "ready", "data": "abc"}))
    assert socket.sent == []


async def test_invalid_status_disconnect_stops_us_re_subscribing_in_a_loop() -> None:
    s, socket = stream(ServerStatus.ONLINE), FakeSocket()
    await s._handle(socket, json.dumps({"type": "ready"}))
    assert socket.sent, "an online server does subscribe"
    with pytest.raises(ExarotonError, match="invalid-status"):
        await s._handle(socket, json.dumps({"type": "disconnected", "data": "invalid-status"}))
    assert s._online is False, "the next connection must only listen"
    assert s._started == set()

    fresh = FakeSocket()
    await s._handle(fresh, json.dumps({"type": "ready"}))
    assert fresh.sent == [], "reconnect must not immediately subscribe again"


async def test_polling_can_tell_the_stream_the_server_came_online() -> None:
    s, socket = stream(ServerStatus.OFFLINE), FakeSocket()
    await s._handle(socket, json.dumps({"type": "ready"}))
    assert socket.sent == []

    s._socket = socket
    await s.set_online(True)
    assert [m["stream"] for m in socket.sent] == ["console", "tick", "stats", "heap"]

    socket.sent.clear()
    await s.set_online(True)
    assert socket.sent == [], "an unchanged status must not re-subscribe"

    await s.set_online(False)
    assert s._started == set()


async def test_set_online_before_the_socket_exists_is_harmless() -> None:
    s = stream(ServerStatus.OFFLINE)
    await s.set_online(True)
    assert s._online is True, "the next ready frame will do the subscribing"


async def test_keep_alive_frames_are_tolerated() -> None:
    s = stream()
    assert await s._handle(FakeSocket(), json.dumps({"type": "keep-alive"})) == []
