"""Run the built exporter image and scrape /metrics. Needs --exporter-image."""

from __future__ import annotations

import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "world.wld"


def _port(name: str) -> int:
    out = subprocess.run(["docker", "port", name, "9150/tcp"], capture_output=True, text=True, check=True).stdout
    return int(out.strip().splitlines()[0].rsplit(":", 1)[1])


@pytest.fixture(scope="module")
def metrics_url(request: pytest.FixtureRequest):
    image = request.config.getoption("--exporter-image")
    if not image:
        pytest.skip("no --exporter-image given")
    platform = request.config.getoption("--platform")
    name = f"exporter-test-{uuid.uuid4().hex[:8]}"
    args = ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::9150",
            "-v", f"{FIXTURE}:/world.wld:ro", "-e", "WORLD_PATH=/world.wld"]
    if platform:
        args += ["--platform", platform]
    args.append(image)
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=180)
    try:
        yield f"http://127.0.0.1:{_port(name)}/metrics"
    finally:
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True).stdout
        if request.session.testsfailed:
            print(f"\n--- exporter logs ({name}) ---\n{logs}")
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _scrape(url: str, timeout: int = 30) -> str:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return r.read().decode()
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1)
    raise AssertionError(f"exporter /metrics did not respond: {last}")


def test_exporter_image_serves_metrics(metrics_url: str) -> None:
    body = _scrape(metrics_url)
    assert "terraria_world_parse_ok 1.0" in body, body[:500]
    assert "terraria_world_info{" in body
    assert 'terraria_boss_defeated{boss="' in body
    assert "terraria_exporter_up 1.0" in body
