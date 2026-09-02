"""Public fail-closed coverage for annotation deletion reference safety."""

import json
from pathlib import Path
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

import pytest


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
        timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
    )
    assert process.stderr == b""
    payload = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert type(payload) is dict
    return payload


@pytest.mark.parametrize(
    "inbound_kind",
    ["irt", "popup", "duplicate_annots", "stream_dict"],
)
def test_public_annotation_delete_rejects_additional_inbound_references_atomically(
    project_root: Path,
    tmp_path: Path,
    inbound_kind: str,
) -> None:
    source = _annotation_reference_pdf(tmp_path / f"{inbound_kind}.pdf", inbound_kind)
    source_before = source.read_bytes()
    destination = tmp_path / "edited.pdf"
    destination_before = b"existing-destination"
    destination.write_bytes(destination_before)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "pdf.edit",
                "input": str(source),
                "output": str(destination),
                "arguments": {
                    "primitives": [
                        {
                            "type": "annotation",
                            "action": "delete",
                            "page": 1,
                            "index": 1,
                            "expected_contents": "Root note",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = _public(project_root, request)

    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED", result
    assert result["status"] == "enhancement_required", result
    assert result["artifacts"] == []
    assert source.read_bytes() == source_before
    assert destination.read_bytes() == destination_before


def _annotation_reference_pdf(path: Path, inbound_kind: str) -> Path:
    target_extra = b""
    if inbound_kind == "duplicate_annots":
        annotations = b"[5 0 R 5 0 R]"
        related: list[bytes] = []
    elif inbound_kind == "stream_dict":
        annotations = b"[5 0 R]"
        related = [
            b"<< /Length 0 /RelatedAnnotation 5 0 R >>\nstream\n\nendstream"
        ]
    elif inbound_kind == "irt":
        annotations = b"[5 0 R 6 0 R]"
        related = [
            (
                b"<< /Type /Annot /Subtype /Text /Rect [40 40 60 60] "
                b"/Contents (Reply) /P 3 0 R /IRT 5 0 R >>"
            )
        ]
    else:
        annotations = b"[5 0 R 6 0 R]"
        target_extra = b"/Popup 6 0 R "
        related = [
            b"<< /Type /Annot /Subtype /Popup /Rect [40 40 80 80] /Parent 5 0 R >>"
        ]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
            b"/Resources << >> /Contents 4 0 R /Annots "
            + annotations
            + b" >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        (
            b"<< /Type /Annot /Subtype /Text /Rect [10 10 30 30] "
            b"/Contents (Root note) /P 3 0 R "
            + target_extra
            + b">>"
        ),
        *related,
    ]
    return _write_pdf(path, objects)


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for obj_num, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{obj_num} 0 obj\n".encode("ascii"))
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
