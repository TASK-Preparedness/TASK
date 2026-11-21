# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""APRS codec for task-aprs: decoder copied from task-launcher 0.2.0 (services/aprs.py, receive-only
monitor) plus an encoder. Encoding only builds bytes; nothing here opens a socket. Whether a frame
may be sent is decided by task_comms.txpolicy, never here.
"""

import time
from dataclasses import dataclass, field


FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD
MAX_FRAME = 4096


# ---------------------------------------------------------------- KISS

class KissDecoder:
    """Incremental KISS de-framer. ``feed(bytes)`` returns [(port, payload)] for data frames."""

    def __init__(self):
        self.buf = bytearray()
        self.in_frame = False
        self.dropped = 0

    def feed(self, data: bytes):
        out = []
        for b in data:
            if b == FEND:
                if self.in_frame and self.buf:
                    frame = self._unescape(bytes(self.buf))
                    if frame:
                        cmd = frame[0]
                        if cmd & 0x0F == 0x00:            # data frame
                            out.append((cmd >> 4, frame[1:]))
                self.buf.clear()
                self.in_frame = True
                continue
            if self.in_frame:
                if len(self.buf) >= MAX_FRAME:
                    self.buf.clear()
                    self.in_frame = False
                    self.dropped += 1
                    continue
                self.buf.append(b)
        return out

    @staticmethod
    def _unescape(data: bytes):
        out = bytearray()
        esc = False
        for b in data:
            if esc:
                if b == TFEND:
                    out.append(FEND)
                elif b == TFESC:
                    out.append(FESC)
                else:
                    return None                           # protocol violation: drop the frame
                esc = False
            elif b == FESC:
                esc = True
            else:
                out.append(b)
        return None if esc else bytes(out)


# ---------------------------------------------------------------- AX.25

@dataclass
class Address:
    call: str
    ssid: int
    repeated: bool = False

    def __str__(self):
        s = self.call + (f"-{self.ssid}" if self.ssid else "")
        return s + ("*" if self.repeated else "")


@dataclass
class Frame:
    dest: Address
    source: Address
    path: list = field(default_factory=list)
    control: int = 0
    pid: int = None
    info: bytes = b""

    @property
    def is_ui(self):
        return self.control & 0xEF == 0x03

    def header(self):
        via = "," + ",".join(str(a) for a in self.path) if self.path else ""
        return f"{self.source.call}{'-' + str(self.source.ssid) if self.source.ssid else ''}>{self.dest.call}" \
               f"{'-' + str(self.dest.ssid) if self.dest.ssid else ''}{via}"


class AX25Error(ValueError):
    pass


def _addr(chunk: bytes):
    chars = []
    for b in chunk[:6]:
        if b & 0x01:
            raise AX25Error("address extension bit set inside callsign")
        c = chr(b >> 1)
        if not (c.isalnum() or c == " "):
            raise AX25Error("invalid callsign character")
        chars.append(c)
    s = chunk[6]
    return Address("".join(chars).strip(), (s >> 1) & 0x0F, bool(s & 0x80)), bool(s & 0x01)


def decode_ax25(data: bytes) -> Frame:
    if len(data) < 15:
        raise AX25Error("frame too short")
    addrs, i, last = [], 0, False
    while not last:
        if i + 7 > len(data) or len(addrs) >= 10:
            raise AX25Error("unterminated address field")
        a, last = _addr(data[i:i + 7])
        addrs.append(a)
        i += 7
    if len(addrs) < 2:
        raise AX25Error("missing source address")
    if i >= len(data):
        raise AX25Error("missing control field")
    dest, src, path = addrs[0], addrs[1], addrs[2:]
    dest.repeated = src.repeated = False                  # C/R bits, not "has been repeated"
    f = Frame(dest, src, path, control=data[i])
    i += 1
    if f.is_ui:
        if i >= len(data):
            raise AX25Error("missing PID")
        f.pid = data[i]
        f.info = data[i + 1:]
    return f


# ---------------------------------------------------------------- APRS

@dataclass
class AprsPacket:
    time: float
    source: str
    dest: str
    path: str
    raw: str
    kind: str = "other"
    lat: float = None
    lon: float = None
    symbol: str = ""
    comment: str = ""
    addressee: str = ""
    message: str = ""
    name: str = ""
    weather: dict = field(default_factory=dict)
    port: int = 0
    error: str = ""

    def summary(self):
        """Decoded content (the packet type is shown separately)."""
        bits = []
        if self.name:
            bits.append(self.name)
        if self.lat is not None and self.lon is not None:
            bits.append(f"{self.lat:.4f}, {self.lon:.4f}")
        if self.addressee:
            bits.append(f"to {self.addressee}: {self.message}")
        if self.weather:
            bits.append(format_weather(self.weather))
        if self.comment and not self.addressee:
            bits.append(self.comment[:80])
        return " · ".join(bits)


def _lat(s: str):
    s = s.replace(" ", "0")
    if len(s) != 8 or s[4] != "." or s[7] not in "NS":
        raise ValueError("bad latitude")
    v = int(s[0:2]) + float(s[2:7]) / 60
    if v > 90:
        raise ValueError("latitude out of range")
    return -v if s[7] == "S" else v


def _lon(s: str):
    s = s.replace(" ", "0")
    if len(s) != 9 or s[5] != "." or s[8] not in "EW":
        raise ValueError("bad longitude")
    v = int(s[0:3]) + float(s[3:8]) / 60
    if v > 180:
        raise ValueError("longitude out of range")
    return -v if s[8] == "W" else v


def _b91(s: str):
    v = 0
    for c in s:
        o = ord(c) - 33
        if not 0 <= o <= 90:
            raise ValueError("bad base91")
        v = v * 91 + o
    return v


def _position(p: AprsPacket, body: str):
    """Uncompressed or compressed position at the start of ``body``; returns the comment."""
    if body[:1].isdigit() or body[:1] == " ":
        p.lat = _lat(body[0:8])
        table = body[8]
        p.lon = _lon(body[9:18])
        p.symbol = table + body[18]
        rest = body[19:]
    else:
        if len(body) < 13:
            raise ValueError("short compressed position")
        table = body[0]
        p.lat = 90 - _b91(body[1:5]) / 380926
        p.lon = -180 + _b91(body[5:9]) / 190463
        p.symbol = table + body[9]
        rest = body[13:]
    if p.symbol.endswith("_"):
        p.weather = parse_weather(rest)
    return rest


def format_weather(wx: dict) -> str:
    """Human text for parse_weather() values, in the units the station sent (APRS: mph, °F)."""
    parts = []
    if "wind_dir_deg" in wx or "wind_mph" in wx:
        parts.append(f"wind {wx.get('wind_dir_deg', '—')}° {wx.get('wind_mph', '—')} mph")
    if "gust_mph" in wx:
        parts.append(f"gust {wx['gust_mph']} mph")
    if "temp_f" in wx:
        parts.append(f"{wx['temp_f']} °F")
    if "humidity_pct" in wx:
        parts.append(f"humidity {wx['humidity_pct']} %")
    if "pressure_dpa" in wx:
        parts.append(f"{wx['pressure_dpa'] / 10:.1f} hPa")
    if "rain_1h_hin" in wx:
        parts.append(f"rain 1 h {wx['rain_1h_hin'] / 100:.2f} in")
    return "weather: " + ", ".join(parts) if parts else ""


def parse_weather(text: str):
    """Common APRS weather fields: wind dir/speed (mph), gust (mph), temperature (°F), rain,
    humidity, pressure (tenths of hPa). Values are reported as received."""
    import re

    wx = {}
    m = re.match(r"^(\d{3}|\.{3})/(\d{3}|\.{3})", text)
    if m:
        if m.group(1).isdigit():
            wx["wind_dir_deg"] = int(m.group(1))
        if m.group(2).isdigit():
            wx["wind_mph"] = int(m.group(2))
    for key, name, width in (("c", "wind_dir_deg", 3), ("s", "wind_mph", 3), ("g", "gust_mph", 3),
                             ("t", "temp_f", 3), ("r", "rain_1h_hin", 3), ("h", "humidity_pct", 2),
                             ("b", "pressure_dpa", 5)):
        m = re.search(rf"{key}(-?\d{{{width - 1},{width}}})", text)
        if m and name not in wx:
            wx[name] = int(m.group(1))
    if "humidity_pct" in wx and wx["humidity_pct"] == 0:
        wx["humidity_pct"] = 100
    return wx


def _mic_e(p: AprsPacket, dest: str, info: bytes):
    if len(dest) < 6 or len(info) < 9:
        raise ValueError("short Mic-E")
    digits = []
    for c in dest[:6]:
        if c.isdigit():
            digits.append(int(c))
        elif "A" <= c <= "J":
            digits.append(ord(c) - ord("A"))
        elif "P" <= c <= "Y":
            digits.append(ord(c) - ord("P"))
        elif c in "KLZ":
            digits.append(0)
        else:
            raise ValueError("bad Mic-E destination")
    lat = digits[0] * 10 + digits[1] + (digits[2] * 10 + digits[3] + (digits[4] * 10 + digits[5]) / 100) / 60
    north = "P" <= dest[3] <= "Z"
    lon_offset = "P" <= dest[4] <= "Z"
    west = "P" <= dest[5] <= "Z"
    d = info[1] - 28 + (100 if lon_offset else 0)
    if 180 <= d <= 189:
        d -= 80
    elif 190 <= d <= 199:
        d -= 190
    m = info[2] - 28
    if m >= 60:
        m -= 60
    h = info[3] - 28
    lon = d + (m + h / 100) / 60
    if lat > 90 or lon > 180:
        raise ValueError("Mic-E out of range")
    p.lat = lat if north else -lat
    p.lon = -lon if west else lon
    p.symbol = chr(info[8]) + chr(info[7])
    p.comment = info[9:].decode("latin-1", "replace").strip()


def parse_aprs(frame: Frame, port: int = 0, now: float = None) -> AprsPacket:
    info_text = frame.info.decode("latin-1", "replace")
    via = ",".join(str(a) for a in frame.path)
    p = AprsPacket(now if now is not None else time.time(), str(frame.source).rstrip("*"),
                   str(frame.dest).rstrip("*"), via, info_text.rstrip("\r\n"), port=port)
    if not frame.is_ui or frame.pid != 0xF0:
        p.kind = "non-APRS AX.25 frame"
        return p
    dti = info_text[:1]
    try:
        if dti in "!=":
            p.kind = "position"
            p.comment = _position(p, info_text[1:]).strip()
        elif dti in "/@":
            p.kind = "position"
            p.comment = _position(p, info_text[8:]).strip()
        elif dti == ":":
            p.kind = "message"
            p.addressee = info_text[1:10].strip()
            p.message = info_text[11:].split("{")[0].strip() if info_text[10:11] == ":" else info_text[10:]
        elif dti == ">":
            p.kind = "status"
            p.comment = info_text[1:].strip()
        elif dti in "`'":
            p.kind = "position (Mic-E)"
            _mic_e(p, frame.dest.call, frame.info)
        elif dti == ";":
            p.kind = "object"
            p.name = info_text[1:10].strip()
            p.comment = _position(p, info_text[18:]).strip()
        elif dti == ")":
            p.kind = "item"
            for i, ch in enumerate(info_text[1:11], start=1):
                if ch in "!_":
                    p.name = info_text[1:i].strip()
                    p.comment = _position(p, info_text[i + 1:]).strip()
                    break
        elif dti == "_":
            p.kind = "weather"
            p.weather = parse_weather(info_text[9:])
        elif dti == "T":
            p.kind = "telemetry"
            p.comment = info_text
        elif dti == "}":
            p.kind = "third-party"
            p.comment = info_text[1:]
        else:
            p.kind = "other"
            p.comment = info_text
    except (ValueError, IndexError) as exc:
        p.error = f"could not decode: {exc}"
    return p


# ---------------------------------------------------------------- encoder

CALL_RE = __import__("re").compile(r"^[A-Z0-9]{1,6}$")
MSG_MAX, ADDRESSEE_MAX, MSGID_MAX = 67, 9, 5
PRINTABLE_FORBIDDEN = set("|~{")


def parse_callsign(text: str) -> Address:
    text = text.strip().upper()
    call, _, ssid = text.partition("-")
    if not CALL_RE.match(call):
        raise ValueError(f"invalid callsign {text!r}")
    n = int(ssid) if ssid else 0
    if ssid and (not ssid.isdigit() or not 0 <= n <= 15):
        raise ValueError(f"invalid SSID in {text!r}")
    return Address(call, n)


def _enc_addr(a: Address, last: bool, h_bit: bool = False, cr: bool = False) -> bytes:
    out = bytes((ord(c) << 1) for c in a.call.ljust(6))
    s = 0x60 | ((a.ssid & 0x0F) << 1) | (0x80 if (h_bit or cr) else 0) | (0x01 if last else 0)
    return out + bytes([s])


def encode_ax25(source: Address, dest: Address, path=(), info: bytes = b"") -> bytes:
    path = list(path)
    if len(path) > 8:
        raise ValueError("at most 8 digipeaters")
    out = _enc_addr(dest, False, cr=True) + _enc_addr(source, not path)
    for i, a in enumerate(path):
        out += _enc_addr(a, i == len(path) - 1, h_bit=a.repeated)
    return out + bytes([0x03, 0xF0]) + info


def kiss_frame(payload: bytes, port: int = 0) -> bytes:
    body = bytearray([(port & 0x0F) << 4])
    for b in payload:
        if b == FEND:
            body += bytes([FESC, TFEND])
        elif b == FESC:
            body += bytes([FESC, TFESC])
        else:
            body.append(b)
    return bytes([FEND]) + bytes(body) + bytes([FEND])


def check_text(text: str, limit: int, what: str):
    if not text:
        raise ValueError(f"{what} is empty")
    if len(text) > limit:
        raise ValueError(f"{what} is {len(text)} characters (max {limit})")
    for ch in text:
        if not 0x20 <= ord(ch) <= 0x7E or ch in PRINTABLE_FORBIDDEN:
            raise ValueError(f"{what} contains a character APRS does not allow ({ch!r})")


def message_info(addressee: str, text: str, msg_id: str = None) -> str:
    """APRS 1.0.1 ch.14 message: ':ADDRESSEE:text{id'."""
    addressee = addressee.strip().upper()
    check_text(addressee, ADDRESSEE_MAX, "addressee")
    check_text(text, MSG_MAX, "message text")
    out = f":{addressee.ljust(9)}:{text}"
    if msg_id is not None:
        if not (1 <= len(msg_id) <= MSGID_MAX and msg_id.isalnum()):
            raise ValueError("message id must be 1-5 letters/digits")
        out += "{" + msg_id
    return out


def ack_info(addressee: str, msg_id: str, reject: bool = False) -> str:
    return f":{addressee.strip().upper().ljust(9)}:{'rej' if reject else 'ack'}{msg_id}"


def _fmt_lat(lat):
    if not -90 <= lat <= 90:
        raise ValueError("latitude out of range")
    d = int(abs(lat))
    m = (abs(lat) - d) * 60
    return f"{d:02d}{m:05.2f}{'N' if lat >= 0 else 'S'}"


def _fmt_lon(lon):
    if not -180 <= lon <= 180:
        raise ValueError("longitude out of range")
    d = int(abs(lon))
    m = (abs(lon) - d) * 60
    return f"{d:03d}{m:05.2f}{'E' if lon >= 0 else 'W'}"


def position_info(lat: float, lon: float, symbol: str = "/>", comment: str = "", messaging: bool = True) -> str:
    """Uncompressed position without timestamp ('=' if messaging capable)."""
    if len(symbol) != 2:
        raise ValueError("symbol is table + code")
    if comment:
        check_text(comment, 43, "comment")
    return f"{'=' if messaging else '!'}{_fmt_lat(lat)}{symbol[0]}{_fmt_lon(lon)}{symbol[1]}{comment}"


def parse_ack(p: "AprsPacket"):
    """('ack'|'rej', id) if a message packet is an ack/rej, else None."""
    if p.kind != "message":
        return None
    body = p.raw[11:] if p.raw[10:11] == ":" else ""
    for kind in ("ack", "rej"):
        if body.startswith(kind) and 1 <= len(body[3:].strip()) <= MSGID_MAX:
            return kind, body[3:].strip()
    return None


def message_id_of(p: "AprsPacket"):
    if p.kind == "message" and "{" in p.raw:
        mid = p.raw.rsplit("{", 1)[1].strip()
        return mid[:MSGID_MAX] or None
    return None
