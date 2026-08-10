"""Cross-format validation-authoritative transaction behavior."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record, make_error_result
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import destination_snapshot
from document_skills_core.core.io.temp_roots import OperationTempRoot


_FORMATS = ("docx", "xlsx", "pptx", "pdf")


@pytest.mark.parametrize("format_id", _FORMATS)
def test_actual_report_is_preserved_and_exact_bytes_promote_atomically(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(f"validated-{format_id}".encode("ascii"))
    output = tmp_path / f"output.{format_id}"
    request = _request(format_id, output)
    report = _report(candidate)

    result = _write(module, SchemaCatalog(project_root), request, candidate, report)
    promoted = module.promote_candidate(
        request,
        candidate,
        result,
        source=None,
        destination=destination_snapshot(output),
    )

    assert promoted["validation"] == report
    assert promoted["artifacts"][-1]["sha256"] == _sha256(output)
    assert output.read_bytes() == candidate.read_bytes()


@pytest.mark.parametrize("format_id", _FORMATS)
@pytest.mark.parametrize("outcome", ["fail", "unavailable", "not_run"])
def test_required_nonpass_is_schema_valid_and_cleans_private_candidate(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
    outcome: str,
) -> None:
    module = _transaction(format_id)
    output = tmp_path / f"existing.{format_id}"
    output.write_bytes(b"existing")
    before = _sha256(output)
    request = _request(format_id, output)
    private_base = tmp_path / "document-skills-operations"

    with OperationTempRoot(base=private_base) as private_root:
        candidate = private_root / f"candidate.{format_id}"
        candidate.write_bytes(b"candidate")
        report = _report(candidate, outcome=outcome)
        with pytest.raises(DocumentSkillsError) as captured:
            _write(module, SchemaCatalog(project_root), request, candidate, report)
        error_result = make_error_result(request.operation, captured.value)

    SchemaCatalog(project_root).validate("operation-result", error_result)
    assert captured.value.validation == report
    assert error_result["validation"] == report
    assert not error_result["artifacts"]
    assert _sha256(output) == before
    assert list(private_base.iterdir()) == []


@pytest.mark.parametrize("format_id", _FORMATS)
def test_post_validation_mutation_is_rejected_before_destination_change(
    project_root: Path,
    tmp_path: Path,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(b"validated")
    output = tmp_path / f"output.{format_id}"
    output.write_bytes(b"existing")
    before = _sha256(output)
    request = _request(format_id, output)
    report = _report(candidate)
    result = _write(module, SchemaCatalog(project_root), request, candidate, report)
    candidate.write_bytes(b"changed-after-validation")

    with pytest.raises(DocumentSkillsError) as captured:
        module.promote_candidate(
            request,
            candidate,
            result,
            source=None,
            destination=destination_snapshot(output),
        )

    assert captured.value.details["candidate_identity_mismatch"] is True
    assert _sha256(output) == before


@pytest.mark.parametrize("format_id", _FORMATS)
def test_destination_race_is_detected_without_overwriting_concurrent_bytes(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_id: str,
) -> None:
    module = _transaction(format_id)
    candidate = tmp_path / f"candidate.{format_id}"
    candidate.write_bytes(b"validated")
    output = tmp_path / f"output.{format_id}"
    output.write_bytes(b"initial")
    request = _request(format_id, output)
    result = _write(module, SchemaCatalog(project_root), request, candidate, _report(candidate))
    snapshot = destination_snapshot(output)
    real_promote = module.atomic_promote

    def race(*args: Any, **kwargs: Any) -> Any:
        output.write_bytes(b"concurrent")
        return real_promote(*args, **kwargs)

    monkeypatch.setattr(module, "atomic_promote", race)
    with pytest.raises(DocumentSkillsError) as captured:
        module.promote_candidate(
            request,
            candidate,
            result,
            source=None,
            destination=snapshot,
        )

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["destination_race"] is True
    assert output.read_bytes() == b"concurrent"


def _transaction(format_id: str) -> Any:
    return importlib.import_module(
        f"document_skills_core.formats.{format_id}.transaction"
    )


def _request(format_id: str, output: Path) -> Any:
    return SimpleNamespace(
        operation=f"{format_id}.create",
        output_path=output,
        requested_fidelity="core",
    )


def _write(
    module: Any,
    schemas: SchemaCatalog,
    request: Any,
    candidate: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    return module.write_candidate_result(
        schemas,
        request,
        candidate,
        report,
        {"transaction_test": True},
        warnings=[],
        source=None,
    )


def _report(path: Path, *, outcome: str = "pass") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "pass" if outcome == "pass" else "fail",
        "gates": [
            gate_record(
                "artifact.identity",
                outcome,
                required=True,
                validator="cross-format-test",
                evidence={"sha256": _sha256(path), "bytes": path.stat().st_size},
            )
        ],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
