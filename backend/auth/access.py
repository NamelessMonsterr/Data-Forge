"""Team-aware access resolution.

This composes the existing per-user :mod:`backend.auth.ownership` rules with the
team sharing model in :mod:`backend.auth.teams`. It does not modify ownership;
it *widens* access so that, in addition to owners and global admins, members of
a team that a resource has been shared with may access it -- read-only for a
``view`` share (or any ``viewer`` member) and read/write for an ``edit`` share.

Resources are addressed by ``(resource_type, resource_id)``:

* ``"dataset"`` -> ``DatasetCatalogRecord.dataset_id``
* ``"project"`` -> ``ProjectRecord.project_id``
* ``"run"``     -> ``RunRecord.task_id``

Usage in a route handler::

    from backend.auth.access import assert_can, visible_records

    ds = repo.get_dataset(dataset_id)
    assert_can(ds, "dataset", "dataset_id", user, teams, need="view")

    return visible_records(
        repo.list_datasets(), "dataset", "dataset_id", user, teams,
    )

The vault is intentionally not addressable here: provider credentials stay
strictly per-user and are never reachable through team sharing.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .ownership import PermissionDenied, is_admin, owner_of
from .teams import TeamService, perm_rank

# Resource types that may be shared with a team. The vault is deliberately
# excluded.
SHAREABLE_RESOURCE_TYPES = ("dataset", "project", "run")


def _record_id(record: object, id_field: str) -> Optional[str]:
    if isinstance(record, dict):
        return record.get(id_field)
    return getattr(record, id_field, None)


def effective_permission(
    record: object,
    resource_type: str,
    id_field: str,
    user: object,
    teams: Optional[TeamService],
) -> Optional[str]:
    """Return the user's permission on a record: ``'edit'``, ``'view'`` or ``None``.

    * Global admins and the resource owner get ``'edit'``.
    * Otherwise the best team-derived permission (if any) is returned.
    """
    if user is None:
        return None
    if is_admin(user):
        return "edit"
    if owner_of(record) == getattr(user, "id", None) and owner_of(record) is not None:
        return "edit"
    if teams is None:
        return None
    rid = _record_id(record, id_field)
    if rid is None:
        return None
    return teams.team_permission_for(resource_type, rid, user)


def can_access(
    record: object,
    resource_type: str,
    id_field: str,
    user: object,
    teams: Optional[TeamService],
    *,
    need: str = "view",
) -> bool:
    """True if ``user`` has at least ``need`` (``'view'``/``'edit'``) on ``record``."""
    have = effective_permission(record, resource_type, id_field, user, teams)
    if have is None:
        return False
    return perm_rank(have) >= perm_rank(need)


def assert_can(
    record: object,
    resource_type: str,
    id_field: str,
    user: object,
    teams: Optional[TeamService],
    *,
    need: str = "view",
) -> object:
    """Return ``record`` if accessible at ``need``, else raise ``PermissionDenied``."""
    if not can_access(record, resource_type, id_field, user, teams, need=need):
        raise PermissionDenied(
            f"{need} access to {resource_type} denied for current user"
        )
    return record


def visible_records(
    records: Iterable,
    resource_type: str,
    id_field: str,
    user: object,
    teams: Optional[TeamService],
    *,
    need: str = "view",
) -> List:
    """Filter an iterable of records to those the user can access at ``need``.

    Owned + admin rows are included directly; team-shared rows are resolved in a
    single batched lookup to avoid a per-row query.
    """
    records = list(records)
    if user is None:
        return []
    if is_admin(user):
        return records
    uid = getattr(user, "id", None)
    shared: dict[str, str] = {}
    if teams is not None:
        shared = teams.shared_permissions(resource_type, user)
    out: List = []
    for r in records:
        if owner_of(r) == uid and uid is not None:
            out.append(r)
            continue
        rid = _record_id(r, id_field)
        have = shared.get(rid) if rid is not None else None
        if have is not None and perm_rank(have) >= perm_rank(need):
            out.append(r)
    return out
