# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Structured logging: JSON-lines file + human console, with secret redaction.

The meshtastic library logs raw FromRadio bytes (including channel PSKs) at DEBUG, so its logger
tree is always capped at WARNING and every handler carries RedactingFilter.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_STANDARD = set(vars(logging.LogRecord("x", 0, "x", 0, "", None, None)).keys()) | {"message", "asctime"}
_EXTRA_FIELDS = ("event", "port", "state", "node_num", "err_type", "from_state", "to_state", "reason")

REDACTED = "[REDACTED: possible key material]"
_SENSITIVE_WORDS = re.compile(
    r"(psk|session_?passkey|passkey|private_?key|public_?key|admin_?key|privateKey|publicKey|adminKey)",
    re.IGNORECASE,
)
_BYTES_LITERAL = re.compile(r"""b(['"])(?:\\x[0-9a-fA-F]{2}|\\.|(?!\1).){16,}?\1""")
_BASE64_BLOB = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/]{22,}={0,2}(?![A-Za-z0-9+/_-])")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def _b64_sub(m: "re.Match[str]") -> str:
    blob = m.group(0)
    # Filesystem paths are not key material: skip things that look like /a/b/c.
    if blob.startswith("/") or "//" in blob:
        return blob
    if re.search(r"[A-Z]", blob) and re.search(r"[a-z]", blob) and re.search(r"[0-9+]", blob):
        return "[REDACTED blob]"
    return blob


def redact_text(text: str) -> str:
    """Return text with likely secrets removed. Whole message is dropped if it names a key field."""
    if _SENSITIVE_WORDS.search(text):
        return REDACTED
    text = _BYTES_LITERAL.sub("b'[REDACTED bytes]'", text)
    text = _BASE64_BLOB.sub(_b64_sub, text)
    text = _HEX_BLOB.sub("[REDACTED hex]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        red = redact_text(msg)
        if red != msg:
            record.msg = red
            record.args = None
        if record.exc_info:
            # Exception text may contain raw packet bytes; format then redact.
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


def _redact_value(val):
    """Extra fields are redacted too: strings individually, structures as a whole."""
    if val is None or isinstance(val, (bool, int, float)):
        return val
    if isinstance(val, str):
        return redact_text(val)
    try:
        dumped = json.dumps(val, ensure_ascii=False)
    except TypeError:
        return redact_text(repr(val))
    return val if redact_text(dumped) == dumped else REDACTED


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                doc[key] = _redact_value(getattr(record, key))
        for key, val in record.__dict__.items():
            if key not in _STANDARD and key not in doc and not key.startswith("_"):
                doc[key] = _redact_value(val)
        if record.exc_text:
            doc["exc"] = record.exc_text
        return json.dumps(doc, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s")


_lock = threading.Lock()
_installed: list[logging.Handler] = []


def clamp_library_loggers() -> None:
    for name in ("meshtastic", "pubsub"):
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(log_file: Optional[Path], level: str = "INFO", console: bool = True) -> None:
    """Idempotent: replaces handlers installed by a previous call."""
    with _lock:
        root = logging.getLogger()
        for h in _installed:
            root.removeHandler(h)
            h.close()
        _installed.clear()
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        redactor = RedactingFilter()
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fh = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            fh.setFormatter(JsonFormatter())
            fh.addFilter(redactor)
            root.addHandler(fh)
            _installed.append(fh)
        if console:
            ch = logging.StreamHandler(sys.stderr)
            ch.setFormatter(ConsoleFormatter())
            ch.addFilter(redactor)
            root.addHandler(ch)
            _installed.append(ch)
        clamp_library_loggers()
