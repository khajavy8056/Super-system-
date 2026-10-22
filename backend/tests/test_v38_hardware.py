# -*- coding: utf-8 -*-
"""v3.8 — Hardware Integration Layer: adapters, transports, scale parser,
health/reconnect, driver gate, UNSUPPORTED_DEVICE honesty.

Everything here runs against MockTransport/file-sinks plus real TCP sockets —
no physical hardware is touched, and no test claims a physical device works.
Those paths stay MANUAL_ACCEPTANCE_REQUIRED (see RELEASE_AUDIT).
"""
from __future__ import annotations

import json
import socket
import threading

import pytest

from app.models import HardwareDevice


def _mkdb(client, **kw):
    from app.database import SessionLocal
    db = SessionLocal()
    fields = {"device_type": "PRINTER", "name": "t", "connection": "mock://",
              "status": "UNKNOWN"}
    fields.update(kw)
    d = HardwareDevice(**fields)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


# ------------------------------------------------------- adapter resolution --
def test_adapter_registry_covers_six_families():
    from app.services.hw import ADAPTERS, adapter_for
    assert len(ADAPTERS) == 6
    for legacy, fam in [("PRINTER", "PRINT_RECEIPT"), ("BARCODE_SCANNER", "SCAN"),
                        ("CASH_DRAWER", "OPEN_DRAWER"), ("DISPLAY", "SHOW_TEXT"),
                        ("LABEL_PRINTER", "PRINT_LABEL"), ("SCALE", "WEIGH")]:
        caps = [c.value for c in adapter_for(legacy).capabilities]
        assert fam in caps, legacy
    # lowercase spellings resolve identically
    assert adapter_for("printer") is adapter_for("PRINTER")


def test_unknown_device_type_is_unsupported_not_crash():
    from app.services.hw import adapter_for
    from app.services.hw.base import UnsupportedDeviceError
    with pytest.raises(UnsupportedDeviceError) as ei:
        adapter_for("HOLOGRAM_PROJECTOR")
    assert "HOLOGRAM_PROJECTOR" in str(ei.value)


def test_custom_adapter_registers_without_core_changes():
    from app.services.hw import ADAPTERS, adapter_for
    from app.services.hw.base import AdapterBase, Capability, DeviceHealth

    class ToasterAdapter(AdapterBase):
        device_types = ("toaster",)
        guidance = "breakfast"

        @property
        def capabilities(self):
            return []

        def probe(self, db, device):
            return DeviceHealth(status="CONNECTED", detail="warm")

        def self_test(self, db, device, **kw):
            return {"health": self.probe(db, device).as_dict()}

    ADAPTERS.append(ToasterAdapter())
    try:
        assert adapter_for("TOASTER").guidance == "breakfast"
    finally:
        ADAPTERS.pop()


# -------------------------------------------------------------- transports ---
def test_transport_for_rejects_unknown_scheme():
    from app.services.hw.transports import transport_for
    with pytest.raises(ValueError):
        transport_for("bluetooth://00:11:22")


def test_tcp_probe_real_socket_roundtrip():
    from app.services.hw.detection import probe_tcp
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert probe_tcp("127.0.0.1", port)["reachable"] is True
    finally:
        srv.close()
    # closed port, loopback: fast refusal; honest DISCONNECTED answer
    assert probe_tcp("127.0.0.1", port)["reachable"] is False


def test_mock_transport_records_writes_and_replays_reads():
    from app.services.hw.transports import MockTransport
    t = MockTransport(read_lines=[b"ST,GS,  12.340kg\r\n"])
    ok, msg = t.write(b"hello")
    assert ok and t.written == [b"hello"]
    ok, line, _ = t.read_line()
    assert ok and line.startswith(b"ST,GS")
    ok, _, msg = t.read_line()
    assert ok is False and msg == "MOCK_QUEUE_EMPTY"


# ------------------------------------------------------------ scale parser ---
@pytest.mark.parametrize("raw,want,stable", [
    (b"ST,GS,  12.340kg", 12340.0, True),
    (b"US,GS,   1.500kg", 1500.0, False),
    (b"S S    123.45 g", 123.45, False),
    (b"ST,NT,   2.000lb", 907.185, True),
])
def test_scale_parser_documented_telegrams(raw, want, stable):
    from app.services.hw.adapters import parse_scale_line
    rep = parse_scale_line(raw)
    assert rep["ok"] is True
    assert abs(rep["weight_g"] - want) < 0.01
    assert rep["stable"] is stable


@pytest.mark.parametrize("raw", [b"", b"????????", b"ERROR 42", b"\x00\xff garbage"])
def test_scale_parser_never_fakes_a_weight(raw):
    from app.services.hw.adapters import parse_scale_line
    rep = parse_scale_line(raw)
    assert rep["ok"] is False
    assert rep["error"] == "UNPARSEABLE"
    assert "weight_g" not in rep  # missing weight is NEVER returned as 0


# ------------------------------------------------------- health + reconnect --
def test_probe_persists_health_and_resets_on_recovery(client):
    from app.database import SessionLocal
    from app.services.hw import ensure_connected
    d = _mkdb(client, connection="tcp://127.0.0.1:9")  # discard port: refused
    db = SessionLocal()
    dev = db.get(HardwareDevice, d.id)
    h = ensure_connected(db, dev, force=True)
    assert h.status == "DISCONNECTED"
    assert dev.consecutive_failures == 1
    assert dev.last_error
    # recovery: point it at a sink and probe again → counter resets
    dev.connection = "mock://"
    h = ensure_connected(db, dev, force=True)
    assert h.status == "CONNECTED"
    assert dev.consecutive_failures == 0
    assert dev.last_error is None
    assert dev.last_seen_at is not None
    assert json.loads(dev.capabilities) == ["PRINT_RECEIPT"]
    db.close()


def test_reconnect_backoff_throttles_dead_devices(client):
    from app.database import SessionLocal
    from app.services.hw import ensure_connected
    d = _mkdb(client, connection="tcp://127.0.0.1:9")
    db = SessionLocal()
    dev = db.get(HardwareDevice, d.id)
    ensure_connected(db, dev, force=True)
    assert dev.consecutive_failures == 1
    # immediate second probe is throttled (no hammering), failures unchanged
    h = ensure_connected(db, dev, force=False)
    assert "backing off" in h.detail
    db.refresh(dev)
    assert dev.consecutive_failures == 1
    db.close()


def test_unsupported_device_health_verdict_not_crash(client):
    from app.database import SessionLocal
    from app.services.hw import ensure_connected
    d = _mkdb(client, device_type="HOLOGRAM_PROJECTOR")
    db = SessionLocal()
    dev = db.get(HardwareDevice, d.id)
    h = ensure_connected(db, dev, force=True)
    assert h.status == "UNSUPPORTED_DEVICE"
    assert "HOLOGRAM_PROJECTOR" in h.detail
    assert dev.consecutive_failures == 0  # a verdict, not a failure
    db.close()


# ------------------------------------------------- adapter behaviour (mock) --
def test_printer_self_test_skips_paper_by_default(client):
    from app.database import SessionLocal
    from app.services.hw import test_device
    from app.services.hw.transports import MockTransport
    d = _mkdb(client)
    db = SessionLocal()
    rep = test_device(db, d.id, test_transport=MockTransport())
    assert rep["ok"] is True
    assert rep["report"]["test_page"] == "skipped"
    db.close()


def test_drawer_pulse_requires_confirmation(client):
    from app.database import SessionLocal
    from app.services.hw import test_device
    from app.services.hw.transports import MockTransport
    d = _mkdb(client, device_type="CASH_DRAWER")
    db = SessionLocal()
    t = MockTransport()
    rep = test_device(db, d.id, test_transport=t)
    assert rep["report"]["pulse"].startswith("skipped")
    assert t.written == []
    rep = test_device(db, d.id, test_transport=t, confirm_open=True)
    assert rep["report"]["pulse"] == "fired"
    assert t.written == [b"\x1bp\x00\x19\xfa"]
    db.close()


def test_scanner_and_scale_read_from_mock_queue(client):
    from app.database import SessionLocal
    from app.services.hw.adapters import adapter_for
    from app.services.hw.transports import MockTransport
    db = SessionLocal()
    scan = _mkdb(client, device_type="BARCODE_SCANNER")
    rep = adapter_for("BARCODE_SCANNER").read_one(
        db, db.get(HardwareDevice, scan.id),
        test_transport=MockTransport(read_lines=[b"6261234567890\r\n"]))
    assert rep == {"ok": True, "code": "6261234567890", "transport": "mock://test"}
    scale = _mkdb(client, device_type="SCALE")
    rep = adapter_for("SCALE").read_weight(
        db, db.get(HardwareDevice, scale.id),
        test_transport=MockTransport(read_lines=[b"ST,GS,  12.340kg\r\n"]))
    assert rep["ok"] is True and rep["weight_g"] == 12340.0 and rep["stable"] is True
    db.close()


def test_label_builder_emits_tspl(client):
    from app.services.hw.adapters import adapter_for
    from app.database import SessionLocal
    db = SessionLocal()
    payload = adapter_for("LABEL_PRINTER").build_label("Sugar 1kg", barcode="123")
    text = payload.decode("ascii")
    assert "SIZE 50 mm,30 mm" in text and 'BARCODE 20,60,"128"' in text and "PRINT 1" in text
    db.close()


def test_display_builder_fits_two_lines():
    from app.services.hw.adapters import adapter_for
    payload = adapter_for("DISPLAY").build_lines("Total", "12,340")
    assert payload.startswith(b"\x0c")
    assert b"Total" in payload and b"12,340" in payload


# ------------------------------------------------------------- driver gate ---
def test_driver_status_names_install_command_for_missing():
    from app.database import SessionLocal
    from app.services.hw import DriverManager
    db = SessionLocal()
    try:
        import usb  # noqa: F401
        pytest.skip("pyusb installed here — nothing missing to report")
    except ImportError:
        pass
    rep = DriverManager(db).status("usb")
    assert rep["status"] == "MISSING"
    assert "pyusb==1.2.1" in rep["install_command"]
    db.close()


def test_driver_ensure_refuses_when_auto_install_off(client):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from app.services.hw import DriverManager
    try:
        import usb  # noqa: F401
        pytest.skip("pyusb installed here — nothing missing to gate")
    except ImportError:
        pass
    db = SessionLocal()
    db.query(SystemSetting).filter(SystemSetting.key == "hw.auto_install_drivers").delete()
    db.add(SystemSetting(key="hw.auto_install_drivers", value="false"))
    db.commit()
    rep = DriverManager(db).ensure("usb")
    assert rep["status"] == "MISSING"
    assert "refused" in rep
    db.close()


def test_driver_ensure_refuses_off_allowlist_package(client):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from app.services.hw import DriverManager
    db = SessionLocal()
    db.query(SystemSetting).filter(SystemSetting.key == "hw.auto_install_drivers").delete()
    db.add(SystemSetting(key="hw.auto_install_drivers", value="true"))
    db.commit()
    with pytest.raises(ValueError, match="pinned allowlist"):
        DriverManager(db).ensure("evil_vendor_blob")
    db.close()
