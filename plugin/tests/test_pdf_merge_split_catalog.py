"""Public catalog reconciliation tests for PDF merge and split."""

import hashlib
import json
from pathlib import Path
import subprocess


def _public(project_root: Path, request: Path) -> dict[str, object]:
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
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


def _request(
    tmp_path: Path,
    name: str,
    operation: str,
    source: Path,
    *,
    output: Path | None = None,
    arguments: dict[str, object] | None = None,
) -> Path:
    path = tmp_path / name
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": operation,
        "input": str(source),
        "arguments": arguments or {},
    }
    if output is not None:
        payload["output"] = str(output)
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


def _catalog_pdf(path: Path, prefix: str, outline_page: int) -> Path:
    page_ref = 3 if outline_page == 1 else 4
    prefix_bytes = prefix.encode("ascii")
    title = f"{prefix} bookmark".encode("ascii")
    return _write_pdf(path, [
        (
            b"<< /Type /Catalog /Pages 2 0 R /PageLabels "
            b"<< /Nums [0 << /P ("
            + prefix_bytes
            + b"-) /S /D /St 1 >>] >> /Outlines 7 0 R >>"
        ),
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 6 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Outlines /First 8 0 R /Last 8 0 R /Count 1 >>",
        (
            b"<< /Title ("
            + title
            + b") /Parent 7 0 R /Dest ["
            + str(page_ref).encode("ascii")
            + b" 0 R /Fit] >>"
        ),
    ])


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


def test_merge_combines_page_labels_and_retargets_flat_outlines(
    project_root: Path,
    tmp_path: Path,
) -> None:
    first = _catalog_pdf(tmp_path / "catalog-a.pdf", "A", 2)
    second = _catalog_pdf(tmp_path / "catalog-b.pdf", "B", 1)
    output = tmp_path / "catalog-merged.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "merge-catalog.json",
            "pdf.edit",
            first,
            output=output,
            arguments={
                "primitives": [{
                    "type": "merge",
                    "inputs": [
                        {
                            "input": str(path),
                            "source_sha256": hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                        }
                        for path in (first, second)
                    ],
                }]
            },
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["page_labels"] == ["A-1", "A-2", "B-1", "B-2"]
    assert operation["outlines"] == [
        {"title": "A bookmark", "page": 2},
        {"title": "B bookmark", "page": 3},
    ]
    assert {1, 2}.issubset(operation["preservation"]["added_objects"])


def test_split_keeps_selected_visible_label_and_retargets_outline(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _catalog_pdf(tmp_path / "catalog-split-source.pdf", "S", 2)
    output = tmp_path / "catalog-split.pdf"
    result = _public(
        project_root,
        _request(
            tmp_path,
            "split-catalog.json",
            "pdf.edit",
            source,
            output=output,
            arguments={
                "primitives": [{"type": "split", "page_ranges": [[2, 2]]}]
            },
        ),
    )

    assert result["status"] == "success", result
    operation = result["diagnostics"]["operation_result"]
    assert operation["page_labels"] == ["S-2"]
    assert operation["outlines"] == [{"title": "S bookmark", "page": 1}]
    read_result = _public(
        project_root,
        _request(tmp_path, "read-split-catalog.json", "pdf.read", output),
    )
    read_operation = read_result["diagnostics"]["operation_result"]
    assert read_operation["page_labels"] == ["S-2"]
    assert read_operation["outlines"] == [{
        "title": "S bookmark",
        "destination_page": 1,
    }]
