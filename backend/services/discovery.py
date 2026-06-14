"""Dataset discovery against REAL provider APIs, with tunable search intensity.

Replaces the previous templated/synthesized discovery (which produced fabricated,
sometimes malformed dataset URLs). Each provider parses the actual upstream JSON
and builds canonical URLs from real identifiers. Network access is gated behind
``DATAFORGE_DISCOVERY_LIVE=true``; when disabled the service returns an empty
result with a clear note rather than inventing datasets. The HTTP client is
injectable so providers are contract-tested without network or secrets. In
addition to dataset portals, a generic web provider searches public web results
for dataset pages so discovery is not dependent on one or two catalog APIs.

Search intensity
----------------
The caller picks how hard the engine should work: ``easy`` -> ``intense``. Higher
intensity consults more providers and fetches more candidates per provider, so it
costs more time but casts a wider net. Intensity never fabricates results - it
only changes how much real work is done.
"""

from __future__ import annotations

import json
import os
import re
import base64
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html import unescape
from typing import Any, Protocol


class DiscoveryError(Exception):
    pass


# -- Search intensity profiles ------------------------------------------------
INTENSITY_ORDER = ("easy", "medium", "hard", "very_hard", "intense")
DEFAULT_INTENSITY = "medium"
INTENSITY_PROFILES: dict[str, dict[str, Any]] = {
    "easy": {
        "limit": 5,
        "providers": 1,
        "query_passes": 1,
        "label": "Easy",
        "strategy": "single-provider quick lookup",
    },
    "medium": {
        "limit": 12,
        "providers": 2,
        "query_passes": 1,
        "label": "Medium",
        "strategy": "balanced multi-provider lookup",
    },
    "hard": {
        "limit": 25,
        "providers": 3,
        "query_passes": 2,
        "label": "Hard",
        "strategy": "multi-provider lookup plus broad query pass",
    },
    "very_hard": {
        "limit": 50,
        "providers": 4,
        "query_passes": 3,
        "label": "Very Hard",
        "strategy": "deep lookup with broad and dataset-focused query passes",
    },
    "intense": {
        "limit": 100,
        "providers": 4,
        "query_passes": 4,
        "label": "Intense",
        "strategy": "exhaustive lookup with multiple broadened query passes",
    },
}


def resolve_intensity(name: str | None) -> str:
    """Normalize a user-supplied intensity to a known key (defaults to medium)."""
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in INTENSITY_PROFILES else DEFAULT_INTENSITY


def query_variants(query: str, passes: int) -> list[str]:
    """Return progressively broader search queries for deeper intensities."""
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return [""]
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized.lower())
        if token not in {"find", "show", "get", "dataset", "datasets", "data", "for", "with", "and", "the"}
    ]
    variants = [normalized]
    if tokens:
        token_query = " ".join(tokens)
        variants.append(token_query)
        variants.append(f"{token_query} dataset")
    if len(tokens) > 2:
        variants.append(" ".join(tokens[:2]))
    if tokens:
        variants.append(tokens[0])

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped[: max(1, passes)]


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

    def __init__(self, client: HttpClient | None = None, timeout: float = 15.0,
                 token: str | None = None) -> None:
        super().__init__(client, timeout)
        # Optional per-user/global access token. Unauthenticated calls still
        # work but are more rate-limited. Resolved by
        # backend.services.credentials.huggingface_token_for.
        self.token = token or ""

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        params = urllib.parse.urlencode({"search": query, "limit": limit, "full": "true"})
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        data = self._get_json(self.API + "?" + params, headers)
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
    SEARCH = "https://catalog.data.gov/dataset/"

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        params = urllib.parse.urlencode({"q": query, "rows": limit})
        try:
            data = self._get_json(self.API + "?" + params)
        except DiscoveryError as exc:
            if "status 404" not in str(exc):
                raise
            return self._search_html(query, limit)
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

    def _search_html(self, query: str, limit: int) -> list[DatasetRef]:
        """Fallback to data.gov's public HTML catalog when CKAN is unavailable."""
        params = urllib.parse.urlencode({"q": query})
        status, body = self.client.get(
            self.SEARCH + "?" + params,
            {"User-Agent": "DataForge/1.0"},
            self.timeout,
        )
        if status != 200:
            raise DiscoveryError(f"data.gov returned status {status}")
        items = re.findall(
            r'<li[^>]*class="[^"]*organization-datasets__item[^"]*"[^>]*>(.*?)</li>\s*(?=<li|\s*</ul>)',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        refs: list[DatasetRef] = []
        for item in items:
            link = re.search(
                r'<a[^>]+class="[^"]*usa-link[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not link:
                continue
            href = unescape(link.group(1)).strip()
            if not href.startswith("/dataset/"):
                continue
            title = self._clean_html(link.group(2))
            if not title:
                continue
            desc_match = re.search(
                r'<p[^>]*class="[^"]*usa-collection__description[^"]*"[^>]*>(.*?)</p>',
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            tags = [
                self._clean_html(match)
                for match in re.findall(r'data-format="([^"]+)"', item, flags=re.IGNORECASE)
            ]
            refs.append(
                DatasetRef(
                    id=href.rsplit("/", 1)[-1],
                    title=title,
                    url=urllib.parse.urljoin("https://catalog.data.gov", href),
                    source=self.source,
                    provider=self.name,
                    description=self._clean_html(desc_match.group(1))[:500] if desc_match else "",
                    downloads=0,
                    tags=sorted({tag.lower() for tag in tags if tag})[:12],
                )
            )
            if len(refs) >= limit:
                break
        return refs

    def _clean_html(self, value: str) -> str:
        value = re.sub(r"<[^>]+>", " ", value)
        value = unescape(value)
        return " ".join(value.split())


class KaggleProvider(_BaseProvider):
    name = "kaggle"
    source = "Kaggle"
    API = "https://www.kaggle.com/api/v1/datasets/list"
    WEB = "https://www.kaggle.com/datasets/"

    def __init__(self, client: HttpClient | None = None, timeout: float = 15.0,
                 env: dict[str, str] | None = None,
                 username: str | None = None, key: str | None = None) -> None:
        super().__init__(client, timeout)
        # Explicit creds (e.g. resolved per-user from the vault) win; otherwise
        # fall back to environment variables for a global/admin deployment.
        if username is not None or key is not None:
            self.username = username or ""
            self.key = key or ""
        else:
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


class WebSearchProvider(_BaseProvider):
    """Generic web dataset discovery via public search-result HTML.

    This is deliberately conservative: it only returns real links parsed from a
    public search page, never generated URLs. Provider APIs are preferred when
    they work, but this keeps DataForge useful when a dataset lives on a lab,
    university, government, or project page outside HF/Kaggle/data.gov.
    """

    name = "web"
    source = "Web"
    API = "https://www.bing.com/search"

    _BLOCKED_HOSTS = {
        "duckduckgo.com",
        "www.duckduckgo.com",
        "google.com",
        "www.google.com",
        "bing.com",
        "www.bing.com",
    }

    def search(self, query: str, limit: int = 10) -> list[DatasetRef]:
        search_query = f"{query} dataset data repository csv"
        params = urllib.parse.urlencode({"q": search_query})
        status, body = self.client.get(
            self.API + "?" + params,
            {"User-Agent": "Mozilla/5.0 DataForge/1.0"},
            self.timeout,
        )
        if status != 200:
            raise DiscoveryError(f"web returned status {status}")
        refs: list[DatasetRef] = []
        seen: set[str] = set()
        for href, title in self._result_links(body):
            url = self._normalize_url(href)
            if not url or url in seen:
                continue
            host = urllib.parse.urlparse(url).netloc.lower()
            if host in self._BLOCKED_HOSTS:
                continue
            clean_title = self._clean_html(title)
            if not clean_title:
                continue
            seen.add(url)
            refs.append(
                DatasetRef(
                    id=self._stable_id(url),
                    title=clean_title,
                    url=url,
                    source=self.source,
                    provider=self.name,
                    description=f"Web result for dataset search: {clean_title}",
                    downloads=0,
                    tags=["web", "dataset"],
                )
            )
            if len(refs) >= limit:
                break
        return refs

    def _result_links(self, body: str) -> list[tuple[str, str]]:
        bing_blocks = re.findall(
            r'<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        bing_links: list[tuple[str, str]] = []
        for block in bing_blocks:
            match = re.search(
                r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                bing_links.append((match.group(1), match.group(2)))
        if bing_links:
            return bing_links
        links = re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if links:
            return links
        return re.findall(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _normalize_url(self, href: str) -> str:
        href = unescape(href).strip()
        parsed = urllib.parse.urlparse(href)
        if parsed.path == "/l/":
            target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
            href = urllib.parse.unquote(target)
        elif parsed.netloc.lower().endswith("bing.com") and parsed.path.startswith("/ck/"):
            target = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
            decoded = self._decode_bing_target(target)
            if decoded:
                href = decoded
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith(("http://", "https://")):
            return ""
        return href

    def _decode_bing_target(self, value: str) -> str:
        if not value:
            return ""
        # Bing commonly prefixes URL-safe base64 targets with "a1".
        encoded = value[2:] if value.startswith("a1") else value
        try:
            padded = encoded + ("=" * (-len(encoded) % 4))
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        except Exception:
            return ""
        return decoded if decoded.startswith(("http://", "https://")) else ""

    def _clean_html(self, value: str) -> str:
        value = re.sub(r"<[^>]+>", " ", value)
        value = unescape(value)
        return " ".join(value.split())

    def _stable_id(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        slug = re.sub(r"[^a-z0-9]+", "-", f"{parsed.netloc}{parsed.path}".lower()).strip("-")
        return slug[:120] or "web-dataset"


class DiscoveryService:
    def __init__(self, providers: list[_BaseProvider] | None = None, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else dict(os.environ)
        self.live = env.get("DATAFORGE_DISCOVERY_LIVE", "false").strip().lower() == "true"
        self.providers = providers if providers is not None else [
            HuggingFaceProvider(),
            WebSearchProvider(),
            DataGovProvider(),
            KaggleProvider(env=env),
        ]

    def search(self, query: str, intensity: str = DEFAULT_INTENSITY,
               limit: int | None = None) -> dict[str, Any]:
        level = resolve_intensity(intensity)
        profile = INTENSITY_PROFILES[level]
        per_provider = int(limit) if limit is not None else int(profile["limit"])
        active = self.providers[: int(profile["providers"])]
        passes = int(profile.get("query_passes", 1))
        queries = query_variants(query, passes)

        if not self.live:
            return {
                "enabled": False,
                "query": query,
                "intensity": level,
                "intensity_label": profile["label"],
                "strategy": profile["strategy"],
                "query_passes": len(queries),
                "queries_used": queries,
                "results": [],
                "note": "Discovery disabled. Set DATAFORGE_DISCOVERY_LIVE=true to enable real provider search.",
            }

        results: list[DatasetRef] = []
        errors: list[str] = []
        seen: set[str] = set()
        providers_used: list[str] = []
        for provider in active:
            providers_used.append(provider.name)
            for search_query in queries:
                try:
                    for ref in provider.search(search_query, per_provider):
                        if ref.url in seen:
                            continue
                        seen.add(ref.url)
                        results.append(ref)
                except DiscoveryError as exc:
                    errors.append(f"{provider.name} ({search_query}): {exc}")
        results.sort(key=lambda r: r.downloads, reverse=True)
        return {
            "enabled": True,
            "query": query,
            "intensity": level,
            "intensity_label": profile["label"],
            "strategy": profile["strategy"],
            "query_passes": len(queries),
            "queries_used": queries,
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
            "configured": {
                provider.name: bool(getattr(provider, "configured", True))
                for provider in self.providers
            },
        }
