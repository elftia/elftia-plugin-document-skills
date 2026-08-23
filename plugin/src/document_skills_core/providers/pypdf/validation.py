"""Independent reopen and semantic gates for pypdf mutations."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PasswordType, PdfReader

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.formats.pdf.byte_preflight import preflight_pdf

from .operations import _PERMISSION_FLAGS


def validate_encrypted(
    source: Path,
    candidate: Path,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    preflight = preflight_pdf(candidate)
    if not preflight.encrypted:
        _failed("Encrypted candidate does not contain an encryption dictionary.")
    user_reader = PdfReader(candidate, strict=True)
    encryption = user_reader.trailer["/Encrypt"]
    if user_reader.decrypt(arguments["user_password"]) != PasswordType.USER_PASSWORD:
        _failed("Encrypted candidate rejected its user credential.")
    if user_reader.are_permissions_valid is not True:
        _failed("Encrypted candidate permission integrity validation failed.")
    _assert_encryption_dictionary(encryption, arguments)
    _assert_permissions(user_reader, arguments["permissions"])
    _assert_semantics(PdfReader(source, strict=True), user_reader)

    owner_reader = PdfReader(candidate, strict=True)
    if owner_reader.decrypt(arguments["owner_password"]) != PasswordType.OWNER_PASSWORD:
        _failed("Encrypted candidate rejected its owner credential.")
    return _report(
        candidate,
        "operation.encryption",
        {
            "algorithm": "AES-256-R5",
            "encrypted": True,
            "page_count": len(user_reader.pages),
            "permissions_valid": True,
        },
    )


def validate_decrypted(
    source_reader: PdfReader,
    candidate: Path,
) -> dict[str, Any]:
    preflight = preflight_pdf(candidate)
    if preflight.encrypted:
        _failed("Decrypted candidate still contains an encryption dictionary.")
    candidate_reader = PdfReader(candidate, strict=True)
    if candidate_reader.is_encrypted:
        _failed("Decrypted candidate still reports encrypted state.")
    _assert_semantics(source_reader, candidate_reader)
    return _report(
        candidate,
        "operation.decryption",
        {
            "encrypted": False,
            "page_count": len(candidate_reader.pages),
            "semantic_round_trip": True,
        },
    )


def validate_compressed(source: Path, candidate: Path) -> dict[str, Any]:
    source_bytes = source.stat().st_size
    candidate_bytes = candidate.stat().st_size
    if candidate_bytes >= source_bytes:
        _failed("Compressed candidate has no positive byte-size evidence.")
    preflight = preflight_pdf(candidate)
    if preflight.encrypted:
        _failed("Lossless compression unexpectedly encrypted the candidate.")
    source_reader = PdfReader(source, strict=True)
    candidate_reader = PdfReader(candidate, strict=True)
    _assert_semantics(source_reader, candidate_reader)
    return _report(
        candidate,
        "operation.lossless-compression",
        {
            "before_bytes": source_bytes,
            "after_bytes": candidate_bytes,
            "bytes_saved": source_bytes - candidate_bytes,
            "semantic_round_trip": True,
        },
    )


def _assert_encryption_dictionary(
    encryption: Any,
    arguments: dict[str, Any],
) -> None:
    if (
        encryption.get("/V") != 5
        or encryption.get("/R") != 5
        or encryption.get("/Length") != 256
        or encryption["/CF"]["/StdCF"].get("/CFM") != "/AESV3"
    ):
        _failed("Encrypted candidate is not AES-256-R5.")
    if encryption.get("/EncryptMetadata", True) is not arguments["encrypt_metadata"]:
        _failed("Encrypted candidate metadata policy does not match the request.")


def _assert_permissions(reader: PdfReader, requested: list[str]) -> None:
    permissions = reader.user_access_permissions
    if permissions is None:
        _failed("Encrypted candidate did not expose verified permissions.")
    actual = sorted(
        name
        for name, flag in _PERMISSION_FLAGS.items()
        if permissions & flag == flag
    )
    if actual != requested:
        _failed("Encrypted candidate permissions do not match the request.")


def _assert_semantics(source: PdfReader, candidate: PdfReader) -> None:
    if _semantic_digest(source) != _semantic_digest(candidate):
        _failed("PDF page and text semantics changed during provider mutation.")


def _semantic_digest(reader: PdfReader) -> str:
    pages = []
    for page in reader.pages:
        pages.append(
            {
                "media_box": [float(value) for value in page.mediabox],
                "rotation": int(page.get("/Rotate", 0)),
                "text": page.extract_text() or "",
            }
        )
    encoded = json.dumps(
        pages,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _report(
    candidate: Path,
    gate_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "bounded_preflight": True,
        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "bytes": candidate.stat().st_size,
    }
    gates = [
        gate_record(
            "pdf.byte-format-security",
            "pass",
            evidence=identity,
        ),
        gate_record(gate_id, "pass", evidence=evidence),
        gate_record(
            "visual.render",
            "unavailable",
            required=False,
            evidence={"reason": "No accepted visual-render provider was used."},
            warnings=["Optional visual validation is unavailable."],
        ),
    ]
    return {"schema_version": "1.0", "status": "pass", "gates": gates}


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message)
