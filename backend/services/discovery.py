"""Dataset discovery against REAL provider APIs, with tunable search intensity.

Replaces the previous templated/synthesized discovery (which produced fabricated,
sometimes malformed dataset URLs). Each provider parses the actual upstream JSON
and builds canonical URLs from real identifiers. Network access is gated behind
``DATAFORGE_DISCOVERY_LIVE=true``; when disabled the service returns an empty
result with a clear note rather than inventing datasets. The HTTP client is
injectable so providers are contract-tested without network or secrets.

Search intensity controls how much real provider work is attempted. Higher
levels consult more providers and request more candidates per provider; it never
fabricates fallback results.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class DiscoveryError(Exception):
    pass


INTENSITY_ORDER = ("easy", "medium", "hard", "very_hard", "intense")
DEFAULT_INTENSITY = "medium"
INTENSITY_PROFILES: dict[str, dict[str, Any]] = {
    "easy": {"limit": 5, "providers": 1, "label": "Easy"},
    "medium": {"limit": 12, "providers": 2, "label": "Medium"},
    "hard": {"limit": 25, "providers": 3, "label": "Hard"},
    "very_hard": {"limit": 50, "providers": 3, "label": "Very Hard"},
    "intense": {"limit": 100, "providers": 3, "label": "Intense"},
}


def resolve_intensity(name: str | None) -> str:
    """Normalize a user-supplied intensity to a known key."""
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in INTENSITY_PROFILES else DEFAULT_INTENSITY


@dataclass(frozen=True)
class DatasetRef:
    id: str
    title: str
    url: str
    source: str
    provider: str
    description: str = ""
    downloads: int = 0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HttpClient(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]: ...


class UrllibHttpClient:
    def get(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            return exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            raise DiscoveryError(f"transport error: {exc.reason}") from exc


class _BaseProvider:
    name = "base"
    source = "base"

    def __init__(self, client: HttpClient | None = None, timeout: float = 15.0) -> None:
        self.client = client or UrllibHttpClient()
        self.timeout = timeout

    def _get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        status, body = self.client.get(url, headers or {}, self.timeout)
        if status != 200:
            raise DiscoveryError(f"{self.name} returned status {status}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"{self.name} returned malformed JSON") from exc


class HuggingFaceProvider(_BaseProvider):
    name = "huggingface"
    source = "HuggingFace Hub"
    API = "https://huggingface.co/api/datasets"
    WEB = "https://huggingface.co/datasets/"

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        params = urllib.parse.urlencode({"search": query, "limit": limit, "full": "true"})
        data = self._get_json(self.API + "?" + params)
        if not isinstance(data, list):
            raise DiscoveryError("huggingface: unexpected response shape")
        refs: list[DatasetRef] = []
        for item in data:
            ds_id = item.get("id") or item.get("modelId")
            if not ds_id:
                continue
            refs.append(
                DatasetRef(
                    id=ds_id,
                    title=ds_id,
                    url=self.WEB + str(ds_id),
                    source=self.source,
                    provider=self.name,
                    description=(item.get("description") or "")[:500],
                    downloads=int(item.get("downloads") or 0),
                    tags=list(item.get("tags") or [])[:12],
                )
            )
        return refs


class DataGovProvider(_BaseProvider):
    name = "data.gov"
    source = "data.gov"
    API = "https://catalog.data.gov/api/3/action/package_search"
    WEB = "https://catalog.data.gov/dataset/"

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        params = urllib.parse.urlencode({"q": query, "rows": limit})
        data = self._get_json(self.API + "?" + params)
        if not isinstance(data, dict) or not data.get("success"):
            raise DiscoveryError("data.gov: request not successful")
        results = data.get("result", {}).get("results", [])
        refs: list[DatasetRef] = []
        for item in results:
            name = item.get("name")
            if not name:
                continue
            refs.append(
                DatasetRef(
                    id=name,
                    title=item.get("title") or name,
                    url=self.WEB + str(name),
                    source=self.source,
                    provider=self.name,
                    description=(item.get("notes") or "")[:500],
                    downloads=0,
                    tags=[t.get("name") for t in item.get("tags", []) if t.get("name")][:12],
                )
            )
        return refs


class KaggleProvider(_BaseProvider):
    name = "kaggle"
    source = "Kaggle"
    API = "https://www.kaggle.com/api/v1/datasets/list"
    WEB = "https://www.kaggle.com/datasets/"

    def __init__(self, client: HttpClient | None = None, timeout: float = 15.0,
                 env: dict[str, str] | None = None) -> None:
        super().__init__(client, timeout)
        env = env if env is not None else dict(os.environ)
        self.username = env.get("KAGGLE_USERNAME", "")
        self.key = env.get("KAGGLE_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.username and self.key)

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        if not self.configured:
            return []
        import base64
        token = base64.b64encode(f"{self.username}:{self.key}".encode()).decode()
        params = urllib.parse.urlencode({"search": query, "pageSize": limit})
        data = self._get_json(self.API + "?" + params, {"Authorization": f"Basic {token}"})
        if not isinstance(data, list):
            raise DiscoveryError("kaggle: unexpected response shape")
        refs: list[DatasetRef] = []
        for item in data:
            ref = item.get("ref")
            if not ref:
                continue
            refs.append(
                DatasetRef(
                    id=ref,
                    title=item.get("title") or ref,
                    url=self.WEB + str(ref),
                    source=self.source,
                    provider=self.name,
                    description=(item.get("subtitle") or "")[:500],
                    downloads=int(item.get("downloadCount") or 0),
                )
            )
        return refs


class DiscoveryService:
    def __init__(self, providers: list[_BaseProvider] | None = None, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else dict(os.environ)
        self.live = env.get("DATAFORGE_DISCOVERY_LIVE", "false").strip().lower() == "true"
        self.providers = providers if providers is not None else [
            HuggingFaceProvider(),
            DataGovProvider(),
            KaggleProvider(env=env),
        ]

    def search(
        self,
        query: str,
        intensity: str = DEFAULT_INTENSITY,
        limit: int | None = None,
    ) -> dict[str, Any]:
        level = resolve_intensity(intensity)
        profile = INTENSITY_PROFILES[level]
        per_provider = int(limit) if limit is not None else int(profile["limit"])
        active_providers = self.providers[: int(profile["providers"])]

        if not self.live:
            return {
                "enabled": False,
                "query": query,
                "intensity": level,
                "intensity_label": profile["label"],
                "results": [],
                "note": "Discovery disabled. Set DATAFORGE_DISCOVERY_LIVE=true to enable real provider search.",
            }
        results: list[DatasetRef] = []
        errors: list[str] = []
        seen: set[str] = set()
        providers_used: list[str] = []
        for provider in active_providers:
            providers_used.append(provider.name)
            try:
                for ref in provider.search(query, per_provider):
                    if ref.url in seen:
                        continue
                    seen.add(ref.url)
                    results.append(ref)
            except DiscoveryError as exc:
                errors.append(f"{provider.name}: {exc}")
        results.sort(key=lambda r: r.downloads, reverse=True)
        return {
            "enabled": True,
            "query": query,
            "intensity": level,
            "intensity_label": profile["label"],
            "limit_per_provider": per_provider,
            "providers_used": providers_used,
            "results": [r.to_dict() for r in results],
            "errors": errors,
        }

    def provider_status(self) -> dict[str, Any]:
        """Return configured provider state for API/status surfaces."""
        return {
            "live": self.live,
            "providers": [provider.name for provider in self.providers],
        }
