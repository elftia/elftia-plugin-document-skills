"""DOCX public-boundary tests split by operation family."""

from tests.support.docx_public import *  # noqa: F401,F403
from tests.support.docx_public import (
    _GIF,
    _PNG,
    _PNG_16,
    _public,
    _read_document,
    _report,
    _request,
    _table_values,
)

def test_public_template_style_overlay_imports_selected_style_and_keeps_conflict(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    overlay = tmp_path / "style-overlay.docx"
    with zipfile.ZipFile(public_created) as source_archive:
        with zipfile.ZipFile(overlay, "w") as overlay_archive:
            for item in source_archive.infolist():
                payload = source_archive.read(item)
                if item.filename == "word/styles.xml":
                    styles = fromstring(payload)
                    normal = next(
                        style
                        for style in styles.findall(qn("w", "style"))
                        if style.attrib.get(qn("w", "styleId")) == "Normal"
                    )
                    normal_run = normal.find(qn("w", "rPr"))
                    if normal_run is None:
                        normal_run = SubElement(normal, qn("w", "rPr"))
                    SubElement(
                        normal_run,
                        qn("w", "color"),
                        {qn("w", "val"): "FF0000"},
                    )
                    imported = SubElement(
                        styles,
                        qn("w", "style"),
                        {
                            qn("w", "type"): "paragraph",
                            qn("w", "styleId"): "AccentQuote",
                        },
                    )
                    SubElement(
                        imported,
                        qn("w", "name"),
                        {qn("w", "val"): "Accent Quote"},
                    )
                    SubElement(
                        imported,
                        qn("w", "basedOn"),
                        {qn("w", "val"): "Normal"},
                    )
                    imported_run = SubElement(imported, qn("w", "rPr"))
                    SubElement(
                        imported_run,
                        qn("w", "color"),
                        {qn("w", "val"): "336699"},
                    )
                    payload = tostring(
                        styles,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                overlay_archive.writestr(item, payload)
    overlay_sha256 = sha256_file(overlay)
    base_sha256 = sha256_file(public_created)
    output = tmp_path / "styled-template.docx"
    request = _request(
        tmp_path,
        "template-style-overlay.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "variables": {"name": "Agent"},
                "style_overlay": {
                    "source": str(overlay),
                    "expected_source_sha256": overlay_sha256,
                    "style_ids": ["AccentQuote", "Normal"],
                    "conflict_policy": "keep-base",
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["style_overlay"] == {
        "source": {
            "path": str(overlay.resolve()),
            "sha256": overlay_sha256,
            "bytes": overlay.stat().st_size,
        },
        "conflict_policy": "keep-base",
        "requested_style_ids": ["AccentQuote", "Normal"],
        "imported_style_ids": ["AccentQuote"],
        "replaced_style_ids": [],
        "kept_style_ids": ["Normal"],
    }
    assert operation["structure_diff"]["changed_parts"] == [
        "word/document.xml",
        "word/styles.xml",
    ]
    with zipfile.ZipFile(public_created) as base_archive:
        base_styles = fromstring(base_archive.read("word/styles.xml"))
    with zipfile.ZipFile(output) as output_archive:
        output_styles = fromstring(output_archive.read("word/styles.xml"))
    base_by_id = {
        node.attrib[qn("w", "styleId")]: tostring(node)
        for node in base_styles.findall(qn("w", "style"))
    }
    output_by_id = {
        node.attrib[qn("w", "styleId")]: tostring(node)
        for node in output_styles.findall(qn("w", "style"))
    }
    assert output_by_id["Normal"] == base_by_id["Normal"]
    assert set(base_by_id).issubset(output_by_id)
    assert "AccentQuote" in output_by_id
    assert sha256_file(public_created) == base_sha256
    assert sha256_file(overlay) == overlay_sha256


def test_public_template_style_overlay_replaces_conflict_from_relative_source(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    invocation = tmp_path / "style-overlay-invocation"
    assets = invocation / "assets"
    result_dir = invocation / "result"
    assets.mkdir(parents=True)
    result_dir.mkdir()
    overlay = assets / "replacement.docx"
    with zipfile.ZipFile(public_created) as source_archive:
        with zipfile.ZipFile(overlay, "w") as overlay_archive:
            for item in source_archive.infolist():
                payload = source_archive.read(item)
                if item.filename == "word/styles.xml":
                    styles = fromstring(payload)
                    normal = next(
                        style
                        for style in styles.findall(qn("w", "style"))
                        if style.attrib.get(qn("w", "styleId")) == "Normal"
                    )
                    run = normal.find(qn("w", "rPr"))
                    if run is None:
                        run = SubElement(normal, qn("w", "rPr"))
                    SubElement(
                        run,
                        qn("w", "color"),
                        {qn("w", "val"): "AA2255"},
                    )
                    payload = tostring(
                        styles,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                overlay_archive.writestr(item, payload)
    overlay_sha256 = sha256_file(overlay)
    request = _request(
        invocation,
        "request.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(public_created),
            "output": "result/replaced-style.docx",
            "arguments": {
                "variables": {"name": "Agent"},
                "style_overlay": {
                    "source": "assets/replacement.docx",
                    "expected_source_sha256": overlay_sha256,
                    "style_ids": ["Normal"],
                    "conflict_policy": "replace-existing",
                },
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        request.name,
        cwd=invocation,
    )

    assert result["status"] == "success", result
    report = result["diagnostics"]["operation_result"]["style_overlay"]
    assert report["imported_style_ids"] == []
    assert report["replaced_style_ids"] == ["Normal"]
    assert report["kept_style_ids"] == []
    output = result_dir / "replaced-style.docx"
    with zipfile.ZipFile(output) as archive:
        styles = fromstring(archive.read("word/styles.xml"))
    normal = next(
        style
        for style in styles.findall(qn("w", "style"))
        if style.attrib.get(qn("w", "styleId")) == "Normal"
    )
    color = next(normal.iter(qn("w", "color")))
    assert color.attrib[qn("w", "val")] == "AA2255"


def test_public_template_style_overlay_stale_hash_preserves_destination(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-stale-style-overlay.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    source_sha256 = sha256_file(public_created)
    request = _request(
        tmp_path,
        "template-style-overlay-stale.json",
        {
            "schema_version": "1.0",
            "operation": "docx.template.apply",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "variables": {"name": "Agent"},
                "style_overlay": {
                    "source": str(public_created),
                    "expected_source_sha256": "0" * 64,
                    "style_ids": ["Normal"],
                    "conflict_policy": "keep-base",
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["reason"] == (
        "expected-style-source-sha256"
    )
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256
