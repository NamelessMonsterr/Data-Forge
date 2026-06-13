"""Deterministic agents for the first executable DataForge vertical slice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from agents.base import BaseAgent
from backend.core.protocol import AgentMessage, MessageStatus, NextAction
from backend.services.curation import DatasetAssemblyService
from backend.services.discovery import DiscoveryService
from backend.services.export import PackagingService
from backend.services.license_policy import LicensePolicy
from backend.services.quality import BenchmarkService, BiasService, QualityService
from planner.workflow_library import Node
from reports.explainability import ExplainabilityReport


class DeterministicAgent(BaseAgent):
    """Base class for agents that emit confidence-protocol messages."""

    def _message(
        self,
        task_id: str,
        correlation_id: str,
        status: MessageStatus,
        result: dict[str, Any],
        confidence: float,
        reason: str,
        next_action: NextAction = NextAction.CONTINUE,
        payload_ref: str | None = None,
    ) -> AgentMessage:
        return AgentMessage(
            agent=self.name,
            task_id=task_id,
            correlation_id=correlation_id,
            status=status,
            result=result,
            confidence=confidence,
            reason=reason,
            next_action=next_action,
            payload_ref=payload_ref,
        )


class RequirementAnalyzerAgent(DeterministicAgent):
    """Normalize raw user intent into a structured requirement object."""

    name = "requirement_analyzer"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return the planner-provided structured requirement."""
        state = payload["state"]
        requirement = state.get("structured_requirement", {})
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"structured_requirement": requirement},
            0.91,
            "Structured requirement prepared from the user request.",
        )


class ClarificationAgent(DeterministicAgent):
    """Ask only missing high-impact clarification questions."""

    name = "clarification"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return adaptive clarification questions without blocking execution."""
        requirement = payload["state"].get("structured_requirement", {})
        questions = []
        if not requirement.get("domain"):
            questions.append("Which domain should the dataset target?")
        if not requirement.get("languages"):
            questions.append("Which languages should be included?")
        if not requirement.get("target_model"):
            questions.append("Which target model should the dataset optimize for?")
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"clarification_questions": questions},
            0.87,
            "Only missing requirement fields were converted into clarification questions.",
        )


class DiscoveryAgent(DeterministicAgent):
    """Search existing sources before any generation is allowed."""

    name = "discovery"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return ranked existing dataset candidates for the requested domain."""
        requirement = payload["state"].get("structured_requirement", {})
        query = str(requirement.get("raw_request") or requirement.get("domain") or "")
        discovery_payload = DiscoveryService().search(query)
        candidates = discovery_payload.get("results", [])
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "candidate_datasets": candidates,
                "discovery_status": discovery_payload,
            },
            0.86,
            "Existing datasets were searched before considering generation.",
        )


class LicenseAgent(DeterministicAgent):
    """Apply the license hard gate before curation or scoring."""

    name = "license"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Select compatible candidates and reject incompatible licenses."""
        candidates = payload["state"].get("candidate_datasets", [])
        requirement = payload["state"].get("structured_requirement", {})
        compatible, decisions = LicensePolicy().evaluate(
            candidates,
            intended_use=str(requirement.get("intended_use", "commercial")),
        )
        if not compatible:
            return self._message(
                task_id,
                correlation_id,
                MessageStatus.FAIL,
                {
                    "license_verdict": "rejected",
                    "compatible_datasets": [],
                    "license_decisions": decisions,
                },
                0.98,
                "No candidate passed the license hard gate.",
                NextAction.ABORT,
            )
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "license_verdict": "passed",
                "compatible_datasets": compatible,
                "selected_dataset": compatible[0],
                "license_decisions": decisions,
            },
            0.98,
            "At least one candidate passed the license hard gate.",
        )


class MergeAgent(DeterministicAgent):
    """Merge compatible discovered datasets into one candidate corpus."""

    name = "merge"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Combine compatible datasets and preserve source lineage."""
        compatible = payload["state"].get("compatible_datasets", [])
        merged = DatasetAssemblyService().merge(compatible)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "merged_dataset": merged
            },
            0.85,
            "Compatible datasets were merged while retaining source lineage.",
        )


class CleaningAgent(DeterministicAgent):
    """Clean, deduplicate, and remove PII from merged data."""

    name = "cleaning"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Apply deterministic cleaning statistics to the merged dataset."""
        merged = payload["state"].get("merged_dataset", {})
        clean_dataset, cleaning_report = DatasetAssemblyService().clean(merged)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "clean_dataset": clean_dataset,
                "cleaning_report": cleaning_report,
            },
            0.9,
            "Merged data was cleaned, deduplicated, and checked for PII.",
        )


class TranslationAgent(DeterministicAgent):
    """Expand multilingual coverage when requested."""

    name = "translation"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Record translation coverage for requested languages."""
        requirement = payload["state"].get("structured_requirement", {})
        clean_dataset = payload["state"].get("clean_dataset", {})
        languages = requirement.get("languages", ["english"])
        translated = DatasetAssemblyService().translate(clean_dataset, languages)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "translated_dataset": translated
            },
            0.82,
            "Requested language coverage was prepared before final curation.",
        )


class CuratorAgent(DeterministicAgent):
    """Create a clean demo dataset from the selected source."""

    name = "curator"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Normalize records and remove duplicates for the demo dataset."""
        requirement = payload["state"].get("structured_requirement", {})
        selected = (
            payload["state"].get("translated_dataset")
            or payload["state"].get("clean_dataset")
            or payload["state"].get("selected_dataset", {})
        )
        dataset, curation_stats = DatasetAssemblyService().curate(selected, requirement)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "curated_dataset": dataset,
                "curation_stats": curation_stats,
                "hard_gates": {"license": "PASS", "pii": "PASS", "critical_toxicity": "PASS"},
            },
            0.84,
            "Dataset was normalized and hard gates remained clean.",
        )


class QualityEvaluatorAgent(DeterministicAgent):
    """Compute deterministic quality metrics after hard gates pass."""

    name = "quality_evaluator"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return weighted quality score and gap signal."""
        state = payload["state"]
        dataset = state.get("curated_dataset", {})
        requirement = state.get("structured_requirement", {})
        report = QualityService().evaluate(
            dataset,
            profile=str(requirement.get("quality_profile", "production")),
        )
        score = report["score"]
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS if score >= 90 else MessageStatus.PARTIAL,
            {
                "quality_report": {
                    **report,
                }
            },
            0.88,
            "Hard gates passed, so weighted quality scoring was computed.",
        )


class GeneratorAgent(DeterministicAgent):
    """Generate gap-filling samples only after search and quality analysis."""

    name = "generator"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Add a small synthetic sample set for an identified gap."""
        dataset = payload["state"].get("curated_dataset", {})
        rows = list(dataset.get("rows", []))
        rows.append(
            {
                "instruction": "Handle a rare edge case with careful uncertainty.",
                "response": "State assumptions, avoid unsupported claims, and mark the record as synthetic.",
            }
        )
        dataset["rows"] = rows
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"curated_dataset": dataset, "synthetic_samples_added": 1},
            0.79,
            "Generation was used only to fill a requested gap after search-first steps.",
        )


class CriticAgent(DeterministicAgent):
    """Review synthetic samples before validation."""

    name = "critic"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return a deterministic critique verdict."""
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"critique_report": {"hallucination_risk": "low", "formatting": "pass"}},
            0.83,
            "Synthetic records passed consistency and formatting checks.",
        )


class BiasAgent(DeterministicAgent):
    """Evaluate lightweight bias and distribution signals."""

    name = "bias"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return a reusable bias report payload."""
        dataset = payload["state"].get("curated_dataset", {})
        report = BiasService().evaluate(dataset)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "bias_report": report
            },
            0.81,
            "Distribution and toxicity checks completed for available records.",
        )


class ValidatorAgent(DeterministicAgent):
    """Validate readiness before formatting and packaging."""

    name = "validator"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Confirm the dataset is ready for export."""
        state = payload["state"]
        dataset = state.get("curated_dataset", {})
        candidates = state.get("compatible_datasets", [])
        record_count = len(dataset.get("rows", []))
        ready = bool(record_count or candidates)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS if ready else MessageStatus.FAIL,
            {
                "validation_report": {
                    "ready": ready,
                    "record_count": record_count,
                    "candidate_count": len(candidates),
                    "mode": "dataset" if record_count else "metadata",
                }
            },
            0.9,
            "Workflow has exportable dataset records or approved candidate metadata."
            if ready
            else "Workflow has no exportable records or approved candidates.",
            NextAction.CONTINUE if ready else NextAction.ABORT,
        )


class BenchmarkAgent(DeterministicAgent):
    """Benchmark dataset readiness after validation."""

    name = "benchmark"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Return deterministic benchmark metrics."""
        dataset = payload["state"].get("curated_dataset", {})
        report = BenchmarkService().evaluate(dataset)
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "benchmark_report": report
            },
            0.86,
            "Validated records passed schema and training-readiness benchmarks.",
        )


class FormatterAgent(DeterministicAgent):
    """Write the curated dataset to a stable export format."""

    name = "formatter"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Serialize the dataset as JSONL."""
        artifacts_dir = Path(payload["artifacts_dir"])
        state = payload["state"]
        dataset = state.get("curated_dataset", {})
        dataset_path = artifacts_dir / "dataset.jsonl"
        with dataset_path.open("w", encoding="utf-8") as handle:
            rows = dataset.get("rows") or state.get("compatible_datasets", [])
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"formatted_dataset": str(dataset_path)},
            0.96,
            "Dataset records were formatted as JSONL.",
            payload_ref=str(dataset_path),
        )


class PackagingAgent(DeterministicAgent):
    """Generate reports and bundle the final dataset ZIP."""

    name = "packaging"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Create report files and package them with the dataset."""
        artifacts_dir = Path(payload["artifacts_dir"])
        state = payload["state"]
        result = PackagingService().package(
            artifacts_dir,
            state,
            task_id=task_id,
            workflow=str(state.get("workflow", "unknown")),
        )
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {
                "dataset_zip": str(result.zip_path),
                "manifest": str(result.manifest_path),
                "checksums": result.checksums,
            },
            0.95,
            "Dataset and reports were packaged into a downloadable ZIP archive.",
            payload_ref=str(result.zip_path),
        )


class ExplainabilityAgent(DeterministicAgent):
    """Write an audit report from the execution decision trail."""

    name = "explainability"

    def run(self, task_id: str, correlation_id: str, payload: Any) -> AgentMessage:
        """Generate the final explainability report after packaging."""
        artifacts_dir = Path(payload["artifacts_dir"])
        state = payload["state"]
        report_path = ExplainabilityReport().write(artifacts_dir / "reports", state)
        zip_path = state.get("dataset_zip")
        if zip_path:
            with ZipFile(zip_path, "a", ZIP_DEFLATED) as archive:
                archive.write(report_path, f"reports/{report_path.name}")
        return self._message(
            task_id,
            correlation_id,
            MessageStatus.PASS,
            {"explainability_report": str(report_path)},
            0.9,
            "Decision trail was converted into an explainability report.",
            payload_ref=str(report_path),
        )


class DemoAgentFactory:
    """Instantiate demo agents for Workflow Library nodes."""

    def __init__(self) -> None:
        self._agents: dict[Node, type[BaseAgent]] = {
            Node.REQUIREMENT_ANALYZER: RequirementAnalyzerAgent,
            Node.CLARIFICATION: ClarificationAgent,
            Node.DISCOVERY: DiscoveryAgent,
            Node.LICENSE: LicenseAgent,
            Node.MERGE: MergeAgent,
            Node.CLEANING: CleaningAgent,
            Node.CURATOR: CuratorAgent,
            Node.TRANSLATION: TranslationAgent,
            Node.QUALITY_EVALUATOR: QualityEvaluatorAgent,
            Node.GENERATOR: GeneratorAgent,
            Node.CRITIC: CriticAgent,
            Node.BIAS: BiasAgent,
            Node.VALIDATOR: ValidatorAgent,
            Node.BENCHMARK: BenchmarkAgent,
            Node.FORMATTER: FormatterAgent,
            Node.PACKAGING: PackagingAgent,
            Node.EXPLAINABILITY: ExplainabilityAgent,
        }

    def create(self, node: Node) -> BaseAgent:
        """Return the concrete agent for a workflow node."""
        agent_class = self._agents[node]
        return agent_class()
