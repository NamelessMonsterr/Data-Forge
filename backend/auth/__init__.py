"""Backend-owned authentication and per-user authorization.

The core (passwords, store, service, ownership) is pure stdlib so it is fully
unit-testable without a web framework. The FastAPI cookie adapter lives in
``backend.auth.web`` and is imported separately (it lazily imports FastAPI),
mirroring the pattern in ``backend.app.security``.

Scope (v1): email+password accounts, register/login/logout/me, HTTP-only secure
cookie sessions, and per-user ownership checks. Encrypted provider-key vault and
team/workspace permissions are intentionally deferred.
"""

from .passwords import hash_password, verify_password
from .store import AuthStore, SessionRecord, UserRecord
from .service import (
    AuthError,
    AuthService,
    EmailAlreadyExists,
    InvalidCredentials,
    InvalidEmail,
    LoginResult,
    MIN_PASSWORD_LENGTH,
    User,
    WeakPassword,
    normalize_email,
)
from .ownership import (
    PermissionDenied,
    assert_owner,
    can_access,
    filter_owned,
    is_admin,
    owner_of,
)

__all__ = [
    "hash_password",
    "verify_password",
    "AuthStore",
    "UserRecord",
    "SessionRecord",
    "AuthService",
    "User",
    "LoginResult",
    "AuthError",
    "InvalidEmail",
    "WeakPassword",
    "EmailAlreadyExists",
    "InvalidCredentials",
    "normalize_email",
    "MIN_PASSWORD_LENGTH",
    "PermissionDenied",
    "assert_owner",
    "can_access",
    "filter_owned",
    "is_admin",
    "owner_of",
]
