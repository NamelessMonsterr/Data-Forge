"""Dataset catalog indexing and search services."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4
from hashlib import sha256

from backend.app.url_safety import validate_http_url
from backend.core.repository import DatasetCatalogRecord, JsonRepository, utc_now
from backend.services.ai_skills import (
    DataCardSkill,
    DatasetGapAnalysisSkill,
    DatasetRecommendationSkill,
    DatasetSummarySkill,
)
from backend.services.discovery import DiscoveryService, INTENSITY_PROFILES, resolve_intensity
from backend.services.llm_orchestrator import LLMOrchestrator
from backend.services.semantic_search import SemanticTextEncoder


class DatasetCatalogService:
    """Persist and search uploaded dataset metadata."""

    def __init__(
        self,
        repository: JsonRepository,
        orchestrator: LLMOrchestrator | None = None,
        encoder: SemanticTextEncoder | None = None,
    ) -> None:
        self.repository = repository
        self.orchestrator = orchestrator or LLMOrchestrator()
        self.encoder = encoder or SemanticTextEncoder()

    def index_processed_upload(
        self,
        result: dict[str, Any],
        user_id: str | None = None,
    ) -> DatasetCatalogRecord:
        """Create a searchable catalog record from a processed upload response."""
        ingestion = result["ingestion"]
        upload_summary = result["summary"]
        title = ingestion["filename"].rsplit(".", 1)[0] or ingestion["filename"]
        schema = ingestion.get("schema", {})
        tags = self._tags(title, schema, result)
        ai_summary = DatasetSummarySkill().run(
            {
                "title": title,
                "rows": upload_summary["rows"],
                "columns": upload_summary["columns"],
                "schema": schema,
                "stats": ingestion.get("stats", {}),
            },
            self.orchestrator,
        )
        quality_report = result.get("quality_report", {})
        card_schema = {
            name: (meta.get("type") if isinstance(meta, dict) else meta)
            for name, meta in schema.items()
        }
        dataset_card = DataCardSkill().run(
            {
                "title": title,
                "rows": upload_summary["rows"],
                "columns": upload_summary["columns"],
                "schema": card_schema,
                "license": "user_provided",
                "quality_score": quality_report.get("score"),
                "tags": tags,
                "summary": ai_summary.text,
            },
            self.orchestrator,
        )
        record = DatasetCatalogRecord(
            dataset_id=f"local-{uuid4().hex[:12]}",
            title=title,
            source="local_upload",
            provider="local",
            task_id=result.get("task_id"),
            filename=ingestion["filename"],
            format=ingestion["format"],
            rows=int(upload_summary["rows"]),
            columns=int(upload_summary["columns"]),
            schema=schema,
            stats=ingestion.get("stats", {}),
            artifacts=result.get("artifacts", {}),
            quality_score=result.get("quality_report", {}).get("score"),
            quality_narrative=result.get("quality_report", {}).get("narrative", ""),
            quality_metrics=result.get("quality_report", {}).get("metrics", {}),
            dataset_card=dataset_card.text,
            tags=tags,
            description=ai_summary.text,
            created_at=utc_now(),
            ai_summary=ai_summary.text,
            ai_provider=ai_summary.provider,
            user_id=user_id,
        )
        return self.repository.save_dataset(record)

    def save_public_candidate(
        self,
        candidate: dict[str, Any],
        *,
        user_id: str | None = None,
        query: str = "",
    ) -> DatasetCatalogRecord:
        """Persist a public discovery result so a user can access it later."""
        url = validate_http_url(candidate.get("url") or candidate.get("source_url") or "")
        if not url:
            raise ValueError("Public dataset result must include a source URL.")
        title = str(candidate.get("title") or candidate.get("id") or "Public dataset")
        provider = str(candidate.get("provider") or candidate.get("source") or "public")
        source = str(candidate.get("source") or "public")
        tags = [str(tag) for tag in candidate.get("tags", []) if str(tag).strip()][:16]
        stable_id = sha256(f"{user_id or 'anon'}:{url}".encode("utf-8")).hexdigest()[:12]
        description = str(candidate.get("description") or candidate.get("snippet") or "")
        if not description:
            description = f"Public dataset from {source} saved from search."
        ai_summary = str(candidate.get("ai_summary") or description)
        dataset_card = (
            f"# {title}\n\n"
            f"## Source\n{source}\n\n"
            f"## URL\n{url}\n\n"
            f"## Search Context\n{query or 'Unavailable'}\n\n"
            f"## Summary\n{ai_summary}\n"
        )
        record = DatasetCatalogRecord(
            dataset_id=f"public-{stable_id}",
            title=title,
            source=source,
            provider=provider,
            task_id=None,
            filename=title,
            format=str(candidate.get("format") or "external"),
            rows=int(candidate.get("rows") or 0),
            columns=int(candidate.get("columns") or 0),
            schema=dict(candidate.get("schema") or {}),
            stats={
                "downloads": int(candidate.get("downloads") or 0),
                "relevance_score": candidate.get("relevance_score"),
                "discovery_score": candidate.get("discovery_score"),
                "saved_from_query": query,
            },
            artifacts={},
            quality_score=candidate.get("quality_score"),
            quality_narrative=str(candidate.get("recommendation") or ""),
            quality_metrics={},
            dataset_card=dataset_card,
            tags=sorted({*tags, "public", provider.lower()}),
            description=description,
            created_at=utc_now(),
            ai_summary=ai_summary,
            ai_provider=str(candidate.get("ai_provider") or "provider-metadata"),
            source_url=url,
            user_id=user_id,
        )
        return self.repository.save_dataset(record)

    def list_datasets(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Return catalog records as serializable dictionaries."""
        records = self.repository.list_datasets()
        if user_id is not None:
            records = [record for record in records if record.user_id == user_id]
        return [self._record_to_dict(record) for record in records]

    def search(
        self,
        query: str,
        limit: int = 10,
        user_id: str | None = None,
        allowed_dataset_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return local catalog results ranked by query relevance."""
        query_tokens = self._tokens(query)
        records = self.repository.list_datasets()
        if user_id is not None:
            records = [record for record in records if record.user_id == user_id]
        if allowed_dataset_ids is not None:
            records = [
                record
                for record in records
                if record.dataset_id in allowed_dataset_ids
            ]
        scored = [
            self._score_record(record, query_tokens)
            for record in records
        ]
        ranked = sorted(
            [result for result in scored if result["relevance_score"] > 0 or not query_tokens],
            key=lambda result: result["relevance_score"],
            reverse=True,
        )
        return ranked[:limit]

    def _score_record(
        self,
        record: DatasetCatalogRecord,
        query_tokens: set[str],
    ) -> dict[str, Any]:
        searchable = self._tokens(
            " ".join(
                [
                    record.title,
                    record.filename,
                    record.description,
                    " ".join(record.tags),
                    " ".join(record.schema.keys()),
                ]
            )
        )
        lexical_score = (
            len(query_tokens & searchable) / len(query_tokens)
            if query_tokens
            else 1.0
        )
        semantic_score = self.encoder.similarity(
            " ".join(sorted(query_tokens)),
            " ".join(
                [
                    record.title,
                    record.description,
                    record.ai_summary,
                    " ".join(record.tags),
                    " ".join(record.schema.keys()),
                ]
            ),
        )
        relevance_score = max(lexical_score, semantic_score)
        quality_score = (record.quality_score or 0) / 100
        size_score = min(1.0, record.rows / 10000)
        completeness = 1.0 - float(record.stats.get("missing_ratio", 0.0))
        source_credibility = 0.9 if record.provider == "local" else 0.75
        freshness = 1.0
        score = round(
            relevance_score * 0.5
            + quality_score * 0.2
            + completeness * 0.15
            + source_credibility * 0.1
            + freshness * 0.05,
            4,
        )
        payload = self._record_to_dict(record)
        payload["relevance_score"] = score
        payload["semantic_relevance"] = round(semantic_score, 4)
        payload["lexical_relevance"] = round(lexical_score, 4)
        payload["recommendation"] = self._recommendation(record, query_tokens & searchable, query_tokens)
        payload["gap_analysis"] = self._gap_analysis(record, query_tokens)
        return payload

    def _record_to_dict(self, record: DatasetCatalogRecord) -> dict[str, Any]:
        return {
            "id": record.dataset_id,
            "title": record.title,
            "source": record.source,
            "provider": record.provider,
            "task_id": record.task_id,
            "filename": record.filename,
            "format": record.format,
            "rows": record.rows,
            "columns": record.columns,
            "schema": record.schema,
            "stats": record.stats,
            "artifacts": record.artifacts,
            "source_url": record.source_url,
            "url": record.source_url,
            "quality_score": record.quality_score,
            "quality_narrative": record.quality_narrative,
            "quality_metrics": record.quality_metrics,
            "dataset_card": record.dataset_card,
            "tags": record.tags,
            "description": record.description,
            "ai_summary": record.ai_summary,
            "ai_provider": record.ai_provider,
            "created_at": record.created_at,
            "user_id": record.user_id,
        }

    def _tags(
        self,
        title: str,
        schema: dict[str, Any],
        result: dict[str, Any],
    ) -> list[str]:
        schema_tags = [name.lower() for name in schema.keys()]
        language_tags = [
            str(item.get("name", "")).lower()
            for item in result.get("summary", {}).get("schema", [])
            if item.get("name") == "language"
        ]
        return sorted({*self._tokens(title), *schema_tags, *language_tags, "uploaded"})

    def _description(
        self,
        title: str,
        summary: dict[str, Any],
        tags: list[str],
    ) -> str:
        return (
            f"{title} uploaded dataset with {summary['rows']} rows, "
            f"{summary['columns']} columns, and fields: {', '.join(tags[:8])}."
        )

    def _recommendation(
        self,
        record: DatasetCatalogRecord,
        matched_tokens: set[str],
        query_tokens: set[str],
    ) -> str:
        result = DatasetRecommendationSkill().run(
            {
                "title": record.title,
                "query": " ".join(sorted(query_tokens)) or "catalog search",
                "matched_terms": sorted(matched_tokens),
                "quality_score": record.quality_score,
                "rows": record.rows,
            },
            self.orchestrator,
        )
        return result.text

    _TUNING_TERMS = {
        "instruction",
        "instructions",
        "instruct",
        "chat",
        "sft",
        "finetune",
        "fine",
        "tuning",
    }

    def _gap_analysis(
        self,
        record: DatasetCatalogRecord,
        query_tokens: set[str],
    ) -> str:
        query = " ".join(sorted(query_tokens))
        requirement: dict[str, Any] = {"domain": query or "the search"}
        if query_tokens & self._TUNING_TERMS:
            requirement["target_model"] = "instruction-tuned"
        result = DatasetGapAnalysisSkill().run(
            {
                "rows": record.rows,
                "schema": record.schema,
                "languages": [
                    tag
                    for tag in record.tags
                    if tag in {"english", "spanish", "hindi", "french", "german"}
                ],
                "requirement": requirement,
            },
            self.orchestrator,
        )
        return result.text

    def _tokens(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 1
        }


class UnifiedDatasetSearchService:
    """Search local uploads and optional public discovery candidates together."""

    def __init__(
        self,
        catalog: DatasetCatalogService,
        discovery: DiscoveryService | None = None,
    ) -> None:
        self.catalog = catalog
        self.discovery = discovery or DiscoveryService()

    def search(
        self,
        query: str,
        *,
        include_public: bool = False,
        limit: int | None = 10,
        intensity: str = "medium",
        user_id: str | None = None,
        allowed_dataset_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Return merged local and public dataset results."""
        level = resolve_intensity(intensity)
        effective_limit = int(limit) if limit is not None else int(INTENSITY_PROFILES[level]["limit"])
        local = self.catalog.search(
            query,
            limit=effective_limit,
            user_id=user_id,
            allowed_dataset_ids=allowed_dataset_ids,
        )
        discovery_payload: dict[str, Any] = {}
        public: list[dict[str, Any]] = []
        if include_public:
            public, discovery_payload = self._public_results(query, limit, intensity)
        merged = sorted(
            [*local, *public],
            key=lambda item: item.get("relevance_score", item.get("discovery_score", 0.0)),
            reverse=True,
        )[:effective_limit]
        warnings = [str(item) for item in discovery_payload.get("errors", [])]
        search_status = self._search_status(
            include_public=include_public,
            returned=len(merged),
            public_count=len(public),
            discovery_payload=discovery_payload,
            warnings=warnings,
        )
        return {
            "query": query,
            "include_public": include_public,
            "intensity": level,
            "search_status": search_status,
            "warnings": warnings,
            "discovery": self._discovery_summary(discovery_payload),
            "results": merged,
            "counts": {
                "local": len(local),
                "public": len(public),
                "returned": len(merged),
            },
        }

    def _public_results(
        self,
        query: str,
        limit: int | None,
        intensity: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        discovery_payload = self.discovery.search(query, intensity=intensity, limit=limit)
        candidates = discovery_payload.get("results", [])
        if limit is not None:
            candidates = candidates[:limit]
        results = []
        query_tokens = self.catalog._tokens(query)
        for candidate in candidates:
            title_tokens = self.catalog._tokens(str(candidate.get("title") or candidate.get("id") or ""))
            desc_tokens = self.catalog._tokens(str(candidate.get("description") or ""))
            tag_tokens = {
                token
                for tag in candidate.get("tags", [])
                for token in self.catalog._tokens(str(tag))
            }
            searchable = set(title_tokens) | set(desc_tokens) | tag_tokens
            overlap = len(query_tokens & searchable)
            relevance = overlap / max(1, len(query_tokens))
            provider = str(candidate.get("provider") or "").lower()
            provider_weight = {"huggingface": 0.9, "kaggle": 0.85, "data.gov": 0.8}.get(provider, 0.7)
            source = str(candidate.get("source") or candidate.get("provider") or "public")
            popularity = min(1.0, float(candidate.get("downloads", 0) or 0) / 5000)
            metadata = 0.0
            if candidate.get("description"):
                metadata += 0.4
            if candidate.get("tags"):
                metadata += 0.3
            if candidate.get("url"):
                metadata += 0.3
            score = min(
                1.0,
                (0.55 * relevance)
                + (0.20 * popularity)
                + (0.15 * metadata)
                + (0.10 * provider_weight),
            )
            results.append(
                {
                    **candidate,
                    "source": source,
                    "result_type": "public",
                    "relevance_score": score,
                    "discovery_score": score,
                    "recommendation": (
                        "Recommended from live public discovery because provider "
                        "metadata and source popularity matched the query."
                    ),
                }
            )
        return results, discovery_payload

    def _search_status(
        self,
        *,
        include_public: bool,
        returned: int,
        public_count: int,
        discovery_payload: dict[str, Any],
        warnings: list[str],
    ) -> str:
        """Describe search outcome without relying on HTTP status alone."""
        if not include_public:
            return "complete" if returned else "empty"
        if discovery_payload and discovery_payload.get("enabled") is False:
            return "disabled" if not returned else "partial"
        if warnings and public_count == 0 and returned == 0:
            return "failed"
        if warnings:
            return "partial"
        return "complete" if returned else "empty"

    def _discovery_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {"enabled": False, "errors": []}
        return {
            "enabled": bool(payload.get("enabled")),
            "intensity": payload.get("intensity"),
            "intensity_label": payload.get("intensity_label"),
            "strategy": payload.get("strategy"),
            "query_passes": payload.get("query_passes"),
            "queries_used": payload.get("queries_used", []),
            "providers_used": payload.get("providers_used", []),
            "errors": payload.get("errors", []),
            "note": payload.get("note", ""),
        }

    def _domain_hint(self, query: str) -> str:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", query.lower())
            if token not in {"find", "dataset", "datasets", "for", "the", "with"}
        ]
        return tokens[0] if tokens else "general"
