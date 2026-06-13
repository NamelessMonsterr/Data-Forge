"""Agent layer that actually uses the model path.

The previous registry shipped inert ``DeterministicAgent`` instances; several
declared ``requires_llm=True`` but none ever called a model. This module gives
the two agents that matter -- generation and critique -- real behavior driven by
the :class:`LLMOrchestrator`, with a clearly labeled deterministic fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .llm_provider import LLMOrchestrator, LLMResult


@dataclass(frozen=True)
class AgentResult:
    agent: str
    output: dict[str, Any]
    provider: str
    fallback_used: bool
    requires_llm: bool


def _extract_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


class GeneratorAgent:
    name = "generator"
    requires_llm = True

    def __init__(self, orchestrator: LLMOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or LLMOrchestrator()

    def run(self, fields: list[str], count: int = 3, topic: str = "general") -> AgentResult:
        prompt = (
            "You generate high-quality supervised training rows. Return ONLY a JSON "
            f"array of {count} objects, each with keys {fields}. Topic: {topic}."
        )
        result: LLMResult = self.orchestrator.generate(prompt, max_tokens=1024)
        rows = self._parse_rows(result.text, fields)
        fallback_used = result.fallback_used
        if not rows:
            rows = self._deterministic_rows(fields, count, topic)
            fallback_used = True
        return AgentResult(
            agent=self.name,
            output={"rows": rows[:count], "requested": count},
            provider=result.provider,
            fallback_used=fallback_used,
            requires_llm=self.requires_llm,
        )

    def _parse_rows(self, text: str, fields: list[str]) -> list[dict[str, Any]]:
        parsed = _extract_json(text)
        if not isinstance(parsed, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict) and all(f in item for f in fields):
                rows.append({f: item[f] for f in fields})
        return rows

    def _deterministic_rows(self, fields: list[str], count: int, topic: str) -> list[dict[str, Any]]:
        return [
            {f: f"[deterministic] {f} #{i} about {topic}" for f in fields}
            for i in range(count)
        ]


class CriticAgent:
    name = "critic"
    requires_llm = True

    def __init__(self, orchestrator: LLMOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or LLMOrchestrator()

    def run(self, rows: list[dict[str, Any]]) -> AgentResult:
        sample = rows[:5]
        prompt = (
            "Critique these training rows. Return ONLY JSON: "
            '{"verdict": "accept"|"revise"|"reject", "issues": [..], "score": 0-100}. '
            f"Rows: {json.dumps(sample)[:2000]}"
        )
        result = self.orchestrator.generate(prompt, max_tokens=512)
        verdict = self._parse_verdict(result.text)
        fallback_used = result.fallback_used
        if verdict is None:
            verdict = self._deterministic_verdict(rows)
            fallback_used = True
        return AgentResult(
            agent=self.name,
            output=verdict,
            provider=result.provider,
            fallback_used=fallback_used,
            requires_llm=self.requires_llm,
        )

    def _parse_verdict(self, text: str):
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            return None
        if parsed.get("verdict") not in {"accept", "revise", "reject"}:
            return None
        return {
            "verdict": parsed["verdict"],
            "issues": list(parsed.get("issues") or []),
            "score": int(parsed.get("score") or 0),
        }

    def _deterministic_verdict(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        empties = sum(1 for r in rows for v in r.values() if v in (None, ""))
        verdict = "accept" if empties == 0 else "revise"
        return {
            "verdict": verdict,
            "issues": [] if empties == 0 else [f"{empties} empty field(s)"],
            "score": 90 if empties == 0 else 60,
        }


@dataclass
class AgentRegistry:
    orchestrator: LLMOrchestrator = field(default_factory=LLMOrchestrator)

    def __post_init__(self) -> None:
        self._agents = {
            "generator": GeneratorAgent(self.orchestrator),
            "critic": CriticAgent(self.orchestrator),
        }

    def get(self, name: str):
        return self._agents[name]

    def names(self) -> list[str]:
        return sorted(self._agents)
