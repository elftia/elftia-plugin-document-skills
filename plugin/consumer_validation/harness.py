"""Aggregate portable and conditional Office consumer evidence."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
from typing import Any

from .contracts import validate_consumer_report
from .office import detect_office, open_with_office, trusted_office_identity
from .ooxml import qualify_ooxml
from .pdf import (
    evidence_failure_gate,
    observe_pdf_artifact,
    qualify_pdf,
    source_change_gate,
)


OfficeDetector = Callable[[str], dict[str, Any]]
OfficeRunner = Callable[[str, Path, float], dict[str, Any]]
_APPLICATIONS = {"docx": "word", "xlsx": "excel", "pptx": "powerpoint"}


def qualify_artifact(
    *,
    format_id: str,
    operation: str,
    artifact: str | Path,
    expectations: dict[str, Any] | None = None,
    office_policy: str = "auto",
    office_detector: OfficeDetector | None = None,
    office_runner: OfficeRunner | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Qualify one bounded artifact without calling producer format code."""

    if format_id not in {"docx", "xlsx", "pptx", "pdf"}:
        raise ValueError(f"Unsupported consumer format: {format_id}")
    if office_policy not in {"auto", "off"}:
        raise ValueError(f"Unsupported Office policy: {office_policy}")
    resolved = Path(artifact).resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError("Artifact is missing or empty.")
    if format_id == "pdf":
        return _qualify_pdf_artifact(
            operation=operation,
            artifact=resolved,
            expectations=expectations or {},
            office_policy=office_policy,
            detector=office_detector or detect_office,
            runner=office_runner or open_with_office,
            timeout_seconds=timeout_seconds,
        )
    before = _sha256(resolved)
    portable = qualify_ooxml(format_id, resolved, expectations or {})
    office = _office_gate(
        format_id,
        resolved,
        office_policy,
        office_detector or detect_office,
        office_runner or open_with_office,
        timeout_seconds,
    )
    after = _sha256(resolved)
    if before != after:
        office = {
            "consumer": office["consumer"],
            "availability": office["availability"],
            "outcome": "fail",
            "assertions": office["assertions"]
            + [
                {
                    "id": "consumer.source-preservation",
                    "outcome": "fail",
                    "evidence": {"before_sha256": before, "after_sha256": after},
                    "message": "Consumer changed the artifact under qualification.",
                }
            ],
            "warnings": office["warnings"],
            "evidence": office["evidence"],
        }
    return _build_report(
        format_id=format_id,
        operation=operation,
        artifact=resolved,
        artifact_sha256=after,
        sha256_status=None,
        artifact_bytes=resolved.stat().st_size,
        portable=portable,
        office=office,
        office_policy=office_policy,
    )


def _qualify_pdf_artifact(
    *,
    operation: str,
    artifact: Path,
    expectations: dict[str, Any],
    office_policy: str,
    detector: OfficeDetector,
    runner: OfficeRunner,
    timeout_seconds: float,
) -> dict[str, Any]:
    before = observe_pdf_artifact(artifact)
    office = _office_gate(
        "pdf",
        artifact,
        office_policy,
        detector,
        runner,
        timeout_seconds,
    )
    if before.outcome != "exact":
        rejection = evidence_failure_gate(before, phase="initial")
        if before.outcome == "resource-limit":
            return _build_report(
                format_id="pdf",
                operation=operation,
                artifact=artifact,
                artifact_sha256=None,
                sha256_status="not-computed-resource-limit",
                artifact_bytes=before.artifact_bytes,
                portable=rejection,
                office=office,
                office_policy=office_policy,
            )
        retry = observe_pdf_artifact(artifact)
        if retry.outcome == "resource-limit":
            return _build_report(
                format_id="pdf",
                operation=operation,
                artifact=artifact,
                artifact_sha256=None,
                sha256_status="not-computed-resource-limit",
                artifact_bytes=retry.artifact_bytes,
                portable=evidence_failure_gate(retry, phase="initial-retry"),
                office=office,
                office_policy=office_policy,
            )
        if retry.outcome != "exact":
            rejection = _merge_portable_gate(
                rejection,
                evidence_failure_gate(retry, phase="initial-retry"),
            )
            observed = retry if retry.sha256 is not None else before
            if observed.sha256 is None:
                raise RuntimeError(
                    "PDF artifact remained unreadable across bounded evidence attempts."
                )
            return _build_report(
                format_id="pdf",
                operation=operation,
                artifact=artifact,
                artifact_sha256=observed.sha256,
                sha256_status=None,
                artifact_bytes=observed.artifact_bytes,
                portable=rejection,
                office=office,
                office_policy=office_policy,
            )
        if retry.sha256 is None:
            raise RuntimeError("Exact PDF evidence omitted its digest.")
        return _build_report(
            format_id="pdf",
            operation=operation,
            artifact=artifact,
            artifact_sha256=retry.sha256,
            sha256_status=None,
            artifact_bytes=retry.artifact_bytes,
            portable=rejection,
            office=office,
            office_policy=office_policy,
        )

    if before.sha256 is None:
        raise RuntimeError("Exact PDF evidence omitted its digest.")
    portable = qualify_pdf(artifact, expectations, artifact_evidence=before)
    after = observe_pdf_artifact(artifact)
    if after.outcome == "resource-limit":
        portable = _merge_portable_gate(
            portable,
            evidence_failure_gate(
                after,
                phase="post-consumer",
                before_sha256=before.sha256,
            ),
        )
        return _build_report(
            format_id="pdf",
            operation=operation,
            artifact=artifact,
            artifact_sha256=None,
            sha256_status="not-computed-resource-limit",
            artifact_bytes=after.artifact_bytes,
            portable=portable,
            office=office,
            office_policy=office_policy,
        )
    if after.outcome == "mutation":
        portable = _merge_portable_gate(
            portable,
            evidence_failure_gate(
                after,
                phase="post-consumer",
                before_sha256=before.sha256,
            ),
        )
        return _build_report(
            format_id="pdf",
            operation=operation,
            artifact=artifact,
            artifact_sha256=before.sha256,
            sha256_status=None,
            artifact_bytes=before.artifact_bytes,
            portable=portable,
            office=office,
            office_policy=office_policy,
        )
    if after.sha256 is None:
        raise RuntimeError("Exact PDF evidence omitted its digest.")
    if before.sha256 != after.sha256:
        portable = _merge_portable_gate(portable, source_change_gate(before, after))
    return _build_report(
        format_id="pdf",
        operation=operation,
        artifact=artifact,
        artifact_sha256=after.sha256,
        sha256_status=None,
        artifact_bytes=after.artifact_bytes,
        portable=portable,
        office=office,
        office_policy=office_policy,
    )


def _merge_portable_gate(
    portable: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    replaced_ids = {item["id"] for item in failure["assertions"]}
    retained = [
        item for item in portable["assertions"] if item["id"] not in replaced_ids
    ]
    return {
        **portable,
        "outcome": "fail",
        "assertions": retained + list(failure["assertions"]),
        "warnings": list(portable["warnings"]) + list(failure["warnings"]),
    }


def _build_report(
    *,
    format_id: str,
    operation: str,
    artifact: Path,
    artifact_sha256: str | None,
    sha256_status: str | None,
    artifact_bytes: int,
    portable: dict[str, Any],
    office: dict[str, Any],
    office_policy: str,
) -> dict[str, Any]:
    artifact_evidence: dict[str, Any] = {
        "path": str(artifact),
        "sha256": artifact_sha256,
        "bytes": artifact_bytes,
    }
    if sha256_status is not None:
        artifact_evidence["sha256_status"] = sha256_status
    status = _aggregate_status(portable["outcome"], office["outcome"], office_policy)
    report = {
        "schema_version": "1.0",
        "format": format_id,
        "operation": operation,
        "consumer_identity": "elftia-independent-consumer/1",
        "artifact": artifact_evidence,
        "status": status,
        "portable": portable,
        "office": office,
        "office_acceptance": office["outcome"] == "pass",
        "warnings": list(portable["warnings"]) + list(office["warnings"]),
    }
    validate_consumer_report(report)
    return report


def _office_gate(
    format_id: str,
    artifact: Path,
    office_policy: str,
    detector: OfficeDetector,
    runner: OfficeRunner,
    timeout_seconds: float,
) -> dict[str, Any]:
    application = _APPLICATIONS.get(format_id)
    if office_policy == "off" or application is None:
        return {
            "consumer": "microsoft-office-com/1",
            "availability": "not_requested",
            "outcome": "not_run",
            "assertions": [],
            "warnings": [],
            "evidence": {"reason": "policy-off" if office_policy == "off" else "not-office"},
        }
    detection = detector(application)
    if not detection.get("available", False):
        reason = str(detection.get("reason", "not-installed"))
        return {
            "consumer": "microsoft-office-com/1",
            "availability": "unavailable",
            "outcome": "unavailable",
            "assertions": [],
            "warnings": [reason],
            "evidence": detection,
        }
    runner_evidence = runner(application, artifact, timeout_seconds)
    evidence = {**detection, **runner_evidence}
    if evidence.get("category") == "timeout":
        evidence.update(trusted_office_identity(application, detection))
    evidence["application"] = str(evidence.get("application", application))
    version = evidence.get("version")
    if not isinstance(version, str) or not version:
        evidence["version"] = "unavailable"
        evidence["category"] = "application-version-unavailable"
        evidence["outcome"] = "fail"
    outcome = "pass" if evidence.get("outcome") == "pass" else "fail"
    return {
        "consumer": "microsoft-office-com/1",
        "availability": "available",
        "outcome": outcome,
        "assertions": [
            {
                "id": f"office.{application}.safe-open",
                "outcome": outcome,
                "evidence": {key: value for key, value in evidence.items() if key != "outcome"},
                "message": "" if outcome == "pass" else "Installed Office rejected the artifact.",
            }
        ],
        "warnings": [],
        "evidence": evidence,
    }


def _aggregate_status(portable: str, office: str, office_policy: str) -> str:
    if portable == "fail" or office == "fail":
        return "fail"
    if office_policy == "auto" and office == "unavailable":
        return "unavailable"
    return "pass"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
