"""Tests for teams, per-team roles, and resource sharing.

Covers the store, the management guards in ``TeamService``, and the team-aware
access layer that composes with the existing per-user ownership rules. Also
pins the invariant that the vault is *not* reachable through team sharing
(provider keys stay strictly per-user).
"""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.auth import access
from backend.auth.ownership import PermissionDenied
from backend.auth.teams import (
    InsufficientTeamRole,
    NotATeamMember,
    TeamService,
    TeamStore,
)


@dataclass(frozen=True)
class FakeUser:
    id: str
    role: str = "user"


@dataclass(frozen=True)
class FakeDataset:
    dataset_id: str
    user_id: str | None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        path = Path(self._tmp.name) / "teams.db"
        self.store = TeamStore(path)
        self.service = TeamService(self.store)
        self.alice = FakeUser("user-alice")
        self.bob = FakeUser("user-bob")
        self.carol = FakeUser("user-carol")
        self.root = FakeUser("user-root", role="admin")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TeamLifecycleTest(_Base):
    def test_default_path_can_come_from_env(self) -> None:
        path = Path(self._tmp.name) / "env-teams.db"
        old = os.environ.get("DATAFORGE_TEAMS_DB")
        os.environ["DATAFORGE_TEAMS_DB"] = str(path)
        try:
            store = TeamStore()
            self.assertEqual(store.path.resolve(), path.resolve())
        finally:
            if old is None:
                os.environ.pop("DATAFORGE_TEAMS_DB", None)
            else:
                os.environ["DATAFORGE_TEAMS_DB"] = old

    def test_creator_becomes_owner_member(self) -> None:
        team = self.service.create_team("Data Team", self.alice)
        membership = self.store.get_membership(team.id, self.alice.id)
        self.assertIsNotNone(membership)
        self.assertEqual(membership.team_role, "owner")
        self.assertEqual(team.owner_id, self.alice.id)

    def test_list_teams_for_user(self) -> None:
        t1 = self.service.create_team("T1", self.alice)
        self.service.create_team("T2", self.bob)
        ids = {t.id for t in self.service.list_teams_for_user(self.alice)}
        self.assertEqual(ids, {t1.id})

    def test_only_owner_or_global_admin_deletes_team(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "admin", self.alice)
        # team admin (not owner) cannot delete
        with self.assertRaises(InsufficientTeamRole):
            self.service.delete_team(team.id, self.bob)
        # global admin can
        self.service.delete_team(team.id, self.root)
        self.assertIsNone(self.store.get_team(team.id))


class MembershipGuardTest(_Base):
    def test_member_cannot_add_members(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "member", self.alice)
        with self.assertRaises(InsufficientTeamRole):
            self.service.add_member(team.id, self.carol.id, "member", self.bob)

    def test_non_member_cannot_manage(self) -> None:
        team = self.service.create_team("T", self.alice)
        with self.assertRaises(NotATeamMember):
            self.service.add_member(team.id, self.carol.id, "member", self.bob)

    def test_admin_can_add_members(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "admin", self.alice)
        self.service.add_member(team.id, self.carol.id, "viewer", self.bob)
        self.assertEqual(
            self.store.get_membership(team.id, self.carol.id).team_role, "viewer"
        )

    def test_cannot_remove_owner(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "admin", self.alice)
        with self.assertRaises(InsufficientTeamRole):
            self.service.remove_member(team.id, self.alice.id, self.bob)

    def test_cannot_demote_owner(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "admin", self.alice)
        with self.assertRaises(InsufficientTeamRole):
            self.service.add_member(team.id, self.alice.id, "member", self.bob)
        self.assertEqual(
            self.store.get_membership(team.id, self.alice.id).team_role, "owner"
        )

    def test_cannot_assign_owner_role_without_transfer(self) -> None:
        team = self.service.create_team("T", self.alice)
        with self.assertRaises(InsufficientTeamRole):
            self.service.add_member(team.id, self.bob.id, "owner", self.alice)
        self.assertIsNone(self.store.get_membership(team.id, self.bob.id))

    def test_role_upsert_is_idempotent(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "viewer", self.alice)
        self.service.add_member(team.id, self.bob.id, "member", self.alice)
        self.assertEqual(
            self.store.get_membership(team.id, self.bob.id).team_role, "member"
        )
        self.assertEqual(len(self.store.list_members(team.id)), 2)


class SharingAccessTest(_Base):
    def _shared_team(self, permission: str, role: str):
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, role, self.alice)
        self.service.share_resource("dataset", "ds-1", team.id, permission, self.alice)
        return team

    def test_owner_has_edit(self) -> None:
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertEqual(
            access.effective_permission(ds, "dataset", "dataset_id", self.alice, self.service),
            "edit",
        )

    def test_unrelated_user_denied(self) -> None:
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertFalse(
            access.can_access(ds, "dataset", "dataset_id", self.carol, self.service, need="view")
        )
        with self.assertRaises(PermissionDenied):
            access.assert_can(ds, "dataset", "dataset_id", self.carol, self.service, need="view")

    def test_edit_share_grants_member_edit(self) -> None:
        self._shared_team("edit", "member")
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertTrue(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="edit")
        )

    def test_view_share_denies_edit(self) -> None:
        self._shared_team("view", "member")
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertTrue(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="view")
        )
        self.assertFalse(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="edit")
        )

    def test_viewer_role_capped_at_view_even_on_edit_share(self) -> None:
        self._shared_team("edit", "viewer")
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertTrue(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="view")
        )
        self.assertFalse(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="edit")
        )

    def test_unshare_revokes_access(self) -> None:
        team = self._shared_team("edit", "member")
        self.service.unshare_resource("dataset", "ds-1", team.id, self.alice)
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertFalse(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="view")
        )

    def test_global_admin_sees_everything(self) -> None:
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertEqual(
            access.effective_permission(ds, "dataset", "dataset_id", self.root, self.service),
            "edit",
        )

    def test_visible_records_batches_owned_and_shared(self) -> None:
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "member", self.alice)
        self.service.share_resource("dataset", "ds-shared", team.id, "view", self.alice)
        records = [
            FakeDataset("ds-own", self.bob.id),       # bob owns
            FakeDataset("ds-shared", self.alice.id),  # shared to bob's team (view)
            FakeDataset("ds-private", self.carol.id),  # bob cannot see
        ]
        visible = access.visible_records(
            records, "dataset", "dataset_id", self.bob, self.service, need="view"
        )
        self.assertEqual({r.dataset_id for r in visible}, {"ds-own", "ds-shared"})
        # need='edit' drops the view-only shared row, keeps owned row.
        editable = access.visible_records(
            records, "dataset", "dataset_id", self.bob, self.service, need="edit"
        )
        self.assertEqual({r.dataset_id for r in editable}, {"ds-own"})

    def test_higher_permission_from_two_teams(self) -> None:
        # ds-1 shared view via team A and edit via team B; bob is in both.
        team_a = self.service.create_team("A", self.alice)
        team_b = self.service.create_team("B", self.alice)
        self.service.add_member(team_a.id, self.bob.id, "member", self.alice)
        self.service.add_member(team_b.id, self.bob.id, "member", self.alice)
        self.service.share_resource("dataset", "ds-1", team_a.id, "view", self.alice)
        self.service.share_resource("dataset", "ds-1", team_b.id, "edit", self.alice)
        ds = FakeDataset("ds-1", self.alice.id)
        self.assertTrue(
            access.can_access(ds, "dataset", "dataset_id", self.bob, self.service, need="edit")
        )


class VaultStaysPrivateTest(_Base):
    def test_vault_is_not_a_shareable_resource_type(self) -> None:
        # The access layer only enumerates dataset/project/run as shareable.
        self.assertNotIn("vault", access.SHAREABLE_RESOURCE_TYPES)
        self.assertNotIn("credential", access.SHAREABLE_RESOURCE_TYPES)
        self.assertEqual(
            set(access.SHAREABLE_RESOURCE_TYPES), {"dataset", "project", "run"}
        )

    def test_sharing_a_dataset_grants_no_vault_visibility(self) -> None:
        # Even with an edit share, team membership exposes no credential surface:
        # there is simply no API on the team layer that returns keys.
        team = self.service.create_team("T", self.alice)
        self.service.add_member(team.id, self.bob.id, "member", self.alice)
        self.service.share_resource("dataset", "ds-1", team.id, "edit", self.alice)
        self.assertFalse(hasattr(self.service, "vault_key_for"))
        self.assertFalse(hasattr(self.store, "get_credential"))


if __name__ == "__main__":
    unittest.main()
