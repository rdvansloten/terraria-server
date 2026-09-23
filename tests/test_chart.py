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
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from terraria_client import KNOWN_PROTOCOLS, TerrariaClient, discover_protocol

CHART_DIR = str(Path(__file__).resolve().parent.parent / "charts" / "terraria-server")
PASSWORD = "chart-test-pw"
SMALL_WORLD_CONFIG = "maxplayers=8\nport=7777\nsecure=1\nautocreate=1\ndifficulty=0\n"

pytestmark = pytest.mark.chart


def _run(*args: str, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)


# Set once the kind_cluster fixture resolves; every kubectl call targets this context.
_CONTEXT: str | None = None


def _kubectl(*args: str, **kw) -> subprocess.CompletedProcess[str]:
    ctx = ["--context", _CONTEXT] if _CONTEXT else []
    return _run("kubectl", *ctx, *args, **kw)


def _tool_missing(*tools: str) -> str | None:
    for tool in tools:
        if shutil.which(tool) is None:
            return f"{tool} not found on PATH"
    return None


def _docker_running() -> bool:
    try:
        return _run("docker", "info", timeout=20, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _current_kind_context() -> str | None:
    """Return the current kube context if it is a reachable kind cluster, else None."""
    ctx = _run("kubectl", "config", "current-context", check=False).stdout.strip()
    if ctx.startswith("kind-") and _run("kubectl", "cluster-info", check=False, timeout=20).returncode == 0:
        return ctx
    return None


@pytest.fixture(scope="module")
def kind_cluster(request: pytest.FixtureRequest):
    """A kind cluster to test against, with the --image loaded in.

    Uses the current context if it is already a kind cluster; otherwise, if docker and kind are
    available, creates an ephemeral cluster and deletes it afterwards. Skips (or, with --chart,
    fails) when the prerequisites are missing, so the chart test runs wherever it can and stays
    out of the way where it cannot.
    """
    force = request.config.getoption("--chart")

    def unavailable(reason: str):
        if force:
            pytest.fail(f"--chart was given but {reason}")
        pytest.skip(f"chart test skipped: {reason}")

    missing = _tool_missing("kubectl", "helm")
    if missing:
        unavailable(missing)
    if not _docker_running():
        unavailable("docker is not running")

    context = _current_kind_context()
    created = None
    if context is None:
        if _tool_missing("kind"):
            unavailable(
                "kind is required to run the chart test locally but is not installed "
                "(install it, e.g. 'brew install kind', or a cluster runs automatically in CI)"
            )
        created = f"terraria-test-{uuid.uuid4().hex[:8]}"
        _run("kind", "create", "cluster", "--name", created, "--wait", "60s", timeout=300)
        context = f"kind-{created}"

    cluster = context[len("kind-"):]
    global _CONTEXT
    _CONTEXT = context
    try:
        _run("kind", "load", "docker-image", request.config.getoption("--image"),
             "--name", cluster, timeout=300)
        yield {"context": context, "cluster": cluster}
    finally:
        _CONTEXT = None
        if created:
            _run("kind", "delete", "cluster", "--name", created, check=False, timeout=120)


@pytest.fixture(scope="module")
def deployment(request: pytest.FixtureRequest, kind_cluster):
    """Install the chart with the image under test into a unique namespace; wait for first rollout."""
    config = request.config
    image = config.getoption("--image")
    release = config.getoption("--release")
    namespace = config.getoption("--namespace") or f"terraria-test-{uuid.uuid4().hex[:8]}"
    repository, _, tag = image.rpartition(":")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as cfg:
        cfg.write(SMALL_WORLD_CONFIG)
        cfg_path = cfg.name
    try:
        _run(
            "helm", "--kube-context", kind_cluster["context"],
            "upgrade", "--install", release, CHART_DIR,
            "-n", namespace, "--create-namespace",
            "--set", f"image.repository={repository}",
            "--set", f"image.tag={tag}",
            "--set", "image.pullPolicy=Never",
            "--set", f"terraria.password.value={PASSWORD}",
            "--set-file", f"terraria.config={cfg_path}",
            timeout=180,
        )
    finally:
        Path(cfg_path).unlink(missing_ok=True)
    try:
        deploy = _kubectl("-n", namespace, "get", "deploy",
                      "-l", f"app.kubernetes.io/instance={release}", "-o", "name").stdout.strip()
        assert deploy, "no deployment created by the chart"
        svc = _kubectl("-n", namespace, "get", "svc",
                   "-l", f"app.kubernetes.io/instance={release}", "-o", "name").stdout.strip()
        _wait_ready(namespace, deploy, config.getoption("--startup-timeout"))
        yield {"namespace": namespace, "release": release, "deploy": deploy, "svc": svc}
    finally:
        if request.session.testsfailed:
            logs = _kubectl("-n", namespace, "logs", "-l",
                        f"app.kubernetes.io/instance={release}", "--tail=-1", check=False).stdout
            print(f"\n--- pod logs ---\n{logs}")
        # Deleting the namespace removes the release and all its PVCs; --wait=false keeps CI fast.
        _kubectl("delete", "namespace", namespace, "--ignore-not-found", "--wait=false", check=False)


def _wait_ready(namespace: str, deploy: str, timeout: int) -> None:
    _kubectl("-n", namespace, "rollout", "status", deploy, f"--timeout={timeout}s",
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
        ["kubectl", *(["--context", _CONTEXT] if _CONTEXT else []), "-n", namespace, "port-forward", svc, ":7777"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = _read_forward_port(proc)
        with TerrariaClient("127.0.0.1", port) as client:
            return client.connect_request(proto)
    finally:
        proc.terminate()


def _protocol(namespace: str, deploy: str, svc: str) -> int:
    logs = _kubectl("-n", namespace, "logs", deploy, "--tail=-1").stdout
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
