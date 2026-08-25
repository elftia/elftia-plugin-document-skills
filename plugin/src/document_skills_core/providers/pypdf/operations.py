"""Bounded pypdf mutations for encryption, decryption, and compression."""

from pathlib import Path
from typing import Any
import warnings

from PIL import Image
from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf import filters as pypdf_filters
from pypdf.constants import UserAccessPermissions

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.byte_preflight import preflight_pdf
from document_skills_core.formats.pdf.constants import (
    MAX_PAGES,
    MAX_STREAM_BYTES,
)
from document_skills_core.formats.pdf.image_assets import MAX_IMAGE_PIXELS

from .compression_evidence import (
    image_diff_metrics,
    measure_compression,
    reopen_visual_evidence,
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
_MAX_COMPRESSION_IMAGES = 1_000
_OUTPUT_VERSION = "1.7"
_COMPRESSION_POLICIES = {
    "balanced": {
        "max_dimension": 1_920,
        "quality": 82,
        "minimum_psnr_db": 24.0,
    },
    "aggressive": {
        "max_dimension": 1_280,
        "quality": 60,
        "minimum_psnr_db": 18.0,
    },
}


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
    writer.pdf_header = f"%PDF-{_OUTPUT_VERSION}"
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
        "output_version": _OUTPUT_VERSION,
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
    writer.pdf_header = f"%PDF-{_OUTPUT_VERSION}"
    writer.write(staged)
    return (
        {
            "decryption": {
                "encrypted_input": True,
                "encrypted_output": False,
                "verified": False,
            },
            "page_count": len(reader.pages),
            "output_version": _OUTPUT_VERSION,
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
    image_evidence: dict[str, Any] | None = None
    if arguments["mode"] != "lossless":
        _compress_images(writer, arguments["mode"])
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
            "PDF rewriting did not produce byte-size compression evidence.",
            status="enhancement_required",
            details={
                "mode": arguments["mode"],
                "before_bytes": before_bytes,
                "candidate_bytes": after_bytes,
            },
        )
    evidence = measure_compression(source, staged)
    if arguments["mode"] != "lossless":
        try:
            image_evidence = reopen_visual_evidence(
                reader,
                PdfReader(staged, strict=True),
                arguments["mode"],
                _COMPRESSION_POLICIES[arguments["mode"]],
            )
        except Exception as error:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Compressed images could not be independently reopened.",
                details={"reason": type(error).__name__},
            ) from None
    result = {
        "compression": {
            "mode": arguments["mode"],
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "bytes_saved": before_bytes - after_bytes,
            "ratio": round(after_bytes / before_bytes, 6),
            "content_streams_recompressed": evidence["components"]["stream"][
                "content_changed_count"
            ],
            "duplicate_cleanup": (
                evidence["components"]["duplicate"]["after"]["count"]
                < evidence["components"]["duplicate"]["before"]["count"]
            ),
            "images_recompressed": (
                image_evidence["images_recompressed"]
                if image_evidence is not None
                else 0
            ),
            "images_downsampled": (
                image_evidence["images_downsampled"]
                if image_evidence is not None
                else 0
            ),
            "semantic_policy": _compression_semantic_policy(arguments["mode"]),
            "evidence": evidence,
            "verified": False,
        },
        "page_count": len(reader.pages),
    }
    if image_evidence is not None:
        result["visual_diff"] = image_evidence
    return result


def _compression_semantic_policy(mode: str) -> dict[str, Any]:
    preserved = [
        "media_box",
        "crop_box",
        "rotation",
        "metadata",
        "resources",
        "image_identity",
    ]
    if mode == "lossless":
        return {"preserved": preserved, "allowed_changes": []}
    policy = _COMPRESSION_POLICIES[mode]
    return {
        "preserved": preserved[:-1],
        "allowed_changes": [{
            "component": "image-xobjects-only",
            "encoding": "jpeg-reencode",
            "maximum_dimension": policy["max_dimension"],
            "minimum_psnr_db": policy["minimum_psnr_db"],
        }],
    }


def _compress_images(writer: PdfWriter, mode: str) -> dict[str, Any]:
    policy = _COMPRESSION_POLICIES[mode]
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    total_pixels = 0
    for page_number, page in enumerate(writer.pages, start=1):
        for image_file in page.images:
            reference = image_file.indirect_reference
            if reference is None:
                skipped.append({
                    "page": page_number,
                    "name": image_file.name,
                    "reason": "inline-image",
                })
                continue
            identity = (reference.idnum, reference.generation)
            if identity in seen:
                continue
            seen.add(identity)
            if len(seen) > _MAX_COMPRESSION_IMAGES:
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "PDF image count exceeds the compression policy.",
                    details={"limit": _MAX_COMPRESSION_IMAGES},
                )
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                original = image_file.image.copy()
                original.load()
            pixels = original.width * original.height
            total_pixels += pixels
            if pixels <= 0 or pixels > MAX_IMAGE_PIXELS or total_pixels > MAX_IMAGE_PIXELS:
                raise DocumentSkillsError(
                    ErrorCode.ARCHIVE_UNSAFE,
                    "PDF images exceed the bounded decoded-pixel policy.",
                    details={
                        "image_pixels": pixels,
                        "total_pixels": total_pixels,
                        "limit": MAX_IMAGE_PIXELS,
                    },
                )
            if "A" in original.getbands() or "transparency" in original.info:
                skipped.append({
                    "page": page_number,
                    "name": image_file.name,
                    "object": reference.idnum,
                    "reason": "alpha-preservation-required",
                })
                continue
            baseline = original.convert("RGB")
            replacement = baseline.copy()
            replacement.thumbnail(
                (policy["max_dimension"], policy["max_dimension"]),
                Image.Resampling.LANCZOS,
            )
            downsampled = replacement.size != baseline.size
            image_file.replace(
                replacement,
                quality=policy["quality"],
                optimize=True,
            )
            actual = image_file.image.convert("RGB")
            actual.load()
            metrics = image_diff_metrics(baseline, actual)
            if metrics["psnr_db"] < policy["minimum_psnr_db"]:
                raise DocumentSkillsError(
                    ErrorCode.VALIDATION_FAILED,
                    "Compressed image did not satisfy its visual quality threshold.",
                    details={
                        "mode": mode,
                        "object": reference.idnum,
                        "psnr_db": metrics["psnr_db"],
                        "minimum_psnr_db": policy["minimum_psnr_db"],
                    },
                )
            records.append({
                "page": page_number,
                "name": image_file.name,
                "object": reference.idnum,
                "before_dimensions": list(baseline.size),
                "after_dimensions": list(actual.size),
                "downsampled": downsampled,
                **metrics,
            })
    if not records:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Lossy compression found no compatible Image XObject to optimize.",
            status="enhancement_required",
            details={"mode": mode, "skipped_images": skipped},
        )
    return {
        "source": "decoded-image-xobject-diff",
        "scope": "image-xobjects",
        "page_rendered": False,
        "mode": mode,
        "quality": policy["quality"],
        "max_dimension": policy["max_dimension"],
        "minimum_psnr_db": policy["minimum_psnr_db"],
        "allowed_changes": {
            "component": "image-xobjects-only",
            "encoding": "jpeg-reencode",
            "maximum_dimension": policy["max_dimension"],
            "minimum_psnr_db": policy["minimum_psnr_db"],
        },
        "images_recompressed": len(records),
        "images_downsampled": sum(record["downsampled"] for record in records),
        "images": records,
        "skipped_images": skipped,
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
