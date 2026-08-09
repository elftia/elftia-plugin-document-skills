"""Strict bounded argument contracts for the five Core DOCX operations."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .constants import MAX_ARGUMENT_TEXT, MAX_RULES, MAX_VARIABLES

DOCX_OPERATIONS = frozenset(
    {
        "docx.read",
        "docx.inspect.structure",
        "docx.create",
        "docx.edit.replace-text",
        "docx.template.apply",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


@dataclass(frozen=True)
class ParsedDocxRequest:
    operation: str
    input_path: Path | None
    output_path: Path | None
    arguments: dict[str, Any]
    requested_fidelity: str


def parse_docx_request(request: dict[str, Any]) -> ParsedDocxRequest:
    operation = request.get("operation")
    if operation not in DOCX_OPERATIONS:
        _invalid("The operation is not a Core DOCX operation.", field="operation")
    arguments = request.get("arguments", {})
    if type(arguments) is not dict:
        _invalid("DOCX arguments must be an object.", field="arguments")
    input_path = _optional_path(request.get("input"), "input")
    output_path = _optional_path(request.get("output"), "output")
    options = request.get("options", {})
    fidelity = options.get("fidelity", "core") if type(options) is dict else "core"
    in_place = options.get("in_place", False) if type(options) is dict else False
    if operation in {"docx.read", "docx.inspect.structure"}:
        if input_path is None:
            _invalid("This DOCX operation requires an input path.", field="input")
        if output_path is not None:
            _invalid("Read-only DOCX operations do not accept output.", field="output")
    elif operation == "docx.create":
        if output_path is None:
            _invalid("DOCX creation requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("DOCX creation does not accept input.", field="input")
    elif input_path is None or output_path is None:
        _invalid("DOCX mutation requires distinct input and output paths.")
    if input_path is not None and input_path.suffix.casefold() != ".docx":
        _invalid("DOCX input path must use the .docx extension.", field="input")
    if output_path is not None and output_path.suffix.casefold() != ".docx":
        _invalid("DOCX output path must use the .docx extension.", field="output")
    if operation in {"docx.edit.replace-text", "docx.template.apply"}:
        assert input_path is not None and output_path is not None
        if in_place or same_path(input_path, output_path):
            raise DocumentSkillsError(
                ErrorCode.OUTPUT_EQUALS_INPUT,
                "Core DOCX mutations require a distinct output and do not support in-place mode.",
                status="invalid_request",
            )
    elif in_place:
        _invalid("in_place is not meaningful for this DOCX operation.", field="options.in_place")
    if operation == "docx.create":
        from .create_contract import parse_create

        parsed = parse_create(arguments)
    else:
        parsed = {
            "docx.read": _parse_read,
            "docx.inspect.structure": _parse_inspect,
            "docx.edit.replace-text": _parse_replace,
            "docx.template.apply": _parse_template,
        }[operation](arguments)
    return ParsedDocxRequest(operation, input_path, output_path, parsed, fidelity)


def _parse_read(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "include_headers_footers",
        "max_paragraphs",
        "max_table_rows",
        "max_tables",
        "max_text_chars",
    }
    _exact_keys(value, allowed)
    return {
        "include_headers_footers": _boolean(
            value.get("include_headers_footers", True), "include_headers_footers"
        ),
        "max_paragraphs": _integer(value.get("max_paragraphs", 5_000), 1, 10_000),
        "max_tables": _integer(value.get("max_tables", 500), 0, 1_000),
        "max_table_rows": _integer(value.get("max_table_rows", 5_000), 0, 10_000),
        "max_text_chars": _integer(
            value.get("max_text_chars", 250_000), 1, 1_000_000
        ),
    }


def _parse_inspect(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"include_hashes", "max_parts", "max_relationships"})
    return {
        "include_hashes": _boolean(value.get("include_hashes", True), "include_hashes"),
        "max_parts": _integer(value.get("max_parts", 2_000), 1, 5_000),
        "max_relationships": _integer(
            value.get("max_relationships", 5_000), 1, 10_000
        ),
    }


def _parse_replace(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"case_sensitive", "replacements"})
    rules = value.get("replacements")
    if type(rules) is not list or not rules or len(rules) > MAX_RULES:
        _invalid("replacements must be a non-empty bounded array.", field="replacements")
    parsed = []
    for index, rule in enumerate(rules):
        if type(rule) is not dict:
            _invalid("Each replacement must be an object.", field=f"replacements.{index}")
        _exact_keys(rule, {"expected_matches", "replace", "search"})
        search = _text(rule.get("search"), f"replacements.{index}.search", allow_empty=False)
        replace = _text(rule.get("replace"), f"replacements.{index}.replace")
        expected = rule.get("expected_matches")
        if expected is not None:
            expected = _integer(expected, 0, 1_000_000)
        parsed.append(
            {"search": search, "replace": replace, "expected_matches": expected}
        )
    return {
        "case_sensitive": _boolean(value.get("case_sensitive", True), "case_sensitive"),
        "replacements": parsed,
    }


def _parse_template(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"missing_policy", "variables"})
    variables = value.get("variables")
    if type(variables) is not dict or len(variables) > MAX_VARIABLES:
        _invalid("variables must be a bounded object.", field="variables")
    flattened: dict[str, str] = {}
    _flatten_variables(variables, "", flattened, depth=0)
    if len(
        str(sorted(flattened.items())).encode("utf-8", errors="strict")
    ) > 512 * 1024:
        _invalid("Template variables exceed the aggregate byte limit.")
    missing_policy = value.get("missing_policy", "error")
    if missing_policy != "error":
        _invalid("Only the fail-closed missing_policy 'error' is supported.")
    return {"variables": flattened, "missing_policy": missing_policy}


def _flatten_variables(
    value: dict[str, Any],
    prefix: str,
    target: dict[str, str],
    *,
    depth: int,
) -> None:
    if depth > 8:
        _invalid("Template variables exceed the nesting limit.")
    for raw_name, item in value.items():
        if type(raw_name) is not str:
            _invalid("Template variable names must be strings.")
        name = f"{prefix}.{raw_name}" if prefix else raw_name
        if not _IDENTIFIER.fullmatch(name):
            _invalid("Template variable names must be bounded ASCII identifiers.", field=name)
        if type(item) is dict:
            _flatten_variables(item, name, target, depth=depth + 1)
        elif item is None or type(item) in {str, int, float, bool}:
            rendered = "" if item is None else str(item).lower() if type(item) is bool else str(item)
            target[name] = _text(rendered, name)
        else:
            _invalid("Template values must be scalar.", field=name)
        if len(target) > MAX_VARIABLES:
            _invalid("Template variables exceed the item limit.")


def _exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown DOCX operation argument.", unknown=unknown)


def _optional_path(value: Any, field: str) -> Path | None:
    if value is None:
        return None
    return Path(_text(value, field, allow_empty=False)).expanduser().resolve(strict=False)


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"Integer must be between {minimum} and {maximum}.")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _invalid("Value must be boolean.", field=field)
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _text(value: Any, field: str, allow_empty: bool = True) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _invalid("Value must be a string.", field=field)
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Text exceeds the byte limit.", field=field)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
