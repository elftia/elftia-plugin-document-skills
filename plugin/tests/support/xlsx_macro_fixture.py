"""Deterministic inert macro/template fixtures for XLSX security tests."""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.formats.xlsx.constants import (
    CONTENT_TYPES,
    CONTENT_TYPES_NS,
    REL_VBA_PROJECT,
    WORKBOOK_CONTENT_TYPES,
    WORKBOOK_RELS,
    qn,
)
from document_skills_core.formats.xlsx.create import create_xlsx
from document_skills_core.formats.xlsx.package import OpcPackage


def create_package_fixture(
    path: Path,
    package_format: str,
    *,
    signed: bool = False,
    external_target: bool = False,
    workbook: dict | None = None,
) -> Path:
    base = path.parent / f"{path.stem}-base.xlsx"
    create_xlsx(base, _workbook() if workbook is None else workbook)
    package = OpcPackage.open(base)
    content_types = package.xml(CONTENT_TYPES)
    workbook_override = next(
        item
        for item in content_types.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        if item.attrib.get("PartName") == "/xl/workbook.xml"
    )
    workbook_override.attrib["ContentType"] = WORKBOOK_CONTENT_TYPES[package_format]
    workbook_relationships = package.xml(WORKBOOK_RELS)
    additions: dict[str, bytes] = {}
    if package_format in {"xlsm", "xltm"}:
        _add_override(
            content_types,
            "/xl/vbaProject.bin",
            "application/vnd.ms-office.vbaProject",
        )
        SubElement(
            workbook_relationships,
            qn("rels", "Relationship"),
            {
                "Id": "rIdVbaProject",
                "Type": REL_VBA_PROJECT,
                "Target": "vbaProject.bin",
            },
        )
        additions["xl/vbaProject.bin"] = b"inert-vba-project-payload\x00"
        if signed:
            _add_override(
                content_types,
                "/xl/vbaProjectSignature.bin",
                "application/vnd.ms-office.vbaProjectSignature",
            )
            additions["xl/vbaProjectSignature.bin"] = b"inert-signature-payload\x00"
            signature_relationships = Element(qn("rels", "Relationships"))
            SubElement(
                signature_relationships,
                qn("rels", "Relationship"),
                {
                    "Id": "rIdVbaSignature",
                    "Type": (
                        "http://schemas.microsoft.com/office/2006/relationships/"
                        "vbaProjectSignature"
                    ),
                    "Target": "vbaProjectSignature.bin",
                },
            )
            additions["xl/_rels/vbaProject.bin.rels"] = tostring(
                signature_relationships,
                encoding="UTF-8",
                xml_declaration=True,
            )
    if external_target:
        SubElement(
            workbook_relationships,
            qn("rels", "Relationship"),
            {
                "Id": "rIdExternal",
                "Type": (
                    "http://schemas.openxmlformats.org/officeDocument/2006/"
                    "relationships/externalLink"
                ),
                "Target": "https://example.invalid/workbook.xlsx",
                "TargetMode": "External",
            },
        )
    package.write_copy(
        path,
        changed_parts={
            CONTENT_TYPES: tostring(
                content_types,
                encoding="UTF-8",
                xml_declaration=True,
            ),
            WORKBOOK_RELS: tostring(
                workbook_relationships,
                encoding="UTF-8",
                xml_declaration=True,
            ),
        },
        added_parts=additions,
    )
    return path


def _add_override(root: Element, part_name: str, content_type: str) -> None:
    SubElement(
        root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": part_name, "ContentType": content_type},
    )


def _workbook() -> dict:
    return {
        "metadata": {"title": "Macro fixture", "creator": "Test", "subject": ""},
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    {
                        "cells": [
                            {"ref": "A1", "value": "10", "type": "n"},
                            {
                                "ref": "B1",
                                "formula": "A1*2",
                                "cached_value": "20",
                                "type": "n",
                            },
                        ]
                    }
                ],
                "number_formats": [],
            }
        ],
        "defined_names": [],
        "tables": [],
    }
