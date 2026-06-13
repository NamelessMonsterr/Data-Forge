"""Dataset catalog indexing and search services."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from backend.core.repository import DatasetCatalogRecord, JsonRepository, utc_now
from backend.services.ai_skills import (
    DataCardSkill,
    DatasetGapAnalysisSkill,
    DatasetRecommendationSkill,
    DatasetSummarySkill,
)
from backend.services.discovery import DiscoveryService
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

    def index_processed_upload(self, result: dict[str, Any]) -> DatasetCatalogRecord:
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
        )
        return self.repository.save_dataset(record)

    def list_datasets(self) -> list[dict[str, Any]]:
        """Return catalog records as serializable dictionaries."""
        return [self._record_to_dict(record) for record in self.repository.list_datasets()]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return local catalog results ranked by query relevance."""
        query_tokens = self._tokens(query)
        scored = [
            self._score_record(record, query_tokens)
            for record in self.repository.list_datasets()
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
            "quality_score": record.quality_score,
            "quality_narrative": record.quality_narrative,
            "quality_metrics": record.quality_metrics,
            "dataset_card": record.dataset_card,
            "tags": record.tags,
            "description": record.description,
            "ai_summary": record.ai_summary,
            "ai_provider": record.ai_provider,
            "created_at": record.created_at,
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
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return merged local and public dataset results."""
        local = self.catalog.search(query, limit=limit)
        public = self._public_results(query, limit) if include_public else []
        merged = sorted(
            [*local, *public],
            key=lambda item: item.get("relevance_score", item.get("discovery_score", 0.0)),
            reverse=True,
        )[:limit]
        return {
            "query": query,
            "include_public": include_public,
            "results": merged,
            "counts": {
                "local": len(local),
                "public": len(public),
                "returned": len(merged),
            },
        }

    def _public_results(self, query: str, limit: int) -> list[dict[str, Any]]:
        discovery_payload = self.discovery.search(query, limit=limit)
        candidates = discovery_payload.get("results", [])[:limit]
        results = []
        for candidate in candidates:
            score = candidate.get("discovery_score", 0.0) or min(
                1.0,
                float(candidate.get("downloads", 0)) / 5000,
            )
            results.append(
                {
                    **candidate,
                    "source": "public",
                    "relevance_score": score,
                    "discovery_score": score,
                    "recommendation": (
                        "Recommended from live public discovery because provider "
                        "metadata and source popularity matched the query."
                    ),
                }
            )
        return results

    def _domain_hint(self, query: str) -> str:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", query.lower())
            if token not in {"find", "dataset", "datasets", "for", "the", "with"}
        ]
        return tokens[0] if tokens else "general"
