"""Public text pagination and widow/orphan policy tests."""

import hashlib
from pathlib import Path

from tests.test_pdf_public import _PNG, _write_pdf_fixture
from tests.test_pdf_unicode import _public, _write_request


def test_public_long_unbroken_token_wraps_inside_content_box(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "long-token.pdf"
    token = "W" * 80
    request = _write_request(
        tmp_path / "long-token.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Long token",
                        "author": "Elftia",
                        "subject": "Horizontal overflow",
                    },
                    "page_size": "A4",
                    "pages": [{"blocks": [{"type": "paragraph", "text": token}]}],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]
    content_box = creation["content_boxes"][0]
    lines = creation["text_blocks"]
    assert len(lines) > 1
    assert "".join(line["text"] for line in lines) == token
    assert all(
        line["bbox"][0] >= content_box[0]
        and line["bbox"][1] >= content_box[1]
        and line["bbox"][2] <= content_box[2]
        and line["bbox"][3] <= content_box[3]
        for line in lines
    )
    gate = next(
        item
        for item in result["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["outcome"] == "pass"


def test_public_text_pagination_respects_widow_and_orphan_lines(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "paginated-text.pdf"
    paragraph = " ".join(f"word-{index:02d}" for index in range(1, 49))
    request = _write_request(
        tmp_path / "paginated-text.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Paginated text",
                        "author": "Elftia",
                        "subject": "Widow and orphan policy",
                    },
                    "page_size": {"width": 240, "height": 180},
                    "pages": [{
                        "overflow_policy": "paginate",
                        "widow_lines": 2,
                        "orphan_lines": 2,
                        "margin": {
                            "top": 24,
                            "right": 24,
                            "bottom": 24,
                            "left": 24,
                        },
                        "blocks": [{
                            "type": "paragraph",
                            "text": paragraph,
                            "style": {
                                "font_family": "Helvetica",
                                "font_size": 12,
                                "font_weight": "normal",
                                "font_style": "normal",
                                "color": [0.0, 0.0, 0.0],
                                "line_height": 16,
                                "alignment": "left",
                                "fallback_fonts": [],
                                "direction": "ltr",
                                "language": "en",
                            },
                            "table": None,
                            "image": None,
                            "shape": None,
                        }],
                        "metadata": None,
                    }],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success"
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_count"] >= 2
    lines_by_page: dict[int, int] = {}
    for block in creation["text_blocks"]:
        lines_by_page[block["page"]] = lines_by_page.get(block["page"], 0) + 1
    assert min(lines_by_page.values()) >= 2

    read_request = _write_request(
        tmp_path / "paginated-text-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    pages = read_result["diagnostics"]["operation_result"]["text_by_page"]
    actual = " ".join(item["text"] for item in pages).split()
    assert actual == paragraph.split()


def test_public_shape_on_static_page_after_paginated_page_uses_output_page(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "shifted-static-shape.pdf"
    paragraph = " ".join(f"shift-{index:02d}" for index in range(1, 49))
    request = _write_request(
        tmp_path / "shifted-static-shape.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Shifted static shape",
                        "author": "Elftia",
                        "subject": "Pagination placement",
                    },
                    "page_size": {"width": 240, "height": 180},
                    "pages": [
                        {
                            "overflow_policy": "paginate",
                            "widow_lines": 2,
                            "orphan_lines": 2,
                            "margin": {
                                "top": 24,
                                "right": 24,
                                "bottom": 24,
                                "left": 24,
                            },
                            "blocks": [{
                                "type": "paragraph",
                                "text": paragraph,
                            }],
                        },
                        {
                            "blocks": [{
                                "type": "vector_shape",
                                "shape": {
                                    "kind": "rectangle",
                                    "x": 30,
                                    "y": 30,
                                    "width": 30,
                                    "height": 20,
                                    "stroke": [0.0, 0.0, 0.0],
                                    "fill": None,
                                },
                            }],
                        },
                    ],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_count"] >= 3
    assert len(creation["shapes"]) == 1
    shape = creation["shapes"][0]
    assert shape["page"] > 2
    mapped_shape = next(
        block
        for page in creation["mapping"]["pages"]
        for block in page["blocks"]
        if block["type"] == "vector_shape"
    )
    mapped_page = next(
        page["page"]
        for page in creation["mapping"]["pages"]
        if mapped_shape in page["blocks"]
    )
    assert (mapped_page, mapped_shape["block_index"]) == (
        shape["page"],
        shape["block_index"],
    )
    gate = next(
        item
        for item in result["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["evidence"]["shapes"][0]["page"] == shape["page"]


def test_public_mixed_content_paginates_flow_blocks_in_order(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "mixed-content.png"
    image.write_bytes(_PNG)
    output = tmp_path / "mixed-content.pdf"
    paragraph = " ".join(f"flow-{index:02d}" for index in range(1, 31))
    rows = [
        {"cells": ["Name", "Value"], "height": 24},
        *[
            {"cells": [f"row-{index}", str(index)], "height": 24}
            for index in range(1, 7)
        ],
    ]
    request = _write_request(
        tmp_path / "mixed-content.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Mixed pagination",
                        "author": "Elftia",
                        "subject": "Flow blocks",
                    },
                    "page_size": {"width": 240, "height": 180},
                    "pages": [{
                        "overflow_policy": "paginate",
                        "widow_lines": 2,
                        "orphan_lines": 2,
                        "margin": {
                            "top": 24,
                            "right": 24,
                            "bottom": 24,
                            "left": 24,
                        },
                        "blocks": [
                            {"type": "heading", "text": "Mixed content"},
                            {"type": "paragraph", "text": paragraph},
                            {
                                "type": "vector_shape",
                                "shape": {
                                    "kind": "rectangle",
                                    "x": 30,
                                    "y": 30,
                                    "width": 30,
                                    "height": 20,
                                    "stroke": [0.0, 0.0, 0.0],
                                    "fill": None,
                                },
                            },
                            {
                                "type": "image",
                                "image": {
                                    "filename": str(image),
                                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                                    "content_type": "image/png",
                                    "fit": "contain",
                                    "width": 50,
                                    "height": 80,
                                    "alt": "Mixed pagination image",
                                },
                            },
                            {
                                "type": "table",
                                "table": {
                                    "rows": rows,
                                    "header_rows": 1,
                                    "repeat_header": True,
                                },
                            },
                            {"type": "paragraph", "text": "After table"},
                        ],
                    }],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_count"] >= 4
    assert len(creation["images"]) == 1
    assert len(creation["shapes"]) == 1
    assert [table["row_count"] for table in creation["tables"]] == [5, 3]
    image_page = creation["images"][0]["page"]
    shape_page = creation["shapes"][0]["page"]
    table_pages = [table["page"] for table in creation["tables"]]
    trailing_page = next(
        block["page"]
        for block in creation["text_blocks"]
        if block["text"] == "After table"
    )
    assert shape_page <= image_page < table_pages[0]
    assert table_pages[1] == table_pages[0] + 1
    assert trailing_page == table_pages[-1]


def test_public_mixed_pagination_rejects_an_oversized_image_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "oversized.png"
    image.write_bytes(_PNG)
    output = tmp_path / "oversized.pdf"
    output.write_bytes(b"existing-destination")
    request = _write_request(
        tmp_path / "oversized.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Oversized image",
                        "author": "Elftia",
                        "subject": "Atomic failure",
                    },
                    "page_size": {"width": 240, "height": 180},
                    "pages": [{
                        "overflow_policy": "paginate",
                        "margin": {
                            "top": 24,
                            "right": 24,
                            "bottom": 24,
                            "left": 24,
                        },
                        "blocks": [{
                            "type": "image",
                            "image": {
                                "filename": str(image),
                                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                                "content_type": "image/png",
                                "fit": "contain",
                                "width": 50,
                                "height": 133,
                                "alt": "Too tall",
                            },
                        }],
                    }],
                },
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["details"]["capability"] == "pdf.image-overflow"
    assert result["artifacts"] == []
    assert output.read_bytes() == b"existing-destination"


def test_public_design_tokens_drive_page_palette_typography_and_spacing(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "design-tokens.pdf"
    request = _write_request(
        tmp_path / "design-tokens.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Design tokens",
                        "author": "Elftia",
                        "subject": "Typed defaults",
                    },
                    "design_tokens": {
                        "page_size": {"width": 300, "height": 240},
                        "margin": {
                            "top": 30,
                            "right": 30,
                            "bottom": 30,
                            "left": 30,
                        },
                        "palette": {
                            "ink": [0.1, 0.2, 0.3],
                            "accent": [0.8, 0.2, 0.1],
                            "surface": [0.95, 0.95, 0.9],
                        },
                        "typography": {
                            "paragraph": {
                                "font_size": 10,
                                "line_height": 12,
                                "color": "ink",
                            },
                        },
                        "spacing": {"paragraph_gap": 24},
                    },
                    "pages": [{
                        "blocks": [
                            {
                                "type": "paragraph",
                                "text": "First tokenized line",
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": None,
                            },
                            {
                                "type": "paragraph",
                                "text": "Second tokenized line",
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": None,
                            },
                            {
                                "type": "vector_shape",
                                "text": None,
                                "style": None,
                                "table": None,
                                "image": None,
                                "shape": {
                                    "kind": "rounded_rectangle",
                                    "x": 40,
                                    "y": 40,
                                    "width": 80,
                                    "height": 30,
                                    "corner_radius": 6,
                                    "stroke": "accent",
                                    "fill": "surface",
                                    "opacity": 0.75,
                                    "dash": [3, 2],
                                },
                            },
                        ],
                        "metadata": None,
                    }],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success"
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_size"] == [300.0, 240.0]
    first, second = creation["text_blocks"]
    assert first["color"] == [0.1, 0.2, 0.3]
    assert first["size"] == 10.0
    assert round(first["bbox"][1] - second["bbox"][1], 4) == 36.0
    assert creation["shapes"][0]["stroke"] == [0.8, 0.2, 0.1]
    assert creation["shapes"][0]["fill"] == [0.95, 0.95, 0.9]
    assert creation["design_tokens"]["spacing"]["paragraph_gap"] == 24.0


def test_public_read_supports_column_order_page_and_bbox_selection(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"\n".join([
        b"BT /F1 12 Tf 1 0 0 1 250 240 Tm (Right top) Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 250 200 Tm (Right bottom) Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 50 240 Tm (Left top) Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 50 200 Tm (Left bottom) Tj ET",
    ])
    source = _write_pdf_fixture(
        tmp_path / "two-columns.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            (
                f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
                + content
                + b"\nendstream"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ],
    )
    columns_request = _write_request(
        tmp_path / "two-columns-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(source),
            "arguments": {
                "pages": [1],
                "reading_order": "columns",
                "column_count": 2,
            },
        },
    )

    columns_result = _public(
        project_root,
        "run",
        "--request",
        str(columns_request),
    )

    operation = columns_result["diagnostics"]["operation_result"]
    assert operation["document_page_count"] == 1
    assert operation["text_by_page"][0]["text"].splitlines() == [
        "Left top",
        "Left bottom",
        "Right top",
        "Right bottom",
    ]
    assert operation["text_selection"]["reading_order"] == "columns"

    bbox_request = _write_request(
        tmp_path / "left-column-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(source),
            "arguments": {
                "pages": [1],
                "bbox": [0, 0, 200, 300],
                "reading_order": "geometric",
            },
        },
    )
    bbox_result = _public(project_root, "run", "--request", str(bbox_request))
    bbox_operation = bbox_result["diagnostics"]["operation_result"]
    assert bbox_operation["text_by_page"][0]["text"].splitlines() == [
        "Left top",
        "Left bottom",
    ]
    assert len(bbox_operation["text_blocks"]) == 2
