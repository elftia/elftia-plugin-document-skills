#!/usr/bin/env python3
"""Generate or verify deterministic phase B/C contract fixtures."""

from __future__ import annotations

import argparse
import filecmp
from hashlib import sha256
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
from tests.support.pptx_reconstruction_fixture import (  # noqa: E402
    write_reconstruction_fixtures,
)
from tests.support.pptx_template_fixture import build_semantic_template  # noqa: E402
from tests.support.pptx_svg_fixture import write_svg_fixtures  # noqa: E402
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1  # noqa: E402


_RELATIVE = "expected/contract-pin.json"
_REGISTRY_PREFIX = "pptx/ecosystem_bc/"
_REGISTRY_RECIPE = "tests/fixtures/pptx/ecosystem_bc/generate.py"
_REGISTRY_RECIPE_DEPENDENCIES = [
    "tests/support/pptx_ecosystem_fixture.py",
    "tests/support/pptx_reconstruction_fixture.py",
    "tests/support/pptx_svg_fixture.py",
    "tests/support/pptx_template_fixture.py",
]
_POWERPOINT_EVIDENCE_RECIPE = "tools/capture_pptx_powerpoint_evidence.py"
_POWERPOINT_EVIDENCE_DEPENDENCIES = [
    "src/document_skills_core/formats/pptx/png_compare.py",
    "tools/prepare_pptx_svg_roundtrip.py",
]


def generate(contract_root: Path, output_root: Path) -> dict[str, object]:
    summary = PresentationContractConsumer.open(contract_root).summary()
    metadata = FixtureMetadata(
        fixture_id="B0-CONTRACT-01",
        format="json",
        purpose="Pin the cross-producer presentation contract conformance result.",
        origin="Elftia-authored metadata derived from the owner package.",
        recipe=(
            "uv run --project plugin --frozen python "
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
    fixture_summary = (
        _write_b2_template_fixtures(writer)
        + _write_template_fixtures(writer)
        + write_svg_fixtures(writer, contract_root)
        + _write_equation_fixtures(writer)
        + write_reconstruction_fixtures(writer)
    )
    return {**summary, "fixtureCount": 1 + len(fixture_summary), "fixtures": fixture_summary}


def _write_equation_fixtures(writer: EcosystemFixtureWriter) -> list[str]:
    recipe = (
        "uv run --project plugin --frozen python "
        "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
        "<presentation-contract-root> --write"
    )
    supported = {
        "schemaVersion": 1,
        "cases": [
            {"id": "fraction", "source": {"kind": "latex", "value": r"\frac{1}{2}"}},
            {"id": "scripts", "source": {"kind": "latex", "value": "x_i^2"}},
            {"id": "sum", "source": {"kind": "latex", "value": r"\sum_{i=1}^{n}i"}},
            {"id": "root", "source": {"kind": "latex", "value": r"\sqrt[3]{x}"}},
            {
                "id": "matrix",
                "source": {
                    "kind": "latex",
                    "value": r"\begin{matrix}a & b \\ c & d\end{matrix}",
                },
            },
            {"id": "greek", "source": {"kind": "latex", "value": r"\alpha+\beta=\Gamma"}},
            {
                "id": "typed-ast",
                "source": {
                    "kind": "ast",
                    "value": {
                        "type": "fraction",
                        "numerator": {"type": "text", "value": "a"},
                        "denominator": {
                            "type": "radical",
                            "radicand": {"type": "text", "value": "b"},
                            "degree": None,
                        },
                    },
                },
            },
        ],
    }
    deep_ast: dict[str, object] = {"type": "text", "value": "x"}
    for _index in range(33):
        deep_ast = {"type": "radical", "radicand": deep_ast, "degree": None}
    unsupported = {
        "schemaVersion": 1,
        "cases": [
            {
                "id": "raw-omml",
                "source": {"kind": "latex", "value": "<m:oMath><m:r/></m:oMath>"},
                "expectedCode": "DS_ARCHIVE_UNSAFE",
            },
            {
                "id": "macro-command",
                "source": {"kind": "latex", "value": r"\newcommand{\x}{1}"},
                "expectedCode": "DS_ARCHIVE_UNSAFE",
            },
            {
                "id": "external-include",
                "source": {"kind": "latex", "value": r"\input{secret.tex}"},
                "expectedCode": "DS_ARCHIVE_UNSAFE",
            },
            {
                "id": "unknown-command",
                "source": {"kind": "latex", "value": r"\unknown{x}"},
                "expectedCode": "DS_UNSUPPORTED_FEATURE",
            },
            {
                "id": "length-limit",
                "source": {"kind": "latex", "value": "x" * 4_097},
                "expectedCode": "DS_RESOURCE_LIMIT",
            },
            {
                "id": "depth-limit",
                "source": {"kind": "ast", "value": deep_ast},
                "expectedCode": "DS_RESOURCE_LIMIT",
            },
        ],
    }
    common = {
        "origin": "Elftia-authored synthetic math fixture.",
        "recipe": recipe,
        "license": "GPL-3.0",
        "expected_operation": "pptx.create,pptx.edit",
        "expected_consumers": ("document-skills", "powerpoint", "libreoffice"),
        "resource_limits": {"maxBytes": 32_768},
    }
    writer.write_json(
        "equations/supported.json",
        supported,
        FixtureMetadata(
            fixture_id="B-EQ-01",
            format="json",
            purpose="Supported fraction, scripts, sum, root, matrix, Greek, and typed-AST equations.",
            invariants=(
                "each source normalizes to one canonical math AST and LaTeX value",
                "each emitted object is native editable Office Math",
                "readback preserves canonical semantics",
            ),
            security_classification="benign-generated-equations",
            **common,
        ),
    )
    writer.write_json(
        "equations/unsupported.json",
        unsupported,
        FixtureMetadata(
            fixture_id="B-EQ-02",
            format="json",
            purpose="Raw XML, macro, external include, unsupported command, and equation resource-limit cases.",
            invariants=(
                "raw OMML and XML are never accepted",
                "macros and external include commands fail closed",
                "depth and length limits return DS_RESOURCE_LIMIT",
            ),
            security_classification="synthetic-adversarial-equations",
            **common,
        ),
    )
    return ["B-EQ-01", "B-EQ-02"]


def _write_template_fixtures(writer: EcosystemFixtureWriter) -> list[str]:
    recipe = (
        "uv run --project plugin --frozen python "
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


def _write_b2_template_fixtures(writer: EcosystemFixtureWriter) -> list[str]:
    recipe = (
        "uv run --project plugin --frozen python "
        "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
        "<presentation-contract-root> --write"
    )
    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pptx-b2-template-fixtures-") as temporary:
        temporary_root = Path(temporary)
        for fixture_id, stem, roles, purpose in (
            (
                "B-TPL-01",
                "semantic-neutral",
                ("cover", "content", "detail", "content", "summary", "appendix"),
                "Six-page semantic template with native text, image, table, chart, and notes.",
            ),
            (
                "B-TPL-02",
                "dependency-heavy",
                ("cover", "content", "detail", "summary"),
                "Semantic template whose slides own distinct notes, media, and chart dependencies.",
            ),
        ):
            fixture_root = temporary_root / stem
            fixture_root.mkdir()
            fixture = build_semantic_template(
                fixture_root,
                _PLUGIN_ROOT,
                slides=len(roles),
                template_id=stem,
                slide_roles=roles,
            )
            writer.write_bytes(
                f"templates/{stem}.pptx",
                fixture.source.read_bytes(),
                FixtureMetadata(
                    fixture_id=fixture_id,
                    format="pptx",
                    purpose=purpose,
                    origin="Elftia-authored synthetic OOXML fixture.",
                    recipe=recipe,
                    license="GPL-3.0",
                    expected_operation="pptx.template.inspect,pptx.create.from-template",
                    expected_consumers=("document-skills", "design-studio", "powerpoint", "libreoffice"),
                    resource_limits={"maxBytes": 4_000_000},
                    invariants=(
                        "stable slide and object ids remain A-Contract conformant",
                        "semantic slots expose only stable addresses and precondition hashes",
                        "unselected private dependencies are physically purged",
                    ),
                    security_classification="benign-generated-semantic-template",
                ),
            )
            for contract_name in ("template_contract", "semantic_slots", "deck_ir"):
                source = Path(fixture.descriptor[contract_name]["path"])
                writer.write_json(
                    f"templates/{stem}.{contract_name.replace('_', '-')}.json",
                    json.loads(source.read_text(encoding="utf-8")),
                    FixtureMetadata(
                        fixture_id=fixture_id,
                        format="json",
                        purpose=f"A-Contract {contract_name} for {stem}.pptx.",
                        origin="Elftia-authored synthetic A-Contract metadata.",
                        recipe=recipe,
                        license="GPL-3.0",
                        expected_operation="pptx.template.inspect,pptx.create.from-template",
                        expected_consumers=("document-skills", "design-studio"),
                        resource_limits={"maxBytes": 256_000},
                        invariants=(
                            "schema version remains pinned to the owner package",
                            "stable ids and slot bindings match the adjacent template",
                            "license status remains not_evaluated without Governance evidence",
                        ),
                        security_classification="benign-generated-metadata",
                    ),
                )
            written.append(fixture_id)

        cjk_root = temporary_root / "cjk-capacity"
        cjk_root.mkdir()
        cjk = build_semantic_template(
            cjk_root,
            _PLUGIN_ROOT,
            slides=3,
            template_id="cjk-capacity",
        )
        cjk_path = temporary_root / "cjk-capacity.pptx"
        _cjk_capacity_template(cjk.source, cjk_path)
        writer.write_bytes(
            "templates/cjk-capacity.pptx",
            cjk_path.read_bytes(),
            FixtureMetadata(
                fixture_id="B-TPL-03",
                format="pptx",
                purpose="CJK capacity, type-scale, placeholder, ellipsis, and speaker-notes leak fixture.",
                origin="Elftia-authored synthetic OOXML fixture.",
                recipe=recipe,
                license="GPL-3.0",
                expected_operation="pptx.template.inspect,pptx.create.from-template",
                expected_consumers=("document-skills",),
                resource_limits={"maxBytes": 4_000_000},
                invariants=(
                    "long CJK text exceeds the declared recommended capacity",
                    "body type scale intentionally exceeds the title type scale",
                    "Chinese table content remains detectable",
                    "placeholder and ellipsis markers remain detectable",
                    "speaker-only notes marker remains detectable",
                ),
                security_classification="benign-generated-content-lint",
            ),
        )
        written.append("B-TPL-03")
    return written


def _cjk_capacity_template(base: Path, destination: Path) -> None:
    package = OpcPackage.open(base)
    parts = dict(package.parts)
    replacements = ("正文层级反转", "[PLACEHOLDER]", "…")
    for index, replacement in enumerate(replacements, 1):
        part = f"ppt/slides/slide{index}.xml"
        root = fromstring(parts[part])
        text = next(
            node
            for node in root.iter(qn("a", "t"))
            if node.text == f"Body {index}"
        )
        text.text = replacement
        if index == 1:
            title = next(
                node
                for node in root.iter(qn("a", "t"))
                if node.text == "Template page 1"
            )
            title.text = "这是一个明显超过推荐容量并用于验证中文字符计数与层级字号检查的超长标题"
            body_run = next(
                node
                for node in root.iter(qn("a", "r"))
                if node.find(qn("a", "t")) is text
            )
            body_run.find(qn("a", "rPr")).set("sz", "3600")
        if index == 2:
            table_text = next(
                node
                for node in root.iter(qn("a", "t"))
                if node.text == "Metric"
            )
            table_text.text = "指标"
        parts[part] = tostring(root, encoding="UTF-8", xml_declaration=True)
    notes = fromstring(parts["ppt/notesSlides/notesSlide1.xml"])
    note_text = next(node for node in notes.iter(qn("a", "t")) if node.text)
    note_text.text = "DO NOT SHARE — speaker only"
    parts["ppt/notesSlides/notesSlide1.xml"] = tostring(
        notes,
        encoding="UTF-8",
        xml_declaration=True,
    )
    write_deterministic_zip(destination, parts)


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
        _check_fixture_registry(checked_root)
        return summary


def _fixture_registry_records(ecosystem_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for manifest_path in sorted(ecosystem_root.rglob("*.manifest.json")):
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload_path = ecosystem_root / metadata["path"]
        payload_relative = _REGISTRY_PREFIX + metadata["path"]
        is_powerpoint_evidence = (
            metadata["security_classification"] == "benign-consumer-evidence"
        )
        common = {
            "authorship": "original-elftia",
            "license": metadata["license"],
            "origin": "generated",
            "recipe": (
                _POWERPOINT_EVIDENCE_RECIPE
                if is_powerpoint_evidence
                else _REGISTRY_RECIPE
            ),
            "recipe_dependencies": (
                _POWERPOINT_EVIDENCE_DEPENDENCIES
                if is_powerpoint_evidence
                else _REGISTRY_RECIPE_DEPENDENCIES
            ),
            "redistribution_allowed": metadata["redistributable"],
        }
        records.append({
            **common,
            "format": metadata["format"],
            "path": payload_relative,
            "purpose": metadata["purpose"],
            "security_classification": metadata["security_classification"],
            "sha256": sha256(payload_path.read_bytes()).hexdigest(),
        })
        records.append({
            **common,
            "format": "json",
            "path": _REGISTRY_PREFIX + manifest_path.relative_to(ecosystem_root).as_posix(),
            "purpose": f"Adjacent hash-bound metadata for {metadata['fixture_id']}.",
            "security_classification": "benign-generated-metadata",
            "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        })
    return sorted(records, key=lambda item: str(item["path"]))


def _fixture_registry_path(ecosystem_root: Path) -> Path:
    return ecosystem_root.parents[1] / "manifest.json"


def _check_fixture_registry(ecosystem_root: Path) -> None:
    registry = json.loads(_fixture_registry_path(ecosystem_root).read_text(encoding="utf-8"))
    actual = sorted(
        (
            record
            for record in registry["fixtures"]
            if str(record["path"]).startswith(_REGISTRY_PREFIX)
        ),
        key=lambda item: str(item["path"]),
    )
    expected = _fixture_registry_records(ecosystem_root)
    if actual != expected:
        raise ValueError("checked-in PPTX ecosystem fixture registry drifted")


def _write_fixture_registry(ecosystem_root: Path) -> None:
    registry_path = _fixture_registry_path(ecosystem_root)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["fixtures"]
    matching = [
        index
        for index, record in enumerate(current)
        if str(record["path"]).startswith(_REGISTRY_PREFIX)
    ]
    insert_at = matching[0] if matching else len(current)
    retained = [
        record
        for record in current
        if not str(record["path"]).startswith(_REGISTRY_PREFIX)
    ]
    retained[insert_at:insert_at] = _fixture_registry_records(ecosystem_root)
    registry_path.write_text(
        json.dumps(
            {"schema_version": "1.0", "fixtures": retained},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    checked_root = Path(__file__).resolve().parent
    if arguments.check:
        summary = _check(arguments.contract_root, checked_root)
    else:
        summary = generate(arguments.contract_root, checked_root)
        _write_fixture_registry(checked_root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
