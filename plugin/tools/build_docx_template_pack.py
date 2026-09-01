"""Deterministically generate the repository-owned academic DOCX template pack."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Any

from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.formats.docx.create import create_docx
from document_skills_core.formats.docx.document_spec import parse_document_spec
from document_skills_core.formats.docx.style_profiles import ACADEMIC_PACK
from document_skills_core.formats.docx.template_pack import canonical_json_bytes, member_record

PACK_ID = "general-academic-paper"
PACK_VERSION = "1.0.0"
CATALOG_RELATIVE = f"{PACK_ID}/{PACK_VERSION}"
ROLE_STYLES = {
    "abstract": "ElftiaAbstract",
    "affiliations": "ElftiaAffiliations",
    "authors": "ElftiaAuthors",
    "bibliography": "ElftiaBibliography",
    "bibliography_heading": "ElftiaHeading1",
    "caption": "ElftiaCaption",
    "citation": "ElftiaCitation",
    "equation": "ElftiaEquation",
    "figure": "ElftiaFigure",
    "heading.1": "ElftiaHeading1",
    "heading.2": "ElftiaHeading2",
    "heading.3": "ElftiaHeading3",
    "heading.4": "ElftiaHeading4",
    "heading.5": "ElftiaHeading5",
    "heading.6": "ElftiaHeading6",
    "keywords": "ElftiaKeywords",
    "paragraph": "ElftiaBody",
    "subtitle": "ElftiaSubtitle",
    "table": "ElftiaTable",
    "title": "ElftiaTitle",
}
_RULE = {"style": "single", "size_eighth_points": 8, "color": "000000"}
AUTHORING_FORMAT = {
    "version": "1.0",
    "role_formats": {
        "title": {"latin_font": "Times New Roman", "east_asia_font": "SimHei", "size_half_points": 48, "bold": True, "alignment": "center", "space_after_twips": 240},
        "heading.1": {"latin_font": "Times New Roman", "east_asia_font": "SimHei", "size_half_points": 32, "bold": True, "space_before_twips": 240, "space_after_twips": 120},
        "heading.2": {"latin_font": "Times New Roman", "east_asia_font": "SimHei", "size_half_points": 28, "bold": True, "space_before_twips": 240, "space_after_twips": 120},
        "paragraph": {"latin_font": "Times New Roman", "east_asia_font": "SimSun", "size_half_points": 22, "alignment": "both", "first_line_chars": 200, "space_after_twips": 120, "line_twips": 276},
        "caption": {"latin_font": "Times New Roman", "east_asia_font": "SimSun", "size_half_points": 18, "alignment": "center", "space_after_twips": 120},
        "bibliography": {"latin_font": "Times New Roman", "east_asia_font": "SimSun", "size_half_points": 20, "hanging_twips": 360, "left_twips": 360, "space_after_twips": 80},
    },
    "default_footer": {
        "paragraphs": [
            {
                "alignment": "center",
                "runs": [
                    {"field": "PAGE"},
                    {"text": " / "},
                    {"field": "NUMPAGES"},
                ],
            }
        ]
    },
    "table": {
        "width_twips": 9_360,
        "borders": {"top": _RULE, "header_bottom": _RULE, "bottom": _RULE},
    },
}


def build_pack(project_root: Path, output_root: Path) -> str:
    pack_root = output_root / CATALOG_RELATIVE
    pack_root.mkdir(parents=True, exist_ok=True)
    payload_path = pack_root / "template.docx"
    report = parse_document_spec(_recipe_document_spec())
    report["style_profile"] = ACADEMIC_PACK
    create_docx(payload_path, report)
    semantic_path = pack_root / "evidence" / "semantic.json"
    semantic_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "docx-template-pack-evidence/v1",
                "status": "pass",
                "document_spec_version": "1.0",
                "domain_profile": {"id": "academic-paper", "version": "1.0"},
                "role_styles": ROLE_STYLES,
                "validation": "deterministic-create-and-reopen",
            }
        )
    )
    preview_path = pack_root / "evidence" / "preview.json"
    preview_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "docx-template-pack-preview/v1",
                "status": "unavailable",
                "provider_context": {
                    "provider": "libreoffice",
                    "version": None,
                    "fonts": [],
                    "platform": "not-recorded",
                },
                "visual_comparison_succeeded": False,
                "reason": "No portable committed LibreOffice baseline was captured for the repository recipe.",
            }
        )
    )
    license_path = pack_root / "LICENSE.txt"
    license_path.write_text(
        "Elftia general-academic-paper template pack\n"
        "Copyright (C) 2026 Elftia contributors\n"
        "SPDX-License-Identifier: GPL-3.0-only\n"
        "This repository-owned generated pack is redistributable under GPL-3.0-only.\n",
        encoding="utf-8",
        newline="\n",
    )
    members = [
        member_record(
            license_path,
            "LICENSE.txt",
            "text/plain; charset=utf-8",
            "evidence",
        ).as_dict(),
        member_record(
            preview_path,
            "evidence/preview.json",
            "application/json",
            "preview",
        ).as_dict(),
        member_record(
            semantic_path,
            "evidence/semantic.json",
            "application/json",
            "evidence",
        ).as_dict(),
        member_record(
            payload_path,
            "template.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "payload",
        ).as_dict(),
    ]
    members.sort(key=lambda item: item["path"])
    payload = next(item for item in members if item["role"] == "payload")
    manifest: dict[str, Any] = {
        "schema_version": "docx-template-pack/v1",
        "id": PACK_ID,
        "version": PACK_VERSION,
        "display_name": "General Academic Paper",
        "description": "Language-neutral academic structure and reusable semantic Word styles for caller-authored content.",
        "payload": payload,
        "members": members,
        "capabilities": {
            "modes": ["document-spec"],
            "variables": [],
            "regions": [],
            "role_styles": ROLE_STYLES,
            "authoring_format": AUTHORING_FORMAT,
            "mode_compatibility": {
                "document-spec": {"status": "compatible", "reasons": []}
            },
        },
        "compatibility": {
            "document_spec_versions": ["1.0"],
            "domain_profiles": [{"id": "academic-paper", "version": "1.0"}],
            "template_engine_versions": [],
            "style_profile_versions": ["template-mapped/1.0"],
        },
        "language_policy": {
            "layout": "language-neutral",
            "content": "caller-owned",
            "translation": "none",
            "examples": ["en-US", "zh-CN"],
        },
        "provenance": {
            "source_kind": "repository",
            "original_filename": "template.docx",
            "source_sha256": payload["sha256"],
            "importer": {"id": "elftia-template-pack-recipe", "version": "1.0.0"},
            "imported_at": "2000-01-01T00:00:00Z",
            "recipe": "tools/build_docx_template_pack.py",
            "license": {
                "status": "reviewed",
                "identifier": "GPL-3.0-only",
                "evidence": "LICENSE.txt",
            },
            "redistributable": True,
        },
        "evidence": [
            {
                "kind": "preview",
                "path": "evidence/preview.json",
                "status": "unavailable",
                "provider_context": {
                    "provider": "libreoffice",
                    "version": None,
                    "fonts": [],
                },
            },
            {
                "kind": "semantic",
                "path": "evidence/semantic.json",
                "status": "pass",
                "provider_context": {
                    "provider": "document-skills-core",
                    "version": "1.0.0",
                },
            },
        ],
    }
    SchemaCatalog(project_root).validate("docx-template-pack", manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    (pack_root / "manifest.json").write_bytes(manifest_bytes)
    digest = sha256(manifest_bytes).hexdigest()
    (output_root / "catalog.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "docx-template-pack-catalog/v1",
                "packs": [
                    {
                        "id": PACK_ID,
                        "version": PACK_VERSION,
                        "path": CATALOG_RELATIVE,
                        "expected_manifest_sha256": digest,
                    }
                ],
            }
        )
    )
    return digest


def _recipe_document_spec() -> dict[str, Any]:
    return {
        "version": "1.0",
        "domain_profile": {
            "id": "academic-paper",
            "version": "1.0",
            "locale": "en-US",
            "citation_style": "author-year",
        },
        "style_profile": {"id": "professional-generic", "version": "1.0"},
        "metadata": {"title": "General Academic Paper Template"},
        "footer": AUTHORING_FORMAT["default_footer"],
        "nodes": [
            {"id": "title", "type": "title", "text": "General Academic Paper"},
            {"id": "authors", "type": "authors", "items": ["Elftia Contributor"]},
            {"id": "abstract", "type": "abstract", "text": "Repository-owned deterministic template-pack recipe."},
            {"id": "keywords", "type": "keywords", "items": ["DOCX", "template pack"]},
            {"id": "introduction", "type": "heading", "level": 1, "text": "Introduction"},
            {"id": "body", "type": "paragraph", "text": "Caller-authored content replaces this recipe fixture during instantiation."},
            {
                "id": "table",
                "type": "table",
                "rows": [["Metric", "Value"], ["Example", "1"]],
                "width_twips": AUTHORING_FORMAT["table"]["width_twips"],
                "borders": AUTHORING_FORMAT["table"]["borders"],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    target = args.output_root or (
        project_root / "skills" / "document-docx" / "assets" / "template-packs"
    )
    if args.check:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix="elftia-template-pack-") as temporary:
            generated = Path(temporary)
            build_pack(project_root, generated)
            expected = sorted(path.relative_to(generated) for path in generated.rglob("*") if path.is_file())
            actual = sorted(path.relative_to(target) for path in target.rglob("*") if path.is_file())
            if expected != actual or any((generated / path).read_bytes() != (target / path).read_bytes() for path in expected):
                raise SystemExit("Committed template pack differs from deterministic regeneration.")
        return 0
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    digest = build_pack(project_root, target)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
