"""Validate the published presentation-contract package without copying its schemas."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def _load(root: Path, relative: str) -> Any:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _stable_id(kind: str, parts: list[str]) -> str:
    frames = ["elftia.presentation-id.v1", kind, *parts]
    framed = "|".join(f"{len(value.encode('utf-8'))}:{value}" for value in frames)
    return f"{kind}_{hashlib.sha256(framed.encode('utf-8')).hexdigest()[:32]}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def check_contracts(contract_root: Path) -> dict[str, Any]:
    root = contract_root.resolve()
    manifest = _load(root, "schemas/schema-manifest.json")
    for artifact in manifest["artifacts"]:
        actual = "sha256:" + hashlib.sha256((root / artifact["path"]).read_bytes()).hexdigest()
        if actual != artifact["sha256"]:
            raise ValueError(f"presentation artifact hash mismatch: {artifact['path']}")

    fixtures = {
        "deckIr": _load(root, "fixtures/v1/deck-ir.valid.json"),
        "semanticSlots": _load(root, "fixtures/v1/semantic-slots.valid.json"),
        "templateContract": _load(root, "fixtures/v1/template-contract.not-evaluated.json"),
    }
    schemas = {
        "deckIr": _load(root, "schemas/v1/deck-ir.schema.json"),
        "semanticSlots": _load(root, "schemas/v1/semantic-slots.schema.json"),
        "templateContract": _load(root, "schemas/v1/template-contract.schema.json"),
    }
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(fixtures[name])

    unknown = dict(fixtures["deckIr"], schemaVersion="2.0.0")
    if not list(Draft202012Validator(schemas["deckIr"]).iter_errors(unknown)):
        raise ValueError("document-skills accepted an unknown Deck IR schema version")

    vectors = _load(root, "fixtures/v1/stable-id-vectors.json")
    deck_id = _stable_id(
        "deck",
        [
            vectors["deck"]["input"]["namespace"],
            vectors["deck"]["input"]["sourceTemplateId"],
            vectors["deck"]["input"]["sourceTemplateVersion"],
        ],
    )
    slide_id = _stable_id(
        "slide",
        [
            deck_id,
            vectors["slide"]["input"]["sourceTemplateId"],
            vectors["slide"]["input"]["semanticKey"],
        ],
    )
    object_id = _stable_id(
        "object",
        [slide_id, vectors["object"]["input"]["semanticKey"]],
    )
    actual_ids = {"deck": deck_id, "slide": slide_id, "object": object_id}
    expected_ids = {name: vectors[name]["expected"] for name in actual_ids}
    if actual_ids != expected_ids:
        raise ValueError("document-skills stable-ID vectors do not match the owner package")

    deck_without_hash = dict(fixtures["deckIr"])
    expected_hash = deck_without_hash.pop("contentHash")
    actual_hash = "sha256:" + hashlib.sha256(
        _canonical_json(deck_without_hash).encode("utf-8")
    ).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("document-skills Deck IR canonical content hash does not match")

    return {
        "consumer": "document-skills",
        "packageVersion": manifest["packageVersion"],
        "artifactCount": len(manifest["artifacts"]),
        "schemaVersions": {
            "deckIr": fixtures["deckIr"]["schemaVersion"],
            "semanticSlots": fixtures["semanticSlots"]["schemaVersion"],
            "templateContract": fixtures["templateContract"]["schemaVersion"],
        },
        "stableIds": actual_ids,
        "deckContentHash": actual_hash,
        "licenseStatus": fixtures["templateContract"]["licenseStatus"],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: presentation_contract_conformance.py <package-root>", file=sys.stderr)
        return 2
    print(json.dumps(check_contracts(Path(sys.argv[1])), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
