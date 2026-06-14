"""SQLite-backed storage for per-user, encrypted provider credentials.

One row per ``(user_id, provider)``; only ciphertext is persisted -- never the
raw key or secret. Mirrors the WAL + ``BEGIN IMMEDIATE`` patterns in
``backend.auth.store.AuthStore``. Stdlib-only (``sqlite3``).

The vault uses its own database file by default and does not declare a foreign
key to ``users`` (which lives in a separate auth database). Call
``delete_user_credentials`` if you remove a user.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProviderCredentialRecord:
    id: str
    user_id: str
    provider: str
    encrypted_api_key: str
    encrypted_secret: Optional[str]
    created_at: str
    updated_at: str


class VaultStore:
    """Transactional SQLite store for ``provider_credentials``."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.getenv("DATAFORGE_VAULT_DB", "tmp/dataforge_vault.db"))
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
                    CREATE TABLE IF NOT EXISTS provider_credentials (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        encrypted_api_key TEXT NOT NULL,
                        encrypted_secret TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(user_id, provider)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_provcred_user "
                    "ON provider_credentials(user_id)"
                )
            finally:
                conn.close()

    def _write(self, op):
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

    def upsert(
        self,
        user_id: str,
        provider: str,
        encrypted_api_key: str,
        encrypted_secret: Optional[str],
    ) -> ProviderCredentialRecord:
        now = _utc_now_iso()

        def op(conn):
            existing = conn.execute(
                "SELECT id, created_at FROM provider_credentials "
                "WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE provider_credentials SET encrypted_api_key = ?, "
                    "encrypted_secret = ?, updated_at = ? "
                    "WHERE user_id = ? AND provider = ?",
                    (encrypted_api_key, encrypted_secret, now, user_id, provider),
                )
                return ProviderCredentialRecord(
                    id=existing["id"],
                    user_id=user_id,
                    provider=provider,
                    encrypted_api_key=encrypted_api_key,
                    encrypted_secret=encrypted_secret,
                    created_at=existing["created_at"],
                    updated_at=now,
                )
            rec_id = f"cred-{uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO provider_credentials "
                "(id, user_id, provider, encrypted_api_key, encrypted_secret, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec_id, user_id, provider, encrypted_api_key, encrypted_secret, now, now),
            )
            return ProviderCredentialRecord(
                id=rec_id,
                user_id=user_id,
                provider=provider,
                encrypted_api_key=encrypted_api_key,
                encrypted_secret=encrypted_secret,
                created_at=now,
                updated_at=now,
            )

        return self._write(op)

    def get(self, user_id: str, provider: str) -> Optional[ProviderCredentialRecord]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM provider_credentials WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            ).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def list_for_user(self, user_id: str) -> List[ProviderCredentialRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM provider_credentials WHERE user_id = ? ORDER BY provider",
                (user_id,),
            ).fetchall()
            return [self._row(r) for r in rows]
        finally:
            conn.close()

    def delete(self, user_id: str, provider: str) -> bool:
        def op(conn):
            cur = conn.execute(
                "DELETE FROM provider_credentials WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            )
            return cur.rowcount > 0

        return self._write(op)

    def delete_user_credentials(self, user_id: str) -> None:
        self._write(
            lambda conn: conn.execute(
                "DELETE FROM provider_credentials WHERE user_id = ?", (user_id,)
            )
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> ProviderCredentialRecord:
        return ProviderCredentialRecord(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            encrypted_api_key=row["encrypted_api_key"],
            encrypted_secret=row["encrypted_secret"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
