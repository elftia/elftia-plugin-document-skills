"""Public styled table creation and bounded header-repeat pagination tests."""

from pathlib import Path

from tests.test_pdf_unicode import _font_spec, _public, _write_request


def test_public_long_table_token_wraps_inside_cell_content_box(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "long-table-token.pdf"
    token = "W" * 40
    request = _write_request(
        tmp_path / "long-table-token.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Long table token",
                        "author": "Elftia",
                        "subject": "Cell overflow",
                    },
                    "page_size": "A4",
                    "pages": [{
                        "blocks": [{
                            "type": "table",
                            "table": {
                                "rows": [{"cells": [token]}],
                                "column_widths": [120],
                                "padding": 4,
                            },
                        }],
                    }],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    table = result["diagnostics"]["operation_result"]["creation"]["tables"][0]
    cell = table["cells"][0]
    assert len(cell["line_bboxes"]) > 1
    assert all(
        line[0] >= cell["content_bbox"][0]
        and line[1] >= cell["content_bbox"][1]
        and line[2] <= cell["content_bbox"][2]
        and line[3] <= cell["content_bbox"][3]
        for line in cell["line_bboxes"]
    )


def test_public_styled_table_paginates_and_repeats_header(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "styled-table.pdf"
    rows = [
        {
            "height": 24,
            "fill": None,
            "cells": [
                {
                    "text": "Item",
                    "alignment": "center",
                    "fill": [0.8, 0.9, 1.0],
                },
                {
                    "text": "Description",
                    "alignment": "center",
                    "fill": [0.8, 0.9, 1.0],
                },
            ],
        },
        *[
            {
                "height": 24,
                "fill": [0.98, 0.98, 0.98] if index % 2 == 0 else None,
                "cells": [
                    {
                        "text": f"Row {index}",
                        "alignment": "right",
                        "fill": None,
                    },
                    f"Bounded table value {index}",
                ],
            }
            for index in range(1, 45)
        ],
    ]
    request = _write_request(
        tmp_path / "styled-table.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Styled table",
                        "author": "Elftia",
                        "subject": "Pagination",
                    },
                    "page_size": "A4",
                    "pages": [{
                        "blocks": [{
                            "type": "table",
                            "text": None,
                            "style": {
                                "font_family": "Helvetica",
                                "font_size": 10,
                                "font_weight": "normal",
                                "font_style": "normal",
                                "color": [0.1, 0.1, 0.1],
                                "line_height": 12,
                                "alignment": "left",
                                "fallback_fonts": [],
                                "direction": "ltr",
                                "language": "en",
                            },
                            "table": {
                                "rows": rows,
                                "column_widths": [140, 280],
                                "padding": 4,
                                "border": {"width": 1.5, "color": [0.1, 0.2, 0.4]},
                                "fill": None,
                                "header_fill": [0.8, 0.9, 1.0],
                                "alignment": "left",
                                "header_rows": 1,
                                "repeat_header": True,
                            },
                            "image": None,
                            "shape": None,
                        }],
                        "metadata": None,
                    }],
                },
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["page_count"] == 2
    assert len(creation["tables"]) == 2
    assert creation["tables"][0]["column_widths"] == [140.0, 280.0]
    assert creation["tables"][0]["header_rows"] == 1
    assert b"1.5 w" in output.read_bytes()

    read_request = _write_request(
        tmp_path / "styled-table-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    pages = read_result["diagnostics"]["operation_result"]["text_by_page"]
    assert pages[0]["text"].startswith("Item\nDescription")
    assert pages[1]["text"].startswith("Item\nDescription")
    assert "Bounded table value 44" in pages[1]["text"]

    extract_request = _write_request(
        tmp_path / "styled-table-extract.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.table.extract",
            "input": str(output),
            "arguments": {
                "pages": [1, 2],
                "min_rows": 2,
                "min_columns": 2,
                "max_tables": 10,
            },
        },
    )
    extract_result = _public(project_root, "run", "--request", str(extract_request))
    extraction = extract_result["diagnostics"]["operation_result"]
    assert extraction["table_count"] == 1
    table = extraction["tables"][0]
    assert table["pages"] == [1, 2]
    assert table["cross_page"] is True
    assert len(table["continuations"]) == 1
    assert table["continuations"][0]["page"] == 2
    assert table["continuations"][0]["repeated_header"] is True
    assert [cell["text"] for cell in table["rows"][0]["cells"]] == [
        "Item",
        "Description",
    ]
    assert len(table["rows"]) == len(rows)
    assert [cell["text"] for cell in table["rows"][-1]["cells"]] == [
        "Row 44",
        "Bounded table value 44",
    ]


def test_public_unicode_table_cells_use_embedded_font_and_round_trip(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "unicode-table.pdf"
    request = _write_request(
        tmp_path / "unicode-table.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {
                "document": {
                    "metadata": {
                        "title": "Unicode table",
                        "author": "Elftia",
                        "subject": "CJK cells",
                    },
                    "page_size": "A4",
                    "fonts": [
                        _font_spec(
                            project_root,
                            "elftia-pdf-cjk-test.ttf",
                            "cjk",
                        )
                    ],
                    "pages": [{
                        "blocks": [{
                            "type": "table",
                            "text": None,
                            "style": {
                                "font_family": "cjk",
                                "font_size": 12,
                                "font_weight": "normal",
                                "font_style": "normal",
                                "color": [0.0, 0.0, 0.0],
                                "line_height": 16,
                                "alignment": "left",
                                "fallback_fonts": [],
                                "direction": "ltr",
                                "language": "zh-Hans",
                            },
                            "table": {
                                "rows": [
                                    {"cells": ["标题", "段落"]},
                                    {"cells": ["中文", "测试"]},
                                ],
                                "header_rows": 1,
                            },
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
    assert creation["fonts"][0]["mapped_cids"] > 0
    read_request = _write_request(
        tmp_path / "unicode-table-read.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read_result = _public(project_root, "run", "--request", str(read_request))
    text = read_result["diagnostics"]["operation_result"]["text_by_page"][0]["text"]
    assert text == "标题\n段落\n中文\n测试"
