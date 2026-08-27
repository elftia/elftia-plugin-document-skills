"""Canonical typed-AST profile for editable PPTX equations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


MAX_LATEX_BYTES = 4_096
MAX_AST_DEPTH = 32
MAX_AST_NODES = 256
MAX_MATRIX_ROWS = 8
MAX_MATRIX_COLUMNS = 8

GREEK_SYMBOLS = {
    "Alpha": "Α",
    "Beta": "Β",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "phi": "φ",
    "psi": "ψ",
    "omega": "ω",
}
UNICODE_TO_GREEK = {value: name for name, value in GREEK_SYMBOLS.items()}

_UNSAFE_COMMAND = re.compile(
    r"\\(?:def|edef|gdef|include|input|newcommand|openin|openout|read|write)\b",
    re.IGNORECASE,
)
_SAFE_TEXT = re.compile(
    r"^[\w\s+\-*/=(),.\[\]|:;!?'\u00B7\u00B1\u00D7\u2212\u221E\u2260\u2264\u2265]+$",
    re.UNICODE,
)


def normalize_equation_source(source: Any, field: str) -> dict[str, Any]:
    """Validate caller-owned math and return one canonical representation."""
    if type(source) is not dict:
        _invalid("Equation source must be an object.", field=field)
    _exact_keys(source, {"kind", "value"}, field)
    kind = source.get("kind")
    if kind in {"omml", "xml", "raw", "raw_xml"}:
        _unsafe("Raw OMML/XML equation input is forbidden.", field=f"{field}.kind")
    if kind not in {"ast", "latex"}:
        _invalid("Equation source kind must be latex or ast.", field=f"{field}.kind")
    if kind == "latex":
        value = source.get("value")
        if type(value) is not str or not value:
            _invalid(
                "LaTeX equation source must be a non-empty string.",
                field=f"{field}.value",
            )
        if len(value.encode("utf-8", errors="strict")) > MAX_LATEX_BYTES:
            _resource("LaTeX equation exceeds the byte limit.", limit=MAX_LATEX_BYTES)
        if "<" in value or ">" in value or "<?xml" in value.casefold():
            _unsafe(
                "Raw XML-like equation input is forbidden.",
                field=f"{field}.value",
            )
        if _UNSAFE_COMMAND.search(value):
            _unsafe(
                "LaTeX macros and external input commands are forbidden.",
                field=f"{field}.value",
            )
        from .equation_latex import LatexParser

        ast = normalize_ast(LatexParser(value).parse(), field=f"{field}.value")
    else:
        ast = normalize_ast(source.get("value"), field=f"{field}.value")
    return {
        "canonical_ast": ast,
        "canonical_latex": ast_to_latex(ast),
        "source_kind": kind,
    }


def normalize_ast(value: Any, *, field: str = "equation") -> dict[str, Any]:
    state = {"nodes": 0, "text_bytes": 0}
    return _normalize_node(value, field, 0, state)


def ast_to_latex(node: dict[str, Any]) -> str:
    kind = node["type"]
    if kind == "text":
        return node["value"]
    if kind == "symbol":
        return "\\" + node["name"]
    if kind == "row":
        return "".join(ast_to_latex(item) for item in node["items"])
    if kind == "fraction":
        return (
            "\\frac{"
            + ast_to_latex(node["numerator"])
            + "}{"
            + ast_to_latex(node["denominator"])
            + "}"
        )
    if kind == "superscript":
        return ast_to_latex(node["base"]) + "^{" + ast_to_latex(node["exponent"]) + "}"
    if kind == "subscript":
        return ast_to_latex(node["base"]) + "_{" + ast_to_latex(node["subscript"]) + "}"
    if kind == "subsuperscript":
        return (
            ast_to_latex(node["base"])
            + "_{"
            + ast_to_latex(node["subscript"])
            + "}"
            + "^{"
            + ast_to_latex(node["exponent"])
            + "}"
        )
    if kind == "radical":
        degree = node["degree"]
        prefix = "\\sqrt" if degree is None else "\\sqrt[" + ast_to_latex(degree) + "]"
        return prefix + "{" + ast_to_latex(node["radicand"]) + "}"
    if kind == "nary":
        result = "\\sum"
        if node["lower"] is not None:
            result += "_{" + ast_to_latex(node["lower"]) + "}"
        if node["upper"] is not None:
            result += "^{" + ast_to_latex(node["upper"]) + "}"
        return result
    if kind == "matrix":
        rows = [" & ".join(ast_to_latex(cell) for cell in row) for row in node["rows"]]
        return "\\begin{matrix}" + " \\\\ ".join(rows) + "\\end{matrix}"
    raise AssertionError(f"unhandled canonical equation node: {kind}")


def is_supported_text(value: str) -> bool:
    return _SAFE_TEXT.fullmatch(value) is not None


def canonicalize_math_text(value: str) -> str:
    """Apply the shared canonical text policy used before emit and after readback."""
    return unicodedata.normalize("NFKC", value).replace("−", "-")


def _normalize_node(
    value: Any,
    field: str,
    depth: int,
    state: dict[str, int],
) -> dict[str, Any]:
    if depth > MAX_AST_DEPTH:
        _resource("Equation exceeds the AST depth limit.", limit=MAX_AST_DEPTH)
    state["nodes"] += 1
    if state["nodes"] > MAX_AST_NODES:
        _resource("Equation exceeds the AST node limit.", limit=MAX_AST_NODES)
    if type(value) is not dict:
        _invalid("Equation AST node must be an object.", field=field)
    kind = value.get("type")
    if kind == "text":
        _exact_keys(value, {"type", "value"}, field)
        text = _safe_text(value.get("value"), f"{field}.value", state)
        return {"type": "text", "value": text}
    if kind == "symbol":
        _exact_keys(value, {"name", "type"}, field)
        name = value.get("name")
        if name not in GREEK_SYMBOLS:
            _unsupported("Equation symbol is outside the closed profile.", symbol=name)
        return {"type": "symbol", "name": name}
    if kind == "row":
        _exact_keys(value, {"items", "type"}, field)
        items = value.get("items")
        if type(items) is not list or not items:
            _invalid(
                "Equation row requires a non-empty items array.",
                field=f"{field}.items",
            )
        return _row(
            [
                _normalize_node(item, f"{field}.items.{index}", depth + 1, state)
                for index, item in enumerate(items)
            ]
        )
    if kind == "fraction":
        _exact_keys(value, {"denominator", "numerator", "type"}, field)
        return {
            "type": "fraction",
            "numerator": _normalize_node(
                value.get("numerator"), f"{field}.numerator", depth + 1, state
            ),
            "denominator": _normalize_node(
                value.get("denominator"), f"{field}.denominator", depth + 1, state
            ),
        }
    if kind in {"subscript", "superscript", "subsuperscript"}:
        return _normalize_script(value, kind, field, depth, state)
    if kind == "radical":
        _exact_keys(value, {"degree", "radicand", "type"}, field)
        degree = value.get("degree")
        return {
            "type": "radical",
            "radicand": _normalize_node(
                value.get("radicand"), f"{field}.radicand", depth + 1, state
            ),
            "degree": (
                None
                if degree is None
                else _normalize_node(degree, f"{field}.degree", depth + 1, state)
            ),
        }
    if kind == "nary":
        _exact_keys(value, {"lower", "operator", "type", "upper"}, field)
        if value.get("operator") != "sum":
            _unsupported("Only the sum n-ary operator is supported.")
        return {
            "type": "nary",
            "operator": "sum",
            "lower": _optional_node(value.get("lower"), f"{field}.lower", depth, state),
            "upper": _optional_node(value.get("upper"), f"{field}.upper", depth, state),
        }
    if kind == "matrix":
        return _normalize_matrix(value, field, depth, state)
    if kind in {"omml", "xml", "raw", "raw_xml"} or any(
        key in value for key in {"omml", "raw_xml", "xml"}
    ):
        _unsafe("Raw OMML/XML equation AST is forbidden.", field=field)
    _unsupported("Equation AST node is outside the closed profile.", node_type=kind)


def _normalize_script(
    value: dict[str, Any],
    kind: str,
    field: str,
    depth: int,
    state: dict[str, int],
) -> dict[str, Any]:
    keys = {"base", "type"}
    if kind in {"subscript", "subsuperscript"}:
        keys.add("subscript")
    if kind in {"superscript", "subsuperscript"}:
        keys.add("exponent")
    _exact_keys(value, keys, field)
    result = {
        "type": kind,
        "base": _normalize_node(value.get("base"), f"{field}.base", depth + 1, state),
    }
    for key in sorted(keys - {"base", "type"}):
        result[key] = _normalize_node(
            value.get(key), f"{field}.{key}", depth + 1, state
        )
    return result


def _normalize_matrix(
    value: dict[str, Any],
    field: str,
    depth: int,
    state: dict[str, int],
) -> dict[str, Any]:
    _exact_keys(value, {"rows", "type"}, field)
    rows = value.get("rows")
    if type(rows) is not list or not 1 <= len(rows) <= MAX_MATRIX_ROWS:
        _resource("Equation matrix exceeds the row limit.", limit=MAX_MATRIX_ROWS)
    normalized_rows: list[list[dict[str, Any]]] = []
    width = None
    for row_index, row in enumerate(rows):
        if type(row) is not list or not 1 <= len(row) <= MAX_MATRIX_COLUMNS:
            _resource(
                "Equation matrix exceeds the column limit.", limit=MAX_MATRIX_COLUMNS
            )
        if width is None:
            width = len(row)
        elif len(row) != width:
            _invalid("Equation matrix rows must have equal column counts.")
        normalized_rows.append(
            [
                _normalize_node(
                    cell,
                    f"{field}.rows.{row_index}.{column_index}",
                    depth + 1,
                    state,
                )
                for column_index, cell in enumerate(row)
            ]
        )
    return {"type": "matrix", "rows": normalized_rows}


def _optional_node(
    value: Any,
    field: str,
    depth: int,
    state: dict[str, int],
) -> dict[str, Any] | None:
    return None if value is None else _normalize_node(value, field, depth + 1, state)


def _safe_text(value: Any, field: str, state: dict[str, int]) -> str:
    if type(value) is not str or not value:
        _invalid("Equation text must be a non-empty string.", field=field)
    text = canonicalize_math_text(value)
    if "<" in text or ">" in text or "\\" in text:
        _unsafe(
            "Raw XML or LaTeX commands are forbidden in typed text nodes.", field=field
        )
    if (
        "_" in text
        or any(character.isspace() for character in text)
        or any(character in UNICODE_TO_GREEK for character in text)
    ):
        _unsupported(
            "Equation text must use structural scripts, symbol nodes, and no whitespace.",
            field=field,
        )
    if not is_supported_text(text):
        _unsupported("Equation text contains unsupported characters.", field=field)
    state["text_bytes"] += len(text.encode("utf-8", errors="strict"))
    if state["text_bytes"] > MAX_LATEX_BYTES:
        _resource("Equation AST text exceeds the byte limit.", limit=MAX_LATEX_BYTES)
    return text


def _row(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        _invalid("Equation row cannot be empty.")
    merged: list[dict[str, Any]] = []
    for item in items:
        candidates = item["items"] if item["type"] == "row" else [item]
        for candidate in candidates:
            if merged and merged[-1]["type"] == candidate["type"] == "text":
                merged[-1] = {
                    "type": "text",
                    "value": merged[-1]["value"] + candidate["value"],
                }
            else:
                merged.append(candidate)
    return {"type": "row", "items": merged}


def _exact_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid("Unknown equation contract field.", field=field, unknown=unknown)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )


def _resource(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.RESOURCE_LIMIT, message, details=details)


def _unsafe(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _unsupported(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.UNSUPPORTED_FEATURE, message, details=details)


__all__ = [
    "GREEK_SYMBOLS",
    "MAX_AST_DEPTH",
    "MAX_AST_NODES",
    "MAX_LATEX_BYTES",
    "MAX_MATRIX_COLUMNS",
    "MAX_MATRIX_ROWS",
    "UNICODE_TO_GREEK",
    "ast_to_latex",
    "canonicalize_math_text",
    "is_supported_text",
    "normalize_ast",
    "normalize_equation_source",
]
