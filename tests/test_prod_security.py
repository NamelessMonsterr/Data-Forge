import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.security import (  # noqa: E402
    ApiKeyAuth,
    RequestLimits,
    SecurityConfig,
    SecurityPolicy,
    TokenBucketRateLimiter,
)


class ApiKeyAuthTest(unittest.TestCase):
    def test_disabled_allows_any(self):
        auth = ApiKeyAuth([])
        self.assertFalse(auth.enabled)
        self.assertTrue(auth.check(None))
        self.assertTrue(auth.check("whatever"))

    def test_enabled_rejects_missing(self):
        self.assertFalse(ApiKeyAuth(["secret"]).check(None))

    def test_enabled_rejects_wrong(self):
        self.assertFalse(ApiKeyAuth(["secret"]).check("nope"))

    def test_enabled_accepts_correct(self):
        self.assertTrue(ApiKeyAuth(["a", "b"]).check("b"))


class RateLimiterTest(unittest.TestCase):
    def test_allows_up_to_capacity(self):
        rl = TokenBucketRateLimiter(capacity=3, refill_per_sec=0, clock=lambda: 0.0)
        self.assertTrue(all(rl.allow("c") for _ in range(3)))

    def test_blocks_when_exhausted(self):
        rl = TokenBucketRateLimiter(capacity=2, refill_per_sec=0, clock=lambda: 0.0)
        rl.allow("c"); rl.allow("c")
        self.assertFalse(rl.allow("c"))

    def test_refills_over_time(self):
        now = [0.0]
        rl = TokenBucketRateLimiter(capacity=1, refill_per_sec=1.0, clock=lambda: now[0])
        self.assertTrue(rl.allow("c"))
        self.assertFalse(rl.allow("c"))
        now[0] = 1.0
        self.assertTrue(rl.allow("c"))

    def test_clients_independent(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_per_sec=0, clock=lambda: 0.0)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("b"))


class RequestLimitsTest(unittest.TestCase):
    def test_allows_under_limit(self):
        self.assertTrue(RequestLimits(100).check_size(50).allowed)

    def test_rejects_over_limit(self):
        d = RequestLimits(100).check_size(101)
        self.assertFalse(d.allowed)
        self.assertEqual(d.status, 413)


class SecurityConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = SecurityConfig.from_env({})
        self.assertEqual(cfg.api_keys, [])
        self.assertEqual(cfg.max_body_bytes, 10 * 1024 * 1024)
        self.assertEqual(cfg.rate_capacity, 60)
        self.assertEqual(cfg.cors_origins, ["http://localhost:5173"])

    def test_parses_keys_csv(self):
        cfg = SecurityConfig.from_env({"DATAFORGE_API_KEYS": "a, b ,c"})
        self.assertEqual(cfg.api_keys, ["a", "b", "c"])

    def test_parses_cors_origins(self):
        cfg = SecurityConfig.from_env({"DATAFORGE_CORS_ORIGINS": "https://a.com, https://b.com"})
        self.assertEqual(cfg.cors_origins, ["https://a.com", "https://b.com"])


class SecurityPolicyTest(unittest.TestCase):
    def policy(self, **env):
        base = {"DATAFORGE_API_KEYS": "secret", "DATAFORGE_MAX_BODY_BYTES": "100",
                "DATAFORGE_RATE_CAPACITY": "2", "DATAFORGE_RATE_REFILL": "0"}
        base.update(env)
        return SecurityPolicy(SecurityConfig.from_env(base), clock=lambda: 0.0)

    def test_public_path_bypasses_everything(self):
        d = self.policy().evaluate("/health", None, 9999, "c")
        self.assertTrue(d.allowed)

    def test_oversize_rejected_before_auth(self):
        d = self.policy().evaluate("/datasets/process", None, 101, "c")
        self.assertEqual(d.status, 413)

    def test_invalid_auth_rejected(self):
        d = self.policy().evaluate("/datasets/process", "wrong", 10, "c")
        self.assertEqual(d.status, 401)

    def test_rate_limit_enforced(self):
        p = self.policy()
        for _ in range(2):
            self.assertTrue(p.evaluate("/x", "secret", 10, "c").allowed)
        self.assertEqual(p.evaluate("/x", "secret", 10, "c").status, 429)

    def test_all_pass_allowed(self):
        self.assertTrue(self.policy().evaluate("/x", "secret", 10, "c").allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
