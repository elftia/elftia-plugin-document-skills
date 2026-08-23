"""True removal for a narrow, verifiable PDF literal-text redaction subset.

Module provenance: original Elftia-authored clean-room implementation.
"""

import hashlib
from pathlib import Path
import re
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import extract_content_stream, walk_text_operators
from .mutation_writer import write_pdf_mutation
from .object_model import PdfDict, PdfObject, PdfObjectModel, parse_pdf
from .page_tree import walk_pages


def redact_literal_text(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove one unique unfiltered literal-string Tj operand and verify absence."""
    pages = walk_pages(model)
    page_number = primitive["page"]
    if page_number > len(pages):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Redaction page is outside the document.",
            status="invalid_request",
            details={"page": page_number, "page_count": len(pages)},
        )
    page = pages[page_number - 1]
    text = primitive["text"]
    blocks = [
        block for block in walk_text_operators(
            extract_content_stream(model, page.contents, page_number),
            page_number,
        )
        if block.text == text
    ]
    if len(blocks) != 1 or blocks[0].operator != "Tj":
        raise _ambiguous_match(len(blocks))
    literal = b"(" + _escape_literal(text).encode("latin-1", errors="strict") + b")"
    pattern = re.compile(re.escape(literal) + rb"(?=\s+Tj(?:\s|$))")
    matches: list[tuple[PdfObject, re.Match[bytes], int, int]] = []
    for reference in page.contents:
        obj = model.get_object(reference)
        dictionary = obj.value[0] if isinstance(obj.value, tuple) else None
        if not obj.is_stream or not isinstance(dictionary, PdfDict):
            continue
        if dictionary.get("/Filter") is not None:
            raise _unsupported_stream()
        start, end = _stream_bounds(obj, dictionary)
        for match in pattern.finditer(obj.payload_bytes[start:end]):
            matches.append((obj, match, start, end))
    if len(matches) != 1:
        raise _ambiguous_match(len(matches))
    target, match, stream_start, stream_end = matches[0]
    _reject_shared_content(model, pages, page_number, target.obj_num)
    stream = target.payload_bytes[stream_start:stream_end]
    redacted_stream = stream[:match.start()] + b"()" + stream[match.end():]
    payload = (
        target.payload_bytes[:stream_start]
        + redacted_stream
        + target.payload_bytes[stream_end:]
    )
    payload = re.sub(
        rb"/Length\s+\d+",
        f"/Length {len(redacted_stream)}".encode("ascii"),
        payload,
        count=1,
    )
    mutations = {target.obj_num: payload}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(write_pdf_mutation(model, mutations, {}, set()))

    output_model = parse_pdf(output)
    output_pages = walk_pages(output_model)
    output_content = extract_content_stream(
        output_model,
        output_pages[page_number - 1].contents,
        page_number,
    )
    output_texts = [
        block.text for block in walk_text_operators(output_content, page_number)
    ]
    verification = {
        "extracted_text_absent": text not in output_texts,
        "literal_bytes_absent": literal not in output_model.raw,
    }
    if not all(verification.values()):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Redacted text remained recoverable in the candidate PDF.",
            details=verification,
        )
    manifest = build_manifest(
        input_hashes,
        output_model.object_hashes(),
        changed={target.obj_num},
        added=set(),
        removed=set(),
    )
    return {
        "primitive": "redact_text",
        "page": page_number,
        "text_sha256": hashlib.sha256(text.encode("latin-1")).hexdigest(),
        "matched_operators": 1,
        "bbox": list(blocks[0].bbox),
        "content_object": target.obj_num,
        "verification": verification,
        "preservation": manifest,
    }, manifest


def _stream_bounds(obj: PdfObject, dictionary: PdfDict) -> tuple[int, int]:
    stream_match = re.search(rb"stream\r?\n", obj.payload_bytes)
    length = dictionary.get("/Length")
    if stream_match is None or not isinstance(length, int) or length < 0:
        raise _unsupported_stream()
    start = stream_match.end()
    end = start + length
    if end > len(obj.payload_bytes) or obj.payload_bytes[end:].find(b"endstream") < 0:
        raise _unsupported_stream()
    return start, end


def _reject_shared_content(
    model: PdfObjectModel,
    pages: list[Any],
    page_number: int,
    content_object: int,
) -> None:
    for page in pages:
        if page.page_number == page_number:
            continue
        if any(reference.obj_num == content_object for reference in page.contents):
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Redaction target content stream is shared by another page.",
                status="enhancement_required",
                details={"capability": "pdf.redaction-shared-content"},
            )


def _escape_literal(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _ambiguous_match(count: int) -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "Redaction requires exactly one matching literal Tj operator.",
        status="invalid_request",
        details={"match_count": count},
    )


def _unsupported_stream() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Core redaction supports unfiltered literal-text content streams only.",
        status="enhancement_required",
        details={"capability": "pdf.redaction-content-stream"},
    )
