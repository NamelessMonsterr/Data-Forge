import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.auth.passwords import hash_password, verify_password  # noqa: E402
from backend.auth.store import AuthStore  # noqa: E402
from backend.auth.service import (  # noqa: E402
    AuthService,
    EmailAlreadyExists,
    InvalidCredentials,
    InvalidEmail,
    User,
    WeakPassword,
    normalize_email,
)
from backend.auth.ownership import (  # noqa: E402
    PermissionDenied,
    assert_owner,
    can_access,
    filter_owned,
)


def _service(tmp, **kwargs):
    return AuthService(AuthStore(os.path.join(tmp, "auth.db")), **kwargs)


class PasswordTest(unittest.TestCase):
    def test_hash_is_not_plaintext(self):
        h = hash_password("hunter2pass")
        self.assertNotIn("hunter2pass", h)
        self.assertTrue(h.startswith("scrypt$"))

    def test_verify_correct(self):
        self.assertTrue(verify_password("hunter2pass", hash_password("hunter2pass")))

    def test_verify_wrong(self):
        self.assertFalse(verify_password("nope", hash_password("hunter2pass")))

    def test_salts_differ_per_hash(self):
        self.assertNotEqual(hash_password("samePassword1"), hash_password("samePassword1"))

    def test_malformed_returns_false(self):
        self.assertFalse(verify_password("x", "not-a-valid-hash"))
        self.assertFalse(verify_password("x", "bcrypt$abc"))


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _service(self.tmp)

    def test_register_creates_user(self):
        user = self.svc.register("Alice@Example.com", "supersecret")
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.role, "user")
        self.assertTrue(user.id.startswith("user-"))

    def test_duplicate_email_rejected(self):
        self.svc.register("a@b.com", "supersecret")
        with self.assertRaises(EmailAlreadyExists):
            self.svc.register("A@B.com", "supersecret")

    def test_invalid_email_rejected(self):
        with self.assertRaises(InvalidEmail):
            self.svc.register("notanemail", "supersecret")

    def test_weak_password_rejected(self):
        with self.assertRaises(WeakPassword):
            self.svc.register("a@b.com", "short")

    def test_admin_role_allowed(self):
        user = self.svc.register("admin@b.com", "supersecret", role="admin")
        self.assertEqual(user.role, "admin")

    def test_unknown_role_defaults_to_user(self):
        user = self.svc.register("a@b.com", "supersecret", role="superadmin")
        self.assertEqual(user.role, "user")

    def test_normalize_email(self):
        self.assertEqual(normalize_email("  Foo@Bar.COM "), "foo@bar.com")


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = _service(self.tmp)
        self.svc.register("a@b.com", "supersecret")

    def test_login_success(self):
        result = self.svc.login("A@B.com", "supersecret")
        self.assertTrue(result.token)
        self.assertEqual(result.user.email, "a@b.com")

    def test_login_wrong_password(self):
        with self.assertRaises(InvalidCredentials):
            self.svc.login("a@b.com", "wrongpassword")

    def test_login_unknown_email(self):
        with self.assertRaises(InvalidCredentials):
            self.svc.login("ghost@b.com", "supersecret")


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        self.svc = _service(
            self.tmp, clock=lambda: self.now[0], session_ttl=timedelta(hours=1)
        )
        self.svc.register("a@b.com", "supersecret")

    def test_authenticate_valid_token(self):
        result = self.svc.login("a@b.com", "supersecret")
        user = self.svc.authenticate(result.token)
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "a@b.com")

    def test_authenticate_invalid_token(self):
        self.assertIsNone(self.svc.authenticate("bogus-token"))
        self.assertIsNone(self.svc.authenticate(None))

    def test_logout_invalidates_session(self):
        result = self.svc.login("a@b.com", "supersecret")
        self.svc.logout(result.token)
        self.assertIsNone(self.svc.authenticate(result.token))

    def test_expired_session_rejected(self):
        result = self.svc.login("a@b.com", "supersecret")
        self.now[0] = self.now[0] + timedelta(hours=2)
        self.assertIsNone(self.svc.authenticate(result.token))


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        self.alice = User(id="user-alice", email="a@b.com", role="user", created_at="t")
        self.bob = User(id="user-bob", email="b@b.com", role="user", created_at="t")
        self.admin = User(id="user-admin", email="admin@b.com", role="admin", created_at="t")

    def test_owner_can_access(self):
        record = {"user_id": "user-alice"}
        self.assertTrue(can_access(record, self.alice))
        self.assertIs(assert_owner(record, self.alice), record)

    def test_non_owner_denied(self):
        record = {"user_id": "user-alice"}
        self.assertFalse(can_access(record, self.bob))
        with self.assertRaises(PermissionDenied):
            assert_owner(record, self.bob)

    def test_admin_bypass(self):
        self.assertTrue(can_access({"user_id": "user-alice"}, self.admin))

    def test_none_user_denied(self):
        self.assertFalse(can_access({"user_id": "user-alice"}, None))

    def test_filter_owned_scopes_list(self):
        records = [
            {"user_id": "user-alice", "x": 1},
            {"user_id": "user-bob", "x": 2},
            {"user_id": "user-alice", "x": 3},
        ]
        self.assertEqual([r["x"] for r in filter_owned(records, self.alice)], [1, 3])

    def test_filter_owned_admin_sees_all(self):
        records = [{"user_id": "user-alice"}, {"user_id": "user-bob"}]
        self.assertEqual(len(filter_owned(records, self.admin)), 2)


@unittest.skipIf(
    importlib.util.find_spec("fastapi") is None, "fastapi not installed"
)
class AuthRouterTest(unittest.TestCase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.auth.web import build_auth_router

        os.environ["DATAFORGE_COOKIE_SECURE"] = "false"
        tmp = tempfile.mkdtemp()
        svc = AuthService(AuthStore(os.path.join(tmp, "auth.db")))
        app = FastAPI()
        app.include_router(build_auth_router(svc))
        return TestClient(app)

    def test_register_login_me_logout_flow(self):
        client = self._client()
        r = client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret"})
        self.assertEqual(r.status_code, 201)
        r = client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})
        self.assertEqual(r.status_code, 200)
        r = client.get("/auth/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["email"], "a@b.com")
        r = client.post("/auth/logout")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/auth/me").status_code, 401)

    def test_me_requires_auth(self):
        self.assertEqual(self._client().get("/auth/me").status_code, 401)

    def test_duplicate_register_conflict(self):
        client = self._client()
        client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret"})
        r = client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret"})
        self.assertEqual(r.status_code, 409)


if __name__ == "__main__":
    unittest.main()
