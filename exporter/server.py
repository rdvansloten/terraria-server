"""Terraria Prometheus exporter: parse the world, tail the log, serve /metrics."""

from __future__ import annotations

import os
import threading
import time

from prometheus_client import REGISTRY, start_http_server

from logs import LogState
from metrics import TerrariaCollector
from terraria_wld import parse_world_file


class Exporter:
    def __init__(self, world_path: str, parse_interval: int = 30):
        self.world_path = world_path
        self.parse_interval = parse_interval
        self.logs = LogState()
        self.world = None
        self.last_parsed = 0.0
        self._lock = threading.Lock()

    def parse_world_once(self) -> None:
        candidates = [self.world_path + ".bak", self.world_path]
        for path in candidates:
            if not os.path.exists(path):
                continue
            for _ in range(10):  # retry a torn read during a save
                try:
                    world = parse_world_file(path)
                    if world.parse_ok:
                        with self._lock:
                            self.world = world
                            self.last_parsed = time.time()
                        return
                except Exception:
                    pass
                time.sleep(0.5)

    def _parse_loop(self) -> None:
        while True:
            self.parse_world_once()
            time.sleep(self.parse_interval)

    def _file_stats(self):
        try:
            st = os.stat(self.world_path)
            return st.st_size, max(0.0, time.time() - st.st_mtime)
        except OSError:
            return 0, 0.0

    def snapshot(self) -> dict:
        with self._lock:
            world = self.world
            last = self.last_parsed
        size, age = self._file_stats()
        return {
            "world": world, "logs": self.logs,
            "world_file_bytes": size, "world_save_age": age,
            "last_parsed": last, "up": True,
        }

    def start(self, port: int) -> None:
        REGISTRY.register(TerrariaCollector(self.snapshot))
        self.parse_world_once()
        threading.Thread(target=self._parse_loop, daemon=True).start()
        start_http_server(port)


def _newest(dir_path: str) -> str | None:
    try:
        files = [os.path.join(dir_path, f) for f in os.listdir(dir_path)]
        files = [f for f in files if os.path.isfile(f)]
        return max(files, key=os.path.getmtime) if files else None
    except OSError:
        return None


def _tail_dir(dir_path: str, logs: LogState) -> None:
    """Follow the newest file in a directory, switching when a newer log appears (server restart)."""
    current, fh = None, None
    while True:
        newest = _newest(dir_path)
        if newest and newest != current:
            if fh:
                fh.close()
            fh = open(newest, "r", errors="replace")
            current = newest
        if fh is None:
            time.sleep(1)
            continue
        line = fh.readline()
        if line:
            logs.feed(line)
        else:
            time.sleep(0.5)
            if _newest(dir_path) != current:  # a newer log rotated in
                fh.close(); fh = None


def _tail(path: str, logs: LogState) -> None:
    while not os.path.exists(path):
        time.sleep(1)
    with open(path, "r", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        while True:
            line = fh.readline()
            if line:
                logs.feed(line)
            else:
                time.sleep(0.5)


def main() -> None:
    world_path = os.environ.get("WORLD_PATH", "/terraria/.local/share/Terraria/Worlds/Terraria.wld")
    port = int(os.environ.get("METRICS_PORT", "9150"))
    interval = int(os.environ.get("PARSE_INTERVAL", "30"))
    exp = Exporter(world_path, interval)
    exp.start(port)

    log_file = os.environ.get("LOG_FILE")
    log_dir = os.environ.get("LOG_DIR")
    if log_file:
        threading.Thread(target=_tail, args=(log_file, exp.logs), daemon=True).start()
    elif log_dir:
        threading.Thread(target=_tail_dir, args=(log_dir, exp.logs), daemon=True).start()
    if os.environ.get("LOG_STDIN", "").lower() == "true":
        import sys
        for line in sys.stdin:
            exp.logs.feed(line)
    else:
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
