"""Parse the Terraria/TShock console log stream into counters and a live player gauge.

Both server flavors print player join/leave lines, death broadcasts, boss and invasion
announcements, and world-save lines to stdout (and to the log volume). TShock additionally logs
authentication results. The patterns are best-effort and documented here; feed each log line to
`LogState.feed`. Counters only ever increase; players_online is derived from joins minus leaves and
is a best-effort live value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# One representative pattern per event. Kept deliberately loose but anchored enough to avoid chat.
JOIN = re.compile(r"^(?P<name>.+?) has joined\.$")
LEAVE = re.compile(r"^(?P<name>.+?) has left\.$")
SERVER_STARTED = re.compile(r"Server started")
WORLD_SAVED = re.compile(r"(Saving world|world saved|Backing up world)", re.IGNORECASE)
BOSS_AWOKEN = re.compile(r"^(?P<boss>.+?) has awoken!$")
INVASION = re.compile(r"(goblin army|pirate|Martian|Frost Legion|Pumpkin Moon|Frost Moon|Old One's Army).{0,40}(approaching|has begun|incoming)", re.IGNORECASE)
# TShock authentication lines
LOGIN_OK = re.compile(r"authenticated successfully", re.IGNORECASE)
LOGIN_BAD = re.compile(r"(failed to login|incorrect password|invalid password)", re.IGNORECASE)
LOGIN_BANNED = re.compile(r"banned", re.IGNORECASE)
# Death broadcasts are highly varied; match the common verbs Terraria uses.
SERVER_VERSION = re.compile(r"Terraria Server v(?P<ver>\d+\.\d+\.\d+(?:\.\d+)?)")
DEATH = re.compile(r"\b(was slain|was killed|got slain|has been slain|was eviscerated|was murdered|didn't|watched .* die|felt|was licked)\b", re.IGNORECASE)

INVASION_NAMES = {
    "goblin army": "goblin_army", "pirate": "pirates", "martian": "martian_madness",
    "frost legion": "frost_legion", "pumpkin moon": "pumpkin_moon",
    "frost moon": "frost_moon", "old one's army": "old_ones_army",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "unknown"


@dataclass
class LogState:
    joins_total: int = 0
    leaves_total: int = 0
    deaths_total: int = 0
    world_saves_total: int = 0
    players_online: int = 0
    server_start_epoch: float = 0.0
    game_version: str = ""
    login_attempts: dict = field(default_factory=lambda: {"success": 0, "bad_password": 0, "banned": 0})
    boss_spawned: dict = field(default_factory=dict)     # boss slug -> count
    invasion_started: dict = field(default_factory=dict) # invasion slug -> count

    def feed(self, line: str, now: float | None = None) -> None:
        line = line.rstrip("\n").lstrip("﻿").strip()
        if not line:
            return
        mv = SERVER_VERSION.search(line)
        if mv:
            self.game_version = mv.group("ver")
        if JOIN.search(line):
            self.joins_total += 1
            self.players_online += 1
            return
        if LEAVE.search(line):
            self.leaves_total += 1
            self.players_online = max(0, self.players_online - 1)
            return
        if SERVER_STARTED.search(line):
            import time
            self.server_start_epoch = now if now is not None else time.time()
            self.players_online = 0
            return
        if WORLD_SAVED.search(line):
            self.world_saves_total += 1
            return
        m = BOSS_AWOKEN.search(line)
        if m:
            slug = _slug(m.group("boss"))
            self.boss_spawned[slug] = self.boss_spawned.get(slug, 0) + 1
            return
        if INVASION.search(line):
            low = line.lower()
            slug = next((v for k, v in INVASION_NAMES.items() if k in low), "unknown")
            self.invasion_started[slug] = self.invasion_started.get(slug, 0) + 1
            return
        if LOGIN_OK.search(line):
            self.login_attempts["success"] += 1
            return
        if LOGIN_BAD.search(line):
            self.login_attempts["bad_password"] += 1
            return
        if LOGIN_BANNED.search(line) and "has joined" not in line:
            self.login_attempts["banned"] += 1
            return
        if DEATH.search(line):
            self.deaths_total += 1
            return
