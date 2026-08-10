"""Normalized path identity and distinct-output checks."""

from __future__ import annotations

import os
from pathlib import Path

from ..contracts.errors import DocumentSkillsError, ErrorCode


def normalized_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def same_path(first: str | Path, second: str | Path) -> bool:
    left = normalized_path(first)
    right = normalized_path(second)
    if os.name == "nt":
        return os.path.normcase(str(left)) == os.path.normcase(str(right))
    return left == right


def assert_distinct_paths(
    input_path: str | Path,
    output_path: str | Path,
    *,
    in_place: bool = False,
) -> None:
    if same_path(input_path, output_path):
        message = (
            "In-place output is not implemented by this operation."
            if in_place
            else "Output resolves to the input; explicit supported in-place mode is required."
        )
        raise DocumentSkillsError(ErrorCode.OUTPUT_EQUALS_INPUT, message)
