"""Transactional public ``xlsx.convert`` operation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import (
    assert_distinct_paths,
    assert_source_preserved,
    destination_snapshot,
    file_record,
    merge_source_preservation_failure,
)
from document_skills_core.core.io.temp_roots import OperationTempRoot

from .contracts import ParsedXlsxRequest
from .conversion_model import (
    resolve_formula_policy,
    select_output_sheets,
    validate_dataset,
)
from .conversion_text import (
    read_canonical_json,
    read_delimited,
    reopen_text_output,
    write_canonical_json,
    write_delimited,
)
from .conversion_xlsx import read_xlsx_dataset, write_xlsx_dataset
from .legacy_conversion import execute_legacy_conversion
from .transaction import promote_candidate, write_candidate_result


def execute_conversion(
    request: ParsedXlsxRequest,
    *,
    schemas: SchemaCatalog,
    libreoffice: Any = None,
) -> dict[str, Any]:
    assert request.input_path is not None and request.output_path is not None
    if request.arguments["source_format"] == "xls":
        return execute_legacy_conversion(
            request,
            schemas=schemas,
            libreoffice=libreoffice,
        )
    assert_distinct_paths(request.input_path, request.output_path, in_place=False)
    source_record = file_record(request.input_path, "input")
    destination = destination_snapshot(request.output_path)
    if source_record.bytes > request.arguments["limits"]["max_input_bytes"]:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Conversion input exceeds the configured byte limit.",
            details={
                "bytes": source_record.bytes,
                "limit": request.arguments["limits"]["max_input_bytes"],
            },
        )
    try:
        with OperationTempRoot() as private_root:
            dataset, read_evidence = _read_source(request.input_path, request.arguments)
            selected, selection_losses = select_output_sheets(
                dataset,
                sheet_name=request.arguments["sheet"],
                target_format=request.arguments["target_format"],
            )
            formula_count, formula_losses = resolve_formula_policy(
                selected,
                request.arguments["values"]["formula_policy"],
            )
            stats = validate_dataset(selected, request.arguments["limits"])
            staged = private_root / f"converted.{request.arguments['target_format']}"
            write_evidence, validation, write_losses = _write_target(
                staged,
                selected,
                request.arguments,
            )
            output_record = file_record(staged, "output")
            if output_record.bytes > request.arguments["limits"]["max_output_bytes"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Conversion output exceeds the configured byte limit.",
                    details={
                        "bytes": output_record.bytes,
                        "limit": request.arguments["limits"]["max_output_bytes"],
                    },
                )
            losses = [
                *_format_losses(request.arguments, selected),
                *read_evidence.get("semantic_losses", []),
                *selection_losses,
                *formula_losses,
                *write_losses,
            ]
            escaped = write_evidence.get("csv_injection_escaped_cells", 0)
            if escaped:
                losses.append(
                    {
                        "code": "csv-injection-escaped",
                        "description": "Dangerous spreadsheet-leading text received an apostrophe prefix.",
                        "count": escaped,
                    }
                )
            assert_source_preserved(source_record.path, source_record.sha256)
            validation = _conversion_validation(
                validation,
                output_record,
                source_record.sha256,
                losses,
            )
            operation_result = {
                "conversion": {
                    "source_format": request.arguments["source_format"],
                    "target_format": request.arguments["target_format"],
                    "selected_sheet": request.arguments["sheet"],
                    "formula_policy": request.arguments["values"]["formula_policy"],
                    "formula_cells": formula_count,
                    "stats": stats,
                    "limits": request.arguments["limits"],
                    "source": read_evidence,
                    "target": write_evidence,
                },
                "semantic_losses": losses,
            }
            degraded = bool(losses)
            result = write_candidate_result(
                schemas,
                request,
                staged,
                validation,
                operation_result,
                warnings=_conversion_warnings(losses),
                source=source_record,
                status="degraded" if degraded else "success",
                degraded=degraded,
                degradations=[_degradation(loss) for loss in losses],
            )
            return promote_candidate(
                request,
                staged,
                result,
                source=source_record,
                destination=destination,
            )
    except Exception as error:
        merge_source_preservation_failure(error, source_record.path, source_record.sha256)
        raise


def _read_source(
    path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_format = arguments["source_format"]
    if source_format == "xlsx":
        return read_xlsx_dataset(path, arguments)
    if source_format in {"csv", "tsv"}:
        return read_delimited(path, arguments)
    return read_canonical_json(path, arguments)


def _write_target(
    path: Path,
    dataset: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    target_format = arguments["target_format"]
    if target_format == "xlsx":
        evidence, validation, losses = write_xlsx_dataset(path, dataset, arguments)
        return evidence, validation, losses
    if target_format in {"csv", "tsv"}:
        evidence = write_delimited(path, dataset, arguments)
    else:
        evidence = write_canonical_json(path, dataset, arguments)
    reopen = reopen_text_output(path, dataset, arguments)
    evidence["reopen"] = reopen
    return evidence, None, []


def _conversion_validation(
    base: dict[str, Any] | None,
    output: Any,
    source_sha256: str,
    losses: list[dict[str, Any]],
) -> dict[str, Any]:
    gates = list((base or {}).get("gates", []))
    if base is None:
        gates.append(
            gate_record(
                "conversion.output-reopen",
                "pass",
                evidence={"sha256": output.sha256, "bytes": output.bytes},
            )
        )
    gates.extend(
        [
            gate_record(
                "conversion.source-preservation",
                "pass",
                evidence={"source_sha256": source_sha256},
            ),
            gate_record(
                "conversion.semantic-loss-disclosure",
                "pass",
                evidence={"loss_count": len(losses), "loss_codes": [item["code"] for item in losses]},
            ),
        ]
    )
    return {"schema_version": "1.0", "status": "pass", "gates": gates}


def _format_losses(
    arguments: dict[str, Any],
    dataset: dict[str, Any],
) -> list[dict[str, Any]]:
    source_format = arguments["source_format"]
    target_format = arguments["target_format"]
    losses: list[dict[str, Any]] = []
    if source_format == "xlsx":
        losses.append(
            {
                "code": "xlsx-formatting-and-objects-dropped",
                "description": "Conversion retained tabular values only, not styles, objects, or workbook features.",
            }
        )
    if source_format in {"csv", "tsv"} and arguments["values"]["infer_types"]:
        inferred = _typed_cell_count(dataset)
        if inferred:
            losses.append(
                {
                    "code": "delimited-value-types-inferred",
                    "description": "Delimited text tokens were interpreted as typed values.",
                    "count": inferred,
                }
            )
    if target_format in {"csv", "tsv"}:
        typed = _typed_cell_count(dataset)
        represented = _cell_count(dataset) if source_format in {"json", "xlsx"} else typed
        if represented:
            losses.append(
                {
                    "code": "typed-values-rendered-as-text",
                    "description": "Delimited output cannot retain typed value metadata.",
                    "count": represented,
                }
            )
    return losses


def _typed_cell_count(dataset: dict[str, Any]) -> int:
    return sum(
        cell["type"] not in {"null", "empty", "string", "error"}
        for sheet in dataset["sheets"]
        for row in sheet["rows"]
        for cell in row
    )


def _cell_count(dataset: dict[str, Any]) -> int:
    return sum(
        len(row)
        for sheet in dataset["sheets"]
        for row in sheet["rows"]
    )


def _degradation(loss: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": loss["code"],
        "semantic_difference": loss["description"],
        "missing_capabilities": [],
        "recommended_providers": [],
    }


def _conversion_warnings(losses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": "DS_CONVERSION_SEMANTIC_LOSS",
            "message": loss["description"],
            "details": {key: value for key, value in loss.items() if key != "description"},
        }
        for loss in losses
    ]
