"""Reopen assertions for planned DOCX table mutations."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mapping import Story
from .table_model import table_semantic_state


def assert_table_state(body: Story, expected: list[dict[str, Any]]) -> dict[str, Any]:
    actual = table_semantic_state(body.root)
    if actual != expected:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited DOCX tables do not match the immutable table plan.",
            details={"expected_tables": len(expected), "actual_tables": len(actual)},
        )
    return {"verified_tables": len(actual)}
