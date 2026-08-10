"""Independent PDF parser, text, image, and raster qualification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def qualify_pdf(artifact: Path, expectations: dict[str, Any]) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    try:
        import fitz

        document = fitz.open(artifact)
        try:
            if document.page_count <= 0:
                raise ValueError("pdf-has-no-pages")
            has_eof = artifact.read_bytes()[-1024:].rstrip().endswith(b"%%EOF")
            repaired = bool(getattr(document, "is_repaired", False))
            _record(
                assertions,
                "pdf.structural-integrity",
                has_eof and not repaired,
                {"eof_marker": has_eof, "parser_repaired": repaired},
            )
            extracted = "\n".join(page.get_text("text") for page in document)
            requested = [str(value) for value in expectations.get("text", [])]
            missing = [value for value in requested if value not in extracted]
            _record(
                assertions,
                "pdf.requested-text",
                not missing,
                {
                    "requested_count": len(requested),
                    "missing": missing,
                    "question_mark_substitution": bool(missing and "?" in extracted),
                },
            )
            actual_images = sum(len(page.get_images(full=True)) for page in document)
            expected_images = int(expectations.get("real_images", 0))
            _record(
                assertions,
                "pdf.real-images",
                actual_images >= expected_images,
                {"expected_minimum": expected_images, "actual": actual_images},
            )
            if expectations.get("render", False):
                render_hashes: list[str] = []
                for page in document:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
                    if pixmap.width <= 0 or pixmap.height <= 0 or not pixmap.samples:
                        raise ValueError("empty-render")
                    render_hashes.append(hashlib.sha256(pixmap.samples).hexdigest())
                _record(
                    assertions,
                    "pdf.render",
                    len(render_hashes) == document.page_count,
                    {"pages": document.page_count, "sha256": render_hashes},
                )
            evidence = {
                "parser": f"PyMuPDF/{fitz.VersionBind}",
                "pages": document.page_count,
                "extracted_text_sha256": hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
            }
        finally:
            document.close()
    except Exception as error:
        _record(
            assertions,
            "pdf.parse",
            False,
            {"category": type(error).__name__, "message": str(error)[:256]},
        )
    failed = any(item["outcome"] == "fail" for item in assertions)
    return {
        "consumer": "PyMuPDF-independent/1",
        "availability": "available",
        "outcome": "fail" if failed else "pass",
        "assertions": assertions,
        "warnings": [],
        "evidence": evidence,
    }


def _record(
    assertions: list[dict[str, Any]],
    assertion_id: str,
    passed: bool,
    evidence: dict[str, Any],
) -> None:
    assertions.append(
        {
            "id": assertion_id,
            "outcome": "pass" if passed else "fail",
            "evidence": evidence,
            "message": "" if passed else f"Independent assertion failed: {assertion_id}",
        }
    )
