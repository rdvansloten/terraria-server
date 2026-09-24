"""A minimal Terraria network client, enough to walk through the join handshake."""

from __future__ import annotations

import socket
import struct
import time

# Packet types (client -> server unless noted)
CONNECT_REQUEST = 1
DISCONNECT = 2
CONTINUE_CONNECTING = 3  # server -> client, assigns the player slot
PLAYER_INFO = 4
REQUEST_WORLD_DATA = 6  # "ContinueConnecting2"
WORLD_INFO = 7  # server -> client
PASSWORD_REQUIRED = 37  # server -> client
PASSWORD_RESPONSE = 38
CLIENT_UUID = 68
VERSION_MISMATCH = "LegacyMultiplayer.4"

KNOWN_PROTOCOLS = {"1.4.5.8": 326, "1.4.5.6": 319}

INCORRECT_PASSWORD = "LegacyMultiplayer.1"


def tstring(text: str) -> bytes:
    data = text.encode()
    assert len(data) < 128, "7-bit length prefix: keep strings short"
    return bytes([len(data)]) + data


def packet(kind: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HB", 3 + len(payload), kind) + payload


def network_text(payload: bytes) -> str:
    """Decode a NetworkText (mode byte followed by a string) as used in Disconnect."""
    if len(payload) < 2:
        return ""
    length = payload[1]
    return payload[2 : 2 + length].decode(errors="replace")


class TerrariaClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.player_id = 0

    def __enter__(self) -> "TerrariaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.sock.close()

    def send(self, kind: int, payload: bytes = b"") -> None:
        self.sock.sendall(packet(kind, payload))

    def recv(self) -> tuple[int, bytes]:
        """Read one packet and return (type, payload). Raises socket.timeout if nothing arrives."""
        header = self._recv_exact(2)
        (length,) = struct.unpack("<H", header)
        body = self._recv_exact(length - 2)
        return body[0], body[1:]

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("server closed the connection")
            data += chunk
        return data

    def recv_until(self, wanted: set[int], timeout: float = 5.0) -> tuple[int, str]:
        """Read packets until one whose type is in `wanted`, or a Disconnect, arrives, skipping"""
        self.sock.settimeout(timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            kind, payload = self.recv()
            if kind == DISCONNECT:
                return kind, network_text(payload)
            if kind in wanted:
                return kind, ""
        raise AssertionError(f"none of {sorted(wanted)} (or Disconnect) arrived within {timeout}s")

    # ---- handshake steps

    def connect_request(self, protocol: int) -> int:
        """Send ConnectRequest and return the reply type (3 continue, 37 password, 2 disconnect)."""
        self.send(CONNECT_REQUEST, tstring(f"Terraria{protocol}"))
        kind, payload = self.recv()
        if kind == CONTINUE_CONNECTING and payload:
            self.player_id = payload[0]
        return kind

    def client_uuid(self, uuid: str = "00000000-0000-4000-8000-00000000c0de") -> None:
        """Send ClientUUID; TShock kicks clients that never send one."""
        self.send(CLIENT_UUID, tstring(uuid))

    def player_info(self, name: str = "pytest") -> None:
        """Send a plain softcore character. Layout per Terraria 1.4.5 / TShock 6.1 HandlePlayerInfo."""
        payload = struct.pack("<BBBf", self.player_id, 0, 0, 0.0)  # slot, skin variant, voice, pitch
        payload += bytes([0])  # hair
        payload += tstring(name)
        payload += bytes([0])  # hair dye
        payload += struct.pack("<H", 0)  # hide visual flags
        payload += bytes([0])  # hide misc
        payload += bytes([200, 150, 100] * 7)
        payload += bytes([0, 0, 0])
        self.send(PLAYER_INFO, payload)

    def request_world_data(self) -> tuple[int, str]:
        """Send RequestWorldData; return the outcome (PASSWORD_REQUIRED if a password is needed,"""
        self.send(REQUEST_WORLD_DATA)
        return self.recv_until({PASSWORD_REQUIRED, WORLD_INFO})

    def send_password(self, password: str) -> tuple[int, str]:
        """Send PasswordResponse; return the outcome: CONTINUE_CONNECTING (vanilla) or WORLD_INFO"""
        self.send(PASSWORD_RESPONSE, tstring(password))
        return self.recv_until({CONTINUE_CONNECTING, WORLD_INFO})


def discover_protocol(host: str, port: int, server_log: str, hint: int | None = None) -> int:
    """Find the protocol version the server speaks."""
    import re

    match = re.search(r"Protocol v[\d.]+ \((\d+)\)", server_log)
    if match:
        return int(match.group(1))
    start = hint or max(KNOWN_PROTOCOLS.values())
    for proto in range(start, start + 40):
        with TerrariaClient(host, port) as client:
            client.send(CONNECT_REQUEST, tstring(f"Terraria{proto}"))
            kind, payload = client.recv()
        if kind == DISCONNECT and network_text(payload) == VERSION_MISMATCH:
            continue
        return proto
    raise AssertionError(f"no protocol version between {start} and {start + 39} was accepted")
