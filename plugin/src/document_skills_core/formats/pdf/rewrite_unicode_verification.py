"""Candidate-derived verification for locator-bound Unicode rewrites."""

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import PdfObjectModel
from .rewrite_operator_targeting import OperatorLocator


def assert_unicode_operator_rewrites(
    input_model: PdfObjectModel,
    output_model: PdfObjectModel,
    locators: list[OperatorLocator],
    rewrite_map: dict[int, str],
) -> None:
    """Reopen each target stream and prove only selected operands were blanked."""
    by_index = {locator.block_index: locator for locator in locators}
    grouped: dict[int, list[OperatorLocator]] = {}
    for block_index in rewrite_map:
        locator = by_index[block_index]
        grouped.setdefault(locator.content_object, []).append(locator)
    failures: list[int] = []
    for object_number, targets in grouped.items():
        source = _stream_bytes(input_model, object_number)
        candidate = _stream_bytes(output_model, object_number)
        expected_prefix = source
        for locator in sorted(targets, key=lambda item: item.operand_start, reverse=True):
            if source[locator.operand_start:locator.operand_end] != locator.original_operand:
                failures.append(object_number)
                break
            expected_prefix = (
                expected_prefix[:locator.operand_start]
                + _empty_operand(locator)
                + expected_prefix[locator.operand_end:]
            )
        if not candidate.startswith(expected_prefix) or len(candidate) <= len(expected_prefix):
            failures.append(object_number)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Unicode rewrite failed exact-operator candidate verification.",
            details={"content_objects": sorted(set(failures))},
        )


def _stream_bytes(model: PdfObjectModel, object_number: int) -> bytes:
    obj = model.objects.get(object_number)
    if obj is None or not obj.is_stream or not isinstance(obj.value, tuple):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Unicode rewrite candidate is missing a target content stream.",
            details={"content_object": object_number},
        )
    return obj.value[1]


def _empty_operand(locator: OperatorLocator) -> bytes:
    if locator.operator == "TJ":
        return b"[]"
    return b"<>" if locator.operand_kind == "hex" else b"()"
