"""Checked real-consumer evidence for the B-SVG-04 round trip."""

from __future__ import annotations

from tests.support.pptx_ecosystem_fixture import (
    EcosystemFixtureWriter,
    FixtureMetadata,
)


_RECIPE = (
    "uv run --project plugin --frozen python "
    "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
    "<presentation-contract-root> --write"
)


def write_powerpoint_consumer_evidence(writer: EcosystemFixtureWriter) -> None:
    """Record the observed PowerPoint 16.0 native-object and render evidence."""

    writer.write_json(
        "expected/visual/b5-powerpoint-consumer.json",
        _evidence(),
        FixtureMetadata(
            fixture_id="B-SVG-04",
            format="json",
            purpose=(
                "Auditable Microsoft PowerPoint native-object and visual round-trip "
                "evidence for B-SVG-04."
            ),
            origin=(
                "Elftia-authored observation recorded from Microsoft PowerPoint "
                "16.0 on Windows."
            ),
            recipe=_RECIPE,
            license="GPL-3.0",
            expected_operation="pptx.scene.export,pptx.create.from-svg",
            expected_consumers=("document-skills", "powerpoint"),
            resource_limits={"maxBytes": 32_768},
            invariants=(
                "PowerPoint opens both source and round-trip decks read-only",
                "group, text, table, chart, and picture remain native objects",
                "PowerPoint PNG exports stay within the checked visual thresholds",
                "unavailable LibreOffice execution remains explicitly not_run",
                "temporary render and round-trip bytes are excluded from release bytes",
            ),
            security_classification="benign-consumer-evidence",
        ),
    )


def _evidence() -> dict[str, object]:
    source_shapes = [
        {
            "children": [
                {"hasTextFrame": True, "msoType": 1, "name": "source-shape", "text": ""},
                {
                    "hasTextFrame": True,
                    "msoType": 1,
                    "name": "source-text",
                    "text": "Round trip",
                },
            ],
            "msoType": 6,
            "name": "source-group",
        },
        {"hasTable": True, "msoType": 19, "name": "source-table"},
        {"hasChart": True, "msoType": 3, "name": "source-chart"},
        {"msoType": 13, "name": "source-image"},
    ]
    roundtrip_shapes = [
        {
            "children": [
                {
                    "hasTextFrame": True,
                    "msoType": 1,
                    "name": "object_15e15359adb7b0df55ecda0c9bbb8294",
                    "text": "",
                },
                {
                    "hasTextFrame": True,
                    "msoType": 1,
                    "name": "object_5e4941d3c4e6c95c18b99f78a5544eb8",
                    "text": "Round trip",
                },
            ],
            "msoType": 6,
            "name": "object_2c2171f908da61fd81548d34789d614f",
        },
        {
            "hasTable": True,
            "msoType": 19,
            "name": "object_774a686ebf1a8cf0e5ee1941efcbff6c",
        },
        {
            "hasChart": True,
            "msoType": 3,
            "name": "object_2573ab4335b7a4244a4219d64998ea61",
        },
        {"msoType": 13, "name": "object_c338f3378510f7f3d976c3515f4aadc6"},
    ]
    return {
        "assertions": {
            "chartEditable": "pass",
            "groupEditable": "pass",
            "nativePictureReadback": "pass",
            "shapeEditable": "pass",
            "tableEditable": "pass",
            "textEditable": "pass",
            "topLevelObjectTypesEqual": True,
        },
        "consumer": {
            "application": "Microsoft PowerPoint",
            "method": "COM read-only open, native object readback, and PNG export",
            "outcome": "pass",
            "platform": "windows-x64",
            "version": "16.0",
        },
        "libreOffice": {
            "availability": "unavailable",
            "outcome": "not_run",
            "reason": "No soffice or libreoffice executable was available on PATH.",
        },
        "observedAt": "2026-08-26",
        "releaseBytePolicy": {
            "checkedInSource": "svg/roundtrip-source.pptx",
            "observationOnly": [
                "roundtrip.pptx",
                "scene-bundle/",
                "renders/source/*.PNG",
                "renders/roundtrip/*.PNG",
            ],
            "renderBytesIncluded": False,
        },
        "renderComparison": {
            "metrics": {
                "aspectRatioDelta": 0.0,
                "changedPixelRatio": 0.00135,
                "meanAbsoluteError": 0.000835,
                "regionDifferences": [],
                "regionDifferencesTruncated": 0,
                "withinThresholds": True,
            },
            "roundtripPng": {
                "bytes": 12_906,
                "height": 1080,
                "sha256": "48fefd81af686a07e4452f605b578501664069ff0635e5c343c7b0e18f65ab52",
                "width": 1920,
            },
            "sourcePng": {
                "bytes": 13_579,
                "height": 1080,
                "sha256": "3d3770867544103ab9765d75c5b6f4fdb86f8ba7c41b63a10d0e4c12594cdf9f",
                "width": 1920,
            },
            "thresholds": {
                "aspectRatioDeltaMax": 0.01,
                "changedPixelDelta": 0.12,
                "changedPixelRatioMax": 0.2,
                "meanAbsoluteErrorMax": 0.08,
                "regionGrid": {"columns": 12, "rows": 6},
                "sampleGrid": {"height": 54, "width": 96},
            },
            "tool": "document_skills_core.formats.pptx.png_compare.compare_png",
        },
        "roundtrip": {
            "artifact": {
                "bytes": 7_153,
                "sha256": "85eceeffd22aeac84f53aa2e8a90173e1c689e6d8e1799b289871df83707a1b8",
            },
            "chartType": 57,
            "slideCount": 1,
            "tableCells": [["Quarter", "Revenue"], ["Q1", "42"]],
            "topLevelShapes": roundtrip_shapes,
        },
        "schemaVersion": 1,
        "shapeTypeLegend": {
            "1": "msoAutoShape",
            "3": "msoChart",
            "6": "msoGroup",
            "13": "msoPicture",
            "19": "msoTable",
        },
        "source": {
            "artifact": {
                "bytes": 7_009,
                "sha256": "44deff5f1e7f028089de2ec3b0a9bef11a54ccdbfc11df1458490754dac56d04",
            },
            "chartType": 57,
            "slideCount": 1,
            "tableCells": [["Quarter", "Revenue"], ["Q1", "42"]],
            "topLevelShapes": source_shapes,
        },
    }


__all__ = ["write_powerpoint_consumer_evidence"]
