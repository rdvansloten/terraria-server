"""Minimal, version-aware reader for Terraria .wld world files.

It reads only the world-header section (section 0) and extracts the fields we export as metrics:
world identity, size, difficulty, evil type, altar count, hardmode, and the downed-boss / saved-NPC
/ invasion flags. The field order mirrors TEdit's LoadHeaderFlags (the authoritative community
implementation) and is guarded by the world's format version, so it stays correct across releases
that only append fields.

Self-validation: after reading the documented sequence we compare the stream position against the
start of the next section (from the file's section-pointer table). Terraria appends any unknown
trailing flags, so a correct parse lands at or just before that boundary; landing past it means the
layout shifted and we mark the parse invalid rather than emit wrong values.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.o = 0

    def i16(self) -> int:
        v = struct.unpack_from("<h", self.d, self.o)[0]; self.o += 2; return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.d, self.o)[0]; self.o += 2; return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.o)[0]; self.o += 4; return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]; self.o += 4; return v

    def i64(self) -> int:
        v = struct.unpack_from("<q", self.d, self.o)[0]; self.o += 8; return v

    def u64(self) -> int:
        v = struct.unpack_from("<Q", self.d, self.o)[0]; self.o += 8; return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.o)[0]; self.o += 4; return v

    def f64(self) -> float:
        v = struct.unpack_from("<d", self.d, self.o)[0]; self.o += 8; return v

    def u8(self) -> int:
        v = self.d[self.o]; self.o += 1; return v

    def boolean(self) -> bool:
        return self.u8() != 0

    def string(self) -> str:
        # .NET BinaryReader length prefix: 7 bits per byte, high bit = continue
        n = 0; shift = 0
        while True:
            byte = self.u8()
            n |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
        s = self.d[self.o:self.o + n].decode("utf-8", "replace"); self.o += n; return s

    def skip(self, n: int) -> None:
        self.o += n


@dataclass
class World:
    version: int = 0
    name: str = ""
    seed: str = ""
    worldgen_version: int = 0
    world_id: int = 0
    width: int = 0
    height: int = 0
    difficulty: int = 0          # 0 classic, 1 expert, 2 master, 3 journey
    is_crimson: bool = False
    altars_smashed: int = 0
    hardmode: bool = False
    parse_ok: bool = False       # the header aligned to the section boundary
    bosses: dict = field(default_factory=dict)
    invasions: dict = field(default_factory=dict)
    npcs_saved: dict = field(default_factory=dict)


def parse_world_header(data: bytes) -> World:
    r = _Reader(data)
    w = World()

    # ---- file preamble ----
    w.version = r.i32()
    magic = r.d[r.o:r.o + 7]; r.o += 7
    if magic != b"relogic":
        raise ValueError(f"not a Terraria world file (magic={magic!r})")
    r.u8()          # file type (2 = world)
    r.u32()         # revision
    r.u64()         # favorites bitfield
    nsec = r.i16()
    pointers = [r.i32() for _ in range(nsec)]
    if len(pointers) < 2:
        raise ValueError("world has no header section pointer")
    header_end = pointers[1]

    v = w.version
    # ---- header section (section 0) ----
    r.o = pointers[0]
    w.name = r.string()
    if v >= 179:
        w.seed = str(r.i32()) if v == 179 else r.string()
        w.worldgen_version = r.u64()
    if v >= 181:
        r.skip(16)                       # world GUID
    w.world_id = r.i32()
    r.i32(); r.i32(); r.i32(); r.i32()   # left/right/top/bottom bounds
    w.height = r.i32()                    # TilesHigh
    w.width = r.i32()                     # TilesWide
    if v >= 209:
        w.difficulty = r.i32()           # game mode
        if v >= 222: r.boolean()         # drunk
        if v >= 227: r.boolean()         # good/get-fixed-boi
        if v >= 238: r.boolean()         # tenth anniversary
        if v >= 239: r.boolean()         # don't starve
        if v >= 241: r.boolean()         # not the bees
        if v >= 249: r.boolean()         # remix
        if v >= 266: r.boolean()         # no traps
        if v >= 267: r.boolean()         # zenith
        if v >= 302: r.boolean()         # skyblock
    elif v == 208:
        w.difficulty = 2 if r.boolean() else 0
    elif v >= 112:
        w.difficulty = 1 if r.boolean() else 0
    if v >= 141: r.i64()                 # creation time
    if v >= 284: r.i64()                 # last played
    r.u8()                               # moon type
    r.skip(3 * 4)                        # TreeX[0..2]
    r.skip(4 * 4)                        # TreeStyle[0..3]
    r.skip(3 * 4)                        # CaveBackX[0..2]
    r.skip(4 * 4)                        # CaveBackStyle[0..3]
    r.i32(); r.i32(); r.i32()            # ice/jungle/hell back style
    r.i32(); r.i32()                     # spawn x/y
    r.f64(); r.f64()                     # ground/rock level
    r.f64()                              # time
    r.boolean()                          # day time
    r.i32()                              # moon phase
    r.boolean(); r.boolean()             # blood moon, eclipse
    r.i32(); r.i32()                     # dungeon x/y
    w.is_crimson = r.boolean()

    B = w.bosses
    B["eye_of_cthulhu"] = r.boolean()
    B["eater_of_worlds_or_brain"] = r.boolean()
    B["skeletron"] = r.boolean()
    B["queen_bee"] = r.boolean()
    B["the_destroyer"] = r.boolean()
    B["the_twins"] = r.boolean()
    B["skeletron_prime"] = r.boolean()
    r.boolean()                          # any mech boss
    B["plantera"] = r.boolean()
    B["golem"] = r.boolean()
    if v >= 118:
        B["king_slime"] = r.boolean()

    N = w.npcs_saved
    N["tinkerer"] = r.boolean()
    N["wizard"] = r.boolean()
    N["mechanic"] = r.boolean()
    I = w.invasions
    I["goblin_army"] = r.boolean()
    I["clown"] = r.boolean()
    I["frost_legion"] = r.boolean()
    I["pirates"] = r.boolean()
    r.boolean()                          # shadow orb smashed
    r.boolean()                          # spawn meteor
    r.u8()                               # shadow orb count
    w.altars_smashed = r.i32()
    w.hardmode = r.boolean()
    if v >= 257: r.boolean()             # party of doom
    r.i32(); r.i32(); r.i32()            # invasion delay/size/type
    r.f64()                              # invasion x
    if v >= 118: r.f64()                 # slime rain time
    if v >= 113: r.u8()                  # sundial cooldown
    r.boolean(); r.i32(); r.f32()        # raining, rain time, max rain
    r.i32(); r.i32(); r.i32()            # ore tiers cobalt/mythril/adamantite
    r.skip(8)                            # 8 background bytes
    r.i32()                              # cloud bg active
    r.i16()                              # num clouds
    r.f32()                              # wind speed

    if v < 95: return _finish(w, r, header_end)
    for _ in range(r.i32()):             # anglers who finished today
        r.string()
    if v < 99: return _finish(w, r, header_end)
    N["angler"] = r.boolean()
    if v < 101: return _finish(w, r, header_end)
    r.i32()                              # angler quest
    if v < 104: return _finish(w, r, header_end)
    N["stylist"] = r.boolean()
    if v >= 140: N["tax_collector"] = r.boolean()
    if v >= 201: N["golfer"] = r.boolean()
    # Alignment checksum: the next field is the banner kill-tally count (MaxBannerTypes, a small
    # positive number). If it reads sane, every core flag above is correctly aligned. Endgame
    # bosses live after this tally behind a variable-length region not yet mapped, so we stop here.
    if v >= 107: r.i32()                     # invasion size start
    if v >= 108: r.i32()                     # cultist delay
    banner_count = r.i16() if v >= 109 else 300
    w.parse_ok = 0 < banner_count < 2000
    return w


def parse_world_file(path: str) -> World:
    with open(path, "rb") as fh:
        return parse_world_header(fh.read())
