"""Phase 5: protocol, parser resync, SerialDevice against a fake port, engine link behaviour."""
import asyncio, json, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from fastapi.testclient import TestClient
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.device import (pack, pack_rx, PacketParser, SerialDevice, SimDevice, pick_port, H_TX, H_RX,
                              describe_tx, describe_rx, checksum)
from companion.emotions import EMOTIONS
from companion.engine import Engine
from companion.memory import Memory
from companion.server import create_app
from companion.states import State


# ---------------------------------------------------------------- fake hardware
class Bus:
    """The 'wire' plus a tiny pretend base ESP32."""
    def __init__(self):
        self.lock = threading.Lock()
        self.to_laptop = bytearray()
        self.sent = bytearray()
        self.unplugged = False
        self.answer = True
        self.opens = 0
        self.rx_parser = PacketParser(H_TX)

    def device_says(self, raw: bytes):
        with self.lock:
            self.to_laptop += raw

    def on_write(self, data: bytes):
        with self.lock:
            self.sent += data
        for cmd, a, b in self.rx_parser.feed(data):
            if self.answer and cmd == 4:
                self.device_says(pack_rx("PONG"))
            if self.answer and cmd == 5:
                self.device_says(pack_rx("BRIGHTNESS_ACK", a))

    def tx_packets(self):
        with self.lock:
            raw = bytes(self.sent)
        p = PacketParser(H_TX)
        return p.feed(raw)

    def ports(self):
        return [] if self.unplugged else [{"port": "COM7", "description": "USB JTAG", "vid_pid": "303A:1001", "likely": True}]


class FakePort:
    def __init__(self, bus):
        self.bus = bus

    @property
    def in_waiting(self):
        return len(self.bus.to_laptop)

    def read(self, n=1):
        if self.bus.unplugged:
            raise OSError("device disconnected")
        time.sleep(0.002)
        with self.bus.lock:
            out = bytes(self.bus.to_laptop[:n])
            del self.bus.to_laptop[:n]
        return out

    def write(self, data):
        if self.bus.unplugged:
            raise OSError("device disconnected")
        self.bus.on_write(bytes(data))
        return len(data)

    def close(self):
        pass


def make_dev(bus, **kw):
    def factory(port, baud):
        if bus.unplugged:
            raise OSError("no such port")
        bus.opens += 1
        return FakePort(bus)
    events = []
    d = SerialDevice(factory and kw.pop("port", ""), serial_factory=factory, ports_func=bus.ports,
                     heartbeat_s=0.05, timeout_s=0.3, backoff_s=0.05, autostart=False, **kw)
    d.on_event = events.append
    return d, events


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def links(events):
    return [e["connected"] for e in events if e["type"] == "link"]


# ---------------------------------------------------------------- protocol
def test_pack_matches_protocol_doc_examples():
    assert pack("FACE", 2).hex(" ") == "a5 01 02 00 03"
    assert pack("MOUTH", 3).hex(" ") == "a5 02 03 00 05"
    assert pack("POWER", 1).hex(" ") == "a5 03 01 00 04"
    assert pack("PING").hex(" ") == "a5 04 00 00 04"
    assert pack("BRIGHTNESS", 128).hex(" ") == "a5 05 80 00 85"
    assert pack("SLEEP_ANIM").hex(" ") == "a5 06 00 00 06"
    assert pack("TEST_EMOTION", 11).hex(" ") == "a5 07 0b 00 12"
    assert pack_rx("PROXIMITY", 1).hex(" ") == "5a 01 01 00 02"
    assert pack_rx("BUTTON").hex(" ") == "5a 02 00 00 02"
    assert pack_rx("PONG").hex(" ") == "5a 03 00 00 03"
    assert pack_rx("ROTOR_STATUS", 1).hex(" ") == "5a 04 01 00 05"
    assert pack_rx("BRIGHTNESS_ACK", 200).hex(" ") == "5a 05 c8 00 cd"


def test_checksum_wraps_at_256():
    assert checksum(7, 250, 10) == (7 + 250 + 10) & 255
    assert pack("BRIGHTNESS", 255)[4] == (5 + 255) & 255


def test_describe_packets():
    assert describe_tx(1, 2, 0) == "FACE smug"
    assert describe_tx(2, 5, 0) == "MOUTH fv"
    assert describe_rx(1, 1, 0) == "PROXIMITY near"
    assert describe_rx(4, 0, 0) == "ROTOR fault"


def test_parser_clean_and_split_across_reads():
    p = PacketParser(H_RX)
    raw = pack_rx("PROXIMITY", 1) + pack_rx("BUTTON") + pack_rx("PONG")
    out = []
    for i in range(len(raw)):                      # one byte at a time
        out += p.feed(raw[i:i + 1])
    assert out == [(1, 1, 0), (2, 0, 0), (3, 0, 0)]
    assert p.checksum_errors == 0 and p.dropped_bytes == 0


def test_parser_resyncs_after_garbage_and_bad_checksum():
    p = PacketParser(H_RX)
    bad = bytearray(pack_rx("BUTTON"))
    bad[4] ^= 0xFF                                 # corrupt the checksum
    stream = b"\x00\x11\x22" + bytes(bad) + pack_rx("PROXIMITY", 0) + b"\x99" + pack_rx("PONG")
    out = p.feed(stream)
    assert out == [(1, 0, 0), (3, 0, 0)]
    assert p.checksum_errors >= 1 and p.dropped_bytes >= 4


def test_parser_header_byte_inside_payload_still_parses():
    p = PacketParser(H_RX)
    pkt = pack_rx("BRIGHTNESS_ACK", H_RX)          # a = 0x5A looks like a header
    assert p.feed(pkt + pkt) == [(5, H_RX, 0)] * 2


def test_parser_corrupted_header_loses_only_that_packet():
    p = PacketParser(H_RX)
    a, b, c = pack_rx("PROXIMITY", 1), bytearray(pack_rx("BUTTON")), pack_rx("PONG")
    b[0] = 0x00
    out = p.feed(a + bytes(b) + c)
    assert out == [(1, 1, 0), (3, 0, 0)]


def test_parser_noise_only_is_discarded():
    p = PacketParser(H_RX)
    assert p.feed(bytes(range(0x10, 0x50))) == [] and p.dropped_bytes == 0x40 and not p.buf


def test_pick_port_rules():
    ports = [{"port": "COM3", "likely": False}, {"port": "COM7", "likely": True}]
    assert pick_port("", ports) == "COM7"
    assert pick_port("COM3", ports) == "COM3"
    assert pick_port("COM9", ports) is None            # configured but absent: wait, do not guess
    assert pick_port("", [{"port": "COM3", "likely": False}]) is None   # never grab a random COM port
    assert pick_port("", []) is None


# ---------------------------------------------------------------- SerialDevice on a fake port
def test_link_up_after_pong_and_brightness_sent_first():
    bus = Bus()
    d, ev = make_dev(bus, brightness_cap=90)
    assert not d.connected
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        assert links(ev) == [True]
        assert wait_for(lambda: d.stats["brightness_ack"] == 90)
        cmds = [c for c, a, b in bus.tx_packets()]
        assert cmds[0] == 4 and 5 in cmds                  # PING, then BRIGHTNESS
        d.set_face("smug"); d.set_mouth("oh"); d.set_power(True)
        assert wait_for(lambda: (1, EMOTIONS.index("smug"), 0) in bus.tx_packets())
        assert (2, 2, 0) in bus.tx_packets() and (3, 1, 0) in bus.tx_packets()
    finally:
        d.close()


def test_device_events_proximity_button_rotor():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        bus.device_says(pack_rx("PROXIMITY", 1) + pack_rx("BUTTON") + pack_rx("ROTOR_STATUS", 1))
        assert wait_for(lambda: any(e["type"] == "rotor" for e in ev))
        assert {"type": "proximity", "near": True} in ev and {"type": "button"} in ev
        assert d.stats["rotor_ok"] is True
        rx = [p for p in d.packets() if p["dir"] == "rx"]
        assert any(p["text"] == "PROXIMITY near" for p in rx)
    finally:
        d.close()


def test_heartbeat_timeout_marks_link_down_then_recovers():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        bus.answer = False                                  # device hangs: port stays open, no replies
        assert wait_for(lambda: not d.connected, 2.0)
        assert links(ev) == [True, False]
        bus.answer = True
        assert wait_for(lambda: d.connected, 2.0)
        assert links(ev) == [True, False, True]
    finally:
        d.close()


def test_unplug_and_replug():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        bus.unplugged = True
        assert wait_for(lambda: not d.connected)
        assert d.stats["last_error"]
        d.set_face("happy")                                 # must not raise or queue while down
        assert d.stats["tx_dropped"] >= 1
        bus.unplugged = False
        assert wait_for(lambda: d.connected, 3.0)
        assert links(ev) == [True, False, True] and bus.opens == 2
    finally:
        d.close()


def test_configured_port_missing_never_opens():
    bus = Bus()
    d, ev = make_dev(bus, port="COM99")
    d.start()
    try:
        time.sleep(0.3)
        assert bus.opens == 0 and not d.connected and "COM99" in d.stats["last_error"]
    finally:
        d.close()


def test_corrupted_bytes_counted_and_link_survives():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        bad = bytearray(pack_rx("BUTTON")); bad[4] ^= 1
        bus.device_says(b"\xde\xad" + bytes(bad) + pack_rx("PROXIMITY", 1))
        assert wait_for(lambda: {"type": "proximity", "near": True} in ev)
        assert d.stats["checksum_errors"] >= 1 and d.stats["dropped_bytes"] >= 3
        assert {"type": "button"} not in ev and d.connected
    finally:
        d.close()


def test_reconnect_request_reopens_port():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    try:
        assert wait_for(lambda: d.connected)
        d.reconnect()
        assert wait_for(lambda: bus.opens == 2 and d.connected, 3.0)
    finally:
        d.close()


def test_close_stops_thread():
    bus = Bus()
    d, ev = make_dev(bus)
    d.start()
    assert wait_for(lambda: d.connected)
    d.close()
    assert not d._thread.is_alive()


# ---------------------------------------------------------------- engine + device
def make_engine(tmp_path, dev, realtime=0.0):
    ev = []
    e = Engine(MockSTT(), MockLLM(), MockTTS(), dev, Memory(str(tmp_path / "d.db")), emit=ev.append, realtime=realtime)
    return e, ev


def test_engine_with_serial_device_disconnect_within_6s_and_recover(tmp_path):
    """Acceptance 7: unplug -> disconnected, plug -> sleeping, no exception. (Fake port, short timers.)"""
    bus = Bus()
    d, _ = make_dev(bus)

    async def go():
        e, ev = make_engine(tmp_path, d)
        e.attach_loop()
        assert e.sm.state == State.DISCONNECTED            # link not up yet
        d.start()
        try:
            for _ in range(300):
                await asyncio.sleep(0.01)
                if e.sm.state == State.SLEEPING:
                    break
            assert e.sm.state == State.SLEEPING
            e.set_settings({"content": "unfiltered"}, from_ui=True)
            assert e.settings["content"] == "unfiltered"
            bus.unplugged = True
            for _ in range(300):
                await asyncio.sleep(0.01)
                if e.sm.state == State.DISCONNECTED:
                    break
            assert e.sm.state == State.DISCONNECTED
            bus.unplugged = False
            for _ in range(400):
                await asyncio.sleep(0.01)
                if e.sm.state == State.SLEEPING:
                    break
            assert e.sm.state == State.SLEEPING
            assert e.settings["content"] == "pg"            # reconnect forces PG
            assert [x["connected"] for x in ev if x["type"] == "device_link"] == [True, False, True]
        finally:
            d.close()
    asyncio.run(go())


def test_engine_wakes_on_serial_proximity_and_button_interrupts(tmp_path):
    bus = Bus()
    d, _ = make_dev(bus)

    async def go():
        e, ev = make_engine(tmp_path, d, realtime=1.0)
        e.attach_loop()
        d.start()
        try:
            for _ in range(300):
                await asyncio.sleep(0.01)
                if e.sm.state == State.SLEEPING:
                    break
            bus.device_says(pack_rx("PROXIMITY", 1))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if e.sm.state == State.LISTENING:
                    break
            assert e.sm.state == State.LISTENING
            t = asyncio.create_task(e.on_text("tell me a joke"))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if e.sm.state == State.SPEAKING:
                    break
            assert e.sm.state == State.SPEAKING
            bus.device_says(pack_rx("BUTTON"))
            await t
            assert any(x["type"] == "interrupted" for x in ev)
            # the face/mouth packets really reached the fake wire
            cmds = {c for c, a, b in bus.tx_packets()}
            assert {1, 2, 3} <= cmds
        finally:
            d.close()
    asyncio.run(go())


def test_selftest_sends_every_face_and_mouth(tmp_path):
    async def go():
        dev = SimDevice()
        e, ev = make_engine(tmp_path, dev)
        e.wake()
        dev.packet_log.clear()
        ok = await e.selftest(step_s=0.0)
        assert ok
        tx = [p["text"] for p in dev.packet_log if p["dir"] == "tx"]
        for emo in EMOTIONS:
            assert f"FACE {emo}" in tx
        for v in ("ah", "oh", "ee", "oo", "fv", "closed"):
            assert f"MOUTH {v}" in tx
        steps = [x for x in ev if x["type"] == "selftest" and not x.get("finished")]
        assert len(steps) == 18 and ev[-1]["type"] == "selftest" and ev[-1]["completed"]
        assert dev.mouth == "closed" and not e._busy
    asyncio.run(go())


def test_selftest_refused_while_speaking_or_disconnected(tmp_path):
    async def go():
        dev = SimDevice()
        e, ev = make_engine(tmp_path, dev)
        dev.sim_disconnect(True)
        assert await e.selftest(0) is False
    asyncio.run(go())


def test_selftest_stops_when_link_drops(tmp_path):
    async def go():
        dev = SimDevice()
        e, ev = make_engine(tmp_path, dev, realtime=1.0)
        e.wake()
        t = asyncio.create_task(e.selftest(step_s=0.05))
        await asyncio.sleep(0.12)
        dev.sim_disconnect(True)
        assert await t is False
        assert e.sm.state == State.DISCONNECTED and not e._busy
    asyncio.run(go())


def test_brightness_cap_setting_reaches_device_and_is_validated(tmp_path):
    dev = SimDevice()
    e, ev = make_engine(tmp_path, dev)
    assert e.set_settings({"device_brightness_cap": 77}, from_ui=True) == {}
    assert dev.brightness == 77 and "BRIGHTNESS 77" in [p["text"] for p in dev.packet_log]
    assert "device_brightness_cap" in e.set_settings({"device_brightness_cap": 300}, from_ui=True)
    assert dev.brightness == 77


def test_swap_device_resets_content_to_pg(tmp_path):
    dev = SimDevice()
    e, ev = make_engine(tmp_path, dev)
    e.set_settings({"content": "unfiltered"}, from_ui=True)
    new = SimDevice()
    e.swap_device(new)
    assert e.dev is new and e.settings["content"] == "pg" and e.sm.state == State.SLEEPING
    bus = Bus()
    sd, _ = make_dev(bus)                                    # not started: link is down
    e.swap_device(sd)
    assert e.sm.state == State.DISCONNECTED


# ---------------------------------------------------------------- REST / WS
def test_device_rest_endpoints_and_mode_switch(tmp_path):
    bus = Bus()
    made = []

    def factory(mode, port, cap):
        if mode == "serial":
            d, _ = make_dev(bus, brightness_cap=cap, port=port)
            d.start()
            made.append(d)
            return d
        return SimDevice()
    app = create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "s.db"), realtime=0.0,
                     device_factory=factory)
    with TestClient(app) as c:
        st = c.get("/api/device/status").json()
        assert st["kind"] == "sim" and st["connected"]
        assert c.get("/api/device/packets").json()["packets"] is not None
        assert c.post("/api/device/test_emotion", json={"emotion": "nope"}).status_code == 422
        assert c.post("/api/device/test_emotion", json={"emotion": "angry"}).json()["ok"]
        r = c.post("/api/device/selftest")
        assert r.status_code == 200 and r.json()["steps"] == 18
        c.post("/api/device/selftest/stop")
        time.sleep(0.2)
        # switch to the (fake) serial device
        r = c.put("/api/settings", json={"device_mode": "serial", "serial_port": ""})
        assert r.status_code == 200
        assert wait_for(lambda: c.get("/api/device/status").json()["connected"], 3.0)
        st = c.get("/api/device/status").json()
        assert st["kind"] == "serial" and st["port"] == "COM7" and st["rx_packets"] >= 1
        assert c.get("/api/snapshot").json()["state"] == "sleeping"
        assert c.post("/api/device/reconnect").json()["ok"]
        # and back to the simulator
        c.put("/api/settings", json={"device_mode": "sim"})
        assert c.get("/api/device/status").json()["kind"] == "sim"
        assert c.put("/api/settings", json={"device_brightness_cap": 999}).status_code == 422
    for d in made:
        d.close()


def test_ws_reconnect_and_sim_buttons_still_work(tmp_path):
    app = create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "w.db"), realtime=0.0)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            snap = json.loads(ws.receive_text())
            assert snap["device"]["kind"] == "sim"
            ws.send_text(json.dumps({"type": "sim", "what": "near"}))
            seen = []
            for _ in range(20):
                ev = json.loads(ws.receive_text())
                seen.append(ev["type"])
                if ev["type"] == "state" and ev["state"] == "listening":
                    break
            assert "wake" in seen
            ws.send_text(json.dumps({"type": "sim", "what": "unplug"}))
            for _ in range(20):
                ev = json.loads(ws.receive_text())
                if ev["type"] == "device_link":
                    assert ev["connected"] is False
                    break
            ws.send_text(json.dumps({"type": "reconnect"}))
            for _ in range(20):
                ev = json.loads(ws.receive_text())
                if ev["type"] == "device_link":
                    assert ev["connected"] is True
                    break
