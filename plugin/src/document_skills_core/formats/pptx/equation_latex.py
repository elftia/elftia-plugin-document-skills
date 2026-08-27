"""Recursive-descent parser for the closed editable-equation LaTeX subset.

Module provenance: original Elftia-authored clean-room implementation.
"""

from __future__ import annotations

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .equation_ast import (
    GREEK_SYMBOLS,
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    MAX_MATRIX_COLUMNS,
    MAX_MATRIX_ROWS,
    UNICODE_TO_GREEK,
    is_supported_text,
)


_OPERATOR_COMMANDS = {
    "cdot": "·",
    "ge": "≥",
    "infty": "∞",
    "le": "≤",
    "neq": "≠",
    "pm": "±",
    "times": "×",
}


class LatexParser:
    """Parse only the documented no-macro LaTeX profile."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.position = 0
        self.nodes = 0

    def parse(self) -> dict[str, Any]:
        result = self._parse_row(stop=None, depth=0)
        self._skip_space()
        if self.position != len(self.source):
            _invalid("Unexpected trailing LaTeX input.", offset=self.position)
        return _unwrap(result)

    def _parse_row(self, *, stop: str | None, depth: int) -> dict[str, Any]:
        self._check_depth(depth)
        items: list[dict[str, Any]] = []
        while self.position < len(self.source):
            self._skip_space()
            if self.position >= len(self.source):
                break
            current = self.source[self.position]
            if stop is not None and current == stop:
                self.position += 1
                return _row(items)
            if current in "^_":
                if not items:
                    _invalid(
                        "LaTeX script marker requires a base.",
                        offset=self.position,
                    )
                self.position += 1
                script = self._parse_script(depth + 1)
                items[-1] = self._attach_script(items[-1], current, script)
                continue
            if current == "}":
                _invalid("Unmatched LaTeX closing brace.", offset=self.position)
            items.append(self._parse_atom(depth + 1))
        if stop is not None:
            _invalid("LaTeX group is not closed.", offset=self.position)
        return _row(items)

    def _parse_atom(self, depth: int) -> dict[str, Any]:
        self._count_node()
        current = self.source[self.position]
        if current == "{":
            self.position += 1
            return _unwrap(self._parse_row(stop="}", depth=depth))
        if current == "\\":
            return self._parse_command(depth)
        if current == "&":
            _invalid(
                "Matrix separators are accepted only inside matrix.",
                offset=self.position,
            )
        if not is_supported_text(current):
            _unsupported(
                "LaTeX character is outside the closed profile.",
                character=current,
            )
        self.position += 1
        if current in UNICODE_TO_GREEK:
            return {"type": "symbol", "name": UNICODE_TO_GREEK[current]}
        return {"type": "text", "value": current}

    def _parse_command(self, depth: int) -> dict[str, Any]:
        self.position += 1
        start = self.position
        while self.position < len(self.source) and self.source[self.position].isalpha():
            self.position += 1
        command = self.source[start : self.position]
        if not command:
            _unsupported("Escaped LaTeX punctuation is outside the closed profile.")
        if command in GREEK_SYMBOLS:
            return {"type": "symbol", "name": command}
        if command in _OPERATOR_COMMANDS:
            return {"type": "text", "value": _OPERATOR_COMMANDS[command]}
        if command == "frac":
            return {
                "type": "fraction",
                "numerator": self._required_group(depth + 1),
                "denominator": self._required_group(depth + 1),
            }
        if command == "sqrt":
            degree = self._optional_degree(depth + 1)
            return {
                "type": "radical",
                "radicand": self._required_group(depth + 1),
                "degree": degree,
            }
        if command == "sum":
            return {
                "type": "nary",
                "operator": "sum",
                "lower": None,
                "upper": None,
            }
        if command == "begin":
            environment = self._required_group_text()
            if environment != "matrix":
                _unsupported(
                    "Only the matrix LaTeX environment is supported.",
                    environment=environment,
                )
            return self._parse_matrix(depth + 1)
        if command in {"end", "include", "input", "newcommand", "def"}:
            _unsafe("Unsafe or misplaced LaTeX command.", command=command)
        _unsupported("LaTeX command is outside the closed profile.", command=command)

    def _parse_matrix(self, depth: int) -> dict[str, Any]:
        marker = r"\end{matrix}"
        end = self.source.find(marker, self.position)
        if end < 0:
            _invalid("LaTeX matrix environment is not closed.")
        content = self.source[self.position : end]
        self.position = end + len(marker)
        raw_rows = _split_matrix(content)
        if not 1 <= len(raw_rows) <= MAX_MATRIX_ROWS:
            _resource("Equation matrix exceeds the row limit.", limit=MAX_MATRIX_ROWS)
        rows: list[list[dict[str, Any]]] = []
        width = None
        for raw_row in raw_rows:
            if not 1 <= len(raw_row) <= MAX_MATRIX_COLUMNS:
                _resource(
                    "Equation matrix exceeds the column limit.",
                    limit=MAX_MATRIX_COLUMNS,
                )
            if width is None:
                width = len(raw_row)
            elif len(raw_row) != width:
                _invalid("Equation matrix rows must have equal column counts.")
            rows.append([LatexParser(cell).parse() for cell in raw_row])
        self._check_depth(depth)
        return {"type": "matrix", "rows": rows}

    def _required_group(self, depth: int) -> dict[str, Any]:
        self._skip_space()
        if self.position >= len(self.source) or self.source[self.position] != "{":
            _invalid(
                "LaTeX command requires a braced argument.",
                offset=self.position,
            )
        self.position += 1
        return _unwrap(self._parse_row(stop="}", depth=depth))

    def _required_group_text(self) -> str:
        self._skip_space()
        if self.position >= len(self.source) or self.source[self.position] != "{":
            _invalid("LaTeX command requires a braced name.", offset=self.position)
        end = self.source.find("}", self.position + 1)
        if end < 0:
            _invalid("LaTeX command name is not closed.")
        value = self.source[self.position + 1 : end]
        self.position = end + 1
        return value

    def _optional_degree(self, depth: int) -> dict[str, Any] | None:
        self._skip_space()
        if self.position >= len(self.source) or self.source[self.position] != "[":
            return None
        end = self.source.find("]", self.position + 1)
        if end < 0:
            _invalid("LaTeX radical degree is not closed.")
        source = self.source[self.position + 1 : end]
        self.position = end + 1
        self._check_depth(depth)
        return _unwrap(LatexParser(source).parse())

    def _parse_script(self, depth: int) -> dict[str, Any]:
        self._skip_space()
        if self.position >= len(self.source):
            _invalid("LaTeX script value is missing.")
        if self.source[self.position] == "{":
            self.position += 1
            return _unwrap(self._parse_row(stop="}", depth=depth))
        return self._parse_atom(depth)

    @staticmethod
    def _attach_script(
        base: dict[str, Any], marker: str, script: dict[str, Any]
    ) -> dict[str, Any]:
        if base["type"] == "nary":
            key = "upper" if marker == "^" else "lower"
            if base[key] is not None:
                _invalid("LaTeX n-ary limit is repeated.")
            return {**base, key: script}
        if marker == "^" and base["type"] == "subscript":
            return {
                "type": "subsuperscript",
                "base": base["base"],
                "subscript": base["subscript"],
                "exponent": script,
            }
        if marker == "_" and base["type"] == "superscript":
            return {
                "type": "subsuperscript",
                "base": base["base"],
                "subscript": script,
                "exponent": base["exponent"],
            }
        if base["type"] in {"subscript", "subsuperscript", "superscript"}:
            _invalid("LaTeX script marker is repeated.")
        return {
            "type": "superscript" if marker == "^" else "subscript",
            "base": base,
            "exponent" if marker == "^" else "subscript": script,
        }

    def _count_node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_AST_NODES:
            _resource("Equation exceeds the AST node limit.", limit=MAX_AST_NODES)

    @staticmethod
    def _check_depth(depth: int) -> None:
        if depth > MAX_AST_DEPTH:
            _resource("Equation exceeds the AST depth limit.", limit=MAX_AST_DEPTH)

    def _skip_space(self) -> None:
        while self.position < len(self.source) and self.source[self.position].isspace():
            self.position += 1


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


def _unwrap(node: dict[str, Any]) -> dict[str, Any]:
    if node["type"] == "row" and len(node["items"]) == 1:
        return node["items"][0]
    return node


def _split_matrix(value: str) -> list[list[str]]:
    rows: list[list[str]] = [[]]
    cell: list[str] = []
    depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                _invalid("Matrix cell has unmatched braces.")
        if depth == 0 and value.startswith(r"\\", index):
            rows[-1].append("".join(cell).strip())
            rows.append([])
            cell = []
            index += 2
            continue
        if depth == 0 and character == "&":
            rows[-1].append("".join(cell).strip())
            cell = []
            index += 1
            continue
        cell.append(character)
        index += 1
    if depth != 0:
        _invalid("Matrix cell has unmatched braces.")
    rows[-1].append("".join(cell).strip())
    if any(not cell_value for row in rows for cell_value in row):
        _invalid("Matrix cells cannot be empty.")
    return rows


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


__all__ = ["LatexParser"]
