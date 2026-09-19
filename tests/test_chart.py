"""Deploy the Helm chart to the current Kubernetes context and prove the game works in-cluster.

Enabled with --chart. Expects helm, kubectl, a reachable cluster (e.g. kind), and the --image
already loaded into it. The chart is installed with that image, the deployment is waited on, and
the Terraria protocol handshake is driven through a port-forward. Reuses terraria_client.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import pytest

from terraria_client import KNOWN_PROTOCOLS, TerrariaClient, discover_protocol

CHART_DIR = str(Path(__file__).resolve().parent.parent / "charts" / "terraria-server")
PASSWORD = "chart-test-pw"

pytestmark = pytest.mark.chart


def _run(*args: str, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)


def _kubectl(config: pytest.Config, *args: str, **kw) -> subprocess.CompletedProcess[str]:
    return _run("kubectl", "-n", config.getoption("--namespace"), *args, **kw)


@pytest.fixture(scope="module")
def deployment(request: pytest.FixtureRequest):
    """Install the chart with the image under test, wait for rollout, and port-forward the service."""
    config = request.config
    image = config.getoption("--image")
    release = config.getoption("--release")
    namespace = config.getoption("--namespace")
    repository, _, tag = image.rpartition(":")

    _run(
        "helm", "upgrade", "--install", release, CHART_DIR,
        "-n", namespace, "--create-namespace",
        "--set", f"image.repository={repository}",
        "--set", f"image.tag={tag}",
        "--set", "image.pullPolicy=Never",
        "--set", f"terraria.password.value={PASSWORD}",
        timeout=180,
    )
    port_forward = None
    try:
        # Wait for the server to become ready (readiness probe = TCP 7777 open, i.e. world generated).
        deploy = _kubectl(config, "get", "deploy", "-l", f"app.kubernetes.io/instance={release}",
                          "-o", "name").stdout.strip()
        assert deploy, "no deployment created by the chart"
        _kubectl(config, "rollout", "status", deploy,
                 f"--timeout={config.getoption('--startup-timeout')}s", timeout=config.getoption("--startup-timeout") + 30)

        svc = _kubectl(config, "get", "svc", "-l", f"app.kubernetes.io/instance={release}",
                       "-o", "name").stdout.strip()
        port_forward = subprocess.Popen(
            ["kubectl", "-n", namespace, "port-forward", svc, ":7777"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        local_port = _read_forward_port(port_forward)
        logs = _kubectl(config, "logs", deploy, "--tail=-1").stdout
        yield {"host": "127.0.0.1", "port": local_port, "logs": logs, "deploy": deploy}
    finally:
        if port_forward:
            port_forward.terminate()
        if request.session.testsfailed:
            logs = _kubectl(config, "logs", "-l", f"app.kubernetes.io/instance={release}",
                            "--tail=-1", check=False).stdout
            print(f"\n--- pod logs ---\n{logs}")
        _run("helm", "uninstall", release, "-n", namespace, check=False)


def _read_forward_port(proc: subprocess.Popen, timeout: int = 30) -> int:
    """Parse the local port kubectl port-forward chose from its first output line."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line)
        if match:
            return int(match.group(1))
        if proc.poll() is not None:
            raise AssertionError("kubectl port-forward exited before reporting a port")
    raise AssertionError("kubectl port-forward did not report a local port in time")


def _protocol(logs: str, host: str, port: int) -> int:
    match = re.search(r"Terraria Server v(\d+\.\d+\.\d+\.\d+)", logs)
    assert match, "server version not found in pod logs"
    return KNOWN_PROTOCOLS.get(match.group(1)) or discover_protocol(host, port, logs)


def test_chart_deploys_and_serves_the_game(deployment) -> None:
    """The pod becomes ready and the server answers the Terraria protocol handshake through the
    Service, with the password (set via the chart's generated Secret path) enforced."""
    host, port = deployment["host"], deployment["port"]
    proto = _protocol(deployment["logs"], host, port)

    last_error: Exception | None = None
    for _attempt in range(5):  # the port-forward can need a moment to be ready
        try:
            with TerrariaClient(host, port) as client:
                reply = client.connect_request(proto)
            assert reply != 2, "server rejected the protocol (version mismatch)"
            return
        except OSError as exc:
            last_error = exc
            time.sleep(2)
    raise AssertionError(f"could not reach the server through the port-forward: {last_error}")
