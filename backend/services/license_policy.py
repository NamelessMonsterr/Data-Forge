"""License hard-gate policy service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PERMISSIVE_LICENSES = {
    "apache-2.0",
    "mit",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc-by-4.0",
}

RESEARCH_ONLY_LICENSES = {
    "cc-by-nc-4.0",
    "research-only",
    "academic-only",
}


@dataclass(frozen=True)
class LicenseDecision:
    """License compatibility decision for one dataset."""

    dataset_id: str
    license: str
    compatible: bool
    reason: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable decision."""
        return self.__dict__


class LicensePolicy:
    """Evaluate dataset license compatibility before any data use."""

    def evaluate(
        self,
        candidates: list[dict[str, Any]],
        intended_use: str = "commercial",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return compatible candidates and all license decisions."""
        decisions: list[LicenseDecision] = []
        compatible: list[dict[str, Any]] = []
        for candidate in candidates:
            license_name = str(
                candidate.get("verified_license")
                or candidate.get("license_guess")
                or candidate.get("license")
                or "unknown"
            ).lower()
            dataset_id = str(candidate.get("id", "unknown"))
            if license_name in PERMISSIVE_LICENSES:
                decision = LicenseDecision(
                    dataset_id=dataset_id,
                    license=license_name,
                    compatible=True,
                    reason="License is compatible with commercial and research use.",
                    status="APPROVED",
                )
                compatible.append(
                    {
                        **candidate,
                        "verified_license": license_name,
                        "status": "approved",
                        "license": license_name,
                    }
                )
            elif intended_use != "commercial" and license_name in RESEARCH_ONLY_LICENSES:
                decision = LicenseDecision(
                    dataset_id=dataset_id,
                    license=license_name,
                    compatible=True,
                    reason="License is compatible with the requested non-commercial use.",
                    status="APPROVED",
                )
                compatible.append(
                    {
                        **candidate,
                        "verified_license": license_name,
                        "status": "approved",
                        "license": license_name,
                    }
                )
            elif license_name == "unknown":
                decision = LicenseDecision(
                    dataset_id=dataset_id,
                    license=license_name,
                    compatible=False,
                    reason="License could not be verified; candidate is not ingested automatically.",
                    status="UNKNOWN",
                )
            else:
                decision = LicenseDecision(
                    dataset_id=dataset_id,
                    license=license_name,
                    compatible=False,
                    reason="License is incompatible with the requested use.",
                    status="REJECTED",
                )
            decisions.append(decision)
        return compatible, [decision.to_dict() for decision in decisions]
