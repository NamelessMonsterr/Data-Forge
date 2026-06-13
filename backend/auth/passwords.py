"""Password hashing using stdlib ``hashlib.scrypt`` -- no third-party dependency.

Stored format: ``scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>``. scrypt is a strong,
memory-hard KDF shipped in the standard library, so this avoids adding bcrypt or
argon2 to deploy. If you prefer bcrypt/argon2 later, swap the two functions
below -- callers only depend on ``hash_password`` / ``verify_password``.

Never store raw passwords; only the derived hash string is persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# Cost parameters. memory ~= 128 * N * r * p bytes (here ~16 MiB).
_N = 16384
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str, *, n: int = _N, r: int = _R, p: int = _P) -> str:
    """Return a self-describing scrypt hash string for ``password``."""
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify ``password`` against a stored scrypt hash.

    Returns ``False`` for any malformed or non-scrypt stored value rather than
    raising, so callers can treat it as a simple boolean check.
    """
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    if not expected:
        return False
    try:
        dk = hashlib.scrypt(
            (password or "").encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(dk, expected)
