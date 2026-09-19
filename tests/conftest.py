"""Shared fixtures for the Terraria server image tests.

The tests are image-agnostic: point them at any image built from this repository with
``--image`` and they start it in TEST_MODE (auto-creating a world), wait until the server
listens, then run the checks against the running container.

    pytest tests --image terraria-server:vanilla --flavor vanilla
    pytest tests --image terraria-server:tshock  --flavor tshock --platform linux/arm64
"""

from __future__ import annotations

import re
import subprocess
import time
import uuid
from dataclasses import dataclass

import pytest

SERVER_PORT = 7777
LISTENING_PATTERN = "Listening on port 7777"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("terraria")
    group.addoption("--image", required=True, help="Image to test, e.g. terraria-server:vanilla")
    group.addoption(
        "--flavor",
        choices=["vanilla", "tshock"],
        default=None,
        help="Image flavor; enables flavor-specific tests (default: generic tests only)",
    )
    group.addoption("--platform", default=None, help="Docker platform, e.g. linux/amd64 (default: host)")
    group.addoption(
        "--startup-timeout",
        type=int,
        default=300,
        help="Seconds to wait for the server to listen (default: 300; emulated builds are slow)",
    )
    group.addoption(
        "--chart",
        action="store_true",
        default=False,
        help="Run the Helm chart deployment tests against the current kube context (needs helm, "
        "kubectl and a cluster with the --image already loaded, e.g. a kind cluster)",
    )
    group.addoption("--release", default="tt", help="Helm release name for the chart tests")
    group.addoption(
        "--namespace",
        default="",
        help="Namespace for the chart tests; empty generates a unique one per run so PVCs are "
        "never reused, even on a persistent cluster (the namespace is deleted afterwards)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "flavor(name): test only applies to the given image flavor")
    config.addinivalue_line("markers", "chart: Helm chart deployment test (needs --chart)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    flavor = config.getoption("--flavor")
    run_chart = config.getoption("--chart")
    for item in items:
        marker = item.get_closest_marker("flavor")
        if marker and marker.args[0] != flavor:
            item.add_marker(pytest.mark.skip(reason=f"only for --flavor {marker.args[0]}"))
        if item.get_closest_marker("chart") and not run_chart:
            item.add_marker(pytest.mark.skip(reason="chart tests require --chart"))
        if run_chart and not item.get_closest_marker("chart"):
            item.add_marker(pytest.mark.skip(reason="--chart runs only the chart tests"))


def docker(*args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


@dataclass
class Server:
    """Handle on a running server container."""

    name: str
    image: str
    host: str
    port: int

    def logs(self) -> str:
        result = docker("logs", self.name, check=False)
        return result.stdout + result.stderr

    def exec(self, *cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return docker("exec", self.name, *cmd, check=check)

    def file_exists(self, path: str) -> bool:
        return self.exec("test", "-e", path, check=False).returncode == 0

    def wait_for_log(self, pattern: str, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        regex = re.compile(pattern)
        while time.monotonic() < deadline:
            if regex.search(self.logs()):
                return True
            if not self.is_running():
                return False
            time.sleep(1)
        return False

    def is_running(self) -> bool:
        result = docker("inspect", "-f", "{{.State.Running}}", self.name, check=False)
        return result.stdout.strip() == "true"

    def exit_code(self) -> int:
        return int(docker("inspect", "-f", "{{.State.ExitCode}}", self.name).stdout.strip())

    def wait_for_exit(self, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                return True
            time.sleep(1)
        return False

    def read_file(self, path: str) -> bytes:
        return subprocess.run(["docker", "exec", self.name, "cat", path], capture_output=True, check=True).stdout

    def write_file(self, path: str, data: bytes) -> None:
        """Write a file as the container user, like kubectl cp does."""
        subprocess.run(["docker", "exec", "-i", self.name, "sh", "-c", f"cat > '{path}'"], input=data, check=True)


def _host_port(name: str) -> tuple[str, int]:
    result = docker("port", name, f"{SERVER_PORT}/tcp", check=False)
    out = result.stdout.strip().splitlines()
    if result.returncode != 0 or not out:
        return "127.0.0.1", 0  # container already exited; there is no mapping to report
    for line in out:
        host, _, port = line.rpartition(":")
        if "." in host:  # prefer the IPv4 binding
            return host, int(port)
    host, _, port = out[0].rpartition(":")
    return host.strip("[]"), int(port)


def start_container(config: pytest.Config, env: dict[str, str], extra_args: list[str] | None = None) -> Server:
    """Start the image under test with the given environment and return a handle."""
    image = config.getoption("--image")
    platform = config.getoption("--platform")
    name = f"terraria-test-{uuid.uuid4().hex[:8]}"

    run_args = ["run", "-d", "--name", name, "-p", f"127.0.0.1::{SERVER_PORT}"]
    for key, value in env.items():
        run_args += ["-e", f"{key}={value}"]
    if platform:
        run_args += ["--platform", platform]
    run_args += extra_args or []
    run_args.append(image)
    docker(*run_args, timeout=600)

    host, port = _host_port(name)
    return Server(name=name, image=image, host=host, port=port)


@pytest.fixture(scope="session")
def server(request: pytest.FixtureRequest) -> Server:
    """A server started in TEST_MODE that has finished generating a world and is listening."""
    timeout = request.config.getoption("--startup-timeout")
    srv = start_container(request.config, {"TEST_MODE": "true"})
    try:
        if not srv.wait_for_log(re.escape(LISTENING_PATTERN), timeout):
            pytest.fail(
                f"Server did not report '{LISTENING_PATTERN}' within {timeout}s "
                f"(running={srv.is_running()}).\n--- container logs ---\n{srv.logs()}"
            )
        yield srv
    finally:
        if request.session.testsfailed:
            print(f"\n--- container logs ({srv.name}) ---\n{srv.logs()}")
        docker("rm", "-f", srv.name, check=False)


@pytest.fixture
def run_server(request: pytest.FixtureRequest):
    """Factory for additional short-lived containers; everything started is removed afterwards."""
    started: list[Server] = []

    def _run(env: dict[str, str], extra_args: list[str] | None = None) -> Server:
        srv = start_container(request.config, env, extra_args)
        started.append(srv)
        return srv

    yield _run

    for srv in started:
        if request.session.testsfailed:
            print(f"\n--- container logs ({srv.name}) ---\n{srv.logs()}")
        docker("rm", "-f", srv.name, check=False)
