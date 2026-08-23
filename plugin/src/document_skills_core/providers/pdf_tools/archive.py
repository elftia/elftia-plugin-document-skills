"""Deterministic sidecar archives and validation for PDF render/OCR."""

import hashlib
import json
from pathlib import Path
from typing import Any
import zipfile

from document_skills_core.core.io.paths import assert_source_preserved, file_record
from document_skills_core.core.validation.runner import ValidationRunner
from document_skills_core.formats.pdf.image_extraction_archive import (
    write_deterministic_image_zip,
)


def manifest_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def write_archive(path: Path, payloads: dict[str, bytes]) -> None:
    write_deterministic_image_zip(path, payloads)


def validate_archive(
    archive: Path,
    *,
    payload_records: list[dict[str, Any]],
    manifest: dict[str, Any],
    source: Path,
    source_sha256: str,
) -> dict[str, Any]:
    runner = ValidationRunner()
    runner.run_gate("artifact.exists-size", lambda: _identity(archive))
    runner.run_gate(
        "archive.sidecar-reopen",
        lambda: _reopen(archive, payload_records, manifest),
    )
    runner.run_gate(
        "source.preservation",
        lambda: _preserved(source, source_sha256),
    )
    return runner.report()


def payload_record(name: str, payload: bytes) -> dict[str, Any]:
    return {
        "archive_path": name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _identity(path: Path) -> dict[str, Any]:
    record = file_record(path, "output")
    if record.bytes <= 0:
        raise ValueError("Provider sidecar archive is empty.")
    return {"sha256": record.sha256, "bytes": record.bytes}


def _reopen(
    path: Path,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected = {record["archive_path"]: record for record in records}
    expected["manifest.json"] = payload_record("manifest.json", manifest_bytes(manifest))
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names != sorted(names) or set(names) != set(expected):
            raise ValueError("Provider sidecar entries are not canonical.")
        if archive.testzip() is not None:
            raise ValueError("Provider sidecar archive contains a corrupt entry.")
        for name, record in expected.items():
            payload = archive.read(name)
            if len(payload) != record["bytes"]:
                raise ValueError("Provider sidecar byte count changed.")
            if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError("Provider sidecar hash changed.")
        if json.loads(archive.read("manifest.json")) != manifest:
            raise ValueError("Provider sidecar manifest changed.")
    return {"entries": len(expected)}


def _preserved(path: Path, expected_sha256: str) -> dict[str, Any]:
    assert_source_preserved(path, expected_sha256)
    return {"sha256": expected_sha256}
