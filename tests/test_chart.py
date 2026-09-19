"""Deploy the Helm chart to the current Kubernetes context and prove the game works in-cluster.

Enabled with --chart. Expects helm, kubectl, a reachable cluster (e.g. kind), and the --image
already loaded into it. The chart is installed into a unique namespace, the deployment is waited
on, and the Terraria protocol handshake is driven through a port-forward. Reuses terraria_client.

Unpatched vanilla Terraria has a netcode race on connection teardown (see tools/crash_repro.py)
that a client connecting to a freshly started server can occasionally trip, crashing it. In
production the pod then restarts and reloads the persisted world. This test mirrors that: it
retries the handshake, waiting for the deployment to become ready again between attempts, so it
verifies the chart deploys a server that serves and recovers, without depending on the unfixed
race never firing.
"""

from __future__ import annotations

import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from terraria_client import KNOWN_PROTOCOLS, TerrariaClient, discover_protocol

CHART_DIR = str(Path(__file__).resolve().parent.parent / "charts" / "terraria-server")
PASSWORD = "chart-test-pw"

pytestmark = pytest.mark.chart


def _run(*args: str, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)


@pytest.fixture(scope="module")
def deployment(request: pytest.FixtureRequest):
    """Install the chart with the image under test into a unique namespace; wait for first rollout."""
    config = request.config
    image = config.getoption("--image")
    release = config.getoption("--release")
    namespace = config.getoption("--namespace") or f"terraria-test-{uuid.uuid4().hex[:8]}"
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
    try:
        deploy = _run("kubectl", "-n", namespace, "get", "deploy",
                      "-l", f"app.kubernetes.io/instance={release}", "-o", "name").stdout.strip()
        assert deploy, "no deployment created by the chart"
        svc = _run("kubectl", "-n", namespace, "get", "svc",
                   "-l", f"app.kubernetes.io/instance={release}", "-o", "name").stdout.strip()
        _wait_ready(namespace, deploy, config.getoption("--startup-timeout"))
        yield {"namespace": namespace, "release": release, "deploy": deploy, "svc": svc}
    finally:
        if request.session.testsfailed:
            logs = _run("kubectl", "-n", namespace, "logs", "-l",
                        f"app.kubernetes.io/instance={release}", "--tail=-1", check=False).stdout
            print(f"\n--- pod logs ---\n{logs}")
        # Deleting the namespace removes the release and all its PVCs; --wait=false keeps CI fast.
        _run("kubectl", "delete", "namespace", namespace, "--ignore-not-found", "--wait=false", check=False)


def _wait_ready(namespace: str, deploy: str, timeout: int) -> None:
    _run("kubectl", "-n", namespace, "rollout", "status", deploy, f"--timeout={timeout}s",
         timeout=timeout + 30)


def _read_forward_port(proc: subprocess.Popen, timeout: int = 30) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line)
        if match:
            return int(match.group(1))
        if proc.poll() is not None:
            raise ConnectionError("kubectl port-forward exited before reporting a port")
    raise ConnectionError("kubectl port-forward did not report a local port in time")


def _handshake(namespace: str, svc: str, proto: int) -> int:
    """One attempt through a fresh port-forward: return the ConnectRequest reply type."""
    proc = subprocess.Popen(
        ["kubectl", "-n", namespace, "port-forward", svc, ":7777"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = _read_forward_port(proc)
        with TerrariaClient("127.0.0.1", port) as client:
            return client.connect_request(proto)
    finally:
        proc.terminate()


def _protocol(namespace: str, deploy: str, svc: str) -> int:
    logs = _run("kubectl", "-n", namespace, "logs", deploy, "--tail=-1").stdout
    match = re.search(r"Terraria Server v(\d+\.\d+\.\d+\.\d+)", logs)
    assert match, "server version not found in pod logs"
    return KNOWN_PROTOCOLS.get(match.group(1)) or discover_protocol("127.0.0.1", 0, logs)


def test_chart_deploys_and_serves_the_game(deployment, request: pytest.FixtureRequest) -> None:
    """The pod becomes ready and the server answers the Terraria handshake through the Service.

    If the unpatched netcode race crashes the server on a connection, the pod restarts and reloads
    the world; the loop waits for it to be ready again and retries, so the test passes as long as
    the chart deploys a server that serves and recovers."""
    ns, deploy, svc = deployment["namespace"], deployment["deploy"], deployment["svc"]
    proto = _protocol(ns, deploy, svc)
    budget = request.config.getoption("--startup-timeout")

    deadline = time.monotonic() + budget
    last: str | None = None
    while time.monotonic() < deadline:
        _wait_ready(ns, deploy, 180)  # blocks if a crash is being restarted
        try:
            reply = _handshake(ns, svc, proto)
            if reply != 2:  # 3 = ContinueConnecting, 37 = PasswordRequired; 2 = version-mismatch Disconnect
                return
            last = "server sent a version-mismatch Disconnect (wrong tests.protocol?)"
        except OSError as exc:
            last = f"{type(exc).__name__}: {exc}"  # likely the netcode race crashed the server; retry after restart
        time.sleep(3)
    raise AssertionError(f"server never completed the handshake within {budget}s: {last}")
