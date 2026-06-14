import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.auth.service import User  # noqa: E402
from backend.vault import ProviderVault, SecretBox, VaultStore  # noqa: E402
from backend.services.llm_provider import HttpLLMProvider  # noqa: E402
from backend.services.discovery import KaggleProvider, WebSearchProvider  # noqa: E402
from backend.services.credentials import (  # noqa: E402
    build_discovery_service_for,
    build_llm_orchestrator_for,
    build_skill_orchestrator_for,
    huggingface_token_for,
    kaggle_creds_for,
    llm_config_for,
)

_MASTER = b"unit-test-master-key-which-is-long-enough"


def _user(uid="user-alice"):
    return User(id=uid, email=uid + "@b.com", role="user", created_at="t")


def _vault(tmp):
    return ProviderVault(VaultStore(os.path.join(tmp, "vault.db")), SecretBox(_MASTER))


class LlmConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault = _vault(self.tmp)
        self.alice = _user("user-alice")
        self.bob = _user("user-bob")

    def test_vault_key_takes_precedence(self):
        self.vault.set_credential(self.alice, "nvidia", "VAULT-NV-KEY")
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_API_KEY": "ENV-KEY",
            "DATAFORGE_LLM_BASE_URL": "https://x/v1",
        }
        cfg = llm_config_for(self.alice, self.vault, env=env)
        self.assertEqual(cfg.api_key, "VAULT-NV-KEY")
        self.assertTrue(cfg.live)

    def test_env_fallback_when_no_vault_key(self):
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_API_KEY": "ENV-KEY",
            "DATAFORGE_LLM_BASE_URL": "https://x/v1",
        }
        cfg = llm_config_for(self.bob, self.vault, env=env)
        self.assertEqual(cfg.api_key, "ENV-KEY")
        self.assertTrue(cfg.live)

    def test_degrades_offline_when_no_key_anywhere(self):
        env = {"DATAFORGE_LIVE_LLM": "true", "DATAFORGE_LLM_BASE_URL": "https://x/v1"}
        cfg = llm_config_for(self.bob, self.vault, env=env)
        self.assertEqual(cfg.api_key, "")
        self.assertFalse(cfg.live)  # forced offline: live requested but no key

    def test_orchestrator_offline_without_key(self):
        orch = build_llm_orchestrator_for(self.bob, self.vault, env={"DATAFORGE_LIVE_LLM": "true"})
        self.assertIsNone(orch.primary)
        res = orch.generate("hello world")
        self.assertEqual(res.provider, "local-deterministic")

    def test_orchestrator_live_with_key(self):
        self.vault.set_credential(self.alice, "nvidia", "VAULT-NV-KEY")
        env = {"DATAFORGE_LIVE_LLM": "true", "DATAFORGE_LLM_BASE_URL": "https://x/v1"}
        orch = build_llm_orchestrator_for(self.alice, self.vault, env=env)
        self.assertIsInstance(orch.primary, HttpLLMProvider)
        self.assertEqual(orch.config.api_key, "VAULT-NV-KEY")

    def test_provider_override(self):
        self.vault.set_credential(self.alice, "openai", "VAULT-OAI-KEY")
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_PROVIDER": "openai",
            "DATAFORGE_LLM_BASE_URL": "https://x/v1",
        }
        cfg = llm_config_for(self.alice, self.vault, env=env)
        self.assertEqual(cfg.api_key, "VAULT-OAI-KEY")

    def test_no_vault_uses_env(self):
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_API_KEY": "ENV-KEY",
            "DATAFORGE_LLM_BASE_URL": "https://x/v1",
        }
        cfg = llm_config_for(self.alice, None, env=env)
        self.assertEqual(cfg.api_key, "ENV-KEY")

    def test_skill_orchestrator_uses_vault_key(self):
        self.vault.set_credential(self.alice, "nvidia", "VAULT-NV-KEY")
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_PROVIDERS": "nim,openai",
            "NVIDIA_NIM_BASE_URL": "https://x/v1",
        }
        orch = build_skill_orchestrator_for(self.alice, self.vault, env=env)
        self.assertEqual(orch.providers[0].name, "nim")
        self.assertEqual(orch.providers[0].api_key, "VAULT-NV-KEY")

    def test_skill_orchestrator_degrades_offline_without_key(self):
        env = {"DATAFORGE_LIVE_LLM": "true", "DATAFORGE_LLM_PROVIDERS": "nim,openai"}
        orch = build_skill_orchestrator_for(self.bob, self.vault, env=env)
        self.assertEqual(orch.status()["active_provider"], "local-deterministic")

    def test_skill_orchestrator_env_fallback(self):
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_PROVIDERS": "openai",
            "OPENAI_API_KEY": "ENV-OAI-KEY",
        }
        orch = build_skill_orchestrator_for(self.bob, self.vault, env=env)
        self.assertEqual(orch.providers[0].name, "openai")
        self.assertEqual(orch.providers[0].api_key, "ENV-OAI-KEY")

    def test_skill_orchestrator_reuses_dataforge_nvidia_model_settings(self):
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_PROVIDERS": "nim",
            "DATAFORGE_LLM_API_KEY": "ENV-NV-KEY",
            "DATAFORGE_LLM_BASE_URL": "https://nvidia.example/v1",
            "DATAFORGE_LLM_MODEL": "meta/llama-3.1-8b-instruct",
        }
        orch = build_skill_orchestrator_for(self.bob, self.vault, env=env)
        self.assertEqual(orch.providers[0].name, "nim")
        self.assertEqual(orch.providers[0].base_url, "https://nvidia.example/v1")
        self.assertEqual(orch.providers[0].model, "meta/llama-3.1-8b-instruct")

    def test_skill_orchestrator_does_not_reuse_nvidia_key_for_openai(self):
        env = {
            "DATAFORGE_LIVE_LLM": "true",
            "DATAFORGE_LLM_PROVIDERS": "openai",
            "DATAFORGE_LLM_API_KEY": "ENV-NV-KEY",
        }
        orch = build_skill_orchestrator_for(self.bob, self.vault, env=env)
        self.assertEqual(orch.status()["active_provider"], "local-deterministic")


class KaggleHfResolverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault = _vault(self.tmp)
        self.alice = _user("user-alice")
        self.bob = _user("user-bob")

    def test_kaggle_vault_precedence(self):
        self.vault.set_credential(self.alice, "kaggle", "vault-user", "vault-key")
        env = {"KAGGLE_USERNAME": "env-user", "KAGGLE_KEY": "env-key"}
        self.assertEqual(
            kaggle_creds_for(self.alice, self.vault, env=env), ("vault-user", "vault-key")
        )

    def test_kaggle_env_fallback(self):
        env = {"KAGGLE_USERNAME": "env-user", "KAGGLE_KEY": "env-key"}
        self.assertEqual(
            kaggle_creds_for(self.bob, self.vault, env=env), ("env-user", "env-key")
        )

    def test_hf_vault_then_env(self):
        self.vault.set_credential(self.alice, "huggingface", "vault-hf")
        self.assertEqual(huggingface_token_for(self.alice, self.vault, env={}), "vault-hf")
        self.assertEqual(
            huggingface_token_for(self.bob, self.vault, env={"HF_TOKEN": "env-hf"}), "env-hf"
        )

    def test_build_discovery_uses_user_creds(self):
        self.vault.set_credential(self.alice, "kaggle", "vault-user", "vault-key")
        svc = build_discovery_service_for(
            self.alice, self.vault, env={"DATAFORGE_DISCOVERY_LIVE": "true"}
        )
        kaggle = [p for p in svc.providers if isinstance(p, KaggleProvider)][0]
        self.assertTrue(any(isinstance(p, WebSearchProvider) for p in svc.providers))
        self.assertTrue(kaggle.configured)
        self.assertEqual(kaggle.username, "vault-user")
        self.assertEqual(kaggle.key, "vault-key")

    def test_isolation_bob_not_alice(self):
        self.vault.set_credential(self.alice, "kaggle", "vault-user", "vault-key")
        svc = build_discovery_service_for(self.bob, self.vault, env={})
        kaggle = [p for p in svc.providers if isinstance(p, KaggleProvider)][0]
        self.assertFalse(kaggle.configured)


if __name__ == "__main__":
    unittest.main()
