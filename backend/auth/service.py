"""Authentication service: register / login / logout / authenticate.

Pure orchestration over :class:`AuthStore` and the password helpers. The web
layer (cookies, HTTP status) lives in ``backend.auth.web``; this stays
framework-agnostic and fully unit-testable. A pluggable ``clock`` and
``token_factory`` make session expiry deterministic in tests.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .passwords import hash_password, verify_password
from .store import AuthStore, UserRecord

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
DEFAULT_SESSION_TTL = timedelta(days=7)
_VALID_ROLES = ("user", "admin")
# A well-formed but non-matching hash, used to keep login timing uniform whether
# or not the email exists (mitigates user-enumeration via response time).
_DUMMY_HASH = (
    "scrypt$16384$8$1$"
    + "00" * 16
    + "$"
    + "00" * 32
)


class AuthError(Exception):
    """Base class for authentication errors."""


class InvalidEmail(AuthError):
    pass


class WeakPassword(AuthError):
    pass


class EmailAlreadyExists(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


@dataclass(frozen=True)
class User:
    """Public user shape (never carries the password hash)."""

    id: str
    email: str
    role: str
    created_at: str

    @classmethod
    def from_record(cls, rec: UserRecord) -> "User":
        return cls(id=rec.id, email=rec.email, role=rec.role, created_at=rec.created_at)


@dataclass(frozen=True)
class LoginResult:
    user: User
    token: str
    expires_at: str


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        *,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self.store = store
        self.session_ttl = session_ttl
        self._clock = clock
        self._token_factory = token_factory

    def register(self, email: str, password: str, role: str = "user") -> User:
        email = normalize_email(email)
        if not _EMAIL_RE.match(email):
            raise InvalidEmail("invalid email address")
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise WeakPassword(
                f"password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        if role not in _VALID_ROLES:
            role = "user"
        try:
            rec = self.store.create_user(email, hash_password(password), role)
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyExists("email already registered") from exc
        return User.from_record(rec)

    def login(self, email: str, password: str) -> LoginResult:
        email = normalize_email(email)
        rec = self.store.get_user_by_email(email)
        if rec is None:
            # Spend comparable time so missing vs wrong-password are indistinguishable.
            verify_password(password or "", _DUMMY_HASH)
            raise InvalidCredentials("invalid email or password")
        if not verify_password(password or "", rec.password_hash):
            raise InvalidCredentials("invalid email or password")
        now = self._clock()
        expires_at = (now + self.session_ttl).astimezone(timezone.utc).isoformat()
        token = self._token_factory()
        self.store.create_session(token, rec.id, expires_at)
        return LoginResult(user=User.from_record(rec), token=token, expires_at=expires_at)

    def logout(self, token: Optional[str]) -> None:
        if token:
            self.store.delete_session(token)

    def authenticate(self, token: Optional[str]) -> Optional[User]:
        """Resolve a session token to a user, or ``None`` if invalid/expired."""
        if not token:
            return None
        session = self.store.get_session(token)
        if session is None:
            return None
        expires = datetime.fromisoformat(session.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= self._clock():
            self.store.delete_session(token)
            return None
        rec = self.store.get_user_by_id(session.user_id)
        return User.from_record(rec) if rec else None
