"""Safe local-image loading for the constrained SVG compiler."""

import hashlib
from pathlib import Path
from typing import Any

from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY

from .scene import SCENE_LIMITS, _image_metadata
from .svg_values import invalid, unsafe


def load_svg_asset(
    source: Path,
    relative: str,
    *,
    purpose: str,
    assets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    try:
        identity = PORTABLE_PATH_POLICY.parse_relative(relative)
    except ValueError as error:
        unsafe("SVG image path is not portable.", reason=str(error))
    candidate = source.parent.joinpath(*identity.components)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(source.parent.resolve(strict=True))
    except (OSError, ValueError) as error:
        unsafe("SVG image path escapes or is missing.", reason=type(error).__name__)
    current = source.parent.resolve(strict=True)
    for component in identity.components:
        current /= component
        if current.is_symlink():
            unsafe("SVG image path contains a symlink.")
    if not resolved.is_file() or resolved.stat().st_size > SCENE_LIMITS["image_bytes"]:
        invalid("SVG image is not a bounded regular file.")
    payload = resolved.read_bytes()
    mime, width, height = _image_metadata(payload)
    digest = hashlib.sha256(payload).hexdigest()
    extension = "png" if mime == "image/png" else "jpg"
    record = {
        "bytes": len(payload),
        "filename": f"asset-{digest}.{extension}",
        "height": height,
        "id": digest,
        "mime": mime,
        "path": resolved,
        "purpose": purpose,
        "width": width,
    }
    prior = assets.get(digest)
    if prior is not None and prior["purpose"] != purpose:
        record = {**prior, "purpose": "source-image"}
    assets[digest] = record
    return record


__all__ = ["load_svg_asset"]
