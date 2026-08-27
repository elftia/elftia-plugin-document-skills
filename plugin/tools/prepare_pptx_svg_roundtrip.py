"""Prepare the deterministic B5 scene-export round trip for consumer capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from document_skills_core.formats.pptx.presentation_contracts import (
    PRESENTATION_CONTRACT_V1_PIN,
)
from document_skills_core.formats.pptx.scene_emitter import emit_scene_pptx
from document_skills_core.formats.pptx.service import PptxService
from document_skills_core.formats.pptx.svg_parser import compile_svg_scene
from document_skills_core.formats.pptx.validation import validate_scene_created


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def prepare_roundtrip(source: Path, contract_root: Path, output: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    contract_root = contract_root.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise ValueError(f"round-trip output already exists: {output}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pptx-b5-roundtrip-") as temporary:
        temporary_root = Path(temporary)
        bundle = temporary_root / "scene-bundle"
        result = PptxService(_PLUGIN_ROOT).execute(
            "pptx.scene.export",
            {
                "schema_version": "1.0",
                "operation": "pptx.scene.export",
                "input": str(source),
                "output": str(bundle),
                "arguments": {
                    "contract": {
                        "manifest_sha256": PRESENTATION_CONTRACT_V1_PIN.manifest_sha256,
                        "root": str(contract_root),
                    },
                    "identity": {
                        "namespace": "example.synthetic",
                        "source_template_id": "svg-roundtrip",
                        "source_template_version": "1.0.0",
                    },
                    "mode": "strict",
                },
            },
        )
        if result["status"] != "success":
            raise RuntimeError("scene export failed: " + json.dumps(result, sort_keys=True))
        exported_svg = next(bundle.glob("slide-*.svg"))
        scene = compile_svg_scene(exported_svg, fallback_policy="reject")
        candidate = temporary_root / "roundtrip.pptx"
        emission = emit_scene_pptx(
            candidate,
            scene,
            {"creator": "Elftia", "subject": "B5", "title": "Round trip output"},
        )
        validation = validate_scene_created(candidate, scene, emission)
        if validation["status"] != "pass":
            raise RuntimeError(
                "round-trip validation failed: " + json.dumps(validation, sort_keys=True)
            )
        shutil.copyfile(candidate, output)
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        output.unlink(missing_ok=True)
        raise RuntimeError("source changed while preparing PowerPoint evidence")
    payload = output.read_bytes()
    return {
        "bytes": len(payload),
        "output": str(output),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    args = _parse_args()
    print(json.dumps(
        prepare_roundtrip(args.source, args.contract_root, args.output),
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
