"""Optional OpenXML SDK schema-gate state tests."""

from pathlib import Path

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.formats.pptx.schema_validation import (
    validate_schema_gate,
    with_schema_gate,
)


class _Provider:
    def __init__(
        self,
        evidence: DetectionEvidence,
        result: dict[str, object] | None,
    ) -> None:
        self.evidence = evidence
        self.result = result

    def detect(self) -> DetectionEvidence:
        return self.evidence

    def try_validate_schema(self, _path: Path) -> dict[str, object] | None:
        return self.result


def test_schema_gate_is_optional_unavailable_when_provider_is_absent(tmp_path: Path) -> None:
    provider = _Provider(
        DetectionEvidence(False, reason="OpenXML SDK is absent."),
        None,
    )
    gate = validate_schema_gate(tmp_path / "candidate.pptx", provider)
    report = with_schema_gate(_report(), gate)

    assert gate["outcome"] == "unavailable"
    assert gate["required"] is False
    assert report["status"] == "pass"


def test_schema_gate_passes_and_becomes_required_when_provider_runs(tmp_path: Path) -> None:
    provider = _Provider(
        DetectionEvidence(True, version="3.0.0"),
        {"valid": True, "errors": []},
    )
    gate = validate_schema_gate(tmp_path / "candidate.pptx", provider)
    report = with_schema_gate(_report(), gate)

    assert gate["outcome"] == "pass"
    assert gate["required"] is True
    assert gate["version"] == "3.0.0"
    assert report["status"] == "pass"


def test_schema_gate_fails_required_on_invalid_document_or_provider_failure(
    tmp_path: Path,
) -> None:
    invalid = _Provider(
        DetectionEvidence(True, version="3.0.0"),
        {"valid": False, "errors": [{"description": "invalid"}]},
    )
    failed = _Provider(DetectionEvidence(True, version="3.0.0"), None)

    invalid_gate = validate_schema_gate(tmp_path / "candidate.pptx", invalid)
    failed_gate = validate_schema_gate(tmp_path / "candidate.pptx", failed)

    assert invalid_gate["outcome"] == "fail"
    assert invalid_gate["evidence"]["error_count"] == 1
    assert failed_gate["outcome"] == "fail"
    assert with_schema_gate(_report(), invalid_gate)["status"] == "fail"
    assert with_schema_gate(_report(), failed_gate)["status"] == "fail"


def _report() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "pass",
        "gates": [{
            "duration_ms": 0,
            "evidence": {"reason": "not configured"},
            "id": "schema.full",
            "outcome": "unavailable",
            "required": False,
            "validator": "document-skills-core",
            "version": None,
            "warnings": [],
        }],
    }
