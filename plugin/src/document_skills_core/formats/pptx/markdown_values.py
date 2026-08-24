"""Bounded Markdown inline values, tables, and local image paths."""

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import MAX_ARGUMENT_TEXT

MAX_TABLE_ROWS = 256
MAX_TABLE_COLUMNS = 32

_TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")


def _resolve_image(root: Path, target: str, line: int) -> Path:
    raw = target[1:-1] if target.startswith("<") and target.endswith(">") else target
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\x00" in raw:
        _invalid("Markdown images must use a plain relative local path.", line=line)
    relative = Path(raw)
    if relative.is_absolute() or raw.startswith(("\\", "/")):
        _invalid("Markdown images must use a relative local path.", line=line)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        _invalid("Markdown image path escapes the source directory.", line=line)
    if not candidate.is_file():
        _invalid("Markdown image does not exist.", line=line, path=str(candidate))
    return candidate


def _is_table_start(line: str, separator: str) -> bool:
    header = _table_cells(line)
    divider = _table_cells(separator)
    return (
        len(header) > 0
        and len(header) == len(divider)
        and all(_TABLE_SEPARATOR.fullmatch(cell.replace(" ", "")) for cell in divider)
    )


def _parse_table(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    header = _table_cells(lines[start])
    if not 1 <= len(header) <= MAX_TABLE_COLUMNS:
        _invalid("Markdown table exceeds the column limit.", line=start + 1)
    rows = [header]
    index = start + 2
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        cells = _table_cells(lines[index])
        if len(cells) != len(header):
            _invalid("Markdown table rows must have equal column counts.", line=index + 1)
        rows.append(cells)
        if len(rows) > MAX_TABLE_ROWS:
            _invalid("Markdown table exceeds the row limit.", line=index + 1)
        index += 1
    return {
        "rows": [
            {
                "cells": [
                    _bounded_text(_visible_text(cell), "table.cell", start + 1)
                    for cell in row
                ]
            }
            for row in rows
        ]
    }, index


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _visible_text(value: str) -> str:
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"(\*\*|__)(.+?)\1", r"\2", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*", r"\1", value)
    value = re.sub(r"(?<!_)_([^_]+)_", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    return value.strip()


def _bounded_text(value: str, field: str, line: int) -> str:
    if len(value.encode("utf-8", errors="strict")) > MAX_ARGUMENT_TEXT:
        _invalid("Markdown text exceeds the byte limit.", field=field, line=line)
    return value


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
