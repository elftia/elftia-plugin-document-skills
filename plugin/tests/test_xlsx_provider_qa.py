"""Provider-gated XLSX schema and PDF-render operation tests."""

import hashlib
import json
from pathlib import Path
import zlib

import pytest

from document_skills_core.core.capabilities import (
    DetectionEvidence,
    ProviderCatalog,
)
from document_skills_core.core.capabilities.reports import build_capabilities
from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.process import ProcessResult
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.byte_preflight import decode_stream
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.providers.dotnet import build_dotnet_provider
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.public_cli.protocol import PublicCommand
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor


class _CallableDetector:
    def __init__(self, path: str) -> None:
        self.path = path

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(True, version="test", path=self.path)


class _AbsentDetector:
    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(False, reason="fixture provider unavailable")


class _DotnetRunner:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def set_executable(self, _executable: str) -> None:
        return None

    def run(self, subcommand: str, *, stdin_payload=None, **_kwargs) -> ProcessResult:
        self.calls.append({"subcommand": subcommand, "payload": stdin_payload})
        return ProcessResult(0, json.dumps(self.response), "", 5)


class _LibreOfficeRunner:
    def __init__(self, pdf_bytes: bytes) -> None:
        self.pdf_bytes = pdf_bytes
        self.calls: list[dict[str, object]] = []

    def set_executable(self, _executable: str) -> None:
        return None

    def convert(
        self,
        input_path: Path,
        target_format: str,
        output_dir: Path,
        *,
        timeout_seconds=None,
    ) -> Path:
        self.calls.append({
            "input": input_path,
            "format": target_format,
            "timeout": timeout_seconds,
        })
        output = output_dir / f"{input_path.stem}.{target_format}"
        output.write_bytes(self.pdf_bytes)
        return output


@pytest.fixture
def qa_xlsx(tmp_path: Path) -> Path:
    destination = tmp_path / "qa-source.xlsx"
    create_xlsx(
        destination,
        {
            "metadata": {},
            "sheets": [{
                "name": "Data",
                "rows": [{
                    "hidden": True,
                    "cells": [
                        {"ref": "A1", "value": "Wide column", "type": "s"},
                        {
                            "ref": "B1",
                            "value": "Long unwrapped text " * 8,
                            "type": "s",
                        },
                    ],
                }],
                "columns": [{
                    "min": 1,
                    "max": 1,
                    "ref": "A",
                    "width": 90.0,
                    "hidden": False,
                    "style": None,
                }],
                "number_formats": [],
            }],
            "defined_names": [],
            "tables": [],
            "charts": [],
        },
    )
    return destination


@pytest.fixture
def qa_pdf(tmp_path: Path) -> Path:
    destination = tmp_path / "qa-render.pdf"
    create_pdf(
        destination,
        {
            "metadata": {"title": "Render", "author": "Test", "subject": ""},
            "page_size": "A4",
            "pages": [{
                "blocks": [{
                    "type": "paragraph",
                    "text": "Rendered spreadsheet page",
                    "style": None,
                    "table": None,
                    "image": None,
                    "shape": None,
                }],
                "metadata": None,
            }],
        },
    )
    return destination


def test_dotnet_xlsx_schema_success_is_public_and_source_preserving(
    project_root: Path,
    qa_xlsx: Path,
) -> None:
    source_hash = hashlib.sha256(qa_xlsx.read_bytes()).hexdigest()
    runner = _DotnetRunner({"valid": True, "errors": [], "truncated": False})
    definition, _provider = build_dotnet_provider(
        project_root,
        detector=_CallableDetector("/fake/dotnet"),
        runner=runner,
    )
    registry = ProviderCatalog()
    registry.register_provider(definition)

    result = registry.execute({
        "schema_version": "1.0",
        "operation": "xlsx.validate.schema",
        "input": str(qa_xlsx),
        "arguments": {"max_errors": 25},
    })

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "success"
    assert result["provider_chain"] == ["dotnet-openxml"]
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["schema.full"]["outcome"] == "pass"
    assert gates["schema.full"]["validator"] == "dotnet-openxml"
    assert runner.calls[0]["subcommand"] == "--xlsx-schema-validate"
    assert runner.calls[0]["payload"]["max_errors"] == 25
    assert hashlib.sha256(qa_xlsx.read_bytes()).hexdigest() == source_hash


def test_dotnet_xlsx_schema_invalid_retains_bounded_error_report(
    project_root: Path,
    qa_xlsx: Path,
) -> None:
    runner = _DotnetRunner({
        "valid": False,
        "errors": [{
            "part": "WorkbookPart",
            "path": "/x:workbook[1]",
            "description": "Fixture schema error",
            "error_type": "Schema",
        }],
        "truncated": False,
    })
    definition, _provider = build_dotnet_provider(
        project_root,
        detector=_CallableDetector("/fake/dotnet"),
        runner=runner,
    )
    registry = ProviderCatalog()
    registry.register_provider(definition)

    result = registry.execute({
        "schema_version": "1.0",
        "operation": "xlsx.validate.schema",
        "input": str(qa_xlsx),
        "arguments": {},
    })

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["diagnostics"]["operation_result"]["schema"]["error_count"] == 1
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["schema.full"]["outcome"] == "fail"


def test_libreoffice_xlsx_render_promotes_reopened_pdf_with_scoped_evidence(
    project_root: Path,
    qa_xlsx: Path,
    qa_pdf: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "rendered.pdf"
    source_hash = hashlib.sha256(qa_xlsx.read_bytes()).hexdigest()
    runner = _LibreOfficeRunner(qa_pdf.read_bytes())
    definition, _provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector("/fake/soffice"),
        runner=runner,
    )
    registry = ProviderCatalog()
    registry.register_provider(definition)

    result = registry.execute({
        "schema_version": "1.0",
        "operation": "xlsx.render",
        "input": str(qa_xlsx),
        "output": str(output),
        "arguments": {"max_sheets": 5, "max_cells_per_sheet": 50},
    })

    SchemaCatalog(project_root).validate("operation-result", result)
    assert result["status"] == "success"
    assert result["provider_chain"] == ["libreoffice"]
    assert reopen_pdf(output)["pages"] == 1
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["visual.render"]["outcome"] == "pass"
    assert gates["visual.render"]["evidence"]["claim_scope"] == (
        "render-produced-and-pdf-reopened"
    )
    assert gates["schema.full"]["outcome"] == "unavailable"
    sampling = result["diagnostics"]["operation_result"]["render"]["sampling"]
    assert sampling["risk_finding_counts"] == {
        "hidden-data": 1,
        "potential-text-truncation": 1,
        "wide-columns": 1,
    }
    assert any(
        warning["code"] == "DS_XLSX_RENDER_SCOPE_LIMITED"
        for warning in result["warnings"]
    )
    assert hashlib.sha256(qa_xlsx.read_bytes()).hexdigest() == source_hash


def test_libreoffice_xlsx_render_validation_failure_preserves_destination(
    project_root: Path,
    qa_xlsx: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"sentinel")
    definition, provider = build_libreoffice_provider(
        project_root,
        detector=_CallableDetector("/fake/soffice"),
        runner=_LibreOfficeRunner(b"not a pdf"),
    )

    result = provider.execute("xlsx.render", {
        "schema_version": "1.0",
        "operation": "xlsx.render",
        "input": str(qa_xlsx),
        "output": str(output),
        "arguments": {},
    })

    assert result["status"] == "failed"
    assert output.read_bytes() == b"sentinel"
    assert any(capability.operation == "xlsx.render" for capability in definition.capabilities)


def test_provider_only_operations_are_reported_unavailable_without_callability(
    project_root: Path,
    qa_xlsx: Path,
    tmp_path: Path,
) -> None:
    registry = ProviderCatalog()
    dotnet, _provider = build_dotnet_provider(
        project_root,
        detector=_AbsentDetector(),
        runner=_DotnetRunner({}),
    )
    libreoffice, _provider = build_libreoffice_provider(
        project_root,
        detector=_AbsentDetector(),
        runner=_LibreOfficeRunner(b""),
    )
    registry.register_provider(dotnet)
    registry.register_provider(libreoffice)
    report = build_capabilities(project_root, "xlsx", registry)
    operations = {item["operation"]: item for item in report["operations"]}
    assert operations["xlsx.validate.schema"]["available"] is False
    assert operations["xlsx.render"]["available"] is False

    output = tmp_path / "not-created.pdf"
    with pytest.raises(DocumentSkillsError) as captured:
        registry.execute({
            "operation": "xlsx.render",
            "input": str(qa_xlsx),
            "output": str(output),
            "arguments": {},
        })
    assert captured.value.status == "unavailable"
    assert not output.exists()


def test_public_worker_grants_provider_operations_bounded_time(
    project_root: Path,
    tmp_path: Path,
) -> None:
    supervisor = PublicCommandSupervisor(project_root, timeout_seconds=8.0)
    observed = {}
    for operation in ("xlsx.render", "xlsx.validate.schema"):
        request = tmp_path / f"{operation}.json"
        request.write_text(json.dumps({"operation": operation}), encoding="utf-8")
        observed[operation] = supervisor._command_limits(
            PublicCommand("run", ("run", "--request", str(request))),
            tmp_path,
        )
    assert observed == {
        "xlsx.render": (45.0, 2_097_152),
        "xlsx.validate.schema": (45.0, 2_097_152),
    }


def test_libreoffice_pdf_filter_name_reopens_through_bounded_flate_decoder() -> None:
    content = b"BT /F1 12 Tf (LibreOffice) Tj ET"
    assert decode_stream(zlib.compress(content), ["/FlateDecode"]) == content
