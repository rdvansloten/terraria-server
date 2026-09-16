"""How the image obtains its world: autocreate, wait-for-import, and refusing to guess."""

from __future__ import annotations

import re
import time

import pytest

from conftest import LISTENING_PATTERN, Server, docker

WORLD_DIR = "/terraria/.local/share/Terraria/Worlds"
WORLD_PATH = f"{WORLD_DIR}/Terraria.wld"


@pytest.fixture
def startup_timeout(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--startup-timeout")


def test_autocreate_generates_world_when_missing(run_server, startup_timeout: int) -> None:
    srv: Server = run_server({"AUTOCREATE": "1", "SEED": "12345", "DIFFICULTY": "0"})
    assert srv.wait_for_log(re.escape(LISTENING_PATTERN), startup_timeout), srv.logs()
    logs = srv.logs()
    assert "No existing world found. Creating world 'Terraria' (size 1, seed 12345, difficulty 0)." in logs
    assert re.search(r"Creating world - Seed: 12345", logs)
    assert srv.file_exists(WORLD_PATH)


def test_missing_world_without_autocreate_exits_with_error(run_server) -> None:
    srv: Server = run_server({})
    assert srv.wait_for_exit(60), "container should have exited"
    assert srv.exit_code() == 1
    logs = srv.logs()
    assert f"Error: No world file at '{WORLD_PATH}'" in logs
    assert "AUTOCREATE" in logs and "WAIT_FOR_WORLD" in logs
    assert LISTENING_PATTERN not in logs


def test_invalid_autocreate_size_is_rejected(run_server) -> None:
    srv: Server = run_server({"AUTOCREATE": "9"})
    assert srv.wait_for_exit(60)
    assert srv.exit_code() == 1
    assert "AUTOCREATE must be 1 (small), 2 (medium) or 3 (large)" in srv.logs()


def test_wait_for_world_then_import_starts_server(server: Server, run_server, startup_timeout: int) -> None:
    # Take the world the session server generated as the "existing world" to import
    world = server.read_file(WORLD_PATH)
    assert len(world) > 100_000, "session server world looks too small"

    srv: Server = run_server({"WAIT_FOR_WORLD": "true", "AUTOCREATE": "2"})
    assert srv.wait_for_log(re.escape(f"Waiting for world file: {WORLD_PATH}"), 60), srv.logs()
    assert "kubectl cp" in srv.logs()
    time.sleep(5)
    assert srv.is_running(), "container should keep waiting"
    assert LISTENING_PATTERN not in srv.logs(), "server must not start (or autocreate) while waiting"

    srv.write_file(WORLD_PATH, world)

    assert srv.wait_for_log(re.escape(LISTENING_PATTERN), startup_timeout), srv.logs()
    logs = srv.logs()
    assert f"World file received ({len(world)} bytes)." in logs
    assert f"Loading existing world: {WORLD_PATH}" in logs
    assert "Creating world" not in logs, "imported world must be loaded, not regenerated"


def test_existing_world_is_not_overwritten_by_autocreate(server: Server, run_server, startup_timeout: int) -> None:
    # Pre-seed a volume with a world, then start with autocreate enabled
    world = server.read_file(WORLD_PATH)
    volume = f"terraria-test-{srv_id()}"
    import subprocess
    subprocess.run(["docker", "volume", "create", volume], check=True, capture_output=True)
    try:
        subprocess.run(
            ["docker", "run", "--rm", "-i", "-v", f"{volume}:{WORLD_DIR}", "--entrypoint", "sh", server.image,
             "-c", f"cat > {WORLD_PATH}"],
            input=world, check=True,
        )
        srv: Server = run_server({"AUTOCREATE": "3"}, ["-v", f"{volume}:{WORLD_DIR}"])
        assert srv.wait_for_log(re.escape(LISTENING_PATTERN), startup_timeout), srv.logs()
        logs = srv.logs()
        assert f"Loading existing world: {WORLD_PATH}" in logs
        assert "Creating world" not in logs
        # remove the container before the volume so the volume can be deleted
        docker("rm", "-f", srv.name, check=False)
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", volume], check=False, capture_output=True)


def srv_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


@pytest.mark.flavor("vanilla")
def test_empty_config_folder_is_seeded_with_default(run_server, startup_timeout: int, tmp_path) -> None:
    """Bind-mounting an empty host folder at /terraria/config (the README quick start) must not
    silently drop the default config; the entrypoint seeds it so the user has a file to edit."""
    import os
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    os.chmod(config_dir, 0o777)  # the container runs as uid 999, which is not the host user
    srv: Server = run_server({"AUTOCREATE": "1"}, ["-v", f"{config_dir}:/terraria/config"])
    assert srv.wait_for_log(re.escape(LISTENING_PATTERN), startup_timeout), srv.logs()
    assert "No serverconfig.txt found in /terraria/config, seeded the default." in srv.logs()
    seeded = (config_dir / "serverconfig.txt").read_text()
    assert "maxplayers=8" in seeded and "port=7777" in seeded


@pytest.mark.flavor("vanilla")
def test_existing_config_is_not_overwritten(run_server, startup_timeout: int, tmp_path) -> None:
    """Second start with a user-edited config: the file is used as-is."""
    import os
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    os.chmod(config_dir, 0o777)
    (config_dir / "serverconfig.txt").write_text("maxplayers=3\nport=7777\nmotd=custom motd\n")
    srv: Server = run_server({"AUTOCREATE": "1"}, ["-v", f"{config_dir}:/terraria/config"])
    assert srv.wait_for_log(re.escape(LISTENING_PATTERN), startup_timeout), srv.logs()
    assert "seeded the default" not in srv.logs()
    assert (config_dir / "serverconfig.txt").read_text() == "maxplayers=3\nport=7777\nmotd=custom motd\n"
