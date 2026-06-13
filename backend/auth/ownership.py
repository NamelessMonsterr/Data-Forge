"""Per-user authorization helpers.

Every data-returning endpoint must answer "does this resource belong to the
current user?". These helpers centralize that check so route handlers stay thin:

    from backend.auth.ownership import assert_owner, filter_owned

    # single resource
    dataset = repo.get_dataset(dataset_id)
    assert_owner(dataset, current_user)        # raises PermissionDenied otherwise

    # list endpoint -> only the caller's rows
    return filter_owned(repo.list_datasets(), current_user)

Works with both dataclass records (``record.user_id``) and dict rows
(``record["user_id"]``). Admins (``role == "admin"``) bypass ownership by default.
"""

from __future__ import annotations

from typing import Iterable, List, Optional


class PermissionDenied(Exception):
    """Raised when a user tries to access a resource they do not own."""


def owner_of(record: object) -> Optional[str]:
    if isinstance(record, dict):
        return record.get("user_id")
    return getattr(record, "user_id", None)


def is_admin(user: object) -> bool:
    return getattr(user, "role", None) == "admin"


def can_access(record: object, user: object, *, allow_admin: bool = True) -> bool:
    if user is None:
        return False
    if allow_admin and is_admin(user):
        return True
    return owner_of(record) == getattr(user, "id", None)


def assert_owner(record: object, user: object, *, allow_admin: bool = True) -> object:
    if not can_access(record, user, allow_admin=allow_admin):
        raise PermissionDenied("resource does not belong to the current user")
    return record


def filter_owned(
    records: Iterable, user: object, *, allow_admin: bool = True
) -> List:
    if user is not None and allow_admin and is_admin(user):
        return list(records)
    uid = getattr(user, "id", None)
    return [r for r in records if owner_of(r) == uid]
