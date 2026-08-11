"""Independent PDF parser, text, image, and raster qualification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


_MAX_PAGES = 32
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RENDER_SAMPLES = 64 * 1024 * 1024


def preflight_pdf_resource_bounds(artifact: Path) -> dict[str, Any] | None:
    """Reject an oversized candidate before any aggregate read or hash."""

    artifact_bytes = _artifact_size(artifact)
    if artifact_bytes <= _MAX_ARTIFACT_BYTES:
        return None
    assertions: list[dict[str, Any]] = []
    _record(
        assertions,
        "pdf.resource-bounds",
        False,
        {
            "actual": artifact_bytes,
            "category": "artifact-byte-limit",
            "maximum": _MAX_ARTIFACT_BYTES,
        },
    )
    return _gate(assertions, {})


def qualify_pdf(artifact: Path, expectations: dict[str, Any]) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    try:
        import fitz

        resource_rejection = preflight_pdf_resource_bounds(artifact)
        if resource_rejection is not None:
            return resource_rejection
        artifact_bytes = _artifact_size(artifact)
        document = fitz.open(artifact)
        try:
            if document.page_count <= 0:
                raise ValueError("pdf-has-no-pages")
            if document.page_count > _MAX_PAGES:
                _record(
                    assertions,
                    "pdf.resource-bounds",
                    False,
                    {
                        "actual": document.page_count,
                        "category": "artifact-page-limit",
                        "maximum": _MAX_PAGES,
                    },
                )
                return _gate(assertions, evidence)
            _record(
                assertions,
                "pdf.resource-bounds",
                True,
                {
                    "artifact_bytes": artifact_bytes,
                    "maximum_artifact_bytes": _MAX_ARTIFACT_BYTES,
                    "maximum_pages": _MAX_PAGES,
                    "pages": document.page_count,
                },
            )
            has_eof = _has_eof_marker(artifact, artifact_bytes)
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
                _validate_render_delta(
                    document,
                    artifact,
                    expectations["render"],
                    assertions,
                    fitz,
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
    return _gate(assertions, evidence)


def _gate(
    assertions: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    failed = any(item["outcome"] == "fail" for item in assertions)
    return {
        "consumer": "PyMuPDF-independent/2",
        "availability": "available",
        "outcome": "fail" if failed else "pass",
        "assertions": assertions,
        "warnings": [],
        "evidence": evidence,
    }


def _artifact_size(path: Path) -> int:
    if not path.is_file():
        raise ValueError("artifact-missing")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("artifact-empty")
    return size


def _has_eof_marker(path: Path, size: int) -> bool:
    with path.open("rb") as handle:
        handle.seek(max(0, size - 1024))
        tail = handle.read(1024)
    return tail.rstrip().endswith(b"%%EOF")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_render_delta(
    document: Any,
    artifact: Path,
    expectation: Any,
    assertions: list[dict[str, Any]],
    fitz: Any,
) -> None:
    if type(expectation) is not dict:
        _record(
            assertions,
            "pdf.render-delta",
            False,
            {"category": "explicit-render-reference-required"},
        )
        return
    reference_value = expectation.get("reference")
    reference_kind = expectation.get("reference_kind")
    mode = expectation.get("mode")
    if not isinstance(reference_value, str) or reference_kind not in {"expected", "source"}:
        _record(
            assertions,
            "pdf.render-delta",
            False,
            {"category": "invalid-render-reference"},
        )
        return
    if mode not in {"match", "different"}:
        _record(
            assertions,
            "pdf.render-delta",
            False,
            {"category": "invalid-render-delta-mode"},
        )
        return
    try:
        reference = Path(reference_value).resolve(strict=True)
        if not reference.is_file() or reference.stat().st_size <= 0:
            raise ValueError("render-reference-missing-or-empty")
        if reference.samefile(artifact):
            raise ValueError("render-reference-is-candidate")
        reference_bytes = _artifact_size(reference)
        if reference_bytes > _MAX_ARTIFACT_BYTES:
            _record(
                assertions,
                "pdf.render-delta",
                False,
                {
                    "actual": reference_bytes,
                    "category": "reference-artifact-byte-limit",
                    "maximum": _MAX_ARTIFACT_BYTES,
                },
            )
            return
        reference_document = fitz.open(reference)
        try:
            if reference_document.page_count <= 0:
                raise ValueError("reference-pdf-has-no-pages")
            if reference_document.page_count > _MAX_PAGES:
                _record(
                    assertions,
                    "pdf.render-delta",
                    False,
                    {
                        "actual": reference_document.page_count,
                        "category": "reference-artifact-page-limit",
                        "maximum": _MAX_PAGES,
                    },
                )
                return
            comparison = _compare_rendered_pages(document, reference_document, fitz)
        finally:
            reference_document.close()
        ratio = comparison["changed_sample_ratio"]
        threshold = float(
            expectation.get(
                "max_changed_sample_ratio" if mode == "match" else "min_changed_sample_ratio",
                0.0 if mode == "match" else 0.0001,
            )
        )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("render-delta-threshold-out-of-range")
        passed = ratio <= threshold if mode == "match" else ratio >= threshold
        _record(
            assertions,
            "pdf.render-delta",
            passed,
            {
                **comparison,
                "mode": mode,
                "reference_kind": reference_kind,
                "reference_path": str(reference),
                "reference_sha256": _sha256_file(reference),
                "threshold": threshold,
            },
        )
    except Exception as error:
        _record(
            assertions,
            "pdf.render-delta",
            False,
            {"category": type(error).__name__, "message": str(error)[:256]},
        )


def _compare_rendered_pages(
    candidate: Any,
    reference: Any,
    fitz: Any,
) -> dict[str, Any]:
    if candidate.page_count <= 0 or candidate.page_count > _MAX_PAGES:
        raise ValueError("candidate-render-page-limit")
    if reference.page_count <= 0 or reference.page_count > _MAX_PAGES:
        raise ValueError("reference-render-page-limit")
    if candidate.page_count != reference.page_count:
        raise ValueError("render-page-count-mismatch")
    candidate_hashes: list[str] = []
    reference_hashes: list[str] = []
    changed_samples = 0
    total_samples = 0
    for page_index in range(candidate.page_count):
        candidate_pixmap = candidate[page_index].get_pixmap(
            matrix=fitz.Matrix(1, 1),
            alpha=False,
        )
        reference_pixmap = reference[page_index].get_pixmap(
            matrix=fitz.Matrix(1, 1),
            alpha=False,
        )
        candidate_samples = candidate_pixmap.samples
        reference_samples = reference_pixmap.samples
        if (
            candidate_pixmap.width <= 0
            or candidate_pixmap.height <= 0
            or (candidate_pixmap.width, candidate_pixmap.height)
            != (reference_pixmap.width, reference_pixmap.height)
            or len(candidate_samples) != len(reference_samples)
        ):
            raise ValueError("render-dimensions-mismatch")
        total_samples += len(candidate_samples)
        if total_samples > _MAX_RENDER_SAMPLES:
            raise ValueError("render-sample-limit")
        changed_samples += sum(
            candidate_value != reference_value
            for candidate_value, reference_value in zip(
                candidate_samples,
                reference_samples,
                strict=True,
            )
        )
        candidate_hashes.append(hashlib.sha256(candidate_samples).hexdigest())
        reference_hashes.append(hashlib.sha256(reference_samples).hexdigest())
    return {
        "pages": candidate.page_count,
        "candidate_render_sha256": candidate_hashes,
        "reference_render_sha256": reference_hashes,
        "changed_samples": changed_samples,
        "total_samples": total_samples,
        "changed_sample_ratio": changed_samples / total_samples if total_samples else 1.0,
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
