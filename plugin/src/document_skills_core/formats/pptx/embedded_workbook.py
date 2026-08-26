"""Bounded read-only extraction of chart-source values from embedded XLSX parts."""

from dataclasses import dataclass
from io import BytesIO
import posixpath
import re
from typing import Any
import zipfile

from defusedxml.ElementTree import fromstring

from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_FORMULA = re.compile(
    r"^(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Z]{1,3})\$?(\d+)"
    r"(?::\$?([A-Z]{1,3})\$?(\d+))?$"
)
_MAX_WORKBOOK_BYTES = 16 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 1_000
_MAX_CELLS = 100_000
_MAX_RANGE_CELLS = 10_000


@dataclass(frozen=True)
class EmbeddedWorkbook:
    sheets: dict[str, dict[str, str]]

    def values(self, formula: str, *, numeric: bool) -> list[Any] | None:
        match = _FORMULA.fullmatch(formula.strip())
        if match is None:
            return None
        sheet_name = (match.group(1) or match.group(2) or "").replace("''", "'")
        cells = self.sheets.get(sheet_name)
        if cells is None:
            return None
        start_column = _column_number(match.group(3))
        start_row = int(match.group(4))
        end_column = _column_number(match.group(5) or match.group(3))
        end_row = int(match.group(6) or match.group(4))
        if end_column < start_column or end_row < start_row:
            return None
        count = (end_column - start_column + 1) * (end_row - start_row + 1)
        if count > _MAX_RANGE_CELLS:
            return None
        result: list[Any] = []
        for row in range(start_row, end_row + 1):
            for column in range(start_column, end_column + 1):
                raw = cells.get(f"{_column_name(column)}{row}", "")
                if numeric:
                    try:
                        result.append(float(raw))
                    except ValueError:
                        result.append(raw)
                else:
                    result.append(raw)
        return result


def load_embedded_workbook(payload: bytes) -> EmbeddedWorkbook:
    if not payload.startswith(b"PK") or not 0 < len(payload) <= _MAX_WORKBOOK_BYTES:
        raise ValueError("embedded workbook payload is invalid")
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if (
            len(members) > _MAX_ENTRIES
            or sum(item.file_size for item in members) > _MAX_UNCOMPRESSED_BYTES
        ):
            raise ValueError("embedded workbook exceeds policy")
        names: set[str] = set()
        for item in members:
            identity = PORTABLE_PATH_POLICY.parse_relative(item.filename.replace("\\", "/"))
            name = "/".join(identity.components)
            if name in names:
                raise ValueError("embedded workbook has duplicate members")
            names.add(name)
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise ValueError("embedded workbook is missing required parts")
        shared_strings = _shared_strings(archive, names)
        relationships = _workbook_relationships(archive)
        workbook = fromstring(archive.read("xl/workbook.xml"))
        sheets: dict[str, dict[str, str]] = {}
        cell_count = 0
        for node in workbook.iter(f"{{{_MAIN_NS}}}sheet"):
            name = node.attrib.get("name", "")
            relationship_id = node.attrib.get(f"{{{_DOC_REL_NS}}}id", "")
            target = relationships.get(relationship_id)
            if not name or target is None or target not in names:
                raise ValueError("embedded workbook sheet relationship is invalid")
            values = _worksheet_values(archive.read(target), shared_strings)
            cell_count += len(values)
            if cell_count > _MAX_CELLS:
                raise ValueError("embedded workbook cell limit exceeded")
            sheets[name] = values
    return EmbeddedWorkbook(sheets)


def _workbook_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    result: dict[str, str] = {}
    for node in root.findall(f"{{{_REL_NS}}}Relationship"):
        relationship_id = node.attrib.get("Id", "")
        target = node.attrib.get("Target", "").replace("\\", "/")
        if node.attrib.get("TargetMode", "Internal") != "Internal":
            continue
        resolved = posixpath.normpath(posixpath.join("xl", target))
        identity = PORTABLE_PATH_POLICY.parse_relative(resolved)
        result[relationship_id] = "/".join(identity.components)
    return result


def _shared_strings(archive: zipfile.ZipFile, names: set[str]) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    root = fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _worksheet_values(payload: bytes, shared_strings: list[str]) -> dict[str, str]:
    root = fromstring(payload)
    result: dict[str, str] = {}
    for cell in root.iter(f"{{{_MAIN_NS}}}c"):
        reference = cell.attrib.get("r", "")
        if not reference:
            continue
        value_node = cell.find(f"{{{_MAIN_NS}}}v")
        raw = "" if value_node is None else value_node.text or ""
        cell_type = cell.attrib.get("t", "")
        if cell_type == "s":
            try:
                raw = shared_strings[int(raw)]
            except (IndexError, ValueError):
                raise ValueError("embedded workbook shared-string index is invalid") from None
        elif cell_type == "inlineStr":
            raw = "".join(
                node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
            )
        result[reference.replace("$", "").upper()] = raw
    return result


def _column_number(value: str) -> int:
    result = 0
    for character in value:
        result = result * 26 + ord(character) - 64
    return result


def _column_name(value: int) -> str:
    result = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result
