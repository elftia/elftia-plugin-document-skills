"""Post-process validation for files produced by LibreOffice.

The observer in this module may detect an anomaly early, but neither polling
nor a free-space check is a hard quota.  Process launch is separately gated by
``libreoffice.quota`` and its aggregate storage contract.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ...formats.docx.constants import MAX_DOCX_BYTES
from ...formats.pdf.constants import MAX_PDF_BYTES
from ...formats.pptx.constants import MAX_PPTX_BYTES
from ...formats.xlsx.constants import MAX_XLSX_BYTES

MAX_IMAGE_BYTES = 128 * 1024 * 1024
OUTPUT_LIMITS = {
    "docx": MAX_DOCX_BYTES,
    "pdf": MAX_PDF_BYTES,
    "png": MAX_IMAGE_BYTES,
    "pptx": MAX_PPTX_BYTES,
    "xlsx": MAX_XLSX_BYTES,
}


def output_limit(target_format: str) -> int:
    try:
        return OUTPUT_LIMITS[target_format]
    except KeyError as error:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "LibreOffice target format has no output byte policy.",
            status="invalid_request",
            details={"target_format": target_format},
        ) from error


def read_provider_output(
    path: Path,
    target_format: str,
    *,
    max_output_bytes: int | None = None,
) -> bytes:
    """Reject non-regular or oversized output before reading its bytes."""

    limit = output_limit(target_format)
    if max_output_bytes is not None:
        if type(max_output_bytes) is not int or max_output_bytes < 1:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "LibreOffice output byte ceiling must be a positive integer.",
                status="invalid_request",
            )
        limit = min(limit, max_output_bytes)
    try:
        with path.open("rb") as handle:
            metadata = path.lstat()
            handle_metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not stat.S_ISREG(handle_metadata.st_mode)
                or (metadata.st_dev, metadata.st_ino)
                != (handle_metadata.st_dev, handle_metadata.st_ino)
            ):
                _failed("LibreOffice output is not one bound regular file.")
            if metadata.st_size > limit:
                _oversized(metadata.st_size, limit, target_format)
            payload = handle.read(limit + 1)
    except DocumentSkillsError:
        raise
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice output could not be read safely.",
            details={"reason": type(error).__name__},
        ) from error
    if len(payload) > limit:
        _oversized(len(payload), limit, target_format)
    return payload


def assert_output_within_limit(path: Path, target_format: str) -> None:
    """Perform the mandatory post-process stat before returning an output path."""

    limit = output_limit(target_format)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "LibreOffice conversion produced no readable output file.",
            details={"reason": type(error).__name__},
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        _failed("LibreOffice output is not a regular file.")
    if metadata.st_size > limit:
        _oversized(metadata.st_size, limit, target_format)


def output_runtime_observer(
    output_dir: Path,
    expected_output: Path,
    target_format: str,
) -> Callable[[], None]:
    """Return a best-effort early anomaly observer.

    A child may complete a large write between observations.  This callback is
    defense in depth only and must never authorize process launch or be cited
    as an aggregate hard-storage quota.
    """

    root = output_dir.resolve()
    expected_name = expected_output.name
    limit = output_limit(target_format)

    def check() -> None:
        total_bytes = 0
        expected_bytes = 0
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        _failed(
                            "LibreOffice output directory contains a non-regular entry."
                        )
                    total_bytes += metadata.st_size
                    if entry.name == expected_name:
                        expected_bytes = metadata.st_size
                    if expected_bytes > limit:
                        _oversized(expected_bytes, limit, target_format)
                    if total_bytes > limit:
                        _oversized(total_bytes, limit, target_format)
        except DocumentSkillsError:
            raise
        except OSError as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "LibreOffice output directory could not be monitored safely.",
                details={"reason": type(error).__name__},
            ) from error

    return check


def _oversized(actual: int, limit: int, target_format: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_FAILED,
        "LibreOffice output exceeds the independent artifact byte ceiling.",
        details={
            "target_format": target_format,
            "output_bytes": actual,
            "output_limit": limit,
        },
    )


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)
