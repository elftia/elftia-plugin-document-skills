#!/usr/bin/env python3
"""Generate or verify deterministic phase B/C contract fixtures."""

from __future__ import annotations

import argparse
import filecmp
import json
from pathlib import Path
import sys
import tempfile

_PLUGIN_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_SRC = _PLUGIN_ROOT / "src"
for candidate in (_PLUGIN_ROOT, _PLUGIN_SRC):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from document_skills_core.formats.pptx.presentation_contracts import (  # noqa: E402
    PresentationContractConsumer,
)
from tests.support.pptx_ecosystem_fixture import (  # noqa: E402
    EcosystemFixtureWriter,
    FixtureMetadata,
)


_RELATIVE = "expected/contract-pin.json"
_MANIFEST_RELATIVE = _RELATIVE + ".manifest.json"


def generate(contract_root: Path, output_root: Path) -> dict[str, object]:
    summary = PresentationContractConsumer.open(contract_root).summary()
    metadata = FixtureMetadata(
        fixture_id="B0-CONTRACT-01",
        format="json",
        purpose="Pin the cross-producer presentation contract conformance result.",
        origin="Elftia-authored metadata derived from the owner package.",
        recipe=(
            "uv run --project plugin python "
            "plugin/tests/fixtures/pptx/ecosystem_bc/generate.py "
            "<presentation-contract-root> --write"
        ),
        license="GPL-3.0",
        expected_operation="presentation-contract.conformance",
        expected_consumers=("document-skills", "design-studio"),
        resource_limits={"maxBytes": 16384},
        invariants=(
            "owner package, version, schema versions, and manifest hash stay pinned",
            "stable IDs and Deck IR content hash match both producer consumers",
            "license status remains not_evaluated without Governance decision evidence",
        ),
        security_classification="benign-generated-metadata",
    )
    EcosystemFixtureWriter(output_root).write_json(_RELATIVE, summary, metadata)
    return summary


def _check(contract_root: Path, checked_root: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="pptx-ecosystem-fixtures-") as temporary:
        generated_root = Path(temporary)
        summary = generate(contract_root, generated_root)
        mismatches = [
            relative
            for relative in (_RELATIVE, _MANIFEST_RELATIVE)
            if not filecmp.cmp(
                generated_root / relative,
                checked_root / relative,
                shallow=False,
            )
        ]
        if mismatches:
            raise ValueError(
                "checked-in PPTX ecosystem fixtures drifted: " + ", ".join(mismatches)
            )
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    checked_root = Path(__file__).resolve().parent
    summary = (
        _check(arguments.contract_root, checked_root)
        if arguments.check
        else generate(arguments.contract_root, checked_root)
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
