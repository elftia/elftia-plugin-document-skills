"""Deterministic B5 constrained-SVG and scene round-trip fixtures."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import tempfile

from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.presentation_contracts import (
    PresentationContractConsumer,
)
from document_skills_core.formats.pptx.scene_emitter import (
    SLIDE_CX,
    SLIDE_CY,
    emit_scene_pptx,
)
from document_skills_core.formats.pptx.scene_export_objects import (
    project_scene_objects,
)
from document_skills_core.formats.pptx.svg_parser import compile_svg_scene
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1
from tests.support.pptx_ecosystem_fixture import (
    EcosystemFixtureWriter,
    FixtureMetadata,
)

_RECIPE = (
    "uv run --project plugin --frozen python "
    "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
    "<presentation-contract-root> --write"
)


def write_svg_fixtures(
    writer: EcosystemFixtureWriter,
    contract_root: Path,
) -> list[str]:
    writer.write_bytes(
        "svg/native-basic/native-basic.svg",
        _svg(_native_basic()).encode("utf-8"),
        _metadata(
            "B-SVG-01",
            "svg",
            "Closed-profile native path, primitive, group, text, and transform fixture.",
            "pptx.create.from-svg",
            (
                "every top-level and grouped object emits editable DrawingML",
                "custom path geometry remains native and no whole-slide raster is present",
                "source ids bind deterministically to emitted object ids",
            ),
            "benign-generated-svg",
            max_bytes=128_000,
        ),
    )
    writer.write_bytes(
        "svg/native-gradient-image/gradient-image.svg",
        _svg(_gradient_image()).encode("utf-8"),
        _metadata(
            "B-SVG-02",
            "svg",
            "Approved gradient plus local bounded transparent PNG fixture.",
            "pptx.create.from-svg",
            (
                "gradient remains native DrawingML",
                "local image is hash-bound and embedded once",
                "z-order, opacity, and source mapping survive reopen",
            ),
            "benign-generated-svg",
            max_bytes=64_000,
        ),
    )
    writer.write_bytes(
        "svg/native-gradient-image/image.png",
        PNG_1X1,
        _metadata(
            "B-SVG-02",
            "png",
            "Local bounded PNG used by the B-SVG-02 gradient/image fixture.",
            "pptx.create.from-svg",
            (
                "bytes remain deterministic",
                "SVG resolution never escapes the adjacent fixture directory",
            ),
            "benign-generated-image",
            max_bytes=4_096,
        ),
    )
    for name, body, classification in _unsupported_cases():
        writer.write_bytes(
            f"svg/unsupported/{name}.svg",
            _svg(body).encode("utf-8"),
            _metadata(
                "B-SVG-03",
                "svg",
                f"Closed-profile rejection fixture for {name}.",
                "pptx.create.from-svg",
                (
                    "unsafe or unsupported content never executes or dereferences",
                    "rejection publishes no PPTX output",
                    "element fallback never becomes a whole-slide raster",
                ),
                classification,
                max_bytes=128_000,
            ),
        )
    _write_roundtrip(writer, contract_root)
    return ["B-SVG-01", "B-SVG-02", "B-SVG-03", "B-SVG-04"]


def _write_roundtrip(
    writer: EcosystemFixtureWriter,
    contract_root: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="pptx-b5-svg-roundtrip-") as temporary:
        root = Path(temporary)
        image = root / "image.png"
        image.write_bytes(PNG_1X1)
        source_svg = root / "roundtrip-source.svg"
        source_svg.write_text(
            _svg(_roundtrip_body()),
            encoding="utf-8",
            newline="\n",
        )
        scene = compile_svg_scene(source_svg, fallback_policy="reject")
        source_pptx = root / "roundtrip-source.pptx"
        emission = emit_scene_pptx(
            source_pptx,
            scene,
            {"creator": "Elftia", "subject": "B5", "title": "B5 Round Trip"},
        )
        writer.write_bytes(
            "svg/roundtrip-source.pptx",
            source_pptx.read_bytes(),
            _metadata(
                "B-SVG-04",
                "pptx",
                "Native text, shape, table, chart, image, and group scene round-trip source.",
                "pptx.scene.export,pptx.create.from-svg",
                (
                    "PPTX exports to pinned A-Contract Deck IR and constrained SVG",
                    "exported SVG recompiles to editable native objects",
                    "semantic object identity, z-order, text, table, chart, image, and group survive",
                ),
                "benign-generated-pptx",
                max_bytes=4_000_000,
                consumers=("document-skills", "powerpoint", "libreoffice"),
            ),
        )
        consumer = PresentationContractConsumer.open(contract_root)
        deck_id = consumer.stable_deck_id(
            namespace="example.synthetic",
            source_template_id="svg-roundtrip",
            source_template_version="1.0.0",
        )
        projection = project_scene_objects(
            OpcPackage.open(source_pptx),
            consumer,
            deck_id=deck_id,
            source_template_id="svg-roundtrip",
            mode="strict",
            slide_cx=SLIDE_CX,
            slide_cy=SLIDE_CY,
        )
        expected = {
            "contractManifestSha256": consumer.pin.manifest_sha256,
            "deckId": deck_id,
            "emission": {
                key: emission[key]
                for key in ("charts", "media", "objects", "slides")
            },
            "objectTypes": [
                item["type"]
                for item in projection.slides[0]["objects"]
            ],
            "slideId": projection.slides[0]["slideId"],
            "sourceMapping": projection.source_mapping,
            "sourcePptxSha256": hashlib.sha256(
                source_pptx.read_bytes()
            ).hexdigest(),
            "unsupported": projection.unsupported,
            "visualExpectation": {
                "libreoffice": "run-when-provider-available",
                "powerpoint": "required-on-windows-release-evidence",
            },
            "wholeSlideRaster": False,
        }
        writer.write_json(
            "expected/scene/b5-roundtrip.json",
            expected,
            _metadata(
                "B-SVG-04",
                "json",
                "Stable semantic and native-object oracle for the B5 scene round-trip.",
                "pptx.scene.export,pptx.create.from-svg",
                (
                    "stable ids match the pinned A-Contract owner package",
                    "all source mappings and native object types remain deterministic",
                    "visual providers remain explicit instead of inferred from structure",
                ),
                "benign-generated-oracle",
                max_bytes=256_000,
                consumers=("document-skills", "design-studio"),
            ),
        )


def _metadata(
    fixture_id: str,
    format_name: str,
    purpose: str,
    operation: str,
    invariants: tuple[str, ...],
    classification: str,
    *,
    max_bytes: int,
    consumers: tuple[str, ...] = ("document-skills",),
) -> FixtureMetadata:
    return FixtureMetadata(
        fixture_id=fixture_id,
        format=format_name,
        purpose=purpose,
        origin="Elftia-authored deterministic synthetic fixture.",
        recipe=_RECIPE,
        license="GPL-3.0",
        expected_operation=operation,
        expected_consumers=consumers,
        resource_limits={"maxBytes": max_bytes},
        invariants=invariants,
        security_classification=classification,
    )


def _svg(body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
        f'viewBox="0 0 1920 1080"><defs>{_definitions()}</defs>{body}</svg>'
    )


def _definitions() -> str:
    return (
        '<linearGradient id="approved-gradient" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#123456"/>'
        '<stop offset="1" stop-color="#88AACC" stop-opacity="0.75"/>'
        '</linearGradient><filter id="unsupported-filter"/>'
    )


def _native_basic() -> str:
    return (
        '<g id="group-main" transform="translate(20 10) scale(0.9)">'
        '<rect id="rect-main" x="40" y="30" width="300" height="160" rx="18" fill="#2255AA"/>'
        '<line id="line-main" x1="380" y1="60" x2="620" y2="180" stroke="#112233" stroke-width="4"/>'
        '<ellipse id="ellipse-main" cx="780" cy="150" rx="120" ry="80" fill="#55AA88"/>'
        '<polygon id="polygon-main" points="980,60 1160,180 920,220" fill="#AA5522"/>'
        '<path id="path-main" d="M 1240 80 L 1450 80 Q 1530 160 1450 240 C 1360 300 1270 260 1240 180 Z" fill="#8844AA"/>'
        '<text id="text-main" x="80" y="360" textLength="700" font-size="44" fill="#111111">Hello <tspan font-weight="700">SVG</tspan></text>'
        '</g>'
    )


def _gradient_image() -> str:
    return (
        '<rect id="gradient-card" x="100" y="80" width="800" height="420" fill="url(#approved-gradient)"/>'
        '<image id="local-image" x="980" y="100" width="400" height="300" href="image.png" opacity="0.6"/>'
    )


def _roundtrip_body() -> str:
    table = html.escape(
        json.dumps(
            {"header_rows": 1, "rows": [["Quarter", "Revenue"], ["Q1", "42"]]},
            sort_keys=True,
            separators=(",", ":"),
        ),
        quote=True,
    )
    chart = html.escape(
        json.dumps(
            {
                "categories": ["Q1", "Q2"],
                "chart_type": "bar",
                "series": [{"name": "Revenue", "values": [42, 55]}],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        quote=True,
    )
    return (
        '<g id="source-group"><rect id="source-shape" x="80" y="70" width="420" height="220" fill="#225588"/>'
        '<text id="source-text" x="110" y="180" textLength="340" font-size="36" fill="#FFFFFF">Round trip</text></g>'
        f'<g id="source-table" data-elftia-kind="table" data-elftia-bounds="80,360,700,300" data-elftia-model="{table}"><rect x="80" y="360" width="700" height="300" fill="#FFFFFF"/></g>'
        f'<g id="source-chart" data-elftia-kind="chart" data-elftia-bounds="860,90,880,570" data-elftia-model="{chart}"><rect x="860" y="90" width="880" height="570" fill="#FFFFFF"/></g>'
        '<image id="source-image" x="80" y="740" width="220" height="180" href="image.png"/>'
    )


def _unsupported_cases() -> tuple[tuple[str, str, str], ...]:
    path_bomb = "M 0 0 " + " ".join(
        f"L {index} {index % 100}" for index in range(3_000)
    )
    return (
        ("script", '<script id="bad">bad()</script>', "adversarial-svg-script"),
        ("foreign-object", '<foreignObject id="bad" x="1" y="1" width="10" height="10"/>', "adversarial-svg-foreign-object"),
        ("event-handler", '<rect id="bad" x="1" y="1" width="10" height="10" onclick="bad()"/>', "adversarial-svg-event"),
        ("external-image", '<image id="bad" x="1" y="1" width="10" height="10" href="https://example.invalid/a.png"/>', "adversarial-svg-external-reference"),
        ("filter", '<rect id="bad" x="1" y="1" width="10" height="10" filter="url(#unsupported-filter)"/>', "unsupported-svg-filter"),
        ("animation", '<animate id="bad" attributeName="x"/>', "adversarial-svg-animation"),
        ("path-bomb", f'<path id="bad" d="{path_bomb}"/>', "adversarial-svg-resource-limit"),
    )


__all__ = ["write_svg_fixtures"]
