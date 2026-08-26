"""Bounded CSV, TSV, and canonical JSON conversion I/O."""

from __future__ import annotations

from contextlib import contextmanager
import csv
import io
import json
from pathlib import Path
from typing import Any, Iterator, TextIO

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .conversion_model import (
    canonical_json_cell,
    cell_to_text,
    infer_text_cell,
    normalize_json_cell,
    validate_dataset,
)

_BOMS = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
}


def read_delimited(path: Path, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source = arguments["source"]
    options = {**arguments["values"], **arguments["limits"]}
    rows: list[list[dict[str, Any]]] = []
    total_cells = 0
    try:
        with _open_text_input(path, source) as handle:
            reader = csv.reader(
                handle,
                delimiter=source["delimiter"],
                quotechar=source["quote"],
                doublequote=True,
                strict=True,
            )
            for row_index, row in enumerate(reader, start=1):
                if row_index > arguments["limits"]["max_rows_per_sheet"]:
                    _failed("Delimited input exceeded the configured row limit.")
                if len(row) > arguments["limits"]["max_columns"]:
                    _failed("Delimited input exceeded the configured column limit.")
                total_cells += len(row)
                if total_cells > arguments["limits"]["max_cells"]:
                    _failed("Delimited input exceeded the configured cell limit.")
                rows.append([infer_text_cell(item, options) for item in row])
    except (UnicodeError, csv.Error) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Delimited input could not be decoded or parsed strictly.",
            details={"reason": type(error).__name__},
        ) from error
    dataset = {"sheets": [{"name": source["sheet_name"], "rows": rows}]}
    stats = validate_dataset(dataset, arguments["limits"])
    return dataset, {
        "strategy": "streaming-read-bounded-buffer",
        "stats": stats,
        "encoding": source["encoding"],
        "bom": source["bom"],
        "delimiter": source["delimiter"],
        "quote": source["quote"],
    }


def read_canonical_json(
    path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = arguments["source"]
    options = {**arguments["values"], **arguments["limits"]}
    try:
        with _open_text_input(path, source) as handle:
            document = json.load(handle, parse_int=str, parse_float=str)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "JSON input could not be decoded or parsed strictly.",
            details={"reason": type(error).__name__},
        ) from error
    if type(document) is not dict or set(document) != {"schema_version", "format", "sheets"}:
        _failed("Canonical JSON requires exactly schema_version, format, and sheets.")
    if document["schema_version"] != "1.0" or document["format"] != "document-skills-tabular":
        _failed("Canonical JSON schema version or format marker is unsupported.")
    raw_sheets = document["sheets"]
    if type(raw_sheets) is not list:
        _failed("Canonical JSON sheets must be an array.")
    sheets: list[dict[str, Any]] = []
    type_normalizations = timezone_normalizations = 0
    for raw_sheet in raw_sheets:
        if type(raw_sheet) is not dict or set(raw_sheet) != {"name", "rows"}:
            _failed("Canonical JSON sheet shape is invalid.")
        if type(raw_sheet["rows"]) is not list:
            _failed("Canonical JSON rows must be an array.")
        rows: list[list[dict[str, Any]]] = []
        for raw_row in raw_sheet["rows"]:
            if type(raw_row) is not list:
                _failed("Canonical JSON row must be an array.")
            normalized_row: list[dict[str, Any]] = []
            for cell in raw_row:
                normalized = normalize_json_cell(cell, options)
                if type(cell) is dict and cell.get("type") != normalized["type"]:
                    type_normalizations += 1
                if (
                    type(cell) is dict
                    and cell.get("type") in {"time", "datetime"}
                    and cell.get("value") != normalized.get("value")
                ):
                    timezone_normalizations += 1
                normalized_row.append(normalized)
            rows.append(normalized_row)
        sheets.append({"name": raw_sheet["name"], "rows": rows})
    dataset = {"sheets": sheets}
    stats = validate_dataset(dataset, arguments["limits"])
    losses: list[dict[str, Any]] = []
    if type_normalizations:
        losses.append(
            {
                "code": "json-value-type-normalized",
                "description": "Risky canonical JSON numeric values were preserved as text by policy.",
                "count": type_normalizations,
            }
        )
    if timezone_normalizations:
        losses.append(
            {
                "code": "timezone-normalized-to-utc",
                "description": "Offset-aware JSON values were normalized to UTC by policy.",
                "count": timezone_normalizations,
            }
        )
    return dataset, {
        "strategy": "bounded-in-memory-json",
        "stats": stats,
        "encoding": source["encoding"],
        "bom": source["bom"],
        "semantic_losses": losses,
    }


def write_delimited(
    path: Path,
    dataset: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    target = arguments["target"]
    options = arguments["values"]
    escaped = 0
    line_ending = "\n" if target["line_ending"] == "lf" else "\r\n"
    with _open_text_output(path, target) as handle:
        writer = csv.writer(
            handle,
            delimiter=target["delimiter"],
            quotechar=target["quote"],
            doublequote=True,
            lineterminator=line_ending,
        )
        for row in dataset["sheets"][0]["rows"]:
            rendered: list[str] = []
            for cell in row:
                text, was_escaped = cell_to_text(cell, options, protect_csv=True)
                escaped += int(was_escaped)
                rendered.append(text)
            writer.writerow(rendered)
    return {
        "strategy": "streaming-write",
        "encoding": target["encoding"],
        "bom": target["bom"],
        "delimiter": target["delimiter"],
        "quote": target["quote"],
        "line_ending": target["line_ending"],
        "csv_injection_policy": options["csv_injection_policy"],
        "csv_injection_escaped_cells": escaped,
    }


def write_canonical_json(
    path: Path,
    dataset: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    target = arguments["target"]
    document = {
        "schema_version": "1.0",
        "format": "document-skills-tabular",
        "sheets": [
            {
                "name": sheet["name"],
                "rows": [
                    [canonical_json_cell(cell) for cell in row]
                    for row in sheet["rows"]
                ],
            }
            for sheet in dataset["sheets"]
        ],
    }
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if target["line_ending"] == "crlf":
        text = text.replace("\n", "\r\n")
    with _open_text_output(path, target) as handle:
        handle.write(text)
    return {
        "strategy": "bounded-in-memory-json",
        "encoding": target["encoding"],
        "bom": target["bom"],
        "line_ending": target["line_ending"],
    }


def reopen_text_output(
    path: Path,
    dataset: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Strictly reopen text output and prove its public shape is readable."""

    target_format = arguments["target_format"]
    mirrored = {
        **arguments,
        "source": {
            "encoding": arguments["target"]["encoding"],
            "delimiter": arguments["target"]["delimiter"],
            "quote": arguments["target"]["quote"],
            "bom": "required" if arguments["target"]["bom"] else "forbid",
            "sheet_name": dataset["sheets"][0]["name"],
        },
    }
    if target_format in {"csv", "tsv"}:
        expected = [
            [cell_to_text(cell, arguments["values"], protect_csv=True)[0] for cell in row]
            for row in dataset["sheets"][0]["rows"]
        ]
        try:
            with _open_text_input(path, mirrored["source"]) as handle:
                reopened = list(
                    csv.reader(
                        handle,
                        delimiter=mirrored["source"]["delimiter"],
                        quotechar=mirrored["source"]["quote"],
                        doublequote=True,
                        strict=True,
                    )
                )
        except (UnicodeError, csv.Error) as error:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Delimited output failed strict reopen.",
                details={"reason": type(error).__name__},
            ) from error
        if reopened != expected:
            _failed("Delimited output values changed during strict reopen.")
        return {
            "strategy": "strict-delimited-reopen",
            "rows": len(reopened),
            "cells": sum(len(row) for row in reopened),
        }
    reopened, evidence = read_canonical_json(path, mirrored)
    expected_public = _canonical_dataset(dataset)
    reopened_public = _canonical_dataset(reopened)
    if reopened_public != expected_public:
        _failed("Canonical JSON output changed during strict reopen.")
    return evidence


def _canonical_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """Project internal-only cell metadata out before public JSON comparison."""

    return {
        "sheets": [
            {
                "name": sheet["name"],
                "rows": [
                    [canonical_json_cell(cell) for cell in row] for row in sheet["rows"]
                ],
            }
            for sheet in dataset["sheets"]
        ]
    }


@contextmanager
def _open_text_input(path: Path, options: dict[str, Any]) -> Iterator[TextIO]:
    raw = path.open("rb")
    try:
        prefix = raw.read(3)
        raw.seek(0)
        detected = next((name for name, marker in _BOMS.items() if prefix.startswith(marker)), None)
        expected = options["encoding"] if options["encoding"] in _BOMS else None
        policy = options["bom"]
        if policy == "required" and (expected is None or detected != expected):
            _failed("Input BOM is required and must match the declared encoding.")
        if policy == "forbid" and detected is not None:
            _failed("Input BOM is forbidden by the conversion contract.")
        if detected is not None and detected != expected:
            _failed("Input BOM conflicts with the declared encoding.")
        if detected is not None:
            raw.seek(len(_BOMS[detected]))
        wrapper = io.TextIOWrapper(raw, encoding=options["encoding"], errors="strict", newline="")
        try:
            yield wrapper
        finally:
            wrapper.close()
    finally:
        if not raw.closed:
            raw.close()


@contextmanager
def _open_text_output(path: Path, options: dict[str, Any]) -> Iterator[TextIO]:
    raw = path.open("wb")
    try:
        marker = _BOMS.get(options["encoding"])
        if options["bom"]:
            if marker is None:
                raise DocumentSkillsError(
                    ErrorCode.REQUEST_INVALID,
                    "The selected target encoding does not define a supported BOM.",
                    status="invalid_request",
                    details={"encoding": options["encoding"]},
                )
            raw.write(marker)
        wrapper = io.TextIOWrapper(raw, encoding=options["encoding"], errors="strict", newline="")
        try:
            yield wrapper
            wrapper.flush()
        finally:
            wrapper.close()
    finally:
        if not raw.closed:
            raw.close()


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)
