"""Provider-backed XLSX recalculation policy and promotion tests."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.mapping import map_workbook
from document_skills_core.formats.xlsx.package import OpcPackage
from document_skills_core.formats.xlsx.service import XlsxService
from document_skills_core.providers.libreoffice.recalc import RecalculatedXlsx


class ArtifactProvider:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def recalculate_xlsx_artifact(
        self,
        _input_path: Path,
        *,
        policy: str,
    ) -> RecalculatedXlsx:
        assert policy in {"auto", "required"}
        self.calls += 1
        return RecalculatedXlsx(self.payload, {})


class FailingProvider:
    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        self.calls = 0

    def recalculate_xlsx_artifact(
        self,
        _input_path: Path,
        *,
        policy: str,
    ) -> RecalculatedXlsx:
        assert policy in {"auto", "required"}
        self.calls += 1
        raise DocumentSkillsError(self.code, "Injected provider failure.")


class PolicyAwareProvider:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.policies: list[str] = []

    def recalculate_xlsx_artifact(
        self,
        _input_path: Path,
        *,
        policy: str,
    ) -> RecalculatedXlsx:
        self.policies.append(policy)
        return RecalculatedXlsx(self.payload, {})


def _workbook(
    *,
    formula: str = "SUM(A1:A2)",
    cached_value: str | None = None,
    result_type: str = "n",
) -> dict[str, object]:
    return {
        "metadata": {},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "10", "type": "n"},
                            {"ref": "A2", "value": "20", "type": "n"},
                            {
                                "ref": "A3",
                                "formula": formula,
                                "cached_value": cached_value,
                                "type": result_type,
                            },
                        ]
                    }
                ],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
    }


def _write_workbook(path: Path, **options: object) -> Path:
    create_xlsx(path, _workbook(**options))
    return path


def _provider(tmp_path: Path, **options: object) -> ArtifactProvider:
    artifact = _write_workbook(tmp_path / "provider.xlsx", **options)
    return ArtifactProvider(artifact.read_bytes())


def _create_request(
    output: Path,
    *,
    policy: str = "auto",
) -> dict[str, object]:
    return {
        "operation": "xlsx.create",
        "output": str(output),
        "arguments": {
            "workbook": _workbook(),
            "recalculation": policy,
        },
        "options": {"fidelity": "core", "in_place": False},
    }


def _recalculate_request(source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "xlsx.recalculate",
        "input": str(source),
        "output": str(output),
        "arguments": {},
        "options": {"fidelity": "core", "in_place": False},
    }


def _edit_request(
    source: Path,
    output: Path,
    *,
    policy: str = "auto",
) -> dict[str, object]:
    return {
        "operation": "xlsx.edit",
        "input": str(source),
        "output": str(output),
        "arguments": {
            "edits": [
                {"type": "cell_value", "sheet": "Sheet1", "ref": "A1", "value": "11"}
            ],
            "expected_edits": 1,
            "recalculation": policy,
        },
        "options": {"fidelity": "core", "in_place": False},
    }


def _formula_record(path: Path) -> dict[str, object]:
    return map_workbook(OpcPackage.open(path))["formula_cells"]["Sheet1!A3"]


def test_create_auto_accepts_provider_and_reopens_cached_value(
    project_root: Path,
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path, cached_value="30")
    output = tmp_path / "created.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output),
    )

    formula = result["diagnostics"]["operation_result"]["formula_state"]
    assert result["status"] == "success"
    assert result["provider_chain"] == ["libreoffice"]
    assert result["achieved_fidelity"] == "enhanced"
    assert formula["cells"]["Sheet1!A3"]["state"] == "recalculated"
    assert formula["summary"]["recalculation_provider"] == "libreoffice"
    assert _formula_record(output)["cached_value"] == "30"


@pytest.mark.parametrize("policy", ["auto", "required"])
def test_recalculation_operation_passes_explicit_policy_to_provider(
    project_root: Path,
    tmp_path: Path,
    policy: str,
) -> None:
    artifact = _write_workbook(tmp_path / f"provider-{policy}.xlsx", cached_value="30")
    provider = PolicyAwareProvider(artifact.read_bytes())
    output = tmp_path / f"policy-{policy}.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output, policy=policy),
    )

    assert result["status"] == "success"
    assert provider.policies == [policy]


@pytest.mark.parametrize(
    "code",
    [ErrorCode.PROVIDER_FAILED, ErrorCode.PROCESS_TIMEOUT],
)
def test_create_auto_provider_failure_promotes_degraded_core_candidate(
    project_root: Path,
    tmp_path: Path,
    code: ErrorCode,
) -> None:
    output = tmp_path / f"auto-{code.value}.xlsx"
    result = XlsxService(project_root, libreoffice=FailingProvider(code)).execute(
        "xlsx.create",
        _create_request(output),
    )

    evidence = result["diagnostics"]["operation_result"]["recalculation"]
    assert result["status"] == "degraded"
    assert result["provider_chain"] == []
    assert evidence["outcome"] == "unavailable"
    assert output.is_file()


@pytest.mark.parametrize(
    "provider",
    [None, FailingProvider(ErrorCode.PROVIDER_FAILED)],
)
def test_create_required_failure_preserves_existing_destination(
    project_root: Path,
    tmp_path: Path,
    provider: FailingProvider | None,
) -> None:
    output = tmp_path / "existing.xlsx"
    output.write_bytes(b"existing-destination")

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output, policy="required"),
    )

    assert result["status"] in {"failed", "unavailable"}
    assert output.read_bytes() == b"existing-destination"


def test_create_skip_never_calls_provider(project_root: Path, tmp_path: Path) -> None:
    provider = _provider(tmp_path, cached_value="30")
    output = tmp_path / "skipped.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output, policy="skip"),
    )

    evidence = result["diagnostics"]["operation_result"]["recalculation"]
    assert provider.calls == 0
    assert result["status"] == "degraded"
    assert evidence["outcome"] == "not_run"


def test_read_excluding_formulas_never_calls_or_leaks_provider_state(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    provider = _provider(tmp_path, cached_value="30")
    request = {
        "operation": "xlsx.read",
        "input": str(source),
        "arguments": {"include_formulas": False},
    }

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.read",
        request,
    )
    formula_state = result["diagnostics"]["operation_result"]["formula_state"]

    assert provider.calls == 0
    assert formula_state["cells"] == {}
    assert result["diagnostics"]["operation_result"]["recalculation"][
        "reason"
    ] == "request-excluded-formulas"


def test_edit_auto_harvests_values_without_adopting_provider_package(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    provider = _provider(tmp_path, cached_value="31")
    output = tmp_path / "edited.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.edit",
        _edit_request(source, output),
    )
    mapped = map_workbook(OpcPackage.open(output))

    assert result["status"] == "success"
    assert result["provider_chain"] == ["libreoffice"]
    assert mapped["sheets"][0]["rows"][0]["cells"][0]["value"] == "11"
    assert _formula_record(output)["cached_value"] == "31"


def test_edit_skip_never_calls_provider_and_preserves_formula_identity(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "skip-source.xlsx")
    source_bytes = source.read_bytes()
    provider = _provider(tmp_path, cached_value="31")
    output = tmp_path / "skip-edited.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.edit",
        _edit_request(source, output, policy="skip"),
    )

    recalculation = result["diagnostics"]["operation_result"]["recalculation"]
    assert result["status"] == "degraded"
    assert provider.calls == 0
    assert source.read_bytes() == source_bytes
    assert _formula_record(output)["formula"] == "SUM(A1:A2)"
    assert recalculation["outcome"] == "not_run"


@pytest.mark.parametrize(
    ("policy", "expected_status", "promoted"),
    [("auto", "degraded", True), ("required", "unavailable", False)],
)
def test_edit_provider_absence_obeys_policy_and_preserves_source(
    project_root: Path,
    tmp_path: Path,
    policy: str,
    expected_status: str,
    promoted: bool,
) -> None:
    source = _write_workbook(tmp_path / f"source-{policy}.xlsx")
    source_bytes = source.read_bytes()
    output = tmp_path / f"output-{policy}.xlsx"
    output.write_bytes(b"existing")

    result = XlsxService(project_root).execute(
        "xlsx.edit",
        _edit_request(source, output, policy=policy),
    )

    assert result["status"] == expected_status
    assert source.read_bytes() == source_bytes
    assert (output.read_bytes() != b"existing") is promoted


def test_explicit_recalculate_preserves_source_unknown_part_and_is_deterministic(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    with zipfile.ZipFile(source, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("opaque/provider-must-not-rewrite.bin", b"opaque-payload")
    source_bytes = source.read_bytes()
    provider = _provider(tmp_path, cached_value="30")
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    service = XlsxService(project_root, libreoffice=provider)

    first_result = service.execute(
        "xlsx.recalculate",
        _recalculate_request(source, first),
    )
    second_result = service.execute(
        "xlsx.recalculate",
        _recalculate_request(source, second),
    )

    assert first_result["status"] == "success"
    assert first_result["provider_chain"] == ["libreoffice"]
    assert second_result["status"] == "success"
    assert second_result["provider_chain"] == ["libreoffice"]
    assert source.read_bytes() == source_bytes
    assert OpcPackage.open(first).parts[
        "opaque/provider-must-not-rewrite.bin"
    ] == b"opaque-payload"
    assert _formula_record(first)["formula"] == "SUM(A1:A2)"
    assert _formula_record(first)["cached_value"] == "30"
    assert first.read_bytes() == second.read_bytes()


def test_explicit_recalculate_rejects_static_formula_reference_before_provider(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "invalid-source.xlsx", formula="Missing!A1")
    provider = _provider(tmp_path, cached_value="30")
    output = tmp_path / "existing.xlsx"
    output.write_bytes(b"existing-static-analysis-destination")

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.recalculate",
        _recalculate_request(source, output),
    )

    assert result["status"] == "failed"
    assert provider.calls == 0
    assert output.read_bytes() == b"existing-static-analysis-destination"


def test_explicit_recalculate_rejects_provider_formula_identity_drift(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    provider = _provider(
        tmp_path,
        formula="SUM(A1:A2)+1",
        cached_value="31",
    )
    output = tmp_path / "identity-drift.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.recalculate",
        _recalculate_request(source, output),
    )

    assert result["status"] == "failed"
    assert not output.exists()


def test_explicit_recalculate_rejects_provider_formula_error_token(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    provider = _provider(tmp_path, cached_value="#REF!", result_type="e")
    output = tmp_path / "formula-error.xlsx"

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.recalculate",
        _recalculate_request(source, output),
    )

    assert result["status"] == "failed"
    assert not output.exists()


def test_explicit_recalculate_requires_provider_when_formulas_exist(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    output = tmp_path / "output.xlsx"
    output.write_bytes(b"existing")

    result = XlsxService(project_root).execute(
        "xlsx.recalculate",
        _recalculate_request(source, output),
    )

    assert result["status"] == "unavailable"
    assert output.read_bytes() == b"existing"


def test_provider_formula_evidence_failure_prevents_promotion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    providers = [
        _provider(tmp_path, formula="A1+A2+1", cached_value="31"),
        _provider(tmp_path, cached_value=None),
    ]
    for index, provider in enumerate(providers):
        output = tmp_path / f"formula-evidence-{index}.xlsx"
        result = XlsxService(project_root, libreoffice=provider).execute(
            "xlsx.create",
            _create_request(output),
        )
        assert result["status"] == "failed"
        assert not output.exists()


def test_malformed_provider_artifact_fails_without_promotion(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "malformed.xlsx"
    provider = ArtifactProvider(b"not-an-xlsx")

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output),
    )

    assert result["status"] == "failed"
    assert not output.exists()


@pytest.mark.parametrize(
    "token",
    ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!"],
)
def test_provider_formula_error_tokens_fail_without_promotion(
    project_root: Path,
    tmp_path: Path,
    token: str,
) -> None:
    output = tmp_path / f"error-{token.replace('/', '-')}.xlsx"
    provider = _provider(tmp_path, cached_value=token, result_type="e")

    result = XlsxService(project_root, libreoffice=provider).execute(
        "xlsx.create",
        _create_request(output),
    )

    assert result["status"] == "failed"
    assert not output.exists()


def test_explicit_recalculate_rejects_equal_paths(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _write_workbook(tmp_path / "source.xlsx")
    result = XlsxService(project_root).execute(
        "xlsx.recalculate",
        _recalculate_request(source, source),
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.OUTPUT_EQUALS_INPUT.value
