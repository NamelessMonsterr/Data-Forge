"""Teams, per-team roles, and resource sharing.

This adds collaboration on top of the existing per-user ownership model without
changing it. The vault is deliberately *out of scope*: provider credentials stay
strictly per-user and are never shared through a team. Only catalog-style
resources (datasets, projects, runs) can be shared.

Storage mirrors :class:`backend.auth.store.AuthStore` and
:class:`backend.core.repository.SqlRepository`: stdlib ``sqlite3`` with WAL
journaling and explicit ``BEGIN IMMEDIATE`` write transactions, so writes are
transactional and safe under concurrent access.

Three tables:

* ``teams``        -- id, name, owner_id, created_at
* ``team_members`` -- (team_id, user_id) unique, team_role, created_at
* ``resource_shares`` -- (resource_type, resource_id, team_id) unique,
  permission, created_at

``user_id`` is a logical reference to ``auth.users(id)``; like the rest of the
app it crosses the store boundary by id rather than a cross-database FK.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Roles and permissions
# --------------------------------------------------------------------------- #
# Team roles in increasing order of privilege.
TEAM_ROLES: tuple[str, ...] = ("viewer", "member", "admin", "owner")
_ROLE_RANK = {role: rank for rank, role in enumerate(TEAM_ROLES)}

# Share permission levels in increasing order of privilege.
PERMISSIONS: tuple[str, ...] = ("view", "edit")
_PERM_RANK = {perm: rank for rank, perm in enumerate(PERMISSIONS)}

# Roles allowed to administer a team's membership and shares.
_MANAGER_ROLES = ("owner", "admin")


def role_rank(role: Optional[str]) -> int:
    return _ROLE_RANK.get(role or "", -1)


def perm_rank(perm: Optional[str]) -> int:
    return _PERM_RANK.get(perm or "", -1)


def higher_permission(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Return whichever of two permissions grants more access (``None`` = none)."""
    if perm_rank(a) >= perm_rank(b):
        return a if perm_rank(a) >= 0 else None
    return b if perm_rank(b) >= 0 else None


class TeamError(Exception):
    """Base class for team errors."""


class TeamNotFound(TeamError):
    pass


class NotATeamMember(TeamError):
    pass


class InsufficientTeamRole(TeamError):
    pass


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TeamRecord:
    id: str
    name: str
    owner_id: str
    created_at: str


@dataclass(frozen=True)
class TeamMemberRecord:
    team_id: str
    user_id: str
    team_role: str
    created_at: str


@dataclass(frozen=True)
class ShareRecord:
    resource_type: str
    resource_id: str
    team_id: str
    permission: str
    created_at: str


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class TeamStore:
    """Transactional SQLite store for teams, membership, and shares."""

    def __init__(self, path: Path | str = "tmp/dataforge_teams.db") -> None:
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
                    CREATE TABLE IF NOT EXISTS teams (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        owner_id TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS team_members (
                        team_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        team_role TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (team_id, user_id),
                        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS resource_shares (
                        resource_type TEXT NOT NULL,
                        resource_id TEXT NOT NULL,
                        team_id TEXT NOT NULL,
                        permission TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (resource_type, resource_id, team_id),
                        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_members_user ON team_members(user_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_shares_resource "
                    "ON resource_shares(resource_type, resource_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_shares_team ON resource_shares(team_id)"
                )
            finally:
                conn.close()

    def _write(self, op: Callable[[sqlite3.Connection], object]) -> object:
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

    # -- teams ----------------------------------------------------------- #
    def create_team(self, name: str, owner_id: str) -> TeamRecord:
        """Create a team and enroll ``owner_id`` as its ``owner`` member."""
        rec = TeamRecord(
            id=f"team-{uuid4().hex[:16]}",
            name=name,
            owner_id=owner_id,
            created_at=_utc_now_iso(),
        )
        member = TeamMemberRecord(
            team_id=rec.id,
            user_id=owner_id,
            team_role="owner",
            created_at=rec.created_at,
        )

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO teams (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
                (rec.id, rec.name, rec.owner_id, rec.created_at),
            )
            conn.execute(
                "INSERT INTO team_members (team_id, user_id, team_role, created_at) "
                "VALUES (?, ?, ?, ?)",
                (member.team_id, member.user_id, member.team_role, member.created_at),
            )

        self._write(_op)
        return rec

    def get_team(self, team_id: str) -> Optional[TeamRecord]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            return self._row_to_team(row) if row else None
        finally:
            conn.close()

    def delete_team(self, team_id: str) -> None:
        # ON DELETE CASCADE clears members and shares.
        self._write(lambda conn: conn.execute("DELETE FROM teams WHERE id = ?", (team_id,)))

    def list_teams_for_user(self, user_id: str) -> List[TeamRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT t.* FROM teams t "
                "JOIN team_members m ON m.team_id = t.id "
                "WHERE m.user_id = ? ORDER BY t.created_at",
                (user_id,),
            ).fetchall()
            return [self._row_to_team(r) for r in rows]
        finally:
            conn.close()

    # -- members --------------------------------------------------------- #
    def add_member(self, team_id: str, user_id: str, team_role: str) -> TeamMemberRecord:
        """Add or update a member's role (idempotent upsert)."""
        if team_role not in TEAM_ROLES:
            raise ValueError(f"invalid team role: {team_role!r}")
        rec = TeamMemberRecord(
            team_id=team_id,
            user_id=user_id,
            team_role=team_role,
            created_at=_utc_now_iso(),
        )
        self._write(
            lambda conn: conn.execute(
                "INSERT INTO team_members (team_id, user_id, team_role, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(team_id, user_id) DO UPDATE SET team_role=excluded.team_role",
                (rec.team_id, rec.user_id, rec.team_role, rec.created_at),
            )
        )
        return rec

    def remove_member(self, team_id: str, user_id: str) -> None:
        self._write(
            lambda conn: conn.execute(
                "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            )
        )

    def get_membership(self, team_id: str, user_id: str) -> Optional[TeamMemberRecord]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
                (team_id, user_id),
            ).fetchone()
            return self._row_to_member(row) if row else None
        finally:
            conn.close()

    def list_members(self, team_id: str) -> List[TeamMemberRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM team_members WHERE team_id = ? ORDER BY created_at",
                (team_id,),
            ).fetchall()
            return [self._row_to_member(r) for r in rows]
        finally:
            conn.close()

    # -- shares ---------------------------------------------------------- #
    def share_resource(
        self, resource_type: str, resource_id: str, team_id: str, permission: str
    ) -> ShareRecord:
        if permission not in PERMISSIONS:
            raise ValueError(f"invalid permission: {permission!r}")
        rec = ShareRecord(
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            permission=permission,
            created_at=_utc_now_iso(),
        )
        self._write(
            lambda conn: conn.execute(
                "INSERT INTO resource_shares "
                "(resource_type, resource_id, team_id, permission, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(resource_type, resource_id, team_id) "
                "DO UPDATE SET permission=excluded.permission",
                (rec.resource_type, rec.resource_id, rec.team_id, rec.permission, rec.created_at),
            )
        )
        return rec

    def unshare_resource(self, resource_type: str, resource_id: str, team_id: str) -> None:
        self._write(
            lambda conn: conn.execute(
                "DELETE FROM resource_shares "
                "WHERE resource_type = ? AND resource_id = ? AND team_id = ?",
                (resource_type, resource_id, team_id),
            )
        )

    def list_shares_for_resource(
        self, resource_type: str, resource_id: str
    ) -> List[ShareRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM resource_shares "
                "WHERE resource_type = ? AND resource_id = ?",
                (resource_type, resource_id),
            ).fetchall()
            return [self._row_to_share(r) for r in rows]
        finally:
            conn.close()

    def list_shares_for_team(self, team_id: str) -> List[ShareRecord]:
        """Return all resources shared with a team."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM resource_shares WHERE team_id = ? "
                "ORDER BY created_at",
                (team_id,),
            ).fetchall()
            return [self._row_to_share(r) for r in rows]
        finally:
            conn.close()

    def list_shared_resource_ids(
        self, resource_type: str, user_id: str
    ) -> dict[str, str]:
        """Map resource_id -> best permission for resources shared with ``user_id``
        via any team they belong to."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT s.resource_id AS resource_id, s.permission AS permission, "
                "m.team_role AS team_role "
                "FROM resource_shares s "
                "JOIN team_members m ON m.team_id = s.team_id "
                "WHERE s.resource_type = ? AND m.user_id = ?",
                (resource_type, user_id),
            ).fetchall()
            out: dict[str, str] = {}
            for r in rows:
                eff = _effective_permission(r["permission"], r["team_role"])
                if eff is None:
                    continue
                out[r["resource_id"]] = higher_permission(out.get(r["resource_id"]), eff)
            return out
        finally:
            conn.close()

    # -- row mappers ----------------------------------------------------- #
    @staticmethod
    def _row_to_team(row: sqlite3.Row) -> TeamRecord:
        return TeamRecord(
            id=row["id"], name=row["name"], owner_id=row["owner_id"], created_at=row["created_at"]
        )

    @staticmethod
    def _row_to_member(row: sqlite3.Row) -> TeamMemberRecord:
        return TeamMemberRecord(
            team_id=row["team_id"],
            user_id=row["user_id"],
            team_role=row["team_role"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_share(row: sqlite3.Row) -> ShareRecord:
        return ShareRecord(
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            team_id=row["team_id"],
            permission=row["permission"],
            created_at=row["created_at"],
        )


def _effective_permission(share_permission: str, team_role: str) -> Optional[str]:
    """Combine a share's permission with a member's role cap.

    A ``viewer`` is capped at ``view`` even if the share grants ``edit``.
    ``member``/``admin``/``owner`` may use the full share permission.
    """
    if role_rank(team_role) < 0:
        return None
    if team_role == "viewer":
        return "view"
    return share_permission


# --------------------------------------------------------------------------- #
# Service: thin orchestration + management-permission checks
# --------------------------------------------------------------------------- #
class TeamService:
    """Orchestration over :class:`TeamStore` with management guards.

    Global admins (``user.role == 'admin'``) may manage any team.
    """

    def __init__(self, store: TeamStore) -> None:
        self.store = store

    # -- helpers --------------------------------------------------------- #
    @staticmethod
    def _is_global_admin(user: object) -> bool:
        return getattr(user, "role", None) == "admin"

    def _require_manager(self, team_id: str, user: object) -> None:
        if self._is_global_admin(user):
            return
        membership = self.store.get_membership(team_id, getattr(user, "id", None))
        if membership is None:
            raise NotATeamMember("caller is not a member of this team")
        if membership.team_role not in _MANAGER_ROLES:
            raise InsufficientTeamRole("requires team owner or admin")

    # -- team lifecycle -------------------------------------------------- #
    def create_team(self, name: str, user: object) -> TeamRecord:
        return self.store.create_team(name, getattr(user, "id", None))

    def delete_team(self, team_id: str, user: object) -> None:
        team = self.store.get_team(team_id)
        if team is None:
            raise TeamNotFound(team_id)
        # Only the team owner or a global admin may delete a team.
        if not self._is_global_admin(user) and team.owner_id != getattr(user, "id", None):
            raise InsufficientTeamRole("only the team owner may delete the team")
        self.store.delete_team(team_id)

    def list_teams_for_user(self, user: object) -> List[TeamRecord]:
        return self.store.list_teams_for_user(getattr(user, "id", None))

    # -- membership ------------------------------------------------------ #
    def add_member(
        self, team_id: str, target_user_id: str, team_role: str, user: object
    ) -> TeamMemberRecord:
        if self.store.get_team(team_id) is None:
            raise TeamNotFound(team_id)
        self._require_manager(team_id, user)
        return self.store.add_member(team_id, target_user_id, team_role)

    def remove_member(self, team_id: str, target_user_id: str, user: object) -> None:
        team = self.store.get_team(team_id)
        if team is None:
            raise TeamNotFound(team_id)
        self._require_manager(team_id, user)
        # The team owner cannot be removed (delete the team instead).
        if target_user_id == team.owner_id:
            raise InsufficientTeamRole("cannot remove the team owner")
        self.store.remove_member(team_id, target_user_id)

    def list_members(self, team_id: str, user: object) -> List[TeamMemberRecord]:
        if self.store.get_team(team_id) is None:
            raise TeamNotFound(team_id)
        if not self._is_global_admin(user):
            if self.store.get_membership(team_id, getattr(user, "id", None)) is None:
                raise NotATeamMember("caller is not a member of this team")
        return self.store.list_members(team_id)

    # -- sharing --------------------------------------------------------- #
    def share_resource(
        self,
        resource_type: str,
        resource_id: str,
        team_id: str,
        permission: str,
        user: object,
    ) -> ShareRecord:
        if self.store.get_team(team_id) is None:
            raise TeamNotFound(team_id)
        self._require_manager(team_id, user)
        return self.store.share_resource(resource_type, resource_id, team_id, permission)

    def unshare_resource(
        self, resource_type: str, resource_id: str, team_id: str, user: object
    ) -> None:
        if self.store.get_team(team_id) is None:
            raise TeamNotFound(team_id)
        self._require_manager(team_id, user)
        self.store.unshare_resource(resource_type, resource_id, team_id)

    def list_shares(self, team_id: str, user: object) -> List[ShareRecord]:
        """List resources shared to a team visible to any team member."""
        if self.store.get_team(team_id) is None:
            raise TeamNotFound(team_id)
        if not self._is_global_admin(user):
            if self.store.get_membership(team_id, getattr(user, "id", None)) is None:
                raise NotATeamMember("caller is not a member of this team")
        return self.store.list_shares_for_team(team_id)

    # -- access resolution ---------------------------------------------- #
    def team_permission_for(
        self, resource_type: str, resource_id: str, user: object
    ) -> Optional[str]:
        """Best team-derived permission (``'edit'``/``'view'``/``None``) the
        ``user`` has on a resource through any team it shares."""
        uid = getattr(user, "id", None)
        if uid is None:
            return None
        best: Optional[str] = None
        for share in self.store.list_shares_for_resource(resource_type, resource_id):
            membership = self.store.get_membership(share.team_id, uid)
            if membership is None:
                continue
            eff = _effective_permission(share.permission, membership.team_role)
            best = higher_permission(best, eff)
        return best

    def shared_permissions(self, resource_type: str, user: object) -> dict[str, str]:
        """resource_id -> best permission for everything shared to ``user``."""
        uid = getattr(user, "id", None)
        if uid is None:
            return {}
        return self.store.list_shared_resource_ids(resource_type, uid)
