"""Transactional service truth for constrained SVG creation."""

import hashlib
from pathlib import Path

from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.service import PptxService


def _request(source: Path, output: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create.from-svg",
        "input": str(source),
        "output": str(output),
        "arguments": {"fallback_policy": "reject"},
    }


def _svg(path: Path, body: str) -> Path:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
        f'viewBox="0 0 1920 1080"><defs/>{body}</svg>',
        encoding="utf-8",
    )
    return path


def test_svg_service_promotes_only_validated_shared_scene(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _svg(
        tmp_path / "source.svg",
        '<rect id="card" x="100" y="100" width="600" height="300" fill="#335577"/>'
        '<text id="label" x="140" y="240" textLength="400" font-size="40" fill="#FFFFFF">Editable</text>',
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "output.pptx"

    result = PptxService(project_root).execute(
        "pptx.create.from-svg",
        _request(source, output),
    )

    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["validation"]["status"] == "pass"
    assert result["diagnostics"]["operation_result"]["coverage"]["whole_slide_raster"] is False
    assert [item["source_id"] for item in result["diagnostics"]["operation_result"]["mapping"]] == [
        "card",
        "label",
    ]
    assert output.is_file()
    assert len(OpcPackage.open(output).slide_parts()) == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash


def test_svg_service_failure_preserves_source_and_destination(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _svg(tmp_path / "unsafe.svg", '<script id="bad">bad()</script>')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "output.pptx"
    output.write_bytes(b"existing destination")
    destination_hash = hashlib.sha256(output.read_bytes()).hexdigest()

    result = PptxService(project_root).execute(
        "pptx.create.from-svg",
        _request(source, output),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(output.read_bytes()).hexdigest() == destination_hash
