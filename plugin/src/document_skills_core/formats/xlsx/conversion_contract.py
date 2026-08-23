"""Bounded typed contract for ``xlsx.convert``."""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

FORMATS = frozenset({"xlsx", "csv", "tsv", "json", "xls"})
FORMAT_SUFFIXES = {
    "xlsx": frozenset({".xlsx"}),
    "csv": frozenset({".csv"}),
    "tsv": frozenset({".tsv", ".tab"}),
    "json": frozenset({".json"}),
    "xls": frozenset({".xls"}),
}
TEXT_FORMATS = frozenset({"csv", "tsv", "json"})
ENCODINGS = frozenset(
    {"utf-8", "utf-16-le", "utf-16-be", "windows-1252", "iso-8859-1"}
)


def parse_conversion_arguments(value: dict[str, Any]) -> dict[str, Any]:
    """Parse conversion arguments without importing the large XLSX contract module."""

    _exact_keys(
        value,
        {"source_format", "target_format", "sheet", "source", "target", "values", "limits"},
    )
    source_format = _choice(value.get("source_format"), FORMATS, "source_format")
    target_format = _choice(value.get("target_format"), FORMATS, "target_format")
    if target_format == "xls":
        _invalid("Legacy .xls is input-only and cannot be a conversion target.")
    if source_format == "xls":
        if target_format != "xlsx":
            _invalid("Legacy .xls conversion only targets .xlsx.", field="target_format")
        unsupported = sorted(set(value).intersection({"sheet", "source", "target", "values"}))
        if unsupported:
            _invalid(
                "Legacy .xls conversion does not accept tabular conversion options.",
                unknown=unsupported,
            )
        return {
            "source_format": source_format,
            "target_format": target_format,
            "sheet": None,
            "source": {},
            "target": {},
            "values": {},
            "limits": _parse_limits(value.get("limits", {})),
        }
    source = _parse_source_options(value.get("source", {}), source_format)
    target = _parse_target_options(value.get("target", {}), target_format)
    values = _parse_value_options(value.get("values", {}), target_format)
    limits = _parse_limits(value.get("limits", {}))
    sheet = _optional_text(value.get("sheet"), "sheet", maximum=31)
    if sheet is not None and source_format not in {"xlsx", "json"}:
        _invalid("sheet is only valid for XLSX or canonical JSON input.", field="sheet")
    return {
        "source_format": source_format,
        "target_format": target_format,
        "sheet": sheet,
        "source": source,
        "target": target,
        "values": values,
        "limits": limits,
    }


def assert_format_suffix(path_suffix: str, format_id: str, field: str) -> None:
    if path_suffix.casefold() not in FORMAT_SUFFIXES[format_id]:
        _invalid(
            "Path extension does not match the declared conversion format.",
            field=field,
            format=format_id,
            accepted=sorted(FORMAT_SUFFIXES[format_id]),
        )


def _parse_source_options(value: Any, format_id: str) -> dict[str, Any]:
    value = _object(value, "source")
    _exact_keys(value, {"encoding", "delimiter", "quote", "bom", "sheet_name"})
    if format_id == "xlsx" and value:
        _invalid("XLSX input does not accept text source options.", field="source")
    if format_id == "json" and set(value).intersection({"delimiter", "quote", "sheet_name"}):
        _invalid("JSON input does not accept delimited-text options.", field="source")
    delimiter = _delimiter(value.get("delimiter"), format_id, "source.delimiter")
    quote = _character(value.get("quote", '"'), "source.quote")
    if delimiter is not None and delimiter == quote:
        _invalid("Delimiter and quote characters must differ.", field="source")
    encoding = _encoding(value.get("encoding", "utf-8"), "source.encoding")
    bom = _choice(
        value.get("bom", "auto"),
        {"auto", "required", "forbid"},
        "source.bom",
    )
    if bom == "required" and encoding not in {"utf-8", "utf-16-le", "utf-16-be"}:
        _invalid("The selected source encoding has no supported BOM.", field="source.bom")
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "quote": quote,
        "bom": bom,
        "sheet_name": _sheet_name(_text(
            value.get("sheet_name", "Sheet1"),
            "source.sheet_name",
            maximum=31,
            allow_empty=False,
        )),
    }


def _parse_target_options(value: Any, format_id: str) -> dict[str, Any]:
    value = _object(value, "target")
    _exact_keys(value, {"encoding", "delimiter", "quote", "bom", "line_ending"})
    if format_id == "xlsx" and value:
        _invalid("XLSX output does not accept text target options.", field="target")
    if format_id == "json" and set(value).intersection({"delimiter", "quote"}):
        _invalid("JSON output does not accept delimited-text options.", field="target")
    delimiter = _delimiter(value.get("delimiter"), format_id, "target.delimiter")
    quote = _character(value.get("quote", '"'), "target.quote")
    if delimiter is not None and delimiter == quote:
        _invalid("Delimiter and quote characters must differ.", field="target")
    bom = value.get("bom", False)
    if type(bom) is not bool:
        _invalid("target.bom must be boolean.", field="target.bom")
    encoding = _encoding(value.get("encoding", "utf-8"), "target.encoding")
    if bom and encoding not in {"utf-8", "utf-16-le", "utf-16-be"}:
        _invalid("The selected target encoding has no supported BOM.", field="target.bom")
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "quote": quote,
        "bom": bom,
        "line_ending": _choice(
            value.get("line_ending", "lf"),
            {"lf", "crlf"},
            "target.line_ending",
        ),
    }


def _parse_value_options(value: Any, target_format: str) -> dict[str, Any]:
    value = _object(value, "values")
    _exact_keys(
        value,
        {
            "infer_types",
            "null_token",
            "true_token",
            "false_token",
            "decimal_separator",
            "leading_zero_policy",
            "large_integer_policy",
            "timezone_policy",
            "formula_policy",
            "csv_injection_policy",
        },
    )
    infer_types = value.get("infer_types", True)
    if type(infer_types) is not bool:
        _invalid("values.infer_types must be boolean.", field="values.infer_types")
    csv_policy = _choice(
        value.get("csv_injection_policy", "escape"),
        {"escape", "reject", "allow"},
        "values.csv_injection_policy",
    )
    if "csv_injection_policy" in value and target_format not in {"csv", "tsv"}:
        _invalid(
            "csv_injection_policy is only valid for CSV or TSV output.",
            field="values.csv_injection_policy",
        )
    result = {
        "infer_types": infer_types,
        "null_token": _text(value.get("null_token", r"\N"), "values.null_token", maximum=64),
        "true_token": _text(value.get("true_token", "TRUE"), "values.true_token", maximum=64),
        "false_token": _text(value.get("false_token", "FALSE"), "values.false_token", maximum=64),
        "decimal_separator": _choice(
            value.get("decimal_separator", "."), {".", ","}, "values.decimal_separator"
        ),
        "leading_zero_policy": _choice(
            value.get("leading_zero_policy", "preserve-text"),
            {"preserve-text", "number"},
            "values.leading_zero_policy",
        ),
        "large_integer_policy": _choice(
            value.get("large_integer_policy", "preserve-text"),
            {"preserve-text", "number", "reject"},
            "values.large_integer_policy",
        ),
        "timezone_policy": _choice(
            value.get("timezone_policy", "preserve-text"),
            {"preserve-text", "utc", "reject"},
            "values.timezone_policy",
        ),
        "formula_policy": _choice(
            value.get("formula_policy", "preserve-text"),
            {"preserve-text", "evaluated", "reject"},
            "values.formula_policy",
        ),
        "csv_injection_policy": csv_policy,
    }
    if result["true_token"].casefold() == result["false_token"].casefold():
        _invalid("Boolean tokens must differ.", field="values")
    if result["null_token"] in {result["true_token"], result["false_token"]}:
        _invalid("Null and boolean tokens must differ.", field="values")
    return result


def _parse_limits(value: Any) -> dict[str, int]:
    value = _object(value, "limits")
    _exact_keys(
        value,
        {
            "max_input_bytes",
            "max_output_bytes",
            "max_rows_per_sheet",
            "max_columns",
            "max_cells",
            "max_cell_bytes",
        },
    )
    return {
        "max_input_bytes": _integer(value.get("max_input_bytes", 64 * 1024 * 1024), 1, 512 * 1024 * 1024, "limits.max_input_bytes"),
        "max_output_bytes": _integer(value.get("max_output_bytes", 64 * 1024 * 1024), 1, 512 * 1024 * 1024, "limits.max_output_bytes"),
        "max_rows_per_sheet": _integer(value.get("max_rows_per_sheet", 100_000), 1, 1_048_576, "limits.max_rows_per_sheet"),
        "max_columns": _integer(value.get("max_columns", 16_384), 1, 16_384, "limits.max_columns"),
        "max_cells": _integer(value.get("max_cells", 1_000_000), 1, 10_000_000, "limits.max_cells"),
        "max_cell_bytes": _integer(value.get("max_cell_bytes", 1_048_576), 1, 16 * 1024 * 1024, "limits.max_cell_bytes"),
    }


def _delimiter(value: Any, format_id: str, field: str) -> str | None:
    if format_id not in {"csv", "tsv"}:
        if value is not None:
            _invalid("Delimiter is only valid for CSV or TSV.", field=field)
        return None
    default = "," if format_id == "csv" else "\t"
    return _character(default if value is None else value, field)


def _character(value: Any, field: str) -> str:
    text = _text(value, field, maximum=4, allow_empty=False)
    if len(text) != 1 or text in {"\r", "\n", "\x00"}:
        _invalid("Value must be one non-newline character.", field=field)
    return text


def _encoding(value: Any, field: str) -> str:
    return _choice(value, ENCODINGS, field)


def _sheet_name(value: str) -> str:
    if any(character in value for character in "[]:*?/\\") or value.startswith("'") or value.endswith("'"):
        _invalid("Generated worksheet name is invalid.", field="source.sheet_name")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid("Value must be an object.", field=field)
    return value


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.", field=field)
    return value


def _optional_text(value: Any, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum, allow_empty=False)


def _text(value: Any, field: str, *, maximum: int, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > maximum:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _choice(value: Any, choices: set[str] | frozenset[str], field: str) -> str:
    if type(value) is not str or value not in choices:
        _invalid("Value is not an accepted enum member.", field=field, accepted=sorted(choices))
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown XLSX conversion argument.", unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
