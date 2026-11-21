# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Password policy (PHASE-2.md section 6.5, D4) and scrypt hashing.

One module, shared by task-core (verification) and task-core-admin (setting).
NFC normalization and nothing else: no NFKC, no case folding, no trimming.
"""

import base64
import hashlib
import hmac
import os
import threading
import unicodedata

MIN_LENGTH = 8
MAX_LENGTH = 256
SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
_MAXMEM = 64 * 1024 * 1024
PREFIX = f"scrypt$n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}$"

LENGTH_MESSAGE = f"password must be {MIN_LENGTH}\u2013{MAX_LENGTH} characters"
CONTROL_MESSAGE = "password contains a control character (for example a pasted newline or tab)"

# scrypt work is serialized so concurrent logins cannot exhaust memory.
_SCRYPT_LOCK = threading.Lock()


class PolicyError(ValueError):
    pass


def normalize(password: str) -> str:
    return unicodedata.normalize("NFC", password)


def length_ok(password: str) -> bool:
    return MIN_LENGTH <= len(normalize(password)) <= MAX_LENGTH


def has_control(password: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in password)


def check_for_set(password: str) -> str:
    """Return the NFC password to store, or raise PolicyError (set time only)."""
    if not isinstance(password, str):
        raise PolicyError(LENGTH_MESSAGE)
    normalized = normalize(password)
    if has_control(normalized):
        raise PolicyError(CONTROL_MESSAGE)
    if not (MIN_LENGTH <= len(normalized) <= MAX_LENGTH):
        raise PolicyError(LENGTH_MESSAGE)
    return normalized


def _derive(normalized: str, salt: bytes) -> bytes:
    with _SCRYPT_LOCK:
        return hashlib.scrypt(
            normalized.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            maxmem=_MAXMEM,
            dklen=KEY_BYTES,
        )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    normalized = check_for_set(password)
    salt = os.urandom(SALT_BYTES)
    return PREFIX + _b64(salt) + "$" + _b64(_derive(normalized, salt))


def parse_hash(stored: str):
    if not isinstance(stored, str) or not stored.startswith(PREFIX):
        return None
    rest = stored[len(PREFIX):]
    parts = rest.split("$")
    if len(parts) != 2:
        return None
    try:
        salt = base64.b64decode(parts[0], validate=True)
        key = base64.b64decode(parts[1], validate=True)
    except (ValueError, TypeError):
        return None
    if len(salt) != SALT_BYTES or len(key) != KEY_BYTES:
        return None
    return salt, key


def valid_hash_format(stored) -> bool:
    return parse_hash(stored) is not None


_DUMMY_SALT = b"rain-dummy-salt!"


def dummy_verify() -> bool:
    """Spend one scrypt so a missing account costs the same as a real one."""
    _derive("dummy password", _DUMMY_SALT)
    return False


def verify(password, stored) -> bool:
    """Login-time check. Never raises for bad input; out-of-policy costs a dummy scrypt."""
    if not isinstance(password, str) or not length_ok(password):
        return dummy_verify()
    parsed = parse_hash(stored)
    if parsed is None:
        return dummy_verify()
    salt, key = parsed
    candidate = _derive(normalize(password), salt)
    return hmac.compare_digest(candidate, key)
