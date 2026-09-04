"""Catalog preservation regressions for public PDF page-tree mutations."""

import hashlib
import json
from pathlib import Path
import subprocess

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS

from pypdf import PdfReader


XMP = (
    b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    b'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Catalog sentinel</rdf:li>'
    b'</rdf:Alt></dc:title></rdf:Description></rdf:RDF></x:xmpmeta>\n'
    b'<?xpacket end="w"?>'
)
ICC = b"safe-icc-profile-sentinel"


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


def _request(tmp_path: Path, source: Path, output: Path, primitive: dict[str, object]) -> Path:
    request = tmp_path / f"{primitive['type']}.json"
    request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pdf.edit",
            "input": str(source),
            "output": str(output),
            "arguments": {"primitives": [primitive]},
        }),
        encoding="utf-8",
        newline="\n",
    )
    return request


def _catalog_pdf(path: Path, *, lang: bytes = b"en-US") -> Path:
    first = b"BT 40 250 Td (First page) Tj ET"
    second = b"BT 40 250 Td (Second page) Tj ET"
    return _write_pdf(path, [
        (
            b"<< /Type /Catalog /Pages 2 0 R /Metadata 7 0 R /Lang ("
            + lang
            + b") "
            b"/ViewerPreferences << /DisplayDocTitle true >> /MarkInfo << /Marked true >> "
            b"/OutputIntents [8 0 R] >>"
        ),
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Contents 6 0 R >>",
        _stream(first),
        _stream(second),
        b"<< /Type /Metadata /Subtype /XML /Length "
        + str(len(XMP)).encode("ascii")
        + b" >>\nstream\n"
        + XMP
        + b"\nendstream",
        (
            b"<< /Type /OutputIntent /S /GTS_PDFA1 "
            b"/OutputConditionIdentifier (safe-profile) /DestOutputProfile 9 0 R >>"
        ),
        b"<< /N 3 /Length "
        + str(len(ICC)).encode("ascii")
        + b" >>\nstream\n"
        + ICC
        + b"\nendstream",
    ])


def _single_page_pdf(
    path: Path,
    catalog_entries: bytes,
    *extra_objects: bytes,
) -> Path:
    return _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R" + catalog_entries + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] >>",
        *extra_objects,
    ])


def _stream(payload: bytes) -> bytes:
    return (
        f"<< /Length {len(payload)} >>\nstream\n".encode("ascii")
        + payload
        + b"\nendstream"
    )


def _write_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f\r\n".encode("ascii"))
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path


def _assert_catalog_preserved(path: Path) -> None:
    raw = path.read_bytes()
    assert raw.count(XMP) == 1
    assert raw.count(ICC) == 1
    reader = PdfReader(path)
    catalog = reader.trailer["/Root"]
    assert catalog["/Lang"] == "en-US"
    assert bool(catalog["/ViewerPreferences"]["/DisplayDocTitle"]) is True
    assert bool(catalog["/MarkInfo"]["/Marked"]) is True
    assert catalog["/Metadata"].get_object().get_data() == XMP
    intent = catalog["/OutputIntents"][0].get_object()
    assert intent["/OutputConditionIdentifier"] == "safe-profile"
    assert intent["/DestOutputProfile"].get_object().get_data() == ICC


def test_public_split_preserves_untargeted_catalog_and_indirect_closure(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _catalog_pdf(tmp_path / "catalog-source.pdf")
    output = tmp_path / "catalog-split.pdf"

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            {"type": "split", "page_ranges": [[1, 1]]},
        ),
    )

    assert result["status"] == "success", result
    _assert_catalog_preserved(output)


def test_public_page_sequence_preserves_catalog_while_reordering(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _catalog_pdf(tmp_path / "catalog-sequence-source.pdf")
    output = tmp_path / "catalog-sequence.pdf"

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            {"type": "page_sequence", "pages": [2, 1]},
        ),
    )

    assert result["status"] == "success", result
    _assert_catalog_preserved(output)


def test_public_merge_preserves_only_primary_catalog_graph(
    project_root: Path,
    tmp_path: Path,
) -> None:
    primary = _catalog_pdf(tmp_path / "catalog-merge-primary.pdf")
    donor = _catalog_pdf(tmp_path / "catalog-merge-donor.pdf", lang=b"fr-FR")
    output = tmp_path / "catalog-merge.pdf"

    result = _public(
        project_root,
        _request(
            tmp_path,
            primary,
            output,
            {
                "type": "merge",
                "inputs": [
                    {
                        "input": str(path),
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in (primary, donor)
                ],
            },
        ),
    )

    assert result["status"] == "success", result
    _assert_catalog_preserved(output)


def test_public_page_insert_preserves_only_destination_catalog_graph(
    project_root: Path,
    tmp_path: Path,
) -> None:
    destination = _catalog_pdf(tmp_path / "catalog-insert-destination.pdf")
    donor = _catalog_pdf(tmp_path / "catalog-insert-donor.pdf", lang=b"fr-FR")
    output = tmp_path / "catalog-insert.pdf"

    result = _public(
        project_root,
        _request(
            tmp_path,
            destination,
            output,
            {
                "type": "page_insert",
                "input": str(donor),
                "source_sha256": hashlib.sha256(donor.read_bytes()).hexdigest(),
                "at": 2,
                "pages": [1],
            },
        ),
    )

    assert result["status"] == "success", result
    _assert_catalog_preserved(output)


def test_public_split_rejects_dangling_catalog_graph_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _single_page_pdf(
        tmp_path / "catalog-dangling.pdf",
        b" /Metadata 99 0 R",
    )
    output = tmp_path / "catalog-dangling-output.pdf"
    before = b"existing destination"
    output.write_bytes(before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            source,
            output,
            {"type": "split", "page_ranges": [[1, 1]]},
        ),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert result["artifacts"] == []
    assert output.read_bytes() == before


def test_public_page_insert_rejects_unsafe_donor_catalog_atomically(
    project_root: Path,
    tmp_path: Path,
) -> None:
    destination = _catalog_pdf(tmp_path / "catalog-safe-destination.pdf")
    donor = _single_page_pdf(
        tmp_path / "catalog-unsafe-donor.pdf",
        b" /OpenAction 4 0 R",
        b"<< /S /JavaScript /JS (noop) >>",
    )
    output = tmp_path / "catalog-unsafe-output.pdf"
    before = b"existing destination"
    output.write_bytes(before)

    result = _public(
        project_root,
        _request(
            tmp_path,
            destination,
            output,
            {
                "type": "page_insert",
                "input": str(donor),
                "source_sha256": hashlib.sha256(donor.read_bytes()).hexdigest(),
                "at": 1,
                "pages": [1],
            },
        ),
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"
    assert result["artifacts"] == []
    assert output.read_bytes() == before


def test_public_page_sequence_reports_unreconciled_safe_catalog_graphs(
    project_root: Path,
    tmp_path: Path,
) -> None:
    fixtures = [
        (
            "tagged",
            b" /StructTreeRoot 4 0 R",
            b"<< /Type /StructTreeRoot /K [] >>",
        ),
        (
            "names",
            b" /Names 4 0 R",
            b"<< /Dests << /Names [(section) [3 0 R /Fit]] >> >>",
        ),
    ]
    for name, catalog_entries, extra_object in fixtures:
        source = _single_page_pdf(
            tmp_path / f"catalog-{name}.pdf",
            catalog_entries,
            extra_object,
        )
        output = tmp_path / f"catalog-{name}-output.pdf"
        before = b"existing destination"
        output.write_bytes(before)

        result = _public(
            project_root,
            _request(
                tmp_path,
                source,
                output,
                {"type": "page_sequence", "pages": [1]},
            ),
        )

        assert result["status"] == "enhancement_required", result
        assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
        assert result["errors"][0]["details"]["capability"] == (
            "pdf.page-tree-catalog-reconciliation"
        )
        assert output.read_bytes() == before
