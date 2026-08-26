from pathlib import Path

import pytest

from document_skills_core.cli import execute_request
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.docx.contracts import parse_docx_request

_MAX_CREATE_CELLS = 8_192
_MAX_CREATE_NODES = 10_000
_MAX_CREATE_TEXT_BYTES = 524_288


def _request(operation: str, **values: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "1.0",
        "operation": operation,
        "arguments": {},
    }
    request.update(values)
    return request
