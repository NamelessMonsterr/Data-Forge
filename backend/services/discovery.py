"""Modular dataset discovery architecture.

Discovery finds and ranks dataset candidates. It never downloads or ingests
unvalidated data; license validation remains a separate hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from time import time
from typing import Any, Protocol
from urllib.parse import urlparse

from backend.core.settings import get_settings


class CandidateStatus(str, Enum):
    """Lifecycle status for discovered dataset candidates."""

    DISCOVERED = "discovered"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN_LICENSE = "unknown_license"


@dataclass(frozen=True)
class DiscoveryQuery:
    """Normalized discovery query sent to every provider."""

    text: str
    domain: str
    languages: tuple[str, ...]
    target_model: str
    intended_use: str = "commercial"

    @classmethod
    def from_requirement(cls, requirement: dict[str, Any]) -> "DiscoveryQuery":
        """Create a query from structured requirements."""
        return cls(
            text=str(requirement.get("raw_request", "")),
            domain=str(requirement.get("domain", "general")),
            languages=tuple(requirement.get("languages", ["english"])),
            target_model=str(requirement.get("target_model", "nemotron")),
            intended_use=str(requirement.get("intended_use", "commercial")),
        )

    def cache_key(self) -> str:
        """Return stable cache key for this query."""
        raw = "|".join(
            [self.text, self.domain, ",".join(self.languages), self.target_model, self.intended_use]
        )
        return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetCandidate:
    """Unified dataset candidate model emitted by every discovery provider."""

    id: str
    title: str
    url: str
    provider: str
    domain: str
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)
    license_guess: str | None = None
    license_confidence: float = 0.0
    discovery_score: float = 0.0
    verified_license: str | None = None
    status: CandidateStatus = CandidateStatus.DISCOVERED

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable candidate payload."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "domain": self.domain,
            "snippet": self.snippet,
            "metadata": self.metadata,
            "license_guess": self.license_guess,
            "license_confidence": self.license_confidence,
            "discovery_score": self.discovery_score,
            "verified_license": self.verified_license,
            "status": self.status.value,
            "license": self.license_guess,
            "rows": self.metadata.get("rows", 0),
            "coverage": self.metadata.get("coverage", 0.0),
            "source": self.provider,
        }

    def with_score(self, score: float) -> "DatasetCandidate":
        """Return a candidate copy with a discovery score."""
        return DatasetCandidate(
            id=self.id,
            title=self.title,
            url=self.url,
            provider=self.provider,
            domain=self.domain,
            snippet=self.snippet,
            metadata=self.metadata,
            license_guess=self.license_guess,
            license_confidence=self.license_confidence,
            discovery_score=score,
            verified_license=self.verified_license,
            status=self.status,
        )


class DiscoveryProvider(Protocol):
    """Provider interface for dataset discovery backends."""

    name: str

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return normalized dataset candidates."""
        ...


class JsonHttpClient(Protocol):
    """Minimal JSON HTTP client interface used by live providers."""

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Return decoded JSON for a GET request."""
        ...


class HttpxJsonClient:
    """HTTPX-backed JSON client with short request timeouts."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Return decoded JSON for a GET request."""
        import httpx

        response = httpx.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


class HuggingFaceProvider:
    """Offline-safe HuggingFace discovery provider."""

    name = "huggingface"

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return HuggingFace-shaped candidates."""
        return [
            DatasetCandidate(
                id=f"hf/{query.domain}-instruction-seed",
                title=f"{query.domain.title()} Instruction Seed",
                url=f"https://huggingface.co/datasets/dataforge/{query.domain}-instruction-seed",
                provider=self.name,
                domain="huggingface.co",
                snippet=f"Instruction dataset for {query.domain} and {', '.join(query.languages)}.",
                metadata={
                    "rows": 9200,
                    "coverage": 0.88,
                    "tags": [query.domain, *query.languages, "instruction"],
                    "downloads": 4200,
                    "last_updated": "2026-05-01",
                },
                license_guess="apache-2.0",
                license_confidence=0.94,
            )
        ]


class LiveHuggingFaceProvider:
    """Live Hugging Face Dataset Hub discovery provider."""

    name = "huggingface_live"

    def __init__(self, http_client: JsonHttpClient | None = None) -> None:
        self.http_client = http_client or HttpxJsonClient()

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Search the Hugging Face Dataset Hub API."""
        payload = self.http_client.get_json(
            "https://huggingface.co/api/datasets",
            params={
                "search": f"{query.domain} {' '.join(query.languages)} dataset",
                "limit": 10,
                "full": "true",
            },
        )
        candidates: list[DatasetCandidate] = []
        for item in payload if isinstance(payload, list) else []:
            dataset_id = str(item.get("id") or item.get("modelId") or "")
            if not dataset_id:
                continue
            card_data = item.get("cardData") or {}
            license_guess = self._extract_license(item, card_data)
            tags = tuple(str(tag) for tag in item.get("tags", [])[:12])
            candidates.append(
                DatasetCandidate(
                    id=f"hf/{dataset_id}",
                    title=dataset_id,
                    url=f"https://huggingface.co/datasets/{dataset_id}",
                    provider="huggingface",
                    domain="huggingface.co",
                    snippet=str(item.get("description") or f"Hugging Face dataset {dataset_id}")[:300],
                    metadata={
                        "rows": self._row_count(card_data),
                        "coverage": 0.75,
                        "tags": list(tags),
                        "downloads": int(item.get("downloads") or 0),
                        "likes": int(item.get("likes") or 0),
                        "last_updated": str(item.get("lastModified") or ""),
                    },
                    license_guess=license_guess,
                    license_confidence=0.9 if license_guess else 0.0,
                )
            )
        return candidates

    def _extract_license(self, item: dict[str, Any], card_data: dict[str, Any]) -> str | None:
        license_value = card_data.get("license")
        if isinstance(license_value, str):
            return license_value.lower()
        for tag in item.get("tags", []):
            tag_text = str(tag).lower()
            if tag_text.startswith("license:"):
                return tag_text.split(":", 1)[1]
        return None

    def _row_count(self, card_data: dict[str, Any]) -> int:
        size_categories = card_data.get("size_categories") or []
        if not size_categories:
            return 0
        first = str(size_categories[0])
        return {
            "n<1k": 500,
            "1k<n<10k": 5000,
            "10k<n<100k": 50000,
            "100k<n<1m": 500000,
            "1m<n<10m": 5000000,
        }.get(first, 0)


class KaggleProvider:
    """Offline-safe Kaggle discovery provider."""

    name = "kaggle"

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return Kaggle-shaped candidates."""
        return [
            DatasetCandidate(
                id=f"kaggle/{query.domain}-public-corpus",
                title=f"{query.domain.title()} Public Corpus",
                url=f"https://www.kaggle.com/datasets/dataforge/{query.domain}-public-corpus",
                provider=self.name,
                domain="kaggle.com",
                snippet=f"Public corpus with metadata for {query.domain} tasks.",
                metadata={
                    "rows": 6100,
                    "coverage": 0.72,
                    "tags": [query.domain, "public"],
                    "downloads": 3100,
                    "last_updated": "2026-04-10",
                },
                license_guess="cc-by-4.0",
                license_confidence=0.86,
            )
        ]


class GitHubProvider:
    """Offline-safe GitHub discovery provider."""

    name = "github"

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return GitHub-shaped dataset repository candidates."""
        return [
            DatasetCandidate(
                id=f"github/{query.domain}-research-samples",
                title=f"{query.domain.title()} Research Samples",
                url=f"https://github.com/dataforge/{query.domain}-research-samples",
                provider=self.name,
                domain="github.com",
                snippet=f"Repository containing sample {query.domain} records and metadata.",
                metadata={
                    "rows": 1800,
                    "coverage": 0.61,
                    "tags": [query.domain, "research"],
                    "stars": 180,
                    "last_updated": "2026-03-19",
                },
                license_guess="mit",
                license_confidence=0.9,
            )
        ]


class LiveGitHubProvider:
    """Live GitHub repository search provider for dataset repositories."""

    name = "github_live"

    def __init__(
        self,
        http_client: JsonHttpClient | None = None,
        token: str | None = None,
    ) -> None:
        self.http_client = http_client or HttpxJsonClient()
        self.token = token

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Search GitHub repositories for dataset candidates."""
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = self.http_client.get_json(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{query.domain} dataset {' '.join(query.languages)} in:name,description,readme",
                "sort": "stars",
                "order": "desc",
                "per_page": 10,
            },
            headers=headers,
        )
        candidates: list[DatasetCandidate] = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            full_name = str(item.get("full_name") or "")
            if not full_name:
                continue
            license_payload = item.get("license") or {}
            license_guess = license_payload.get("spdx_id")
            if isinstance(license_guess, str):
                license_guess = license_guess.lower()
            candidates.append(
                DatasetCandidate(
                    id=f"github/{full_name}",
                    title=full_name,
                    url=str(item.get("html_url") or ""),
                    provider="github",
                    domain="github.com",
                    snippet=str(item.get("description") or "")[:300],
                    metadata={
                        "rows": 0,
                        "coverage": 0.62,
                        "tags": [query.domain, *query.languages, "github"],
                        "stars": int(item.get("stargazers_count") or 0),
                        "last_updated": str(item.get("updated_at") or ""),
                        "repository_owner": str(item.get("owner", {}).get("login") or ""),
                    },
                    license_guess=license_guess,
                    license_confidence=0.85 if license_guess else 0.0,
                )
            )
        return candidates


class WebSearchProvider:
    """Discover dataset URLs from allowlisted web domains without ingestion."""

    name = "web"

    def __init__(self, allowlisted_domains: tuple[str, ...] | None = None) -> None:
        self.allowlisted_domains = allowlisted_domains or (
            "huggingface.co",
            "kaggle.com",
            "github.com",
            "data.gov",
            "data.europa.eu",
            "zenodo.org",
            "openml.org",
            "archive.ics.uci.edu",
        )

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Return metadata-only web candidates from trusted dataset domains."""
        candidates: list[DatasetCandidate] = []
        for domain in self.allowlisted_domains[:4]:
            url = f"https://{domain}/search?q={query.domain}+dataset"
            candidates.append(
                DatasetCandidate(
                    id=f"web/{domain}/{query.domain}",
                    title=f"{query.domain.title()} dataset result on {domain}",
                    url=url,
                    provider=self.name,
                    domain=domain,
                    snippet=f"Web discovery result for {query.domain}; metadata only, no ingestion.",
                    metadata={
                        "rows": 0,
                        "coverage": 0.45 if domain in {"data.gov", "data.europa.eu"} else 0.58,
                        "tags": [query.domain, "web"],
                        "source_engine": "local-web-boundary",
                    },
                    license_guess=None,
                    license_confidence=0.0,
                )
            )
        return candidates


class LiveWebSearchProvider:
    """Configurable live web-search provider for metadata-only discovery."""

    name = "web_live"

    def __init__(
        self,
        endpoint: str,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.http_client = http_client or HttpxJsonClient()

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Call a configured web-search endpoint and normalize URL candidates."""
        payload = self.http_client.get_json(
            self.endpoint,
            params={"q": f"{query.domain} dataset {' '.join(query.languages)}"},
        )
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        candidates: list[DatasetCandidate] = []
        for item in raw_results[:10]:
            url = str(item.get("url") or item.get("link") or "")
            if not url:
                continue
            domain = urlparse(url).netloc.lower()
            candidates.append(
                DatasetCandidate(
                    id=f"web/{domain}/{sha256(url.encode('utf-8')).hexdigest()[:12]}",
                    title=str(item.get("title") or domain),
                    url=url,
                    provider="web",
                    domain=domain,
                    snippet=str(item.get("snippet") or item.get("description") or "")[:300],
                    metadata={
                        "rows": 0,
                        "coverage": 0.45,
                        "tags": [query.domain, "web"],
                        "source_engine": "configured-web-search",
                    },
                    license_guess=item.get("license_guess"),
                    license_confidence=float(item.get("license_confidence") or 0.0),
                )
            )
        return candidates


class DiscoveryCache:
    """In-memory discovery cache with TTL."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, list[DatasetCandidate]]] = {}

    def get(self, key: str) -> list[DatasetCandidate] | None:
        """Return cached candidates when fresh."""
        item = self._items.get(key)
        if item is None:
            return None
        created_at, candidates = item
        if time() - created_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        return candidates

    def set(self, key: str, candidates: list[DatasetCandidate]) -> None:
        """Store candidates in cache."""
        self._items[key] = (time(), candidates)


class MetadataExtractor:
    """Enrich candidates with normalized URL and reputation metadata."""

    trusted_domains = {
        "huggingface.co",
        "kaggle.com",
        "github.com",
        "data.gov",
        "data.europa.eu",
        "zenodo.org",
        "openml.org",
        "archive.ics.uci.edu",
    }

    def enrich(self, candidate: DatasetCandidate) -> DatasetCandidate:
        """Return candidate enriched with derived metadata."""
        parsed = urlparse(candidate.url)
        domain = parsed.netloc.lower() or candidate.domain
        metadata = {
            **candidate.metadata,
            "resolved_domain": domain,
            "trusted_domain": domain in self.trusted_domains,
            "metadata_completeness": self._metadata_completeness(candidate),
        }
        return DatasetCandidate(
            id=candidate.id,
            title=candidate.title,
            url=candidate.url,
            provider=candidate.provider,
            domain=domain,
            snippet=candidate.snippet,
            metadata=metadata,
            license_guess=candidate.license_guess,
            license_confidence=candidate.license_confidence,
            discovery_score=candidate.discovery_score,
            verified_license=candidate.verified_license,
            status=candidate.status,
        )

    def _metadata_completeness(self, candidate: DatasetCandidate) -> float:
        fields = [
            candidate.title,
            candidate.url,
            candidate.snippet,
            candidate.license_guess,
            candidate.metadata.get("tags"),
            candidate.metadata.get("coverage"),
        ]
        return sum(1 for field in fields if field) / len(fields)


class DiscoveryRanker:
    """Rank candidates with weighted discovery signals."""

    trusted_providers = {"huggingface", "kaggle", "github"}

    def score(self, candidate: DatasetCandidate, query: DiscoveryQuery) -> float:
        """Return weighted discovery score."""
        trusted_provider = 1.0 if candidate.provider in self.trusted_providers else 0.6
        trusted_domain = 1.0 if candidate.metadata.get("trusted_domain") else 0.4
        explicit_license = 1.0 if candidate.license_guess else 0.0
        relevance = self._relevance(candidate, query)
        quality = float(candidate.metadata.get("coverage", 0.0))
        popularity = min(
            1.0,
            (
                float(candidate.metadata.get("downloads", 0))
                + float(candidate.metadata.get("stars", 0)) * 10
            )
            / 5000,
        )
        metadata_completeness = float(candidate.metadata.get("metadata_completeness", 0.0))
        license_confidence = candidate.license_confidence
        return round(
            trusted_provider * 0.16
            + trusted_domain * 0.12
            + explicit_license * 0.16
            + relevance * 0.18
            + quality * 0.14
            + popularity * 0.08
            + metadata_completeness * 0.08
            + license_confidence * 0.08,
            4,
        )

    def rank(
        self,
        candidates: list[DatasetCandidate],
        query: DiscoveryQuery,
    ) -> list[DatasetCandidate]:
        """Return candidates sorted by discovery score."""
        scored = [candidate.with_score(self.score(candidate, query)) for candidate in candidates]
        return sorted(scored, key=lambda candidate: candidate.discovery_score, reverse=True)

    def _relevance(self, candidate: DatasetCandidate, query: DiscoveryQuery) -> float:
        text = " ".join(
            [
                candidate.title.lower(),
                candidate.snippet.lower(),
                " ".join(str(tag).lower() for tag in candidate.metadata.get("tags", [])),
            ]
        )
        signals = [query.domain.lower(), *[language.lower() for language in query.languages]]
        matches = sum(1 for signal in signals if signal in text)
        return matches / len(signals) if signals else 0.0


class ProviderManager:
    """Isolate provider failures and merge partial discovery results."""

    def __init__(self, providers: list[DiscoveryProvider]) -> None:
        self.providers = providers
        self.errors: dict[str, str] = {}

    def search(self, query: DiscoveryQuery) -> list[DatasetCandidate]:
        """Query providers and continue when one provider fails."""
        candidates: list[DatasetCandidate] = []
        self.errors = {}
        for provider in self.providers:
            try:
                candidates.extend(provider.search(query))
            except Exception as exc:
                self.errors[provider.name] = str(exc)
        return self._deduplicate(candidates)

    def _deduplicate(self, candidates: list[DatasetCandidate]) -> list[DatasetCandidate]:
        by_url: dict[str, DatasetCandidate] = {}
        for candidate in candidates:
            existing = by_url.get(candidate.url)
            if existing is None or candidate.license_confidence > existing.license_confidence:
                by_url[candidate.url] = candidate
        return list(by_url.values())


class DiscoveryService:
    """Orchestrate provider search, cache, metadata enrichment, and ranking."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        cache: DiscoveryCache | None = None,
        extractor: MetadataExtractor | None = None,
        ranker: DiscoveryRanker | None = None,
    ) -> None:
        self.provider_manager = provider_manager or ProviderManager(self._default_providers())
        self.cache = cache or DiscoveryCache()
        self.extractor = extractor or MetadataExtractor()
        self.ranker = ranker or DiscoveryRanker()

    def search(self, requirement: dict[str, Any]) -> list[dict[str, Any]]:
        """Return ranked, metadata-enriched dataset candidates."""
        query = DiscoveryQuery.from_requirement(requirement)
        cache_key = query.cache_key()
        cached = self.cache.get(cache_key)
        if cached is None:
            discovered = self.provider_manager.search(query)
            enriched = [self.extractor.enrich(candidate) for candidate in discovered]
            ranked = self.ranker.rank(enriched, query)
            self.cache.set(cache_key, ranked)
        else:
            ranked = cached
        return [candidate.to_dict() for candidate in ranked]

    def provider_status(self) -> dict[str, Any]:
        """Return provider names and last provider-manager errors."""
        return {
            "providers": [provider.name for provider in self.provider_manager.providers],
            "errors": self.provider_manager.errors,
        }

    def _default_providers(self) -> list[DiscoveryProvider]:
        settings = get_settings().discovery
        providers: list[DiscoveryProvider] = []
        if settings.live_enabled:
            http_client = HttpxJsonClient(settings.timeout_seconds)
            providers.extend(
                [
                    LiveHuggingFaceProvider(http_client),
                    LiveGitHubProvider(http_client, token=settings.github_token),
                ]
            )
            if settings.web_search_endpoint:
                providers.append(LiveWebSearchProvider(settings.web_search_endpoint, http_client))
        providers.extend(
            [
                HuggingFaceProvider(),
                KaggleProvider(),
                GitHubProvider(),
                WebSearchProvider(),
            ]
        )
        return providers
