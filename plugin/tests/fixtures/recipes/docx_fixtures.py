"""Generate deterministic original Elftia DOCX acceptance fixtures.

Run through the frozen project Python:
`uv run --project . --frozen python tests/fixtures/recipes/docx_fixtures.py
--output tests/fixtures`
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
RECIPE_ROOT = Path(__file__).resolve().parent
for import_root in (PROJECT_ROOT, SOURCE_ROOT, RECIPE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tests.support.public_cli import PUBLIC_CLI_TEST_TIMEOUT_SECONDS  # noqa: E402

from document_skills_core.core.io import DangerousContentPolicy, inspect_ooxml
from document_skills_core.formats.docx.create import create_docx
from document_skills_core.formats.docx.inspect import inspect_docx
from document_skills_core.formats.docx.package import OpcPackage
from document_skills_core.formats.docx.projection import feature_counts
from document_skills_core.formats.docx.read import read_docx

from docx_fixture_security import builders
from docx_fixture_support import (
    PNG_1X1,
    copy_with_additions,
    enrich_rich,
    legacy_prefixed_relationship_fixture,
    nested_revision_fixture,
    report_model,
    revision_fixture,
)

RECIPE = "tests/fixtures/recipes/docx_fixtures.py"
RECIPE_DEPENDENCIES = [
    "tests/fixtures/recipes/docx_fixture_security.py",
    "tests/fixtures/recipes/docx_fixture_support.py",
]
_READ_ARGUMENTS = {
    "include_headers_footers": True,
    "max_paragraphs": 5_000,
    "max_tables": 500,
    "max_table_rows": 5_000,
    "max_text_chars": 250_000,
}
_INSPECT_ARGUMENTS = {
    "include_hashes": True,
    "max_parts": 2_000,
    "max_relationships": 5_000,
}


def generate(output: Path) -> list[dict[str, object]]:
    """Generate all DOCX fixtures and return their complete manifest records."""

    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="elftia-docx-fixture-") as temporary:
        image = Path(temporary) / "pixel.png"
        image.write_bytes(PNG_1X1)
        rich = output / "docx-rich.docx"
        create_docx(rich, report_model(image))
        enrich_rich(rich)
    records.append(_record(rich, "Rich read/create/template/replace fixture", "benign"))

    rejected = output / "docx-rich-word16-rejected.docx"
    legacy_prefixed_relationship_fixture(rich, rejected)
    records.append(
        _record(
            rejected,
            "Explicit Word 16 rejection regression preserving the legacy relationship bytes",
            "consumer-negative",
        )
    )

    public_bounded = output / "docx-public-bounded-word16-accepted.docx"
    public_bounded.unlink(missing_ok=True)
    _create_public_bounded_fixture(public_bounded)
    records.append(
        _record(
            public_bounded,
            "Bounded public frozen-uv DOCX accepted by Word 16",
            "consumer-positive",
        )
    )

    preservation = output / "docx-preservation.docx"
    copy_with_additions(
        rich,
        preservation,
        {
            "customXml/item1.xml": (
                b'<?xml version="1.0"?><elftia>preserve-me</elftia>'
            ),
            "elftia/unknown-safe.bin": b"ELFTIA-UNKNOWN-SAFE-PAYLOAD\n",
            "word/media/unrelated2.png": PNG_1X1,
        },
    )
    records.append(
        _record(
            preservation,
            "Copy-through fixture with custom XML, unknown safe data, and unrelated media",
            "benign-preservation",
        )
    )

    revision = output / "docx-revision-comments.docx"
    revision_fixture(rich, revision)
    records.append(
        _record(
            revision,
            "Field, revision, deleted text, and comment mutation boundary fixture",
            "protected-content",
        )
    )
    nested_revision = output / "docx-revisions-nested.docx"
    nested_revision_fixture(revision, nested_revision)
    records.append(
        _record(
            nested_revision,
            "Nested-table tracked-revision scope and filtering fixture",
            "protected-content",
        )
    )

    for name, builder in builders().items():
        path = output / name
        _call_builder(builder, rich, path)
        records.append(
            _record(
                path,
                (
                    "Bounded security-negative fixture: "
                    f"{name.removeprefix('docx-malicious-').removesuffix('.docx')}"
                ),
                "malicious",
            )
        )

    records.extend(_write_oracles(output, rich, preservation, revision))
    return records


def _write_oracles(
    output: Path,
    rich: Path,
    preservation: Path,
    revision: Path,
) -> list[dict[str, object]]:
    structured, _read_warnings = read_docx(rich, _READ_ARGUMENTS)
    inspection, _inspection_warnings = inspect_docx(rich, _INSPECT_ARGUMENTS)
    rich_oracle = output / "docx-rich.expected.json"
    _write_json(rich_oracle, {"read": structured, "inspection": inspection})

    package = OpcPackage.open(preservation)
    preservation_oracle = output / "docx-preservation.expected.json"
    _write_json(
        preservation_oracle,
        {
            "part_hashes": package.part_hashes,
            "unknown_parts": package.unknown_parts,
        },
    )

    cases = output / "docx-cases.expected.json"
    _write_json(cases, _case_matrix(output, revision))
    return [
        _record(
            rich_oracle,
            "Complete rich DOCX structured-read and inspection oracle",
            "oracle",
        ),
        _record(
            preservation_oracle,
            "Per-part copy-through preservation hash oracle",
            "oracle",
        ),
        _record(
            cases,
            "Fixture behavior, mutation, and security-classification oracle matrix",
            "oracle",
        ),
    ]


def _case_matrix(output: Path, revision: Path) -> dict[str, object]:
    active = inspect_ooxml(
        output / "docx-malicious-active.docx",
        dangerous_policy=DangerousContentPolicy.PRESERVE_DISABLED,
    )
    return {
        "schema_version": "1.0",
        "rich": {
            "template": {
                "tokens": ["customer.name", "normal", "region"],
                "split_run_token": "customer.name",
                "missing_case": ["region"],
                "unused_case": ["unused"],
                "formatting_anchor": "first-affected-run",
            },
            "replacement": {
                "search": "TARGET",
                "expected_matches": 4,
                "counts_by_story": {
                    "body:word/document.xml": [2],
                    "footer:word/footer1.xml": [1],
                    "header:word/header1.xml": [1],
                },
                "overlap_source": "AAAA",
                "overlap_rules": ["AAA", "AA"],
                "formatting_anchor": "first-affected-run",
            },
        },
        "preservation": {
            "required_untouched_parts": [
                "customXml/item1.xml",
                "elftia/unknown-safe.bin",
                "word/media/unrelated2.png",
            ],
            "expected_unknown_parts": ["elftia/unknown-safe.bin"],
        },
        "protected": {
            "features": feature_counts(OpcPackage.open(revision)),
            "template_tokens": [
                "protected.comment",
                "protected.deleted",
                "protected.field",
                "protected.revision",
            ],
            "replacement_text": [
                "comment-only",
                "deleted-only",
                "field-only",
                "revision-only",
            ],
            "expected_status": "enhancement_required",
            "recommended_provider": "dotnet-openxml",
        },
        "security": {
            "container_reject": {
                "docx-malicious-absolute.docx": "archive-preflight",
                "docx-malicious-path.docx": "archive-preflight",
                "docx-malicious-alias.docx": "opc-index",
                "docx-malicious-duplicate.docx": "opc-index",
                "docx-malicious-entity.docx": "archive-preflight",
                "docx-malicious-xml-limit.docx": "archive-preflight",
                "docx-malicious-expansion.docx": "archive-preflight",
                "docx-malicious-symlink.docx": "archive-preflight",
                "docx-malicious-crc.docx": "archive-preflight",
            },
            "inert_inventory": {
                "fixture": "docx-malicious-active.docx",
                "expected_positive_categories": [
                    category
                    for category, count in active["security"]["counts"].items()
                    if count > 0
                ],
                "mutation_authorized": False,
            },
        },
    }


def _call_builder(
    builder: object,
    source: Path,
    destination: Path,
) -> None:
    if not callable(builder):
        raise TypeError("DOCX fixture builder must be callable")
    typed_builder: Callable[[Path, Path], None] = builder
    typed_builder(source, destination)


def _create_public_bounded_fixture(destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="elftia-public-docx-fixture-") as temporary:
        request_path = Path(temporary) / "request.json"
        _write_json(
            request_path,
            {
                "schema_version": "1.0",
                "operation": "docx.create",
                "output": str(destination),
                "arguments": {
                    "report": {
                        "metadata": {
                            "title": "Bounded public DOCX",
                            "creator": "Elftia",
                        },
                        "blocks": [
                            {
                                "type": "heading",
                                "text": "Bounded public DOCX",
                                "level": 1,
                            },
                            {
                                "type": "paragraph",
                                "text": "Public frozen-uv consumer qualification fixture.",
                            },
                            {
                                "type": "table",
                                "rows": [["Gate", "Expected"], ["Word", "Accepted"]],
                            },
                        ],
                    }
                },
            },
        )
        environment = os.environ.copy()
        environment.pop("UV_PROJECT_ENVIRONMENT", None)
        environment.pop("VIRTUAL_ENV", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(PROJECT_ROOT),
                "--frozen",
                "python",
                str(PROJECT_ROOT / "skills/document-docx/scripts/run.py"),
                "run",
                "--request",
                str(request_path),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=False,
            shell=False,
            timeout=PUBLIC_CLI_TEST_TIMEOUT_SECONDS,
        )
        if process.returncode != 0 or process.stderr:
            raise RuntimeError(
                "Public DOCX fixture creation failed: "
                + process.stderr[:4096].decode("utf-8", errors="replace")
            )
        result = json.loads(process.stdout.decode("utf-8", errors="strict"))
        if result.get("status") != "success" or not destination.is_file():
            raise RuntimeError("Public DOCX fixture creation did not publish a success artifact.")


def _record(path: Path, purpose: str, classification: str) -> dict[str, object]:
    return {
        "path": path.name,
        "format": path.suffix.lstrip("."),
        "purpose": purpose,
        "origin": "generated",
        "authorship": "original-elftia",
        "recipe": RECIPE,
        "recipe_dependencies": RECIPE_DEPENDENCIES,
        "license": "GPL-3.0",
        "redistribution_allowed": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "security_classification": classification,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_retained_records(output: Path) -> list[dict[str, Any]]:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        record
        for record in manifest.get("fixtures", [])
        if type(record) is dict and not str(record.get("path", "")).startswith("docx-")
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    retained = _load_retained_records(output)
    records = generate(output)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": "1.0",
            "fixtures": [*retained, *records],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
