"""Schemas used by deterministic demo agents."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DemoDataset(BaseModel):
    """Small dataset payload used for hackathon execution demos."""

    name: str
    license: str
    rows: list[dict[str, str]] = Field(default_factory=list)


class QualityMetrics(BaseModel):
    """Quality metrics aligned to the frozen quality framework."""

    completeness: int
    consistency: int
    diversity: int
    duplicate_ratio: int
    formatting: int
    readability: int
    model_compatibility: int

    def score(self) -> int:
        """Return the weighted quality score from the framework."""
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
