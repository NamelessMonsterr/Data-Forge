"""Authenticated symmetric encryption for provider secrets -- stdlib only.

The vault must never store provider API keys in plaintext and must never return
decrypted secrets to the frontend. This module gives the backend an
encrypt/decrypt pair built only on ``hashlib``/``hmac`` so the tested core needs
no third-party crypto dependency -- matching ``backend.auth.passwords``, which
uses stdlib scrypt instead of bcrypt/argon2.

Construction (encrypt-then-MAC, all HMAC-SHA256):
  * The master key (env ``DATAFORGE_VAULT_KEY``) is run through HKDF (RFC 5869)
    to derive independent encryption and MAC subkeys.
  * Confidentiality: a keystream is generated as
    ``HMAC(enc_key, nonce || counter)`` per 32-byte block (CTR mode) and XORed
    with the plaintext.
  * Integrity/authenticity: ``tag = HMAC(mac_key, version || nonce || len(aad) ||
    aad || ct)`` is verified in constant time before decryption, so any
    tampering is rejected.
  * Additional authenticated data (AAD) binds each ciphertext to its
    ``user_id:provider:field`` so a stored blob cannot be replayed into another
    user's or provider's row.

Token layout (base64url, no padding): ``version(2) || nonce(16) || tag(32) || ct``.

If you later prefer AES-GCM/Fernet, swap ``SecretBox`` -- callers only depend on
``encrypt``/``decrypt``. That would add a deploy dependency; the default here
keeps the tested core stdlib-only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct

_VERSION = b"v1"
_NONCE_BYTES = 16
_TAG_BYTES = 32
_MIN_KEY_BYTES = 16


class VaultCryptoError(Exception):
    """Base class for vault encryption errors."""


class VaultKeyMissing(VaultCryptoError):
    """Raised when no master key is configured, or it is too weak."""


class InvalidToken(VaultCryptoError):
    """Raised when a token is malformed or fails authentication."""


def _hkdf(master: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 extract-and-expand using HMAC-SHA256."""
    prk = hmac.new(salt, master, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(
            enc_key, nonce + struct.pack(">I", counter), hashlib.sha256
        ).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


class SecretBox:
    """Authenticated encryption keyed by a master secret."""

    def __init__(self, master_key: bytes) -> None:
        if not isinstance(master_key, (bytes, bytearray)) or len(master_key) < _MIN_KEY_BYTES:
            raise VaultKeyMissing(
                f"vault master key must be at least {_MIN_KEY_BYTES} bytes"
            )
        master = bytes(master_key)
        self._enc_key = _hkdf(master, salt=b"dataforge.vault.enc", info=b"enc", length=32)
        self._mac_key = _hkdf(master, salt=b"dataforge.vault.mac", info=b"mac", length=32)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "SecretBox":
        env = env if env is not None else os.environ
        key = (env.get("DATAFORGE_VAULT_KEY") or "").strip()
        if not key:
            raise VaultKeyMissing(
                "DATAFORGE_VAULT_KEY is not set; the provider vault is disabled"
            )
        return cls(key.encode("utf-8"))

    def _tag(self, nonce: bytes, aad: bytes, ct: bytes) -> bytes:
        mac = hmac.new(self._mac_key, digestmod=hashlib.sha256)
        mac.update(_VERSION)
        mac.update(nonce)
        mac.update(struct.pack(">I", len(aad)))
        mac.update(aad)
        mac.update(ct)
        return mac.digest()

    def encrypt(self, plaintext: str, *, aad: bytes = b"") -> str:
        if not isinstance(plaintext, str):
            raise VaultCryptoError("plaintext must be a string")
        data = plaintext.encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ct = _xor(data, _keystream(self._enc_key, nonce, len(data)))
        tag = self._tag(nonce, aad, ct)
        return _b64e(_VERSION + nonce + tag + ct)

    def decrypt(self, token: str, *, aad: bytes = b"") -> str:
        try:
            raw = _b64d(token)
        except (ValueError, TypeError) as exc:
            raise InvalidToken("malformed token") from exc
        if len(raw) < 2 + _NONCE_BYTES + _TAG_BYTES:
            raise InvalidToken("token too short")
        version = raw[:2]
        nonce = raw[2:2 + _NONCE_BYTES]
        tag = raw[2 + _NONCE_BYTES:2 + _NONCE_BYTES + _TAG_BYTES]
        ct = raw[2 + _NONCE_BYTES + _TAG_BYTES:]
        if version != _VERSION:
            raise InvalidToken("unsupported token version")
        if not hmac.compare_digest(tag, self._tag(nonce, aad, ct)):
            raise InvalidToken("authentication failed")
        data = _xor(ct, _keystream(self._enc_key, nonce, len(ct)))
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidToken("invalid plaintext encoding") from exc
