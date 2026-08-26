"""Resource-bound identity checks for provider input snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import tracemalloc

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io import ArtifactRecord
from document_skills_core.core.io.paths import destination_snapshot
from document_skills_core.formats.xlsx import (
    read_operation,
    render_operation,
    schema_operation,
    source_snapshot,
)
from document_skills_core.formats.xlsx.contracts import parse_xlsx_request
from document_skills_core.formats.xlsx.source_snapshot import stage_source_snapshot
from document_skills_core.formats.xlsx.transaction import promote_candidate
from document_skills_core.providers.libreoffice import input_snapshot
from document_skills_core.providers.libreoffice.input_snapshot import (
    private_libreoffice_input,
)


def test_snapshot_rejects_recorded_oversize_before_private_file(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "recorded.xlsx"
    source_path.write_bytes(b"x")
    source = ArtifactRecord(
        "input",
        str(source_path),
        hashlib.sha256(b"x").hexdigest(),
        9,
    )

    with pytest.raises(DocumentSkillsError) as caught:
        stage_source_snapshot(source, tmp_path, byte_limit=8)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}
    assert not (tmp_path / "provider-source.xlsx").exists()


def test_snapshot_stops_copy_when_source_grows_past_record_and_limit(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "grown.xlsx"
    source_path.write_bytes(b"123456789")
    source = ArtifactRecord(
        "input",
        str(source_path),
        hashlib.sha256(b"12345678").hexdigest(),
        8,
    )

    with pytest.raises(DocumentSkillsError) as caught:
        stage_source_snapshot(source, tmp_path, byte_limit=8)

    staged = tmp_path / "provider-source.xlsx"
    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details["input_limit"] == 8
    assert staged.stat().st_size <= 8


def test_source_record_rejects_oversize_before_hashing_unbounded_bytes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "oversize.xlsx"
    source_path.write_bytes(b"123456789")

    with pytest.raises(DocumentSkillsError) as caught:
        source_snapshot.bounded_source_record(
            source_path,
            "input",
            byte_limit=8,
        )

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}


def test_source_preservation_rejects_growth_without_hashing_past_limit(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "preserved.xlsx"
    source_path.write_bytes(b"12345678")
    source = source_snapshot.bounded_source_record(
        source_path,
        "input",
        byte_limit=8,
    )
    source_path.write_bytes(b"123456789")

    with pytest.raises(DocumentSkillsError) as caught:
        source_snapshot.assert_bounded_source_preserved(source, byte_limit=8)

    assert caught.value.code == ErrorCode.VALIDATION_FAILED
    assert caught.value.details["source_growth_exceeds_limit"] is True
    assert caught.value.details["actual_bytes"] == 9
    assert caught.value.details["input_limit"] == 8


def test_source_preservation_failure_merges_into_primary_error(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "merged.xlsx"
    source_path.write_bytes(b"12345678")
    source = source_snapshot.bounded_source_record(
        source_path,
        "input",
        byte_limit=8,
    )
    source_path.write_bytes(b"123456789")
    primary = DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "primary")

    source_snapshot.merge_bounded_source_preservation_failure(
        primary,
        source,
        byte_limit=8,
    )

    preservation = primary.details["source_preservation"]
    assert preservation["status"] == "fail"
    assert preservation["error"]["code"] == ErrorCode.VALIDATION_FAILED.value


def test_libreoffice_input_rejects_oversize_before_private_copy(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "oversize.docx"
    source_path.write_bytes(b"123456789")

    with pytest.raises(DocumentSkillsError) as caught:
        with private_libreoffice_input(
            source_path,
            operation="libreoffice.convert-pdf",
            byte_limit=8,
        ):
            raise AssertionError("oversize input must not reach the provider")

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}


def test_xlsx_read_rejects_oversize_before_private_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "oversize-read.xlsx"
    source_path.write_bytes(b"123456789")
    monkeypatch.setattr(read_operation, "MAX_XLSX_BYTES", 8, raising=False)
    request = parse_xlsx_request({
        "operation": "xlsx.read",
        "input": str(source_path),
        "arguments": {},
    })

    with pytest.raises(DocumentSkillsError) as caught:
        read_operation.execute_read(request, libreoffice=None)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}


def test_xlsx_render_rejects_oversize_before_private_copy(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "oversize-render.xlsx"
    source_path.write_bytes(b"123456789")
    monkeypatch.setattr(render_operation, "MAX_XLSX_BYTES", 8, raising=False)

    with pytest.raises(DocumentSkillsError) as caught:
        render_operation.execute_render(
            {
                "operation": "xlsx.render",
                "input": str(source_path),
                "output": str(tmp_path / "rendered.pdf"),
                "arguments": {},
            },
            project_root=project_root,
            converter=lambda _path: (_ for _ in ()).throw(
                AssertionError("oversize input reached the provider")
            ),
        )

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}


def test_xlsx_schema_rejects_oversize_before_private_copy(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "oversize-schema.xlsx"
    source_path.write_bytes(b"123456789")
    monkeypatch.setattr(schema_operation, "MAX_XLSX_BYTES", 8, raising=False)

    with pytest.raises(DocumentSkillsError) as caught:
        schema_operation.execute_schema_validation(
            {
                "operation": "xlsx.validate.schema",
                "input": str(source_path),
                "arguments": {},
            },
            project_root=project_root,
            validator=lambda _path, _max_errors: (_ for _ in ()).throw(
                AssertionError("oversize input reached the provider")
            ),
        )

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert caught.value.details == {"input_bytes": 9, "input_limit": 8}


def test_bounded_promotion_reports_clean_committed_source(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.xlsx"
    source_path.write_bytes(b"12345678")
    source = source_snapshot.bounded_source_record(
        source_path,
        "input",
        byte_limit=8,
    )
    candidate = tmp_path / "candidate.pdf"
    candidate.write_bytes(b"pdf")
    output = tmp_path / "output.pdf"

    result = promote_candidate(
        _render_request(source_path, output),
        candidate,
        _promotion_result(source, output, b"pdf"),
        source=source,
        destination=destination_snapshot(output),
        source_preservation=lambda record: source_snapshot.assert_bounded_source_preserved(
            record,
            byte_limit=8,
        ),
    )

    promotion = result["diagnostics"]["promotion"]
    assert output.read_bytes() == b"pdf"
    assert promotion["state"] == "committed_clean"
    assert promotion["source_preservation"] == {"status": "pass"}


def test_bounded_promotion_reports_source_growth_after_commit(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source-growth.xlsx"
    source_path.write_bytes(b"12345678")
    source = source_snapshot.bounded_source_record(
        source_path,
        "input",
        byte_limit=8,
    )
    candidate = tmp_path / "candidate-growth.pdf"
    candidate.write_bytes(b"pdf")
    output = tmp_path / "output-growth.pdf"
    checks = 0

    def preserve(record: ArtifactRecord) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            source_path.write_bytes(b"123456789")
        source_snapshot.assert_bounded_source_preserved(record, byte_limit=8)

    result = promote_candidate(
        _render_request(source_path, output),
        candidate,
        _promotion_result(source, output, b"pdf"),
        source=source,
        destination=destination_snapshot(output),
        source_preservation=preserve,
    )

    promotion = result["diagnostics"]["promotion"]
    assert output.read_bytes() == b"pdf"
    assert promotion["state"] == "committed_with_warnings"
    assert promotion["filesystem_state"] == "committed_clean"
    assert promotion["source_preservation"]["status"] == "fail"
    assert result["warnings"][-1]["code"] == "DS_SOURCE_CHANGED_AFTER_COMMIT"


def test_128_mib_cfb_rejects_fat_and_difat_amplification_geometry(
    tmp_path: Path,
) -> None:
    source = tmp_path / "amplified.xls"
    sector_count = (128 * 1024 * 1024) // 512 - 1

    _write_cfb_header(
        source,
        file_bytes=128 * 1024 * 1024,
        fat_count=sector_count,
        difat_count=0,
    )
    fat_peak = _assert_cfb_geometry_rejected(source)

    _write_cfb_header(
        source,
        file_bytes=128 * 1024 * 1024,
        fat_count=2048,
        first_difat=0,
        difat_count=2048,
    )
    difat_peak = _assert_cfb_geometry_rejected(source)

    assert fat_peak < 2 * 1024 * 1024
    assert difat_peak < 2 * 1024 * 1024


def test_cfb_directory_chain_has_fixed_resource_ceiling(tmp_path: Path) -> None:
    source = tmp_path / "directory-amplification.xls"
    _write_128_mib_directory_chain_cfb(source, directory_sectors=4097)

    tracemalloc.start()
    try:
        with pytest.raises(DocumentSkillsError) as caught:
            input_snapshot._detect_format(source)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert "directory sector ceiling" in str(caught.value)
    assert peak < 4 * 1024 * 1024


def _render_request(source: Path, output: Path):
    return parse_xlsx_request({
        "operation": "xlsx.render",
        "input": str(source),
        "output": str(output),
        "arguments": {},
    })


def _promotion_result(
    source: ArtifactRecord,
    output: Path,
    candidate_bytes: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    return {
        "status": "success",
        "validation": {
            "status": "pass",
            "gates": [{
                "id": "candidate.identity",
                "required": True,
                "outcome": "pass",
                "evidence": {"sha256": digest, "bytes": len(candidate_bytes)},
            }],
        },
        "artifacts": [
            source.as_dict(),
            {
                "role": "output",
                "path": str(output),
                "sha256": digest,
                "bytes": len(candidate_bytes),
            },
        ],
        "warnings": [],
        "diagnostics": {},
    }


def _assert_cfb_geometry_rejected(path: Path) -> int:
    tracemalloc.start()
    try:
        with pytest.raises(DocumentSkillsError) as caught:
            input_snapshot._detect_format(path)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE
    assert "allocation geometry" in str(caught.value)
    return peak


def _write_cfb_header(
    path: Path,
    *,
    file_bytes: int,
    fat_count: int,
    first_difat: int = 0xFFFFFFFF,
    difat_count: int,
) -> None:
    header = _cfb_header(
        fat_count=fat_count,
        first_directory=0,
        first_difat=first_difat,
        difat_count=difat_count,
        fat_sector_ids=[1],
    )
    with path.open("wb") as handle:
        handle.write(header)
        handle.truncate(file_bytes)


def _write_128_mib_directory_chain_cfb(
    path: Path,
    *,
    directory_sectors: int,
) -> None:
    fat_count = 2048
    difat_count = 16
    fat_sector_ids = list(range(directory_sectors, directory_sectors + fat_count))
    difat_sector_ids = list(range(fat_sector_ids[-1] + 1, fat_sector_ids[-1] + 17))
    header = _cfb_header(
        fat_count=fat_count,
        first_directory=0,
        first_difat=difat_sector_ids[0],
        difat_count=difat_count,
        fat_sector_ids=fat_sector_ids,
    )
    fat_payloads = [bytearray(b"\xff" * 512) for _index in range(fat_count)]
    for sector_id in range(directory_sectors):
        next_sector = (
            sector_id + 1 if sector_id + 1 < directory_sectors else 0xFFFFFFFE
        )
        _set_fat_entry(fat_payloads, sector_id, next_sector)
    for sector_id in fat_sector_ids:
        _set_fat_entry(fat_payloads, sector_id, 0xFFFFFFFD)
    for sector_id in difat_sector_ids:
        _set_fat_entry(fat_payloads, sector_id, 0xFFFFFFFC)
    first_directory = bytearray(512)
    _write_directory_entry(first_directory, 0, "Root Entry", 5)
    _write_directory_entry(first_directory, 128, "Workbook", 2)
    remaining_fat_ids = fat_sector_ids[109:]
    difat_payloads: list[bytes] = []
    for index, sector_id in enumerate(difat_sector_ids):
        values = remaining_fat_ids[index * 127 : (index + 1) * 127]
        values += [0xFFFFFFFF] * (127 - len(values))
        next_sector = (
            difat_sector_ids[index + 1]
            if index + 1 < len(difat_sector_ids)
            else 0xFFFFFFFE
        )
        difat_payloads.append(struct.pack("<128I", *values, next_sector))
    with path.open("wb") as handle:
        handle.write(header)
        handle.truncate(128 * 1024 * 1024)
        handle.seek(512)
        handle.write(first_directory)
        handle.seek(512 + fat_sector_ids[0] * 512)
        handle.write(b"".join(fat_payloads))
        handle.seek(512 + difat_sector_ids[0] * 512)
        handle.write(b"".join(difat_payloads))


def _cfb_header(
    *,
    fat_count: int,
    first_directory: int,
    first_difat: int,
    difat_count: int,
    fat_sector_ids: list[int],
) -> bytes:
    header = bytearray(512)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHH", header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into(
        "<IIIIIIIII",
        header,
        40,
        0,
        fat_count,
        first_directory,
        0,
        4096,
        0xFFFFFFFF,
        0,
        first_difat,
        difat_count,
    )
    difat = fat_sector_ids[:109] + [0xFFFFFFFF] * (109 - len(fat_sector_ids))
    struct.pack_into("<109I", header, 76, *difat)
    return bytes(header)


def _write_directory_entry(
    directory: bytearray,
    offset: int,
    name: str,
    object_type: int,
) -> None:
    encoded = name.encode("utf-16le") + b"\x00\x00"
    directory[offset : offset + len(encoded)] = encoded
    struct.pack_into("<HBB", directory, offset + 64, len(encoded), object_type, 1)


def _set_fat_entry(
    fat_payloads: list[bytearray],
    sector_id: int,
    value: int,
) -> None:
    entries_per_sector = 128
    struct.pack_into(
        "<I",
        fat_payloads[sector_id // entries_per_sector],
        (sector_id % entries_per_sector) * 4,
        value,
    )
