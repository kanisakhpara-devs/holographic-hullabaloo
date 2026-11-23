"""Device link. The 12 faces + 6 mouth patches live ON the rotor, so the laptop
only sends tiny commands (face id, mouth id, power), never frames.

Byte level format and examples: docs/PROTOCOL.md (keep it in sync with this file).

Laptop -> device   [0xA5, cmd, a, b, checksum]   checksum = (cmd + a + b) & 0xFF
  1 FACE (a = emotion index 0..11)   2 MOUTH (a = viseme index 0..5)   3 POWER (a = 0 sleep / 1 awake)
  4 PING   5 BRIGHTNESS (a = 0..255 cap)   6 SLEEP_ANIM (reserved)
  7 SHOW_EMOTION_TEST (a = emotion index, device holds it for 3 s)
Device -> laptop   [0x5A, cmd, a, b, checksum]   same checksum
  1 PROXIMITY (a = 1 near / 0 far)   2 BUTTON   3 PONG   4 ROTOR_STATUS (a = 1 ok)
  5 BRIGHTNESS_ACK (a = cap now in force)

SerialDevice keeps one IO thread that owns the port: it opens it, reads, writes the queue,
pings every 2 s and declares the link down after 6 s of silence. Events reach the engine
through `on_event` from that thread (the engine hops them onto its event loop).
"""
import collections, logging, queue, threading, time
from typing import Callable, List
from .emotions import EMOTIONS

log = logging.getLogger("hullabaloo.device")

VISEMES = ["closed", "ah", "oh", "ee", "oo", "fv"]
H_TX, H_RX = 0xA5, 0x5A                      # laptop -> device, device -> laptop
CMD = {"FACE": 1, "MOUTH": 2, "POWER": 3, "PING": 4, "BRIGHTNESS": 5, "SLEEP_ANIM": 6, "TEST_EMOTION": 7}
RX_CMD = {"PROXIMITY": 1, "BUTTON": 2, "PONG": 3, "ROTOR_STATUS": 4, "BRIGHTNESS_ACK": 5}
CMD_NAME = {v: k for k, v in CMD.items()}
RX_NAME = {v: k for k, v in RX_CMD.items()}
ESP32S3_VID_PID = "303A:1001"                 # ESP32-S3 built in USB serial/JTAG
DEFAULT_BAUD = 921600


def checksum(cmd: int, a: int = 0, b: int = 0) -> int:
    return (cmd + a + b) & 0xFF


def pack(cmd: str, a: int = 0, b: int = 0) -> bytes:
    """Laptop -> device packet."""
    c = CMD[cmd]
    return bytes([H_TX, c, a & 255, b & 255, checksum(c, a & 255, b & 255)])


def pack_rx(cmd: str, a: int = 0, b: int = 0) -> bytes:
    """Device -> laptop packet (used by the simulator, the firmware reference and the tests)."""
    c = RX_CMD[cmd]
    return bytes([H_RX, c, a & 255, b & 255, checksum(c, a & 255, b & 255)])


class PacketParser:
    """Byte stream -> (cmd, a, b) tuples. A bad checksum drops one byte and hunts for the next
    header byte, so one corrupted byte costs at most the packets that overlap it."""

    def __init__(self, header: int = H_RX):
        self.header = bytes([header])
        self.buf = bytearray()
        self.packets = 0
        self.checksum_errors = 0
        self.dropped_bytes = 0

    def feed(self, data: bytes) -> list:
        self.buf += data
        out = []
        while True:
            i = self.buf.find(self.header)
            if i < 0:
                self.dropped_bytes += len(self.buf)
                self.buf.clear()
                break
            if i > 0:
                self.dropped_bytes += i
                del self.buf[:i]
            if len(self.buf) < 5:
                break
            cmd, a, b, ck = self.buf[1], self.buf[2], self.buf[3], self.buf[4]
            if checksum(cmd, a, b) == ck:
                out.append((cmd, a, b))
                self.packets += 1
                del self.buf[:5]
            else:
                self.checksum_errors += 1
                self.dropped_bytes += 1
                del self.buf[:1]
        return out


def describe_tx(cmd: int, a: int, b: int) -> str:
    n = CMD_NAME.get(cmd, f"cmd{cmd}")
    if n in ("FACE", "TEST_EMOTION") and a < len(EMOTIONS):
        return f"{n} {EMOTIONS[a]}"
    if n == "MOUTH" and a < len(VISEMES):
        return f"MOUTH {VISEMES[a]}"
    if n == "POWER":
        return "POWER awake" if a else "POWER sleep"
    if n == "BRIGHTNESS":
        return f"BRIGHTNESS {a}"
    return n


def describe_rx(cmd: int, a: int, b: int) -> str:
    n = RX_NAME.get(cmd, f"cmd{cmd}")
    if n == "PROXIMITY":
        return "PROXIMITY near" if a else "PROXIMITY far"
    if n == "ROTOR_STATUS":
        return "ROTOR ok" if a else "ROTOR fault"
    if n == "BRIGHTNESS_ACK":
        return f"BRIGHTNESS_ACK {a}"
    return n


def decode_rx_event(cmd: int, a: int, b: int):
    """Device packet -> engine event dict (None for packets the engine does not act on)."""
    n = RX_NAME.get(cmd)
    if n == "PROXIMITY":
        return {"type": "proximity", "near": bool(a)}
    if n == "BUTTON":
        return {"type": "button"}
    if n == "ROTOR_STATUS":
        return {"type": "rotor", "ok": bool(a)}
    if n == "BRIGHTNESS_ACK":
        return {"type": "brightness_ack", "value": a}
    return None


def list_serial_ports():
    """COM ports, ESP32-S3 USB-JTAG (303A:1001) marked as likely."""
    from serial.tools import list_ports
    out = []
    for p in list_ports.comports():
        vidpid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else None
        out.append({"port": p.device, "description": p.description, "vid_pid": vidpid,
                    "likely": vidpid == ESP32S3_VID_PID})
    return {"ports": out}


def pick_port(configured: str, ports: list):
    """Which COM port to open. A configured port is used only if it exists right now. With none
    configured, only a port with the ESP32-S3 VID:PID is auto-picked (never a random COM port,
    so Bluetooth serial ports and other boards are left alone)."""
    names = {p["port"] for p in ports}
    if configured:
        return configured if configured in names else None
    for p in ports:
        if p.get("likely"):
            return p["port"]
    return None


class DeviceLink:
    kind = "base"
    on_event: Callable[[dict], None] = lambda self, e: None

    def __init__(self):
        self.packet_log = collections.deque(maxlen=100)
        self.brightness = 255
        self.tx_count = 0

    connected = False

    def _log_packet(self, direction: str, raw: bytes, text: str):
        self.packet_log.append({"t": round(time.time(), 3), "dir": direction, "hex": raw.hex(" "), "text": text})

    def packets(self, n: int = 100) -> list:
        return list(self.packet_log)[-max(1, min(n, 100)):]

    def set_face(self, emotion: str): ...
    def set_mouth(self, viseme: str): ...
    def set_power(self, awake: bool): ...
    def set_brightness(self, cap: int): ...
    def test_emotion(self, emotion: str): ...
    def play_audio(self, pcm: bytes, sample_rate: int): ...
    def reconnect(self): ...
    def close(self): ...

    def status(self) -> dict:
        return {"kind": self.kind, "connected": self.connected, "brightness_cap": self.brightness,
                "tx_packets": self.tx_count}


class SimDevice(DeviceLink):
    """Software stand-in: records everything sent (also what the UI preview shows)."""
    kind = "sim"

    def __init__(self):
        super().__init__()
        self.connected = True
        self.face, self.mouth, self.awake = "neutral", "closed", False
        self.log: List[tuple] = []
        self.audio_bytes = 0
        self.test_face = None

    def _l(self, *a):
        self.log.append((time.time(), *a))

    def _tx(self, name, a=0, b=0):
        raw = pack(name, a, b)
        self.tx_count += 1
        self._log_packet("tx", raw, describe_tx(raw[1], raw[2], raw[3]))
        return raw

    def set_face(self, emotion):
        self.face = emotion
        self._l("face", emotion, self._tx("FACE", EMOTIONS.index(emotion)).hex())

    def set_mouth(self, viseme):
        self.mouth = viseme
        self._l("mouth", viseme, self._tx("MOUTH", VISEMES.index(viseme)).hex())

    def set_power(self, awake):
        self.awake = awake
        self._tx("POWER", int(awake))
        self._l("power", awake)

    def set_brightness(self, cap):
        self.brightness = int(cap)
        self._tx("BRIGHTNESS", int(cap))
        self._l("brightness", int(cap))

    def test_emotion(self, emotion):
        self.test_face = emotion
        self._tx("TEST_EMOTION", EMOTIONS.index(emotion))
        self._l("test_emotion", emotion)

    def play_audio(self, pcm, sample_rate):
        self.audio_bytes += len(pcm)

    def reconnect(self):
        self.sim_disconnect(False)

    # test helpers: pretend the hardware did something
    def sim_proximity(self, near: bool):
        self._log_packet("rx", pack_rx("PROXIMITY", int(near)), describe_rx(1, int(near), 0))
        self.on_event({"type": "proximity", "near": near})

    def sim_button(self):
        self._log_packet("rx", pack_rx("BUTTON"), "BUTTON")
        self.on_event({"type": "button"})

    def sim_disconnect(self, down=True):
        self.connected = not down
        self.on_event({"type": "link", "connected": self.connected})


class SerialDevice(DeviceLink):
    """Real link to the base ESP32-S3 over USB serial (921600 baud).

    Link rules: the port opening is not enough, the link counts as UP only once the device has
    sent a valid packet (answering our PING is enough). It goes DOWN after `timeout_s` without
    any valid packet, or when the port errors out (cable pulled). While down the IO thread keeps
    retrying the port every `backoff_s`. `serial_factory(port, baud)` and `ports_func()` exist so
    the tests can run the whole thing against a fake port."""
    kind = "serial"

    def __init__(self, port="", baud=DEFAULT_BAUD, brightness_cap=255, serial_factory=None, ports_func=None,
                 heartbeat_s=2.0, timeout_s=6.0, backoff_s=1.0, clock=time.monotonic, autostart=True):
        super().__init__()
        self.port_pref, self.baud = port or "", baud
        self.brightness = int(brightness_cap)
        self._factory = serial_factory or _open_real_port
        self._ports = ports_func or (lambda: list_serial_ports()["ports"])
        self.heartbeat_s, self.timeout_s, self.backoff_s, self._clock = heartbeat_s, timeout_s, backoff_s, clock
        self._tx_q: "queue.Queue[bytes]" = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._force_reopen = threading.Event()
        self._thread = None
        self.s = None
        self.port = None
        self._up = False
        self._last_rx = 0.0
        self._last_ping = float("-inf")
        self._ping_sent_at = None
        self.parser = PacketParser(H_RX)
        self.stats = {"rx_packets": 0, "checksum_errors": 0, "dropped_bytes": 0, "tx_dropped": 0,
                      "link_ups": 0, "link_downs": 0, "opens": 0, "ping_ms": None, "last_error": None,
                      "rotor_ok": None, "brightness_ack": None}
        if autostart:
            self.start()

    @property
    def connected(self):
        return self._up

    @connected.setter
    def connected(self, v):          # DeviceLink declares a plain attribute; the link flag is private here
        pass

    # ---- lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="serial-link", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._close_port()

    def reconnect(self):
        """Drop the port and open it again (the UI 'Reconnect' button)."""
        self._force_reopen.set()

    def set_port(self, port: str):
        self.port_pref = port or ""
        self._force_reopen.set()

    # ---- public tx (called from the engine thread)
    def _tx(self, name, a=0, b=0):
        raw = pack(name, a, b)
        if not self._up and name != "PING":
            self.stats["tx_dropped"] += 1          # nobody is listening, and stale faces would be wrong later
            return
        try:
            self._tx_q.put_nowait(raw)
        except queue.Full:
            self.stats["tx_dropped"] += 1

    def set_face(self, emotion): self._tx("FACE", EMOTIONS.index(emotion))
    def set_mouth(self, viseme): self._tx("MOUTH", VISEMES.index(viseme))
    def set_power(self, awake): self._tx("POWER", int(awake))

    def set_brightness(self, cap):
        self.brightness = int(cap)
        self._tx("BRIGHTNESS", self.brightness)

    def test_emotion(self, emotion): self._tx("TEST_EMOTION", EMOTIONS.index(emotion))

    def play_audio(self, pcm, sample_rate):
        pass  # audio goes out the base's USB sound card via the OS audio device, not this serial port

    # ---- IO thread
    def _run(self):
        while not self._stop.is_set():
            try:
                if self._force_reopen.is_set():
                    self._force_reopen.clear()
                    self._lost("reconnect requested", quiet=True)
                if self.s is None and not self._open():
                    self._stop.wait(self.backoff_s)
                    continue
                self._cycle()
            except Exception as ex:                   # SerialException, OSError (cable pulled), anything odd
                self._lost(f"{type(ex).__name__}: {ex}")
                self._stop.wait(self.backoff_s)
        self._lost("closed", quiet=True)

    def _open(self) -> bool:
        try:
            port = pick_port(self.port_pref, self._ports())
        except Exception as ex:
            self.stats["last_error"] = f"port list failed: {ex}"
            return False
        if not port:
            self.stats["last_error"] = ("port %s not present" % self.port_pref) if self.port_pref \
                else "no ESP32-S3 serial port found (303A:1001)"
            return False
        try:
            self.s = self._factory(port, self.baud)
        except Exception as ex:
            self.stats["last_error"] = f"open {port} failed: {ex}"
            self.s = None
            return False
        self.port = port
        self.stats["opens"] += 1
        self.stats["last_error"] = None
        self.parser = PacketParser(H_RX)
        self._last_rx = self._clock()
        self._last_ping = float("-inf")               # ping right away
        while not self._tx_q.empty():
            try:
                self._tx_q.get_nowait()
            except queue.Empty:
                break
        log.info("serial port %s open at %d baud", port, self.baud)
        return True

    def _close_port(self):
        s, self.s = self.s, None
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    def _write(self, raw: bytes):
        self.s.write(raw)
        self.tx_count += 1
        self._log_packet("tx", raw, describe_tx(raw[1], raw[2], raw[3]))

    def _cycle(self):
        now = self._clock()
        if now - self._last_ping >= self.heartbeat_s:
            self._write(pack("PING"))
            self._last_ping, self._ping_sent_at = now, now
        while True:
            try:
                raw = self._tx_q.get_nowait()
            except queue.Empty:
                break
            self._write(raw)
        n = getattr(self.s, "in_waiting", 0) or 1
        data = self.s.read(n)
        if data:
            self._on_bytes(data)
        if self._up and self._clock() - self._last_rx > self.timeout_s:
            self._set_link(False, "heartbeat timeout")

    def _on_bytes(self, data: bytes):
        p = self.parser
        before_err, before_drop = p.checksum_errors, p.dropped_bytes
        pkts = p.feed(data)
        self.stats["checksum_errors"] += p.checksum_errors - before_err
        self.stats["dropped_bytes"] += p.dropped_bytes - before_drop
        for cmd, a, b in pkts:
            self._last_rx = self._clock()
            self.stats["rx_packets"] += 1
            self._log_packet("rx", bytes([H_RX, cmd, a, b, checksum(cmd, a, b)]), describe_rx(cmd, a, b))
            if not self._up:
                self._set_link(True, "packet received")
            if cmd == RX_CMD["PONG"] and self._ping_sent_at is not None:
                self.stats["ping_ms"] = round((self._clock() - self._ping_sent_at) * 1000, 1)
            elif cmd == RX_CMD["ROTOR_STATUS"]:
                self.stats["rotor_ok"] = bool(a)
            elif cmd == RX_CMD["BRIGHTNESS_ACK"]:
                self.stats["brightness_ack"] = a
            ev = decode_rx_event(cmd, a, b)
            if ev:
                self._emit(ev)

    def _set_link(self, up: bool, why: str):
        if up == self._up:
            return
        self._up = up
        self.stats["link_ups" if up else "link_downs"] += 1
        log.info("device link %s (%s)", "UP" if up else "DOWN", why)
        if up:
            try:
                self._write(pack("BRIGHTNESS", self.brightness))     # cap first, before any face
            except Exception:
                pass
        self._emit({"type": "link", "connected": up})

    def _lost(self, why: str, quiet=False):
        had_port = self.s is not None
        self._close_port()
        if had_port and not quiet:
            self.stats["last_error"] = why
            log.warning("serial port lost: %s", why)
        if self._up:
            self._set_link(False, why)

    def _emit(self, ev):
        try:
            self.on_event(ev)
        except Exception:
            log.exception("device event handler failed")

    def status(self) -> dict:
        return {"kind": self.kind, "connected": self._up, "port": self.port, "port_open": self.s is not None,
                "baud": self.baud, "port_setting": self.port_pref, "brightness_cap": self.brightness,
                "tx_packets": self.tx_count, **self.stats}


def _open_real_port(port: str, baud: int):
    """Open with DTR/RTS held low: toggling them resets an ESP32-S3 or drops it into the bootloader."""
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.write_timeout = port, baud, 0.01, 0.5
    s.dtr, s.rts = False, False
    s.open()
    return s
