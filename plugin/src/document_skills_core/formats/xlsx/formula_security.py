"""Fail-closed formula screening before an external spreadsheet provider runs."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from defusedxml.ElementTree import iterparse

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .format_policy import allowed_inert_categories, format_id
from .render_package import RenderPackageIndex

_ACTIVE_FUNCTION = re.compile(
    r"(?<![A-Za-z0-9_.])(?:(?:_xlfn|_xlws)\.)*"
    r"(?P<name>WEBSERVICE|RTD|DDE|HYPERLINK|IMAGE|STOCKHISTORY|"
    r"SQL\.REQUEST|CALL|REGISTER(?:\.ID)?|EXEC|FIELDVALUE|"
    r"CUBE(?:MEMBER|VALUE|SET|RANKEDMEMBER|KPIMEMBER))\s*\(",
    re.IGNORECASE,
)
_FORMULA_ELEMENTS = {
    "calculatedColumnFormula",
    "definedName",
    "f",
    "formula",
    "formula1",
    "formula2",
    "totalsRowFormula",
}


def active_formula_tokens(formula: str) -> tuple[str, ...]:
    """Return the active/provider-capable tokens in one formula expression."""

    masked = _mask_strings(formula)
    tokens = {
        match.group("name").upper()
        for match in _ACTIVE_FUNCTION.finditer(masked)
    }
    if _has_dde_link(masked):
        tokens.add("DDE_LINK")
    return tuple(sorted(tokens))


def _has_dde_link(value: str) -> bool:
    topic_started = False
    for character in value:
        if character == "|":
            topic_started = True
        elif character in "\r\n":
            topic_started = False
        elif character == "!" and topic_started:
            return True
    return False


def assert_provider_formula_safe(
    path: str | Path,
    *,
    package: RenderPackageIndex | None = None,
) -> dict[str, int]:
    """Reject active formula surfaces before LibreOffice sees workbook bytes."""

    package = package or RenderPackageIndex.open(
        path,
        allowed_inert_categories=allowed_inert_categories(format_id(path)),
    )
    xml_parts = 0
    formula_nodes = 0
    for part in package.spreadsheet_xml_parts():
        xml_parts += 1
        try:
            with package.open_part(part) as source_stream:
                elements = iterparse(
                    source_stream,
                    events=("end",),
                    forbid_dtd=True,
                    forbid_entities=True,
                    forbid_external=True,
                )
                for _event, element in elements:
                    local_name = _local_name(element.tag)
                    candidates: list[tuple[str, str]] = []
                    if local_name in _FORMULA_ELEMENTS:
                        formula_nodes += 1
                        candidates.append((local_name, element.text or ""))
                    for attribute, value in element.attrib.items():
                        if _local_name(attribute).casefold() == "formula":
                            formula_nodes += 1
                            candidates.append((f"{local_name}@formula", value))
                    for surface, formula in candidates:
                        tokens = active_formula_tokens(formula)
                        if tokens:
                            raise DocumentSkillsError(
                                ErrorCode.ARCHIVE_UNSAFE,
                                "Active or network-capable formulas are never sent to LibreOffice.",
                                details={
                                    "part": part,
                                    "surface": surface,
                                    "tokens": list(tokens),
                                },
                            )
                    element.clear()
        except DocumentSkillsError:
            raise
        except Exception as error:
            raise DocumentSkillsError(
                ErrorCode.ARCHIVE_UNSAFE,
                "Formula security preflight could not parse an XLSX XML part.",
                details={"part": part, "reason": type(error).__name__},
            ) from error
    return {"xml_parts_scanned": xml_parts, "formula_nodes_scanned": formula_nodes}


def _mask_strings(value: str) -> str:
    result = list(value)
    in_string = False
    index = 0
    while index < len(result):
        if result[index] == '"':
            if in_string and index + 1 < len(result) and result[index + 1] == '"':
                result[index] = result[index + 1] = " "
                index += 2
                continue
            in_string = not in_string
            result[index] = " "
        elif in_string:
            result[index] = " "
        index += 1
    return "".join(result)


def _local_name(value: Any) -> str:
    text = str(value)
    return text.rsplit("}", 1)[-1].rsplit(":", 1)[-1]
