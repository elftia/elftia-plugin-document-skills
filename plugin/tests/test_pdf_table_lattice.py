"""Public supervisor/worker coverage for bounded ruled-table extraction."""

import json
from pathlib import Path
import subprocess
from typing import Any


def _public(project_root: Path, request: Path) -> dict[str, Any]:
    process = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills/document-pdf/scripts/run.py"),
            "run",
            "--request",
            str(request),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(tmp_path: Path, source: Path, name: str, *, max_tables: int = 10) -> Path:
    request = tmp_path / name
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.table.extract",
                "input": str(source),
                "arguments": {
                    "pages": [1],
                    "min_rows": 2,
                    "min_columns": 2,
                    "max_tables": max_tables,
                },
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    return request


def _table_pdf(path: Path, content: bytes) -> Path:
    stream = (
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream"
    )
    return _write_pdf(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 540 360] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
            ),
            stream,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ],
    )


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def test_public_lattice_table_reports_grid_and_true_cell_boxes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"\n".join(
        [
            b"0.5 w",
            b"40 180 m 240 180 l 240 280 l 40 280 l h",
            b"40 230 m 240 230 l",
            b"140 180 m 140 280 l",
            b"S",
            b"BT /F1 10 Tf 1 0 0 1 55 250 Tm (A) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 155 250 Tm (B) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 55 200 Tm (C) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 155 200 Tm (D) Tj ET",
        ]
    )
    source = _table_pdf(tmp_path / "lattice-grid.pdf", content)

    result = _public(
        project_root,
        _request(tmp_path, source, "lattice-grid.json"),
    )

    assert result["status"] == "success", result
    assert result["provider_chain"][0] == "core-python"
    extraction = result["diagnostics"]["operation_result"]
    assert extraction["source"] == "core-lattice"
    assert extraction["table_count"] == 1
    table = extraction["tables"][0]
    assert table["source"] == "core-lattice"
    assert table["confidence"] >= 0.8
    assert table["bbox"] == [40.0, 180.0, 240.0, 280.0]
    assert table["grid"] == {
        "row_count": 2,
        "column_count": 2,
        "merged_cell_count": 0,
    }
    cells = [cell for row in table["rows"] for cell in row["cells"]]
    assert [cell["text"] for cell in cells] == ["A", "B", "C", "D"]
    assert [cell["bbox"] for cell in cells] == [
        [40.0, 230.0, 140.0, 280.0],
        [140.0, 230.0, 240.0, 280.0],
        [40.0, 180.0, 140.0, 230.0],
        [140.0, 180.0, 240.0, 230.0],
    ]
    assert all(cell["row_span"] == cell["column_span"] == 1 for cell in cells)


def test_public_lattice_table_reports_rectangular_row_and_column_spans(
    project_root: Path,
    tmp_path: Path,
) -> None:
    content = b"\n".join(
        [
            b"0.5 w",
            b"40 180 m 240 180 l 240 280 l 40 280 l h",
            b"40 230 m 240 230 l",
            b"140 180 m 140 230 l",
            b"S",
            b"BT /F1 10 Tf 1 0 0 1 60 250 Tm (Wide) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 60 200 Tm (Left) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 160 200 Tm (Right) Tj ET",
            b"300 180 m 500 180 l 500 280 l 300 280 l h",
            b"400 180 m 400 280 l",
            b"400 230 m 500 230 l",
            b"S",
            b"BT /F1 10 Tf 1 0 0 1 320 230 Tm (Tall) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 420 250 Tm (Top) Tj ET",
            b"BT /F1 10 Tf 1 0 0 1 420 200 Tm (Bottom) Tj ET",
        ]
    )
    source = _table_pdf(tmp_path / "lattice-merged.pdf", content)

    result = _public(
        project_root,
        _request(tmp_path, source, "lattice-merged.json"),
    )

    assert result["status"] == "success", result
    tables = result["diagnostics"]["operation_result"]["tables"]
    assert len(tables) == 2
    column_merged = tables[0]
    wide = column_merged["rows"][0]["cells"][0]
    assert wide == {
        "text": "Wide",
        "bbox": [40.0, 230.0, 240.0, 280.0],
        "row": 1,
        "column": 1,
        "row_span": 1,
        "column_span": 2,
        "confidence": 0.9,
    }
    assert column_merged["grid"]["merged_cell_count"] == 1
    row_merged = tables[1]
    tall = row_merged["rows"][0]["cells"][0]
    assert tall == {
        "text": "Tall",
        "bbox": [300.0, 180.0, 400.0, 280.0],
        "row": 1,
        "column": 1,
        "row_span": 2,
        "column_span": 1,
        "confidence": 0.9,
    }
    assert row_merged["rows"][1]["cells"][0]["text"] == "Bottom"
    assert row_merged["grid"]["merged_cell_count"] == 1
