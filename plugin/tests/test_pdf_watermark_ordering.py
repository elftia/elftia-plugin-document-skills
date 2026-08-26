"""Ordered public PDF edit transactions that include watermarks."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from PIL import Image

from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.watermark_scan import scan_watermark_uses
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor


def test_public_page_sequence_then_text_watermark_succeeds(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "ordered-watermark.pdf"
    create_pdf(source, _document(2))
    request = _request(
        tmp_path / "ordered-watermark.json",
        source,
        output,
        [
            {"type": "page_sequence", "pages": [2]},
            {
                "type": "watermark",
                "text": "AFTER SEQUENCE",
                "pages": [1],
                "opacity": 0.3,
            },
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert [item["primitive"] for item in operation["primitives"]] == [
        "page_sequence",
        "watermark",
    ]
    watermark = operation["primitives"][1]
    assert watermark["pages"] == [1]
    assert [record["page"] for record in watermark["watermark_uses"]] == [1]
    assert "_watermark_source_objects" not in operation["preservation"]
    assert "_watermark_source_objects" not in watermark["preservation"]
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 1
    uses = scan_watermark_uses(model, pages[0])
    assert len(uses) == 1
    assert uses[0].text == "AFTER SEQUENCE"


def test_public_page_sequence_then_rgba_image_watermark_succeeds(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "ordered-image-watermark.pdf"
    image = tmp_path / "alpha-watermark.png"
    create_pdf(source, _document(2))
    Image.new("RGBA", (3, 2), (25, 100, 220, 96)).save(image, format="PNG")
    request = _request(
        tmp_path / "ordered-image-watermark.json",
        source,
        output,
        [
            {"type": "page_sequence", "pages": [2]},
            _image_primitive(image),
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    watermark = result["diagnostics"]["operation_result"]["primitives"][1]
    evidence = watermark["image"]
    assert evidence["image_object"] in watermark["added_objects"]
    assert evidence["soft_mask"]["object"] in watermark["added_objects"]
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 1
    uses = scan_watermark_uses(model, pages[0])
    assert len(uses) == 1
    assert uses[0].asset_sha256 == sha256(image.read_bytes()).hexdigest()
    assert uses[0].soft_mask_present is True


def test_public_split_then_text_watermark_uses_the_split_stage_baseline(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "split-watermark.pdf"
    create_pdf(source, _document(2))
    request = _request(
        tmp_path / "split-watermark.json",
        source,
        output,
        [
            {"type": "split", "page_ranges": [[2, 2]]},
            {
                "type": "watermark",
                "text": "AFTER SPLIT",
                "pages": [1],
                "opacity": 0.25,
            },
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["primitives"][0]["retained_pages"] == 1
    assert operation["primitives"][1]["watermark_uses"][0]["page"] == 1
    uses = scan_watermark_uses(parse_pdf(output), walk_pages(parse_pdf(output))[0])
    assert [use.text for use in uses] == ["AFTER SPLIT"]


def test_public_page_insert_then_text_watermark_uses_the_combined_stage(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    donor = tmp_path / "donor.pdf"
    output = tmp_path / "insert-watermark.pdf"
    create_pdf(source, _document(1))
    create_pdf(donor, _document(1))
    request = _request(
        tmp_path / "insert-watermark.json",
        source,
        output,
        [
            {
                "type": "page_insert",
                "input": str(donor),
                "source_sha256": sha256(donor.read_bytes()).hexdigest(),
                "at": 1,
                "pages": [1],
            },
            {
                "type": "watermark",
                "text": "AFTER INSERT",
                "pages": [1],
                "opacity": 0.2,
            },
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["primitives"][0]["page_count"] == 2
    assert operation["primitives"][1]["watermark_uses"][0]["page"] == 1
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 2
    assert [use.text for use in scan_watermark_uses(model, pages[0])] == [
        "AFTER INSERT"
    ]
    assert scan_watermark_uses(model, pages[1]) == []


def test_public_merge_then_text_watermark_uses_the_merged_stage(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    donor = tmp_path / "donor.pdf"
    output = tmp_path / "merge-watermark.pdf"
    create_pdf(source, _document(1))
    create_pdf(donor, _document(1))
    request = _request(
        tmp_path / "merge-watermark.json",
        source,
        output,
        [
            {
                "type": "merge",
                "inputs": [
                    {
                        "input": str(source),
                        "source_sha256": sha256(source.read_bytes()).hexdigest(),
                    },
                    {
                        "input": str(donor),
                        "source_sha256": sha256(donor.read_bytes()).hexdigest(),
                    },
                ],
            },
            {
                "type": "watermark",
                "text": "AFTER MERGE",
                "pages": [2],
                "opacity": 0.2,
            },
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["primitives"][0]["page_count"] == 2
    assert operation["primitives"][1]["watermark_uses"][0]["page"] == 2
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 2
    assert scan_watermark_uses(model, pages[0]) == []
    assert [use.text for use in scan_watermark_uses(model, pages[1])] == [
        "AFTER MERGE"
    ]


def test_public_text_watermark_then_page_sequence_still_succeeds(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "watermark-then-sequence.pdf"
    create_pdf(source, _document(2))
    request = _request(
        tmp_path / "watermark-then-sequence.json",
        source,
        output,
        [
            {
                "type": "watermark",
                "text": "BEFORE SEQUENCE",
                "pages": [2],
                "opacity": 0.3,
            },
            {"type": "page_sequence", "pages": [2]},
        ],
    )

    result, success = PublicCommandSupervisor(project_root).run(
        "pdf",
        ["run", "--request", str(request)],
    )

    assert success is True, result
    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert [item["primitive"] for item in operation["primitives"]] == [
        "watermark",
        "page_sequence",
    ]
    model = parse_pdf(output)
    pages = walk_pages(model)
    assert len(pages) == 1
    assert [use.text for use in scan_watermark_uses(model, pages[0])] == [
        "BEFORE SEQUENCE"
    ]


def _document(page_count: int) -> dict[str, Any]:
    return {
        "metadata": {"title": "Watermark ordering", "author": "Elftia"},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": f"Page {number}",
                        "style": None,
                        "table": None,
                        "image": None,
                        "shape": None,
                    }
                ],
                "metadata": None,
            }
            for number in range(1, page_count + 1)
        ],
    }


def _image_primitive(path: Path) -> dict[str, Any]:
    return {
        "type": "watermark",
        "image": {
            "filename": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "content_type": "image/png",
            "fit": "contain",
            "width": 90,
            "height": 60,
            "alt": "Alpha watermark",
        },
        "pages": [1],
        "opacity": 0.4,
    }


def _request(
    path: Path,
    source: Path,
    output: Path,
    primitives: list[dict[str, Any]],
) -> Path:
    path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"primitives": primitives},
        }),
        encoding="utf-8",
        newline="\n",
    )
    return path
