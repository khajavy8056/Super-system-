# -*- coding: utf-8 -*-
"""Pluggable byte transports: TCP / serial / file-sink / in-memory mock.

Adapters build protocol bytes; transports move them. Tests use MockTransport
(recorded writes, scripted reads) and FileTransport — no real hardware needed,
and no fake hardware success is ever claimed (a mock result is labelled mock).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Transport(ABC):
    label: str = "?"

    @abstractmethod
    def write(self, payload: bytes) -> tuple[bool, str]:
        """Send bytes. Returns (ok, message)."""

    def read_line(self, timeout: float = 2.0) -> tuple[bool, bytes, str]:
        """Read one line (scales). Transports without input return ok=False."""
        return False, b"", "READ_NOT_SUPPORTED"


class TcpTransport(Transport):
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.label = f"tcp://{host}:{port}"

    def write(self, payload: bytes) -> tuple[bool, str]:
        import socket
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(payload)
            return True, f"sent {len(payload)} bytes to {self.label}"
        except OSError as exc:
            return False, f"{self.label}: {exc}"


class FileTransport(Transport):
    """Honest sink for demos/tests: bytes land in a file, labelled as such."""

    def __init__(self, path: str):
        self.path = path
        self.label = f"file://{path}"

    def write(self, payload: bytes) -> tuple[bool, str]:
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "ab") as f:
                f.write(payload)
            return True, f"wrote {len(payload)} bytes to {self.label} (sink — no device)"
        except OSError as exc:
            return False, f"{self.label}: {exc}"


class MockTransport(Transport):
    """In-memory transport for unit tests: records writes, replays reads."""

    def __init__(self, read_lines: list[bytes] | None = None):
        self.written: list[bytes] = []
        self._reads = list(read_lines or [])
        self.label = "mock://test"

    def write(self, payload: bytes) -> tuple[bool, str]:
        self.written.append(bytes(payload))
        return True, f"mock accepted {len(payload)} bytes"

    def read_line(self, timeout: float = 2.0) -> tuple[bool, bytes, str]:
        if not self._reads:
            return False, b"", "MOCK_QUEUE_EMPTY"
        return True, self._reads.pop(0), "mock"


class SerialTransport(Transport):
    """RS-232/USB-serial via pyserial. Without the driver it reports
    DRIVER_MISSING — it never pretends the port opened."""

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 2.0):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.label = f"serial://{port}@{baudrate}"

    def _open(self):
        try:
            import serial  # type: ignore
        except ImportError:
            raise DriverMissingError("pyserial is not installed (pip install pyserial==3.5)")
        return serial.Serial(self.port, self.baudrate, timeout=self.timeout)

    def write(self, payload: bytes) -> tuple[bool, str]:
        try:
            with self._open() as s:
                s.write(payload)
            return True, f"sent {len(payload)} bytes to {self.label}"
        except DriverMissingError as exc:
            return False, f"DRIVER_MISSING: {exc}"
        except Exception as exc:  # noqa: BLE001 — pyserial raises SerialException
            return False, f"{self.label}: {exc}"

    def read_line(self, timeout: float = 2.0) -> tuple[bool, bytes, str]:
        try:
            with self._open() as s:
                s.timeout = timeout
                line = s.readline()
            if not line:
                return False, b"", "TIMEOUT"
            return True, bytes(line), "ok"
        except DriverMissingError as exc:
            return False, b"", f"DRIVER_MISSING: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, b"", f"{self.label}: {exc}"


def transport_for(connection: str | None) -> Transport:
    """Build a transport from a connection string.

    tcp://host:port · serial:///dev/ttyUSB0@9600 · file:///path · mock://
    Unknown schemes raise ValueError (the caller reports UNSUPPORTED_DEVICE).
    """
    conn = (connection or "").strip()
    if conn.startswith("tcp://"):
        hostport = conn[6:]
        if ":" not in hostport:
            raise ValueError(f"bad tcp connection (want tcp://host:port): {conn!r}")
        host, port = hostport.rsplit(":", 1)
        return TcpTransport(host, int(port))
    if conn.startswith("serial://"):
        rest = conn[9:]
        port, _, baud = rest.partition("@")
        return SerialTransport(port, int(baud) if baud else 9600)
    if conn.startswith("file://"):
        return FileTransport(conn[7:])
    if conn.startswith("mock://"):
        return MockTransport()
    raise ValueError(f"unsupported connection scheme: {conn!r} "
                     f"(want tcp:// | serial:// | file:// | mock://)")
