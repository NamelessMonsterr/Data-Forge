"""Per-user provider-key vault.

Encrypts provider API keys/secrets with ``SecretBox`` before persistence, scopes
every operation to the calling user, and never returns decrypted secrets through
status/list APIs. Only ``get_secrets`` decrypts -- and that is for backend use
(e.g. building an ``LLMConfig`` for a live request), never exposed over HTTP.

Ciphertext is bound to its ``user_id:provider:field`` via AAD, so a stored blob
cannot be replayed into another user's or provider's row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .crypto import SecretBox
from .store import ProviderCredentialRecord, VaultStore


class VaultError(Exception):
    """Base class for vault service errors."""


class UnknownProvider(VaultError):
    """Raised when a provider is not in the configured allowlist."""


class MissingApiKey(VaultError):
    """Raised when a required API key is blank."""


class MissingSecret(VaultError):
    """Raised when a provider requires a secret that is blank."""


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    requires_secret: bool = False
    api_key_label: str = "API key"
    secret_label: Optional[str] = None


DEFAULT_PROVIDERS: Dict[str, ProviderSpec] = {
    "nvidia": ProviderSpec("nvidia", "NVIDIA", api_key_label="API key"),
    "openai": ProviderSpec("openai", "OpenAI", api_key_label="API key"),
    "huggingface": ProviderSpec("huggingface", "HuggingFace", api_key_label="Access token"),
    "kaggle": ProviderSpec(
        "kaggle", "Kaggle", requires_secret=True,
        api_key_label="Username", secret_label="API key",
    ),
}

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    label: str
    configured: bool
    requires_secret: bool
    has_secret: bool
    api_key_label: str
    secret_label: Optional[str]
    updated_at: Optional[str]

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "label": self.label,
            "configured": self.configured,
            "requires_secret": self.requires_secret,
            "has_secret": self.has_secret,
            "api_key_label": self.api_key_label,
            "secret_label": self.secret_label,
            "updated_at": self.updated_at,
        }


def _uid(user) -> str:
    uid = getattr(user, "id", None)
    if not uid:
        raise VaultError("a valid authenticated user is required")
    return uid


class ProviderVault:
    """User-scoped, encrypted store of provider credentials."""

    def __init__(self, store: VaultStore, box: SecretBox, providers=None) -> None:
        self.store = store
        self.box = box
        self.providers = providers or DEFAULT_PROVIDERS

    def _spec(self, provider: str) -> ProviderSpec:
        key = (provider or "").strip().lower()
        if not _PROVIDER_RE.match(key) or key not in self.providers:
            raise UnknownProvider(f"unknown provider: {provider!r}")
        return self.providers[key]

    @staticmethod
    def _aad(user_id: str, provider: str, field: str) -> bytes:
        return f"{user_id}:{provider}:{field}".encode("utf-8")

    def set_credential(self, user, provider, api_key, secret=None) -> ProviderStatus:
        uid = _uid(user)
        spec = self._spec(provider)
        api_key = (api_key or "").strip()
        if not api_key:
            raise MissingApiKey(f"{spec.label}: {spec.api_key_label} is required")
        secret = (secret or "").strip() or None
        if spec.requires_secret and not secret:
            raise MissingSecret(
                f"{spec.label}: {spec.secret_label or 'secret'} is required"
            )
        enc_key = self.box.encrypt(api_key, aad=self._aad(uid, spec.name, "api_key"))
        enc_secret = (
            self.box.encrypt(secret, aad=self._aad(uid, spec.name, "secret"))
            if secret is not None
            else None
        )
        rec = self.store.upsert(uid, spec.name, enc_key, enc_secret)
        return self._status_from_record(spec, rec)

    def get_secrets(self, user, provider) -> Optional[Dict[str, Optional[str]]]:
        """Decrypt credentials for BACKEND use only. Never expose over HTTP."""
        uid = _uid(user)
        spec = self._spec(provider)
        rec = self.store.get(uid, spec.name)
        if rec is None:
            return None
        api_key = self.box.decrypt(
            rec.encrypted_api_key, aad=self._aad(uid, spec.name, "api_key")
        )
        secret = (
            self.box.decrypt(rec.encrypted_secret, aad=self._aad(uid, spec.name, "secret"))
            if rec.encrypted_secret
            else None
        )
        return {"api_key": api_key, "secret": secret}

    def delete_credential(self, user, provider) -> bool:
        uid = _uid(user)
        spec = self._spec(provider)
        return self.store.delete(uid, spec.name)

    def status(self, user, provider) -> ProviderStatus:
        uid = _uid(user)
        spec = self._spec(provider)
        return self._status_from_record(spec, self.store.get(uid, spec.name))

    def list_status(self, user) -> List[ProviderStatus]:
        uid = _uid(user)
        configured = {r.provider: r for r in self.store.list_for_user(uid)}
        return [
            self._status_from_record(spec, configured.get(name))
            for name, spec in self.providers.items()
        ]

    @staticmethod
    def _status_from_record(
        spec: ProviderSpec, rec: Optional[ProviderCredentialRecord]
    ) -> ProviderStatus:
        return ProviderStatus(
            provider=spec.name,
            label=spec.label,
            configured=rec is not None,
            requires_secret=spec.requires_secret,
            has_secret=bool(rec and rec.encrypted_secret),
            api_key_label=spec.api_key_label,
            secret_label=spec.secret_label,
            updated_at=rec.updated_at if rec else None,
        )
