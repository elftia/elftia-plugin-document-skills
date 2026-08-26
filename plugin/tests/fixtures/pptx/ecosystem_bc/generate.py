#!/usr/bin/env python3
"""Generate or verify deterministic phase B/C contract fixtures."""

from __future__ import annotations

import argparse
import filecmp
import json
from pathlib import Path
import sys
import tempfile
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml.ElementTree import fromstring

_PLUGIN_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_SRC = _PLUGIN_ROOT / "src"
for candidate in (_PLUGIN_ROOT, _PLUGIN_SRC):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from document_skills_core.formats.pptx.presentation_contracts import (  # noqa: E402
    PresentationContractConsumer,
)
from document_skills_core.formats.pptx.constants import (  # noqa: E402
    CONTENT_TYPES_NS,
    NS,
    qn,
)
from document_skills_core.formats.pptx.contracts import parse_deck  # noqa: E402
from document_skills_core.formats.pptx.create import create_pptx  # noqa: E402
from document_skills_core.formats.pptx.package import (  # noqa: E402
    OpcPackage,
    write_deterministic_zip,
)
from tests.support.pptx_ecosystem_fixture import (  # noqa: E402
    EcosystemFixtureWriter,
    FixtureMetadata,
)
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1  # noqa: E402


_RELATIVE = "expected/contract-pin.json"


def generate(contract_root: Path, output_root: Path) -> dict[str, object]:
    summary = PresentationContractConsumer.open(contract_root).summary()
    metadata = FixtureMetadata(
        fixture_id="B0-CONTRACT-01",
        format="json",
        purpose="Pin the cross-producer presentation contract conformance result.",
        origin="Elftia-authored metadata derived from the owner package.",
        recipe=(
            "uv run --project plugin python "
            "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
            "<presentation-contract-root> --write"
        ),
        license="GPL-3.0",
        expected_operation="presentation-contract.conformance",
        expected_consumers=("document-skills", "design-studio"),
        resource_limits={"maxBytes": 16384},
        invariants=(
            "owner package, version, schema versions, and manifest hash stay pinned",
            "stable IDs and Deck IR content hash match both producer consumers",
            "license status remains not_evaluated without Governance decision evidence",
        ),
        security_classification="benign-generated-metadata",
    )
    writer = EcosystemFixtureWriter(output_root)
    writer.write_json(_RELATIVE, summary, metadata)
    fixture_summary = _write_template_fixtures(writer)
    return {**summary, "fixtureCount": 1 + len(fixture_summary), "fixtures": fixture_summary}


def _write_template_fixtures(writer: EcosystemFixtureWriter) -> list[str]:
    recipe = (
        "uv run --project plugin python "
        "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
        "<presentation-contract-root> --write"
    )
    cases = (
        (
            "B-TPL-04",
            "templates/external-and-ole.pptx",
            _external_and_ole_template,
            "Synthetic external hyperlink/image plus an internal chart workbook.",
            (
                "sanitizer never dereferences external targets",
                "external and embedded relationships are removed with hash evidence",
                "chart caches remain native literal data after workbook purge",
            ),
            "synthetic-dangerous-external-and-embedded",
        ),
        (
            "B-TPL-05",
            "templates/mislabelled-active.pptx",
            _mislabelled_active_template,
            "Synthetic active-content and package-signature markers in a .pptx.",
            (
                "active content is rejected despite the .pptx extension",
                "signed input is rejected instead of silently invalidated",
                "no output is published",
            ),
            "synthetic-active-and-signed",
        ),
        (
            "B-TPL-06",
            "templates/orphan-and-dangling.pptx",
            _orphan_and_dangling_template,
            "Synthetic orphan part, dangling relationship, and duplicate relationship id.",
            (
                "all relationship anomalies are reported before mutation",
                "ambiguous input is rejected without output",
                "orphan payload identity is recorded",
            ),
            "synthetic-malformed-relationship-graph",
        ),
    )
    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pptx-ecosystem-template-fixtures-") as temporary:
        temporary_root = Path(temporary)
        image = temporary_root / "pixel.png"
        image.write_bytes(PNG_1X1)
        base = temporary_root / "base.pptx"
        create_pptx(base, parse_deck(_fixture_deck(image)))
        for fixture_id, relative, builder, purpose, invariants, classification in cases:
            candidate = temporary_root / f"{fixture_id}.pptx"
            builder(base, candidate)
            writer.write_bytes(
                relative,
                candidate.read_bytes(),
                FixtureMetadata(
                    fixture_id=fixture_id,
                    format="pptx",
                    purpose=purpose,
                    origin="Elftia-authored synthetic OOXML fixture.",
                    recipe=recipe,
                    license="GPL-3.0",
                    expected_operation="pptx.template.sanitize",
                    expected_consumers=("document-skills", "powerpoint", "libreoffice"),
                    resource_limits={"maxBytes": 2_000_000},
                    invariants=invariants,
                    security_classification=classification,
                ),
            )
            written.append(fixture_id)
    return written


def _fixture_deck(image: Path) -> dict[str, object]:
    return {
        "metadata": {
            "title": "Synthetic sanitizer fixture",
            "creator": "Elftia",
            "subject": "B1",
        },
        "slides": [
            {
                "layout": "content",
                "title": "Synthetic evidence",
                "shapes": [{"text": "Local text", "runs": []}],
                "table": None,
                "chart_reference": {
                    "title": "Synthetic chart",
                    "chart_type": "column",
                    "categories": ["A", "B"],
                    "series": [{"name": "Value", "values": [1, 2]}],
                    "legend": {"show": False, "position": "right"},
                    "axes": {
                        "category": {"title": "Category", "number_format": "General"},
                        "value": {"title": "Value", "number_format": "0"},
                    },
                    "data_labels": {"show_value": True},
                    "colors": ["3366CC"],
                },
                "image_reference": {
                    "path": str(image),
                    "content_type": "image/png",
                    "fit": "contain",
                    "alt_text": "Synthetic pixel",
                },
                "notes": "Synthetic private notes remain because B1 keeps hidden content.",
            }
        ],
    }


def _external_and_ole_template(base: Path, destination: Path) -> None:
    package = OpcPackage.open(base)
    parts = dict(package.parts)
    slide = ElementTreePayload(parts, "ppt/slides/slide1.xml")
    relationships = ElementTreePayload(parts, "ppt/slides/_rels/slide1.xml.rels")
    chart = ElementTreePayload(parts, "ppt/charts/chart1.xml")
    content_types = ElementTreePayload(parts, "[Content_Types].xml")

    blip = next(node for node in slide.root.iter() if node.tag == qn("a", "blip"))
    blip.set(qn("r", "link"), "rIdExternalImage")
    non_visual = next(node for node in slide.root.iter() if node.tag == qn("p", "cNvPr"))
    SubElement(non_visual, qn("a", "hlinkClick"), {qn("r", "id"): "rIdExternalHyperlink"})
    SubElement(
        relationships.root,
        qn("rels", "Relationship"),
        {
            "Id": "rIdExternalImage",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": "https://example.invalid/private-image.png",
            "TargetMode": "External",
        },
    )
    SubElement(
        relationships.root,
        qn("rels", "Relationship"),
        {
            "Id": "rIdExternalHyperlink",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            "Target": "https://example.invalid/private-link",
            "TargetMode": "External",
        },
    )
    parent_map = {
        child: parent
        for parent in chart.root.iter()
        for child in parent
    }
    for literal in [
        node
        for node in chart.root.iter()
        if node.tag in {qn("c", "numLit"), qn("c", "strLit")}
    ]:
        numeric = literal.tag == qn("c", "numLit")
        reference = Element(qn("c", "numRef" if numeric else "strRef"))
        formula = SubElement(reference, qn("c", "f"))
        formula.text = "Sheet1!$B$2:$B$3" if numeric else "Sheet1!$A$2:$A$3"
        cache = SubElement(reference, qn("c", "numCache" if numeric else "strCache"))
        for child in list(literal):
            literal.remove(child)
            cache.append(child)
        parent = parent_map[literal]
        index = list(parent).index(literal)
        parent.remove(literal)
        parent.insert(index, reference)
    SubElement(chart.root, qn("c", "externalData"), {qn("r", "id"): "rIdWorkbook"})
    chart_relationships = Element(qn("rels", "Relationships"))
    SubElement(
        chart_relationships,
        qn("rels", "Relationship"),
        {
            "Id": "rIdWorkbook",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
            "Target": "../embeddings/syntheticWorkbook.xlsx",
        },
    )
    SubElement(
        content_types.root,
        f"{{{CONTENT_TYPES_NS}}}Override",
        {
            "PartName": "/ppt/embeddings/syntheticWorkbook.xlsx",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
    slide.store(parts)
    relationships.store(parts)
    chart.store(parts)
    content_types.store(parts)
    parts["ppt/charts/_rels/chart1.xml.rels"] = tostring(
        chart_relationships,
        encoding="UTF-8",
        xml_declaration=True,
    )
    parts["ppt/embeddings/syntheticWorkbook.xlsx"] = b"PK-synthetic-workbook-fixture"
    write_deterministic_zip(destination, parts)


def _mislabelled_active_template(base: Path, destination: Path) -> None:
    package = OpcPackage.open(base)
    parts = dict(package.parts)
    content_types = ElementTreePayload(parts, "[Content_Types].xml")
    presentation_rels = ElementTreePayload(parts, "ppt/_rels/presentation.xml.rels")
    root_rels = ElementTreePayload(parts, "_rels/.rels")
    for part, content_type in (
        ("/ppt/vbaProject.bin", "application/vnd.ms-office.vbaProject"),
        ("/ppt/activeX/activeX1.xml", "application/vnd.ms-office.activeX+xml"),
        ("/_xmlsignatures/origin.sigs", "application/vnd.openxmlformats-package.digital-signature-origin"),
        ("/_xmlsignatures/sig1.xml", "application/vnd.openxmlformats-package.digital-signature-xmlsignature+xml"),
    ):
        SubElement(
            content_types.root,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {"PartName": part, "ContentType": content_type},
        )
    SubElement(
        presentation_rels.root,
        qn("rels", "Relationship"),
        {
            "Id": "rIdSyntheticVba",
            "Type": "http://schemas.microsoft.com/office/2006/relationships/vbaProject",
            "Target": "vbaProject.bin",
        },
    )
    SubElement(
        root_rels.root,
        qn("rels", "Relationship"),
        {
            "Id": "rIdSyntheticSignature",
            "Type": "http://schemas.openxmlformats.org/package/2006/relationships/digital-signature/origin",
            "Target": "_xmlsignatures/origin.sigs",
        },
    )
    content_types.store(parts)
    presentation_rels.store(parts)
    root_rels.store(parts)
    parts["ppt/vbaProject.bin"] = b"synthetic-vba-marker-not-executable"
    parts["ppt/activeX/activeX1.xml"] = b'<?xml version="1.0" encoding="UTF-8"?><activeX/>'
    parts["_xmlsignatures/origin.sigs"] = b"synthetic-signature-origin"
    parts["_xmlsignatures/sig1.xml"] = b'<?xml version="1.0" encoding="UTF-8"?><Signature/>'
    write_deterministic_zip(destination, parts)


def _orphan_and_dangling_template(base: Path, destination: Path) -> None:
    package = OpcPackage.open(base)
    parts = dict(package.parts)
    relationships = ElementTreePayload(parts, "ppt/slides/_rels/slide1.xml.rels")
    existing = next(iter(relationships.root))
    SubElement(
        relationships.root,
        qn("rels", "Relationship"),
        {
            "Id": existing.attrib["Id"],
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": "../media/orphan.bin",
        },
    )
    SubElement(
        relationships.root,
        qn("rels", "Relationship"),
        {
            "Id": "rIdDangling",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": "../media/missing.png",
        },
    )
    relationships.store(parts)
    parts["ppt/media/orphan.bin"] = b"synthetic-orphan-private-payload"
    parts["ppt/media/unreachable.bin"] = b"synthetic-unreachable-private-payload"
    write_deterministic_zip(destination, parts)


class ElementTreePayload:
    def __init__(self, parts: dict[str, bytes], part: str) -> None:
        self.part = part
        self.root = fromstring(parts[part])

    def store(self, parts: dict[str, bytes]) -> None:
        parts[self.part] = tostring(
            self.root,
            encoding="UTF-8",
            xml_declaration=True,
        )


def _check(contract_root: Path, checked_root: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="pptx-ecosystem-fixtures-") as temporary:
        generated_root = Path(temporary)
        summary = generate(contract_root, generated_root)
        generated_files = sorted(
            path.relative_to(generated_root).as_posix()
            for path in generated_root.rglob("*")
            if path.is_file()
        )
        mismatches = [
            relative
            for relative in generated_files
            if not (checked_root / relative).is_file()
            or not filecmp.cmp(
                generated_root / relative,
                checked_root / relative,
                shallow=False,
            )
        ]
        if mismatches:
            raise ValueError(
                "checked-in PPTX ecosystem fixtures drifted: " + ", ".join(mismatches)
            )
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    checked_root = Path(__file__).resolve().parent
    summary = (
        _check(arguments.contract_root, checked_root)
        if arguments.check
        else generate(arguments.contract_root, checked_root)
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
