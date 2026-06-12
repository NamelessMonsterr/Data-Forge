"""Dependency-free semantic scoring utilities for dataset search."""

from __future__ import annotations

from collections import Counter
from math import sqrt
import re


SYNONYMS = {
    "accident": {"crash", "collision", "incident"},
    "accidents": {"crashes", "collisions", "incidents"},
    "traffic": {"road", "vehicle", "transport"},
    "diabetes": {"glucose", "insulin", "bmi", "outcome"},
    "fraud": {"anomaly", "risk", "transaction"},
    "healthcare": {"medical", "clinical", "patient"},
    "crop": {"agriculture", "plant", "farm"},
}


class SemanticTextEncoder:
    """Small lexical-semantic encoder for offline search demos."""

    def encode(self, text: str) -> dict[str, float]:
        """Return a sparse semantic vector with synonym expansion."""
        tokens = self._tokens(text)
        expanded = []
        for token in tokens:
            expanded.append(token)
            expanded.extend(SYNONYMS.get(token, set()))
        counts = Counter(expanded)
        return {token: float(count) for token, count in counts.items()}

    def similarity(self, left: str, right: str) -> float:
        """Return cosine similarity between two text payloads."""
        return self.cosine(self.encode(left), self.encode(right))

    def cosine(self, left: dict[str, float], right: dict[str, float]) -> float:
        """Return cosine similarity between sparse vectors."""
        if not left or not right:
            return 0.0
        shared = set(left) & set(right)
        dot = sum(left[token] * right[token] for token in shared)
        left_norm = sqrt(sum(value * value for value in left.values()))
        right_norm = sqrt(sum(value * value for value in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    def _tokens(self, text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 1
        ]
