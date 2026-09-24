"""Generic tests that every Terraria server image built from this repository must pass."""

from __future__ import annotations

import re
import socket
import time

import pytest

from conftest import LISTENING_PATTERN, Server

WORLD_PATH = "/terraria/.local/share/Terraria/Worlds/Terraria.wld"
CONFIG_PATH = "/terraria/config"
LOG_PATH = "/terraria/logs"
EXPECTED_UID = "999"

CONNECT_PACKET = b"\x04\x00\x01\x00"


@pytest.mark.portable
def test_server_listens(server: Server) -> None:
    assert LISTENING_PATTERN in server.logs()


@pytest.mark.portable
def test_server_reports_terraria_version(server: Server) -> None:
    match = re.search(r"Terraria Server v(\d+\.\d+\.\d+(?:\.\d+)?)", server.logs())
    assert match, "no 'Terraria Server v<version>' line in logs"
    print(f"Terraria version: {match.group(1)}")


@pytest.mark.portable
def test_server_speaks_terraria_protocol(server: Server) -> None:
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with socket.create_connection((server.host, server.port), timeout=5) as sock:
                sock.sendall(CONNECT_PACKET)
                response = sock.recv(1024)
        except OSError as exc:
            last_error = exc
            time.sleep(1)
            continue
        assert b"Multiplayer" in response, f"unexpected protocol response: {response!r}"
        return
    pytest.fail(f"could not complete protocol handshake: {last_error}")


@pytest.mark.portable
def test_server_runs_as_terraria_user(server: Server) -> None:
    uid = server.exec("id", "-u").stdout.strip()
    assert uid == EXPECTED_UID, f"server runs as uid {uid}, expected {EXPECTED_UID}"


@pytest.mark.portable
def test_world_file_is_created(server: Server) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if server.file_exists(WORLD_PATH):
            return
        time.sleep(2)
    pytest.fail(f"world file {WORLD_PATH} was not written within 120s")


@pytest.mark.portable
def test_writable_paths_are_owned_by_server_user(server: Server) -> None:
    for path in (CONFIG_PATH, LOG_PATH, WORLD_PATH.rsplit("/", 1)[0]):
        owner = server.exec("stat", "-c", "%u", path).stdout.strip()
        assert owner == EXPECTED_UID, f"{path} is owned by uid {owner}, expected {EXPECTED_UID}"


@pytest.mark.portable
def test_no_startup_errors_in_logs(server: Server) -> None:
    logs = server.logs()
    for pattern in (
        r"Exception",
        r"Permission denied",
        r"Access to the path",
        r"cannot recover",
        r"Native Crash Reporting",
        r"exec format error",
    ):
        assert not re.search(pattern, logs), f"found '{pattern}' in server logs"


@pytest.mark.portable
@pytest.mark.flavor("vanilla")
def test_vanilla_uses_repository_serverconfig(server: Server) -> None:
    assert server.file_exists(f"{CONFIG_PATH}/serverconfig.txt")
    assert f"Config file   : {CONFIG_PATH}/serverconfig.txt" in server.logs()


@pytest.mark.portable
@pytest.mark.flavor("tshock")
def test_tshock_plugin_is_running(server: Server) -> None:
    logs = server.logs()
    assert re.search(r"TShock \d+\.\d+\.\d+\.\d+ .* now running", logs), "TShock banner not found"
    assert "Plugin TShock" in logs and "initiated" in logs


@pytest.mark.portable
@pytest.mark.flavor("tshock")
def test_tshock_writes_config_and_database(server: Server) -> None:
    for name in ("config.json", "sscconfig.json", "tshock.sqlite"):
        assert server.file_exists(f"{CONFIG_PATH}/{name}"), f"{name} missing from {CONFIG_PATH}"


@pytest.mark.portable
@pytest.mark.flavor("tshock")
def test_tshock_writes_its_log_files(server: Server) -> None:
    """TShock keeps a timestamped log and TerrariaServerAPI writes ServerLog.txt; both must exist in"""
    listing = server.exec("sh", "-c", f"ls -1 {LOG_PATH}").stdout.split()
    assert "ServerLog.txt" in listing, listing
    assert any(re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log", name) for name in listing), listing
    for name in listing:
        stat = server.exec("stat", "-c", "%u %s", f"{LOG_PATH}/{name}").stdout.split()
        assert stat[0] == EXPECTED_UID, f"{name} owned by uid {stat[0]}"
        assert int(stat[1]) > 0, f"{name} is empty"
    server_log = server.exec("cat", f"{LOG_PATH}/ServerLog.txt").stdout
    assert "Plugin TShock" in server_log and "initiated" in server_log
    assert "Could not write" not in server.logs()
