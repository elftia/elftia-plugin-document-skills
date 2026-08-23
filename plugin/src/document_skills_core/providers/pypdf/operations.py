"""Bounded pypdf mutations for encryption, decryption, and compression."""

from pathlib import Path
from typing import Any

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf import filters as pypdf_filters
from pypdf.constants import UserAccessPermissions

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.byte_preflight import preflight_pdf
from document_skills_core.formats.pdf.constants import (
    MAX_PAGES,
    MAX_STREAM_BYTES,
)

pypdf_filters.ZLIB_MAX_OUTPUT_LENGTH = MAX_STREAM_BYTES

_PERMISSION_FLAGS = {
    "annotate": UserAccessPermissions.ADD_OR_MODIFY,
    "assemble": UserAccessPermissions.ASSEMBLE_DOC,
    "extract": UserAccessPermissions.EXTRACT,
    "fill_forms": UserAccessPermissions.FILL_FORM_FIELDS,
    "high_quality_print": UserAccessPermissions.PRINT_TO_REPRESENTATION,
    "modify": UserAccessPermissions.MODIFY,
    "print": UserAccessPermissions.PRINT,
    "accessibility": UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS,
}
_RESERVED_PERMISSION_FLAGS = tuple(
    member
    for member in UserAccessPermissions
    if member.name in {"R7", "R8"}
    or member.name.startswith("R1") and member.name != "R1"
    or member.name.startswith("R2") and member.name != "R2"
    or member.name.startswith("R3")
)


def encrypt_pdf(
    source: Path,
    staged: Path,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    preflight = preflight_pdf(source)
    if preflight.encrypted:
        _invalid("pdf.encrypt requires an unencrypted input PDF.")
    reader = _reader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.pdf_header = "%PDF-1.7"
    writer.encrypt(
        arguments["user_password"],
        arguments["owner_password"],
        permissions_flag=_permission_mask(arguments["permissions"]),
        algorithm=arguments["algorithm"],
    )
    writer.write(staged)
    return {
        "encryption": {
            "algorithm": arguments["algorithm"],
            "encrypt_metadata": arguments["encrypt_metadata"],
            "permissions": arguments["permissions"],
            "verified": False,
        },
        "page_count": len(reader.pages),
    }


def decrypt_pdf(
    source: Path,
    staged: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], PasswordType]:
    preflight = preflight_pdf(source)
    if not preflight.encrypted:
        _invalid("pdf.decrypt requires an encrypted input PDF.")
    reader = _reader(source)
    password_type = reader.decrypt(arguments["password"])
    if password_type == PasswordType.NOT_DECRYPTED:
        _invalid("The supplied password did not unlock the encrypted PDF.")
    _assert_page_budget(reader)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.pdf_header = "%PDF-1.7"
    writer.write(staged)
    return (
        {
            "decryption": {
                "encrypted_input": True,
                "encrypted_output": False,
                "verified": False,
            },
            "page_count": len(reader.pages),
        },
        password_type,
    )


def compress_pdf(
    source: Path,
    staged: Path,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    preflight = preflight_pdf(source)
    if preflight.encrypted:
        _invalid("pdf.compress requires an unencrypted input PDF.")
    reader = _reader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for page in writer.pages:
        page.compress_content_streams(level=9)
    writer.compress_identical_objects(
        remove_duplicates=True,
        remove_unreferenced=True,
    )
    writer.write(staged)
    before_bytes = source.stat().st_size
    after_bytes = staged.stat().st_size
    if after_bytes >= before_bytes:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Lossless rewriting did not produce byte-size compression evidence.",
            status="enhancement_required",
            details={
                "mode": arguments["mode"],
                "before_bytes": before_bytes,
                "candidate_bytes": after_bytes,
            },
        )
    return {
        "compression": {
            "mode": arguments["mode"],
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "bytes_saved": before_bytes - after_bytes,
            "ratio": round(after_bytes / before_bytes, 6),
            "content_streams_recompressed": len(writer.pages),
            "duplicate_cleanup": True,
            "verified": False,
        },
        "page_count": len(reader.pages),
    }


def _reader(path: Path) -> PdfReader:
    try:
        reader = PdfReader(path, strict=True)
        if not reader.is_encrypted:
            _assert_page_budget(reader)
        return reader
    except Exception as error:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "pypdf rejected the input PDF during strict parsing.",
            details={"reason": type(error).__name__},
        ) from None


def _assert_page_budget(reader: PdfReader) -> None:
    page_count = len(reader.pages)
    if page_count <= 0 or page_count > MAX_PAGES:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF page count exceeds the bounded provider policy.",
            details={"page_count": page_count, "limit": MAX_PAGES},
        )


def _permission_mask(names: list[str]) -> UserAccessPermissions:
    flags = UserAccessPermissions(0)
    for member in _RESERVED_PERMISSION_FLAGS:
        flags |= member
    for name in names:
        flags |= _PERMISSION_FLAGS[name]
    return flags


def _invalid(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
    )
