"""SQLite-backed storage for user accounts and login sessions.

Uses the same WAL + ``BEGIN IMMEDIATE`` patterns as
``backend.core.repository.SqlRepository`` so writes are transactional and safe
under concurrent access. Stdlib-only (``sqlite3``). Sessions are server-side:
the cookie carries only an opaque token, and revoking a session is a row delete.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    role: str
    created_at: str


@dataclass(frozen=True)
class SessionRecord:
    token: str
    user_id: str
    created_at: str
    expires_at: str


class AuthStore:
    """Transactional SQLite store for ``users`` and ``sessions``."""

    def __init__(self, path: Path | str = "tmp/dataforge_auth.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'user',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
                )
            finally:
                conn.close()

    def _write(self, op) -> object:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = op(conn)
                conn.execute("COMMIT")
                return result
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    # -- users ----------------------------------------------------------- #
    def create_user(self, email: str, password_hash: str, role: str = "user") -> UserRecord:
        """Insert a user. Raises ``sqlite3.IntegrityError`` on duplicate email."""
        rec = UserRecord(
            id=f"user-{uuid4().hex[:16]}",
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=_utc_now_iso(),
        )
        self._write(
            lambda conn: conn.execute(
                "INSERT INTO users (id, email, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec.id, rec.email, rec.password_hash, rec.role, rec.created_at),
            )
        )
        return rec

    def get_user_by_email(self, email: str) -> UserRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            return self._row_to_user(row) if row else None
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return self._row_to_user(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            role=row["role"],
            created_at=row["created_at"],
        )

    # -- sessions -------------------------------------------------------- #
    def create_session(self, token: str, user_id: str, expires_at: str) -> SessionRecord:
        rec = SessionRecord(
            token=token,
            user_id=user_id,
            created_at=_utc_now_iso(),
            expires_at=expires_at,
        )
        self._write(
            lambda conn: conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (rec.token, rec.user_id, rec.created_at, rec.expires_at),
            )
        )
        return rec

    def get_session(self, token: str) -> SessionRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ?", (token,)
            ).fetchone()
            if not row:
                return None
            return SessionRecord(
                token=row["token"],
                user_id=row["user_id"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
            )
        finally:
            conn.close()

    def delete_session(self, token: str) -> None:
        self._write(lambda conn: conn.execute("DELETE FROM sessions WHERE token = ?", (token,)))

    def delete_user_sessions(self, user_id: str) -> None:
        self._write(lambda conn: conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)))

    def purge_expired(self, now_iso: str) -> None:
        self._write(lambda conn: conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso,)))
