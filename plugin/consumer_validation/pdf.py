"""Independent PDF parser, text, image, and raster qualification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .pdf_evidence import PdfArtifactEvidence, read_bounded_pdf_evidence


_MAX_PAGES = 32
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RENDER_SAMPLES = 64 * 1024 * 1024
_EVIDENCE_CHUNK_BYTES = 64 * 1024


def observe_pdf_artifact(artifact: Path) -> PdfArtifactEvidence:
    """Return exact bounded bytes or a typed resource/mutation observation."""

    return read_bounded_pdf_evidence(
        artifact,
        maximum_bytes=_MAX_ARTIFACT_BYTES,
        chunk_bytes=_EVIDENCE_CHUNK_BYTES,
    )


def qualify_pdf(
    artifact: Path,
    expectations: dict[str, Any],
    *,
    artifact_evidence: PdfArtifactEvidence | None = None,
) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    try:
        import fitz

        observation = artifact_evidence or observe_pdf_artifact(artifact)
        if observation.outcome != "exact":
            return evidence_failure_gate(observation, phase="portable")
        if observation.content is None or observation.sha256 is None:
            raise ValueError("pdf-exact-evidence-incomplete")
        artifact_bytes = observation.artifact_bytes
        document = fitz.open(stream=observation.content, filetype="pdf")
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
            has_eof = _has_eof_marker(observation.content)
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


def evidence_failure_gate(
    observation: PdfArtifactEvidence,
    *,
    phase: str,
    before_sha256: str | None = None,
) -> dict[str, Any]:
    """Project a non-exact byte observation into portable typed evidence."""

    if observation.outcome == "exact":
        raise ValueError("exact-pdf-evidence-is-not-a-failure")
    assertion_id = (
        "pdf.resource-bounds"
        if observation.outcome == "resource-limit"
        else "consumer.source-preservation"
    )
    details = (
        {
            "actual": observation.evidence["actual"],
            "category": "artifact-byte-limit",
            "maximum": observation.evidence["maximum"],
        }
        if observation.outcome == "resource-limit"
        else {**observation.evidence, "phase": phase}
    )
    if before_sha256 is not None:
        details["before_sha256"] = before_sha256
    assertions: list[dict[str, Any]] = []
    _record(assertions, assertion_id, False, details)
    return _gate(assertions, {})


def source_change_gate(before: PdfArtifactEvidence, after: PdfArtifactEvidence) -> dict[str, Any]:
    """Return a typed failure when two exact bounded observations differ."""

    if before.sha256 is None or after.sha256 is None:
        raise ValueError("source-change-requires-exact-digests")
    assertions: list[dict[str, Any]] = []
    _record(
        assertions,
        "consumer.source-preservation",
        False,
        {
            "before_bytes": before.artifact_bytes,
            "before_sha256": before.sha256,
            "after_bytes": after.artifact_bytes,
            "after_sha256": after.sha256,
            "category": "artifact-changed-between-evidence-points",
            "phase": "post-consumer",
        },
    )
    return _gate(assertions, {})


def _has_eof_marker(content: bytes) -> bool:
    return content[-1024:].rstrip().endswith(b"%%EOF")


def _sha256_file(path: Path) -> str:
    """Retain the legacy private test seam without an unbounded file read."""

    observation = observe_pdf_artifact(path)
    if observation.outcome != "exact" or observation.sha256 is None:
        raise ValueError("pdf-hash-evidence-not-exact")
    return observation.sha256


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
        reference_observation = observe_pdf_artifact(reference)
        if reference_observation.outcome == "resource-limit":
            _record(
                assertions,
                "pdf.render-delta",
                False,
                {
                    "actual": reference_observation.evidence["actual"],
                    "category": "reference-artifact-byte-limit",
                    "maximum": reference_observation.evidence["maximum"],
                },
            )
            return
        if reference_observation.outcome == "mutation":
            _record(
                assertions,
                "pdf.render-delta",
                False,
                {
                    **reference_observation.evidence,
                    "category": "reference-artifact-mutated-during-evidence",
                },
            )
            return
        if reference_observation.content is None or reference_observation.sha256 is None:
            raise ValueError("reference-pdf-exact-evidence-incomplete")
        reference_document = fitz.open(
            stream=reference_observation.content,
            filetype="pdf",
        )
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
                "reference_sha256": reference_observation.sha256,
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
