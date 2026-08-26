"""Registry and path policy for public DOCX operation contracts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import same_path

from .contract_utils import (
    _exact_keys,
    _integer,
    _invalid,
    _optional_path,
    _optional_text,
    _text,
)
from .public_mutation_contract import (
    _parse_edit,
    _parse_merge,
    _parse_replace,
    _parse_template,
)
from .read_contract import _parse_accessibility, _parse_inspect, _parse_read
from .render_contract import (
    _parse_convert_legacy,
    _parse_convert_pdf,
    _parse_layout_repair,
    _parse_render,
    _parse_semantic_compare,
    _parse_visual_compare,
)
from .review_contract import (
    _parse_comments_add,
    _parse_comments_read,
    _parse_comments_resolve,
    _parse_revisions_apply,
    _parse_revisions_read,
    _parse_schema_validation,
)

DOCX_OPERATIONS = frozenset(
    {
        "docx.read",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.merge",
        "docx.create",
        "docx.edit",
        "docx.edit.replace-text",
        "docx.template.apply",
        "docx.revisions.read",
        "docx.revisions.apply",
        "docx.comments.read",
        "docx.comments.add",
        "docx.comments.resolve",
        "docx.compare.semantic",
        "docx.compare.visual",
        "docx.validate.schema",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.render",
        "docx.layout.repair",
    }
)

@dataclass(frozen=True)
class ParsedDocxRequest:
    operation: str
    input_path: Path | None
    output_path: Path | None
    arguments: dict[str, Any]
    requested_fidelity: str


def parse_docx_request(request: dict[str, Any]) -> ParsedDocxRequest:
    operation = request.get("operation")
    if operation not in DOCX_OPERATIONS:
        _invalid("The operation is not a public DOCX operation.", field="operation")
    arguments = request.get("arguments", {})
    if type(arguments) is not dict:
        _invalid("DOCX arguments must be an object.", field="arguments")
    input_path = _optional_path(request.get("input"), "input")
    output_path = _optional_path(request.get("output"), "output")
    options = request.get("options", {})
    fidelity = options.get("fidelity", "core") if type(options) is dict else "core"
    in_place = options.get("in_place", False) if type(options) is dict else False
    if operation in {
        "docx.read",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.revisions.read",
        "docx.comments.read",
        "docx.validate.schema",
        "docx.compare.semantic",
        "docx.compare.visual",
    }:
        if input_path is None:
            _invalid("This DOCX operation requires an input path.", field="input")
        if output_path is not None:
            _invalid("Read-only DOCX operations do not accept output.", field="output")
    elif operation == "docx.create":
        if output_path is None:
            _invalid("DOCX creation requires an explicit output path.", field="output")
        if input_path is not None:
            _invalid("DOCX creation does not accept input.", field="input")
    elif input_path is None or output_path is None:
        _invalid("DOCX mutation requires distinct input and output paths.")
    keep_vba = operation == "docx.edit" and arguments.get("keep_vba") is True
    legacy_format = arguments.get("format") if operation == "docx.convert.legacy" else None
    if operation == "docx.convert.legacy":
        input_extensions = {".doc"}
    elif operation == "docx.template.apply":
        input_extensions = {".docx", ".dotx"}
    elif operation == "docx.inspect.structure":
        input_extensions = {".docx", ".docm"}
    elif keep_vba:
        input_extensions = {".docm"}
    else:
        input_extensions = {".docx"}
    if (
        input_path is not None
        and input_path.suffix.casefold() not in input_extensions
    ):
        expected = " or ".join(sorted(input_extensions))
        _invalid(f"DOCX input path must use the {expected} extension.", field="input")
    expected_output_extension = (
        ".pdf"
        if operation in {"docx.convert.pdf", "docx.render"} or legacy_format == "pdf"
        else ".docm"
        if keep_vba
        else ".docx"
    )
    if (
        output_path is not None
        and output_path.suffix.casefold() != expected_output_extension
    ):
        _invalid(
            f"DOCX output path must use the {expected_output_extension} extension.",
            field="output",
        )
    if operation in {
        "docx.edit.replace-text",
        "docx.edit",
        "docx.merge",
        "docx.template.apply",
        "docx.revisions.apply",
        "docx.comments.add",
        "docx.comments.resolve",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.render",
        "docx.layout.repair",
    }:
        assert input_path is not None and output_path is not None
        if in_place or same_path(input_path, output_path):
            raise DocumentSkillsError(
                ErrorCode.OUTPUT_EQUALS_INPUT,
                "Core DOCX mutations require a distinct output and do not support in-place mode.",
                status="invalid_request",
            )
    elif in_place:
        _invalid("in_place is not meaningful for this DOCX operation.", field="options.in_place")
    if operation == "docx.create":
        from .create_contract import parse_create

        parsed = parse_create(arguments)
    else:
        parsed = {
            "docx.read": _parse_read,
            "docx.inspect.accessibility": _parse_accessibility,
            "docx.inspect.structure": _parse_inspect,
            "docx.edit": _parse_edit,
            "docx.merge": _parse_merge,
            "docx.edit.replace-text": _parse_replace,
            "docx.template.apply": _parse_template,
            "docx.revisions.read": _parse_revisions_read,
            "docx.revisions.apply": _parse_revisions_apply,
            "docx.comments.read": _parse_comments_read,
            "docx.comments.add": _parse_comments_add,
            "docx.comments.resolve": _parse_comments_resolve,
            "docx.compare.semantic": _parse_semantic_compare,
            "docx.compare.visual": _parse_visual_compare,
            "docx.validate.schema": _parse_schema_validation,
            "docx.convert.legacy": _parse_convert_legacy,
            "docx.convert.pdf": _parse_convert_pdf,
            "docx.render": _parse_render,
            "docx.layout.repair": _parse_layout_repair,
        }[operation](arguments)
    return ParsedDocxRequest(operation, input_path, output_path, parsed, fidelity)
