"""Resolve PDF image filters and bind their parameter arrays."""

from typing import Any, NoReturn

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObjectModel


def filter_chain(
    model: PdfObjectModel,
    value: Any,
    *,
    object_number: int,
) -> list[str]:
    """Resolve a direct or indirect image Filter name or array."""
    value = _resolve_reference(model, value, object_number=object_number)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        filters = [
            _resolve_reference(model, item, object_number=object_number)
            for item in value
        ]
        if all(isinstance(item, str) for item in filters):
            return filters
    _unsafe("PDF image filter chain is malformed.", object=object_number)


def reject_dct_decode_parameters(
    model: PdfObjectModel,
    filters: list[str],
    value: Any,
    *,
    object_number: int,
) -> None:
    """Reject non-empty DecodeParms paired with any DCTDecode filter."""
    if "/DCTDecode" not in filters or value is None:
        return
    value = _resolve_reference(model, value, object_number=object_number)
    if isinstance(value, list):
        if len(value) != len(filters):
            _unsafe(
                "PDF image DecodeParms length does not match its filter chain.",
                object=object_number,
                filters=len(filters),
                parameters=len(value),
            )
        parameters = [
            _resolve_reference(model, item, object_number=object_number)
            for item in value
        ]
    elif len(filters) == 1:
        parameters = [value]
    else:
        _unsafe(
            "PDF image DecodeParms must be an array for multiple filters.",
            object=object_number,
            filters=len(filters),
        )
    for index, (filter_name, parameter) in enumerate(zip(filters, parameters)):
        if filter_name != "/DCTDecode" or parameter is None:
            continue
        if not isinstance(parameter, PdfDict):
            _unsafe(
                "PDF DCTDecode parameters are malformed.",
                object=object_number,
                filter_index=index,
            )
        if parameter.entries:
            _enhancement(
                "DCTDecode DecodeParms require an enhancement provider.",
                object=object_number,
                filter_index=index,
                parameter_keys=sorted(parameter.entries),
            )


def _resolve_reference(
    model: PdfObjectModel,
    value: Any,
    *,
    object_number: int,
) -> Any:
    seen: set[int] = set()
    while isinstance(value, IndirectReference):
        if value.obj_num in seen:
            _unsafe(
                "PDF image filter metadata contains an indirect cycle.",
                object=object_number,
            )
        seen.add(value.obj_num)
        value = model.get_object(value).value
    return value


def _unsafe(message: str, **details: Any) -> NoReturn:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)


def _enhancement(message: str, **details: Any) -> NoReturn:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.jpeg-decode-parameters", **details},
    )
