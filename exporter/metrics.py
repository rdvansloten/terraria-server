"""Prometheus collector assembled from the parsed world and log state."""

from __future__ import annotations

from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily


class TerrariaCollector:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def collect(self):
        snap = self._snapshot()
        w = snap["world"]
        logs = snap["logs"]


        info = GaugeMetricFamily(
            "terraria_world_info", "World identity; value is always 1",
            labels=["world_name", "seed", "game_version", "format_version", "worldgen_version"],
        )
        if w is not None:
            info.add_metric(
                [w.name, w.seed, logs.game_version or "", str(w.version), str(w.worldgen_version)], 1
            )
        yield info

        # ---- world state gauges ----
        if w is not None and w.parse_ok:
            for name, help_text, value in (
                ("terraria_hardmode", "World is in hardmode", int(w.hardmode)),
                ("terraria_difficulty", "0 classic 1 expert 2 master 3 journey", w.difficulty),
                ("terraria_evil_type", "0 corruption 1 crimson", int(w.is_crimson)),
                ("terraria_world_width", "World width in tiles", w.width),
                ("terraria_world_height", "World height in tiles", w.height),
                ("terraria_altars_smashed", "Demon/crimson altars smashed", w.altars_smashed),
            ):
                yield GaugeMetricFamily(name, help_text, value=value)

            boss = GaugeMetricFamily("terraria_boss_defeated", "1 if the boss has been defeated", labels=["boss"])
            for k, v in sorted(w.bosses.items()):
                boss.add_metric([k], int(v))
            yield boss

            inv = GaugeMetricFamily("terraria_invasion_defeated", "1 if the invasion has been defeated", labels=["invasion"])
            for k, v in sorted(w.invasions.items()):
                inv.add_metric([k], int(v))
            yield inv

            npc = GaugeMetricFamily("terraria_npc_saved", "1 if the NPC has been rescued/unlocked", labels=["npc"])
            for k, v in sorted(w.npcs_saved.items()):
                npc.add_metric([k], int(v))
            yield npc

        # ---- live activity (from logs) ----
        yield GaugeMetricFamily("terraria_players_online", "Players currently connected (best-effort)", value=logs.players_online)
        yield CounterMetricFamily("terraria_player_joins", "Total player joins", value=logs.joins_total)
        yield CounterMetricFamily("terraria_player_leaves", "Total player leaves", value=logs.leaves_total)
        yield CounterMetricFamily("terraria_player_deaths", "Total player deaths", value=logs.deaths_total)
        yield CounterMetricFamily("terraria_world_saves", "Total world saves observed", value=logs.world_saves_total)

        login = CounterMetricFamily("terraria_login_attempts", "Login attempts by status (TShock)", labels=["status"])
        for status, count in sorted(logs.login_attempts.items()):
            login.add_metric([status], count)
        yield login

        bs = CounterMetricFamily("terraria_boss_spawned", "Boss spawn announcements", labels=["boss"])
        for k, v in sorted(logs.boss_spawned.items()):
            bs.add_metric([k], v)
        yield bs

        inv_started = CounterMetricFamily("terraria_invasion_started", "Invasion start announcements", labels=["invasion"])
        for k, v in sorted(logs.invasion_started.items()):
            inv_started.add_metric([k], v)
        yield inv_started

        yield GaugeMetricFamily("terraria_server_start_time_seconds", "Unix time the server last started", value=logs.server_start_epoch)

        # ---- file + health ----
        yield GaugeMetricFamily("terraria_world_file_bytes", "Size of the world file", value=snap["world_file_bytes"])
        yield GaugeMetricFamily("terraria_world_save_age_seconds", "Seconds since the world file was written", value=snap["world_save_age"])
        yield GaugeMetricFamily("terraria_world_parse_ok", "1 if the world file parsed and aligned", value=int(bool(w is not None and w.parse_ok)))
        yield GaugeMetricFamily("terraria_world_last_parsed_seconds", "Unix time of the last successful parse", value=snap["last_parsed"])
        yield GaugeMetricFamily("terraria_exporter_up", "Exporter liveness", value=int(snap["up"]))
