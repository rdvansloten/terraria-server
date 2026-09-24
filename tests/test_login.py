"""Walk the real join handshake against a password-protected server, per flavor."""

from __future__ import annotations

import re
import time

import pytest

from conftest import LISTENING_PATTERN, Server
from terraria_client import (
    CONTINUE_CONNECTING,
    DISCONNECT,
    INCORRECT_PASSWORD,
    KNOWN_PROTOCOLS,
    PASSWORD_REQUIRED,
    WORLD_INFO,
    TerrariaClient,
    discover_protocol,
)

PASSWORD = "s3cret-pass"


def _protocol(srv: Server) -> int:
    """Known mapping first; otherwise discover it so a Terraria bump does not break the tests."""
    logs = srv.logs()
    match = re.search(r"Terraria Server v(\d+\.\d+\.\d+\.\d+)", logs)
    assert match, "server version not found in logs"
    version = match.group(1)
    proto = KNOWN_PROTOCOLS.get(version) or discover_protocol(srv.host, srv.port, logs)
    if version not in KNOWN_PROTOCOLS:
        print(f"\nTerraria {version} speaks protocol {proto}; add it to KNOWN_PROTOCOLS in terraria_client.py")
    return proto


@pytest.fixture(scope="module")
def protected(request: pytest.FixtureRequest):
    """A server started with TERRARIA_PASSWORD, shared by the tests in this module."""
    from conftest import docker, start_container

    timeout = request.config.getoption("--startup-timeout")
    srv = start_container(request.config, {"TEST_MODE": "true", "TERRARIA_PASSWORD": PASSWORD})
    try:
        assert srv.wait_for_log(re.escape(LISTENING_PATTERN), timeout), srv.logs()
        yield srv
    finally:
        if request.session.testsfailed:
            print(f"\n--- container logs ({srv.name}) ---\n{srv.logs()}")
        docker("rm", "-f", srv.name, check=False)


@pytest.mark.flavor("vanilla")
def test_vanilla_password_login_flow(protected: Server) -> None:
    """Vanilla prompts for the password right after ConnectRequest."""
    proto = _protocol(protected)

    with TerrariaClient(protected.host, protected.port) as client:
        assert client.connect_request(proto) == PASSWORD_REQUIRED
        kind, _ = client.send_password(PASSWORD)
        assert kind == CONTINUE_CONNECTING, f"right password was not accepted (reply {kind})"
    time.sleep(1)
    assert protected.is_running(), "server died on a normal login"

    with TerrariaClient(protected.host, protected.port) as client:
        assert client.connect_request(proto) == PASSWORD_REQUIRED
        kind, reason = client.send_password("definitely-wrong")
        assert kind == DISCONNECT, f"wrong password was not rejected (reply {kind})"
        assert reason == INCORRECT_PASSWORD, reason  # vanilla sends the localization key


@pytest.mark.flavor("tshock")
def test_tshock_password_login_flow(protected: Server) -> None:
    """TShock assigns a slot first and asks for the server password once the client requests"""
    proto = _protocol(protected)

    with TerrariaClient(protected.host, protected.port) as client:
        assert client.connect_request(proto) == CONTINUE_CONNECTING
        client.client_uuid()
        client.player_info("rightpw")
        kind, reason = client.request_world_data()
        assert kind == PASSWORD_REQUIRED, f"expected the password prompt, got {kind} {reason!r}"
        kind, _ = client.send_password(PASSWORD)
        assert kind == WORLD_INFO, f"right password was not accepted (reply {kind})"
    time.sleep(1)
    assert protected.is_running(), "server died on a normal login"

    # Wrong password last.
    with TerrariaClient(protected.host, protected.port) as client:
        assert client.connect_request(proto) == CONTINUE_CONNECTING
        client.client_uuid()
        client.player_info("wrongpw")
        kind, reason = client.request_world_data()
        assert kind == PASSWORD_REQUIRED, f"expected the password prompt, got {kind} {reason!r}"
        kind, reason = client.send_password("definitely-wrong")
        assert kind == DISCONNECT, f"wrong password was not rejected (reply {kind})"
        assert "invalid server password" in reason.lower(), reason

    time.sleep(1)
    assert protected.is_running(), "server died during the login flow"
    assert "FATAL" not in protected.logs(), protected.logs()
