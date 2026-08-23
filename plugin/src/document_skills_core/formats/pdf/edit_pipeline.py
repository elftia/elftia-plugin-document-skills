"""Sequential bounded PDF edit transaction orchestration.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Any

from .object_model import PdfObjectModel, parse_pdf

PrimitiveRunner = Callable[
    [PdfObjectModel, dict[str, Any], Path, dict[int, str]],
    tuple[dict[str, Any], dict[str, Any]],
]
ManifestBuilder = Callable[..., dict[str, Any]]


def run_edit_pipeline(
    input_path: Path,
    output_path: Path,
    primitives: list[dict[str, Any]],
    *,
    run_primitive: PrimitiveRunner,
    build_manifest: ManifestBuilder,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply primitives in request order and publish only the final candidate."""
    if len(primitives) == 1:
        model = parse_pdf(input_path)
        return run_primitive(
            model,
            primitives[0],
            output_path,
            model.object_hashes(),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    original_model = parse_pdf(input_path)
    original_hashes = original_model.object_hashes()
    current_path = input_path
    staged_paths: list[Path] = []
    primitive_results: list[dict[str, Any]] = []
    try:
        for index, primitive in enumerate(primitives):
            staged_path = _new_staged_path(output_path, index)
            staged_paths.append(staged_path)
            current_model = parse_pdf(current_path)
            result, _manifest = run_primitive(
                current_model,
                primitive,
                staged_path,
                current_model.object_hashes(),
            )
            primitive_results.append({"index": index, **result})
            current_path = staged_path

        final_model = parse_pdf(current_path)
        final_hashes = final_model.object_hashes()
        original_objects = set(original_hashes)
        final_objects = set(final_hashes)
        changed = {
            obj_num
            for obj_num in original_objects & final_objects
            if original_hashes[obj_num] != final_hashes[obj_num]
        }
        manifest = build_manifest(
            original_hashes,
            final_hashes,
            changed=changed,
            added=final_objects - original_objects,
            removed=original_objects - final_objects,
        )
        os.replace(current_path, output_path)
        staged_paths.remove(current_path)
        return {
            "primitive_count": len(primitive_results),
            "primitives": primitive_results,
            "preservation": manifest,
        }, manifest
    finally:
        for staged_path in staged_paths:
            staged_path.unlink(missing_ok=True)


def _new_staged_path(output_path: Path, index: int) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{output_path.name}.primitive-{index}-",
        suffix=".pdf",
        dir=output_path.parent,
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    return path
