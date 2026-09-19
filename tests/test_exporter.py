"""The exporter emits every metric it promises, with values set.

Parses a real 1.4.5.8 world fixture, feeds representative log lines, renders the Prometheus
exposition, and asserts every expected metric family is present and populated. No container needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXPORTER = str(Path(__file__).resolve().parent.parent / "exporter")
sys.path.insert(0, EXPORTER)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "world-1.4.5.8.wld"

prometheus_client = pytest.importorskip("prometheus_client")
from prometheus_client import CollectorRegistry, generate_latest  # noqa: E402

from logs import LogState  # noqa: E402
from metrics import TerrariaCollector  # noqa: E402
from terraria_wld import parse_world_file  # noqa: E402

# Every metric family the exporter must emit.
EXPECTED = [
    "terraria_world_info",
    "terraria_hardmode", "terraria_difficulty", "terraria_evil_type",
    "terraria_world_width", "terraria_world_height", "terraria_altars_smashed",
    "terraria_boss_defeated", "terraria_invasion_defeated", "terraria_npc_saved",
    "terraria_players_online", "terraria_player_joins_total", "terraria_player_leaves_total",
    "terraria_player_deaths_total", "terraria_world_saves_total", "terraria_login_attempts_total",
    "terraria_boss_spawned_total", "terraria_invasion_started_total",
    "terraria_server_start_time_seconds",
    "terraria_world_file_bytes", "terraria_world_save_age_seconds",
    "terraria_world_parse_ok", "terraria_world_last_parsed_seconds", "terraria_exporter_up",
]


@pytest.fixture
def exposition() -> str:
    world = parse_world_file(str(FIXTURE))
    assert world.parse_ok, "fixture world did not parse"
    logs = LogState()
    for line in [
        "Terraria Server v1.4.5.8",
        "Server started",
        "Alice has joined.", "Bob has joined.", "Bob has left.",
        "Skeletron has awoken!",
        "A goblin army is approaching from the east!",
        "Saving world data: ",
        "Alice authenticated successfully as user alice.",
        "Mallory failed to login.",
        "Bob was slain by a Zombie",
    ]:
        logs.feed(line, now=1000.0)

    snapshot = {
        "world": world, "logs": logs,
        "world_file_bytes": FIXTURE.stat().st_size,
        "world_save_age": 5.0, "last_parsed": 1000.0, "up": True,
    }
    registry = CollectorRegistry()
    registry.register(TerrariaCollector(lambda: snapshot))
    return generate_latest(registry).decode()


def _samples(text: str) -> dict:
    """Map metric series (name plus sorted labels) to float value, ignoring HELP/TYPE lines."""
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        series, _, value = line.rpartition(" ")
        out[series] = float(value)
    return out


def test_every_expected_metric_family_is_present(exposition: str) -> None:
    families = {line.split()[2] for line in exposition.splitlines() if line.startswith("# TYPE")}
    for name in EXPECTED:
        assert name in families, f"metric family {name} is missing from the exposition"


def test_world_state_values_are_set(exposition: str) -> None:
    s = _samples(exposition)
    assert s["terraria_world_parse_ok"] == 1.0
    assert s["terraria_exporter_up"] == 1.0
    assert s["terraria_world_width"] == 4200.0
    assert s["terraria_world_height"] == 1200.0
    assert s["terraria_world_file_bytes"] > 0
    assert s["terraria_world_last_parsed_seconds"] == 1000.0
    # difficulty/evil/hardmode/altars exist as numbers
    for name in ("terraria_difficulty", "terraria_evil_type", "terraria_hardmode", "terraria_altars_smashed"):
        assert name in s, name


def test_world_info_labels_are_populated(exposition: str) -> None:
    info = [ln for ln in exposition.splitlines() if ln.startswith("terraria_world_info{")]
    assert info, "world_info series missing"
    line = info[0]
    for label in ("world_name=", "seed=", "game_version=", "format_version=", "worldgen_version="):
        assert label in line, f"{label} missing from world_info"
    assert 'game_version="1.4.5.8"' in line
    assert 'format_version="326"' in line
    assert line.rstrip().endswith(" 1.0")


def test_labeled_families_have_series(exposition: str) -> None:
    s = _samples(exposition)
    assert any(k.startswith("terraria_boss_defeated{") for k in s), "no boss_defeated series"
    assert any(k.startswith("terraria_invasion_defeated{") for k in s), "no invasion_defeated series"
    assert any(k.startswith("terraria_npc_saved{") for k in s), "no npc_saved series"
    # a known boss label is present
    assert any('boss="plantera"' in k for k in s), "plantera series missing"


def test_live_activity_counters_reflect_the_log(exposition: str) -> None:
    s = _samples(exposition)
    assert s["terraria_player_joins_total"] == 2.0
    assert s["terraria_player_leaves_total"] == 1.0
    assert s["terraria_player_deaths_total"] == 1.0
    assert s["terraria_world_saves_total"] == 1.0
    assert s['terraria_login_attempts_total{status="success"}'] == 1.0
    assert s['terraria_login_attempts_total{status="bad_password"}'] == 1.0
    assert s['terraria_login_attempts_total{status="banned"}'] == 0.0
    assert s['terraria_boss_spawned_total{boss="skeletron"}'] == 1.0
    assert s['terraria_invasion_started_total{invasion="goblin_army"}'] == 1.0
    assert s["terraria_server_start_time_seconds"] == 1000.0
