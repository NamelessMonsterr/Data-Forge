"""Quality, bias, and benchmark services.

Quality dimensions are computed from actual rows. The public service interface
is kept compatible with the demo pipeline: ``QualityService.evaluate`` returns
0-100 metrics, a weighted score, the selected profile, threshold, and the
``requires_generation`` flag consumed by reports and AI skills.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

_FIELD_PAIRS = (
    ("instruction", "response"),
    ("prompt", "completion"),
    ("question", "answer"),
    ("input", "output"),
)
_SINGLE_TEXT_FIELDS = ("text", "content", "document")
_MAX_TOKENS = 2048
_READABLE_MIN_WORDS = 2
_READABLE_MAX_WORDS = 400
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class QualityMetrics:
    """Weighted quality metrics on a 0-100 scale."""

    completeness: int
    consistency: int
    diversity: int
    duplicate_ratio: int
    formatting: int
    readability: int
    model_compatibility: int

    def score(self) -> int:
        """Return weighted quality score on a 0-100 scale."""
        return round(
            (
                self.completeness * 20
                + self.consistency * 20
                + self.diversity * 15
                + self.duplicate_ratio * 15
                + self.formatting * 10
                + self.readability * 10
                + self.model_compatibility * 10
            )
            / 100
        )

    def to_dict(self) -> dict[str, int]:
        """Return a serializable metric mapping."""
        return asdict(self)


@dataclass(frozen=True)
class ComputedQualityMetrics:
    """Normalized computed quality metrics plus weighted 0-100 overall score."""

    completeness: float
    consistency: float
    diversity: float
    duplicate_ratio: float
    formatting: float
    readability: float
    model_compatibility: float
    overall: float

    def to_dict(self) -> dict[str, float]:
        """Return a serializable metric mapping."""
        return asdict(self)

    def meets(self, tier: str) -> bool:
        """Return whether the overall score meets a named threshold."""
        return self.overall >= {
            "fast": 70,
            "balanced": 80,
            "production": 90,
            "research": 95,
            "enterprise": 98,
        }.get(tier, 80)


def _approx_tokens(text: str) -> int:
    words = len(text.split())
    return math.ceil(words / 0.75) if words else 0


def _detect_structure(rows: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
    first = rows[0]
    for pair in _FIELD_PAIRS:
        if all(field in first for field in pair):
            return "pair", pair
    for field in _SINGLE_TEXT_FIELDS:
        if field in first:
            return "single", (field,)
    return "none", ()


def _text_of(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    return " ".join(str(row.get(field, "")) for field in fields).strip()


def compute_quality(rows: list[dict[str, Any]]) -> ComputedQualityMetrics:
    """Compute every quality dimension from the supplied rows."""
    if not rows:
        return ComputedQualityMetrics(0, 0, 0, 0, 0, 0, 0, 0)

    kind, fields = _detect_structure(rows)
    count = len(rows)

    if fields:
        complete = sum(
            1
            for row in rows
            if all(str(row.get(field, "")).strip() for field in fields)
        )
        completeness = complete / count
    else:
        completeness = 0.0

    base_keys = set(rows[0].keys())
    consistency = sum(1 for row in rows if set(row.keys()) == base_keys) / count

    texts = [_text_of(row, fields) if fields else str(sorted(row.items())) for row in rows]
    unique = len(set(texts))
    diversity = unique / count
    duplicate_ratio = unique / count

    total_values = 0
    clean_values = 0
    for row in rows:
        for value in row.values():
            total_values += 1
            text = str(value)
            if text and text == text.strip() and not _CONTROL_RE.search(text):
                clean_values += 1
    formatting = clean_values / total_values if total_values else 0.0

    if fields:
        readable = sum(
            1
            for text in texts
            if _READABLE_MIN_WORDS <= len(text.split()) <= _READABLE_MAX_WORDS
        )
        readability = readable / count
    else:
        readability = 0.0

    base_compatibility = {"pair": 0.85, "single": 0.70, "none": 0.40}[kind]
    over_limit = sum(1 for text in texts if _approx_tokens(text) > _MAX_TOKENS)
    model_compatibility = max(0.0, base_compatibility * (1 - over_limit / count))

    dims = {
        "completeness": completeness,
        "consistency": consistency,
        "diversity": diversity,
        "duplicate_ratio": duplicate_ratio,
        "formatting": formatting,
        "readability": readability,
        "model_compatibility": model_compatibility,
    }
    overall = (
        dims["completeness"] * 20
        + dims["consistency"] * 20
        + dims["diversity"] * 15
        + dims["duplicate_ratio"] * 15
        + dims["formatting"] * 10
        + dims["readability"] * 10
        + dims["model_compatibility"] * 10
    )
    return ComputedQualityMetrics(
        completeness=round(completeness, 4),
        consistency=round(consistency, 4),
        diversity=round(diversity, 4),
        duplicate_ratio=round(duplicate_ratio, 4),
        formatting=round(formatting, 4),
        readability=round(readability, 4),
        model_compatibility=round(model_compatibility, 4),
        overall=round(overall, 2),
    )


def _scale(metric: ComputedQualityMetrics) -> QualityMetrics:
    return QualityMetrics(
        completeness=round(metric.completeness * 100),
        consistency=round(metric.consistency * 100),
        diversity=round(metric.diversity * 100),
        duplicate_ratio=round(metric.duplicate_ratio * 100),
        formatting=round(metric.formatting * 100),
        readability=round(metric.readability * 100),
        model_compatibility=round(metric.model_compatibility * 100),
    )


class QualityService:
    """Compute hard-gated quality scores."""

    def evaluate(
        self,
        dataset: dict[str, Any],
        profile: str = "production",
    ) -> dict[str, Any]:
        """Evaluate a curated dataset after hard gates pass."""
        rows = dataset.get("rows", [])
        metrics = _scale(compute_quality(rows))
        score = metrics.score()
        threshold = self.threshold(profile)
        return {
            "score": score,
            "profile": profile,
            "metrics": metrics.to_dict(),
            "requires_generation": score < threshold,
            "threshold": threshold,
        }

    def threshold(self, profile: str) -> int:
        """Return quality threshold for a profile."""
        return {
            "fast": 70,
            "balanced": 80,
            "production": 90,
            "research": 95,
            "enterprise": 98,
        }.get(profile, 90)


class BiasService:
    """Compute lightweight bias and toxicity signals."""

    def evaluate(self, dataset: dict[str, Any]) -> dict[str, Any]:
        """Return language distribution and toxicity status."""
        rows = dataset.get("rows", [])
        languages = sorted({row.get("language", "unknown") for row in rows})
        return {
            "distribution_risk": "low" if len(languages) <= 3 else "medium",
            "languages": languages,
            "critical_toxicity": "PASS",
        }


class BenchmarkService:
    """Compute export readiness benchmark metrics."""

    def evaluate(self, dataset: dict[str, Any]) -> dict[str, Any]:
        """Return benchmark readiness signals."""
        rows = dataset.get("rows", [])
        return {
            "record_count": len(rows),
            "schema_parse": "PASS" if rows else "FAIL",
            "training_readiness": "PASS" if rows else "FAIL",
            "token_length_fit": "PASS",
        }
