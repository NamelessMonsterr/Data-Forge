import importlib.util
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.auth.service import User  # noqa: E402
from backend.vault.crypto import (  # noqa: E402
    InvalidToken,
    SecretBox,
    VaultKeyMissing,
)
from backend.vault.store import VaultStore  # noqa: E402
from backend.vault.service import (  # noqa: E402
    MissingApiKey,
    MissingSecret,
    ProviderVault,
    UnknownProvider,
)

_MASTER = b"unit-test-master-key-which-is-long-enough"
_PLAINTEXT_KEY = "nvapi-PLAINTEXT-KEY-do-not-leak"


def _user(uid="user-alice", role="user"):
    return User(id=uid, email=uid + "@b.com", role=role, created_at="t")


def _vault(tmp, box=None):
    return ProviderVault(VaultStore(os.path.join(tmp, "vault.db")), box or SecretBox(_MASTER))


class CryptoTest(unittest.TestCase):
    def setUp(self):
        self.box = SecretBox(_MASTER)

    def test_round_trip(self):
        token = self.box.encrypt(_PLAINTEXT_KEY)
        self.assertEqual(self.box.decrypt(token), _PLAINTEXT_KEY)

    def test_ciphertext_is_not_plaintext(self):
        self.assertNotIn(_PLAINTEXT_KEY, self.box.encrypt(_PLAINTEXT_KEY))

    def test_unique_nonce_per_encrypt(self):
        self.assertNotEqual(self.box.encrypt("same"), self.box.encrypt("same"))

    def test_tamper_detected(self):
        token = self.box.encrypt(_PLAINTEXT_KEY)
        bad = token[:-1] + ("A" if token[-1] != "A" else "B")
        with self.assertRaises(InvalidToken):
            self.box.decrypt(bad)

    def test_wrong_key_fails(self):
        token = self.box.encrypt(_PLAINTEXT_KEY)
        other = SecretBox(b"a-totally-different-master-key-value")
        with self.assertRaises(InvalidToken):
            other.decrypt(token)

    def test_aad_binding(self):
        token = self.box.encrypt(_PLAINTEXT_KEY, aad=b"user-alice:nvidia:api_key")
        self.assertEqual(
            self.box.decrypt(token, aad=b"user-alice:nvidia:api_key"), _PLAINTEXT_KEY
        )
        with self.assertRaises(InvalidToken):
            self.box.decrypt(token, aad=b"user-bob:nvidia:api_key")

    def test_weak_key_rejected(self):
        with self.assertRaises(VaultKeyMissing):
            SecretBox(b"short")

    def test_from_env_missing(self):
        with self.assertRaises(VaultKeyMissing):
            SecretBox.from_env({})

    def test_from_env_present(self):
        box = SecretBox.from_env({"DATAFORGE_VAULT_KEY": "this-is-a-long-enough-key"})
        self.assertEqual(box.decrypt(box.encrypt("x")), "x")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = VaultStore(os.path.join(self.tmp, "vault.db"))

    def test_default_path_can_come_from_env(self):
        path = os.path.join(self.tmp, "env-vault.db")
        old = os.environ.get("DATAFORGE_VAULT_DB")
        os.environ["DATAFORGE_VAULT_DB"] = path
        try:
            store = VaultStore()
            self.assertEqual(os.path.abspath(str(store.path)), os.path.abspath(path))
        finally:
            if old is None:
                os.environ.pop("DATAFORGE_VAULT_DB", None)
            else:
                os.environ["DATAFORGE_VAULT_DB"] = old

    def test_insert_and_get(self):
        self.store.upsert("user-alice", "nvidia", "ENC1", None)
        rec = self.store.get("user-alice", "nvidia")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.encrypted_api_key, "ENC1")

    def test_upsert_updates_in_place(self):
        r1 = self.store.upsert("user-alice", "nvidia", "ENC1", None)
        r2 = self.store.upsert("user-alice", "nvidia", "ENC2", None)
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(r2.encrypted_api_key, "ENC2")
        self.assertEqual(r1.created_at, r2.created_at)
        self.assertEqual(len(self.store.list_for_user("user-alice")), 1)

    def test_scoped_get(self):
        self.store.upsert("user-alice", "nvidia", "ENC1", None)
        self.assertIsNone(self.store.get("user-bob", "nvidia"))

    def test_delete(self):
        self.store.upsert("user-alice", "nvidia", "ENC1", None)
        self.assertTrue(self.store.delete("user-alice", "nvidia"))
        self.assertFalse(self.store.delete("user-alice", "nvidia"))


class VaultServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault = _vault(self.tmp)
        self.alice = _user("user-alice")
        self.bob = _user("user-bob")

    def test_set_stores_encrypted(self):
        self.vault.set_credential(self.alice, "nvidia", _PLAINTEXT_KEY)
        rec = self.vault.store.get("user-alice", "nvidia")
        self.assertNotIn(_PLAINTEXT_KEY, rec.encrypted_api_key)
        creds = self.vault.get_secrets(self.alice, "nvidia")
        self.assertEqual(creds["api_key"], _PLAINTEXT_KEY)

    def test_status_reports_configured(self):
        self.vault.set_credential(self.alice, "nvidia", "k-value")
        statuses = {s.provider: s for s in self.vault.list_status(self.alice)}
        self.assertTrue(statuses["nvidia"].configured)
        self.assertFalse(statuses["openai"].configured)

    def test_no_secret_in_status(self):
        self.vault.set_credential(self.alice, "nvidia", _PLAINTEXT_KEY)
        blob = repr([s.to_dict() for s in self.vault.list_status(self.alice)])
        self.assertNotIn(_PLAINTEXT_KEY, blob)
        blob2 = repr(self.vault.status(self.alice, "nvidia").to_dict())
        self.assertNotIn(_PLAINTEXT_KEY, blob2)

    def test_missing_api_key(self):
        with self.assertRaises(MissingApiKey):
            self.vault.set_credential(self.alice, "nvidia", "   ")

    def test_kaggle_requires_secret(self):
        with self.assertRaises(MissingSecret):
            self.vault.set_credential(self.alice, "kaggle", "my-username")

    def test_kaggle_with_secret(self):
        self.vault.set_credential(self.alice, "kaggle", "my-username", "kaggle-key")
        creds = self.vault.get_secrets(self.alice, "kaggle")
        self.assertEqual(creds["api_key"], "my-username")
        self.assertEqual(creds["secret"], "kaggle-key")

    def test_unknown_provider(self):
        with self.assertRaises(UnknownProvider):
            self.vault.set_credential(self.alice, "bogus", "k")

    def test_delete(self):
        self.vault.set_credential(self.alice, "nvidia", "k-value")
        self.assertTrue(self.vault.delete_credential(self.alice, "nvidia"))
        self.assertFalse(self.vault.status(self.alice, "nvidia").configured)

    def test_ownership_isolation(self):
        self.vault.set_credential(self.alice, "nvidia", "alice-secret-key")
        # Bob cannot read, see, or remove Alice's credential.
        self.assertIsNone(self.vault.get_secrets(self.bob, "nvidia"))
        self.assertFalse(self.vault.delete_credential(self.bob, "nvidia"))
        self.assertFalse(self.vault.status(self.bob, "nvidia").configured)
        # Alice's credential is intact.
        self.assertEqual(
            self.vault.get_secrets(self.alice, "nvidia")["api_key"], "alice-secret-key"
        )


@unittest.skipIf(importlib.util.find_spec("fastapi") is None, "fastapi not installed")
class SettingsRouterTest(unittest.TestCase):
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.auth import AuthService, AuthStore
        from backend.auth.web import build_auth_router, make_current_user_dependency
        from backend.vault.web import build_settings_router

        os.environ["DATAFORGE_COOKIE_SECURE"] = "false"
        tmp = tempfile.mkdtemp()
        auth = AuthService(AuthStore(os.path.join(tmp, "auth.db")))
        vault = ProviderVault(VaultStore(os.path.join(tmp, "vault.db")), SecretBox(_MASTER))
        app = FastAPI()
        app.include_router(build_auth_router(auth))
        app.include_router(build_settings_router(vault, make_current_user_dependency(auth)))
        return TestClient(app)

    def _login(self, client):
        client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret"})
        client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})

    def test_requires_auth(self):
        self.assertEqual(self._client().get("/settings/providers").status_code, 401)

    def test_set_list_delete_flow(self):
        client = self._client()
        self._login(client)
        r = client.post("/settings/providers/nvidia", json={"api_key": _PLAINTEXT_KEY})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["configured"])
        self.assertNotIn(_PLAINTEXT_KEY, r.text)  # raw key never echoed
        r = client.get("/settings/providers")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(_PLAINTEXT_KEY, r.text)
        provs = {p["provider"]: p for p in r.json()["providers"]}
        self.assertTrue(provs["nvidia"]["configured"])
        self.assertFalse(provs["openai"]["configured"])
        r = client.delete("/settings/providers/nvidia")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.delete("/settings/providers/nvidia").status_code, 404)

    def test_unknown_provider_404(self):
        client = self._client()
        self._login(client)
        self.assertEqual(
            client.post("/settings/providers/bogus", json={"api_key": "k"}).status_code, 404
        )

    def test_kaggle_requires_secret_400(self):
        client = self._client()
        self._login(client)
        r = client.post("/settings/providers/kaggle", json={"api_key": "user"})
        self.assertEqual(r.status_code, 400)


@unittest.skipIf(importlib.util.find_spec("fastapi") is None, "fastapi not installed")
class MissingVaultKeyRouterTest(unittest.TestCase):
    """When DATAFORGE_VAULT_KEY is unset the app still boots and settings
    routes return 503 for authenticated users (auth still enforced first)."""

    def _client(self, vault=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.auth import AuthService, AuthStore
        from backend.auth.web import build_auth_router, make_current_user_dependency
        from backend.vault.web import build_settings_router

        os.environ["DATAFORGE_COOKIE_SECURE"] = "false"
        tmp = tempfile.mkdtemp()
        auth = AuthService(AuthStore(os.path.join(tmp, "auth.db")))
        app = FastAPI()
        app.include_router(build_auth_router(auth))
        # vault unavailable -> simulates a deployment with no DATAFORGE_VAULT_KEY
        app.include_router(build_settings_router(vault, make_current_user_dependency(auth)))
        return TestClient(app)

    def _login(self, client):
        client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret"})
        client.post("/auth/login", json={"email": "a@b.com", "password": "supersecret"})

    def test_unauthenticated_still_401(self):
        # Auth boundary runs before the vault-availability check.
        self.assertEqual(self._client(None).get("/settings/providers").status_code, 401)

    def test_authenticated_get_503(self):
        client = self._client(None)
        self._login(client)
        r = client.get("/settings/providers")
        self.assertEqual(r.status_code, 503)
        self.assertIn("vault", r.text.lower())

    def test_authenticated_writes_503(self):
        client = self._client(None)
        self._login(client)
        self.assertEqual(
            client.post("/settings/providers/nvidia", json={"api_key": "k"}).status_code, 503
        )
        self.assertEqual(client.delete("/settings/providers/nvidia").status_code, 503)

    def test_factory_returning_none_503(self):
        # A zero-arg factory that resolves to None behaves the same as None.
        client = self._client(lambda: None)
        self._login(client)
        self.assertEqual(client.get("/settings/providers").status_code, 503)


if __name__ == "__main__":
    unittest.main()
