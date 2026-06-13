"""Per-user encrypted provider-key vault.

The core (crypto, store, service) is pure stdlib and unit-testable without a web
framework or third-party crypto. The FastAPI adapter lives in
``backend.vault.web`` and lazily imports FastAPI, mirroring ``backend.auth``.

Secrets are encrypted at rest with ``SecretBox`` (HMAC-SHA256 encrypt-then-MAC)
and are never returned to the frontend -- only configured/unconfigured status.
"""

from .crypto import InvalidToken, SecretBox, VaultCryptoError, VaultKeyMissing
from .store import ProviderCredentialRecord, VaultStore
from .service import (
    DEFAULT_PROVIDERS,
    MissingApiKey,
    MissingSecret,
    ProviderSpec,
    ProviderStatus,
    ProviderVault,
    UnknownProvider,
    VaultError,
)

__all__ = [
    "SecretBox",
    "VaultCryptoError",
    "VaultKeyMissing",
    "InvalidToken",
    "VaultStore",
    "ProviderCredentialRecord",
    "ProviderVault",
    "ProviderSpec",
    "ProviderStatus",
    "DEFAULT_PROVIDERS",
    "VaultError",
    "UnknownProvider",
    "MissingApiKey",
    "MissingSecret",
]
