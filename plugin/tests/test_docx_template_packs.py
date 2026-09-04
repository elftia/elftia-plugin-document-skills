"""Focused integrity, import, and instantiation coverage for DOCX template packs."""

from __future__ import annotations

from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import shutil

import pytest

import document_skills_core.formats.docx.template_import as template_import_module
import document_skills_core.formats.docx.template_pack as template_pack_module
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.io.paths import sha256_file
from document_skills_core.formats.docx.content_types import (
    WORD_DOCUMENT_MAIN_CONTENT_TYPE,
    WORD_TEMPLATE_MAIN_CONTENT_TYPE,
)
from document_skills_core.formats.docx.contracts import parse_docx_request
from document_skills_core.formats.docx.create import create_docx
from document_skills_core.formats.docx.package import OpcPackage, write_deterministic_zip
from document_skills_core.formats.docx.service import DocxService
from document_skills_core.formats.docx.template_pack import (
    canonical_json_bytes,
    resolve_pack_directory,
)
from document_skills_core.formats.pdf.create import create_pdf
from tools.build_docx_template_pack import ROLE_STYLES, build_pack


def _builtin_root(project_root: Path) -> Path:
    return project_root / "skills/document-docx/assets/template-packs"


def _builtin_pack(project_root: Path) -> Path:
    return _builtin_root(project_root) / "general-academic-paper/1.0.0"


def _catalog_digest(project_root: Path) -> str:
    catalog = json.loads((_builtin_root(project_root) / "catalog.json").read_text(encoding="utf-8"))
    return catalog["packs"][0]["expected_manifest_sha256"]


def _request(operation: str, **values: object) -> dict[str, object]:
    result: dict[str, object] = {"schema_version": "1.0", "operation": operation, "arguments": {}}
    result.update(values)
    return result


def _minimal_academic(locale: str = "en-US") -> dict[str, object]:
    return {
        "version": "1.0",
        "domain_profile": {"id": "academic-paper", "version": "1.0", "locale": locale},
        "header": "调用方页眉" if locale == "zh-CN" else "Caller header",
        "footer": "调用方页脚" if locale == "zh-CN" else "Caller footer",
        "nodes": [
            {"id": "title", "type": "title", "text": "调用方内容" if locale == "zh-CN" else "Caller Content"},
            {"id": "authors", "type": "authors", "items": ["Ada Lovelace"]},
            {"id": "abstract", "type": "abstract", "text": "不会翻译。" if locale == "zh-CN" else "No translation is performed."},
            {"id": "keywords", "type": "keywords", "items": ["DOCX", "styles"]},
            {"id": "heading", "type": "heading", "level": 1, "text": "引言" if locale == "zh-CN" else "Introduction"},
            {"id": "body", "type": "paragraph", "text": "正文保持原样。" if locale == "zh-CN" else "Body text remains unchanged."},
        ],
    }


def test_builtin_catalog_read_and_regeneration_are_deterministic(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = DocxService(project_root)
    listed = service.execute(
        "docx.template.pack.list",
        _request("docx.template.pack.list"),
    )
    assert listed["status"] == "success", listed
    assert listed["diagnostics"]["operation_result"]["ambient_scan"] is False
    assert [(item["id"], item["version"]) for item in listed["diagnostics"]["operation_result"]["packs"]] == [
        ("general-academic-paper", "1.0.0")
    ]
    read = service.execute(
        "docx.template.pack.read",
        _request(
            "docx.template.pack.read",
            arguments={
                "pack": {"kind": "builtin", "id": "general-academic-paper", "version": "1.0.0"}
            },
        ),
    )
    assert read["status"] == "success", read
    manifest = read["diagnostics"]["operation_result"]["pack"]
    assert manifest["manifest_sha256"] == _catalog_digest(project_root)
    assert manifest["language_policy"]["translation"] == "none"
    assert manifest["provenance"]["redistributable"] is True

    for module_name in (
        "document_skills_core.formats.docx.constants",
        "document_skills_core.formats.pptx.constants",
    ):
        importlib.reload(importlib.import_module(module_name))
    for module_name in (
        "document_skills_core.formats.pptx.constants",
        "document_skills_core.formats.xlsx.constants",
    ):
        assert "r14" not in importlib.import_module(module_name).NS

    regenerated = tmp_path / "packs"
    build_pack(project_root, regenerated)
    expected = sorted(path.relative_to(_builtin_root(project_root)) for path in _builtin_root(project_root).rglob("*") if path.is_file())
    actual = sorted(path.relative_to(regenerated) for path in regenerated.rglob("*") if path.is_file())
    assert actual == expected
    assert all((regenerated / path).read_bytes() == (_builtin_root(project_root) / path).read_bytes() for path in expected)


@pytest.mark.parametrize("mutation", ["undeclared", "payload-drift", "noncanonical", "escape"])
def test_local_pack_integrity_failures_are_closed(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    expected = _catalog_digest(project_root)
    if mutation == "undeclared":
        (pack / "rogue.txt").write_text("rogue", encoding="utf-8")
    elif mutation == "payload-drift":
        with (pack / "template.docx").open("ab") as handle:
            handle.write(b"drift")
    else:
        manifest_path = pack / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "escape":
            manifest["members"][0]["path"] = "../outside.txt"
            expected_bytes = canonical_json_bytes(manifest)
        else:
            expected_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        manifest_path.write_bytes(expected_bytes)
        expected = sha256(expected_bytes).hexdigest()
    with pytest.raises(DocumentSkillsError) as captured:
        resolve_pack_directory(
            pack,
            SchemaCatalog(project_root),
            expected_manifest_sha256=expected,
        )
    assert captured.value.code in {ErrorCode.PATH_UNSAFE, ErrorCode.VALIDATION_FAILED}


def test_local_pack_rejects_symlink_member_when_supported(
    project_root: Path,
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    link = pack / "linked.txt"
    try:
        link.symlink_to(pack / "LICENSE.txt")
    except OSError:
        pytest.skip("This Windows account cannot create symlinks.")
    with pytest.raises(DocumentSkillsError) as captured:
        resolve_pack_directory(
            pack,
            SchemaCatalog(project_root),
            expected_manifest_sha256=_catalog_digest(project_root),
        )
    assert captured.value.code == ErrorCode.PATH_UNSAFE


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("unsupported-schema", ErrorCode.VALIDATION_FAILED),
        ("missing-member", ErrorCode.VALIDATION_FAILED),
        ("case-collision", ErrorCode.PATH_UNSAFE),
    ],
)
def test_local_pack_rejects_schema_member_and_portable_collision_failures(
    project_root: Path,
    tmp_path: Path,
    mutation: str,
    expected_code: ErrorCode,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "unsupported-schema":
        manifest["schema_version"] = "docx-template-pack/v999"
    elif mutation == "missing-member":
        (pack / "LICENSE.txt").unlink()
    else:
        collision = dict(manifest["members"][0])
        collision["path"] = collision["path"].swapcase()
        manifest["members"].append(collision)
    if mutation != "missing-member":
        manifest_path.write_bytes(canonical_json_bytes(manifest))
    expected = sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(DocumentSkillsError) as captured:
        resolve_pack_directory(
            pack,
            SchemaCatalog(project_root),
            expected_manifest_sha256=expected,
        )
    assert captured.value.code == expected_code


def test_local_pack_detects_member_mutation_during_resolution(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    original = template_pack_module._read_stable_file
    mutated = False

    def mutate_after_read(path: Path, expected: tuple[int, int, int, int]) -> bytes:
        nonlocal mutated
        payload = original(path, expected)
        if not mutated and path.name != "manifest.json":
            mutated = True
            manifest_path = pack / "manifest.json"
            metadata = manifest_path.stat()
            os.utime(
                manifest_path,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
            )
        return payload

    monkeypatch.setattr(template_pack_module, "_read_stable_file", mutate_after_read)
    with pytest.raises(DocumentSkillsError) as captured:
        resolve_pack_directory(
            pack,
            SchemaCatalog(project_root),
            expected_manifest_sha256=_catalog_digest(project_root),
        )
    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert captured.value.details["reason"] == "mutation-race"


def test_pack_list_accepts_explicit_local_pack_and_rejects_unbounded_input(
    project_root: Path,
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    local = {
        "kind": "local",
        "path": str(pack),
        "expected_manifest_sha256": _catalog_digest(project_root),
    }
    listed = DocxService(project_root).execute(
        "docx.template.pack.list",
        _request("docx.template.pack.list", arguments={"local_packs": [local]}),
    )
    assert listed["status"] == "success", listed
    packs = listed["diagnostics"]["operation_result"]["packs"]
    assert len(packs) == 2
    assert packs[-1]["reference_kind"] == "local"

    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.template.pack.list",
                arguments={"local_packs": [local] * 33},
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID


def test_inspection_accepts_inert_dotx_and_rejects_active_fixture(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = DocxService(project_root)
    source = _builtin_pack(project_root) / "template.docx"
    package = OpcPackage.open(source)
    dotx = tmp_path / "reference.dotx"
    parts = dict(package.parts)
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        WORD_DOCUMENT_MAIN_CONTENT_TYPE.encode(),
        WORD_TEMPLATE_MAIN_CONTENT_TYPE.encode(),
    )
    write_deterministic_zip(dotx, parts)
    inspected = service.execute(
        "docx.template.import.inspect",
        _request(
            "docx.template.import.inspect",
            input=str(dotx),
            arguments={"expected_source_sha256": sha256_file(dotx)},
        ),
    )
    assert inspected["status"] == "success", inspected
    operation = inspected["diagnostics"]["operation_result"]
    assert operation["source"]["extension"] == ".dotx"
    assert operation["role_candidates"]
    assert all(item["approved"] is False for item in operation["role_candidates"])

    malicious = project_root / "tests/fixtures/docx-malicious-active.docx"
    rejected = service.execute(
        "docx.template.import.inspect",
        _request(
            "docx.template.import.inspect",
            input=str(malicious),
            arguments={"expected_source_sha256": sha256_file(malicious)},
        ),
    )
    assert rejected["status"] == "failed"
    assert rejected["errors"][0]["code"] == ErrorCode.ARCHIVE_UNSAFE.value


@pytest.mark.parametrize(
    "filename",
    [
        "docx-malicious-absolute.docx",
        "docx-malicious-active.docx",
        "docx-malicious-alias.docx",
        "docx-malicious-crc.docx",
        "docx-malicious-duplicate.docx",
        "docx-malicious-entity.docx",
        "docx-malicious-expansion.docx",
        "docx-malicious-path.docx",
        "docx-malicious-symlink.docx",
        "docx-malicious-xml-limit.docx",
    ],
)
def test_import_inspection_rejects_the_complete_malicious_fixture_matrix(
    project_root: Path,
    filename: str,
) -> None:
    source = project_root / "tests/fixtures" / filename
    result = DocxService(project_root).execute(
        "docx.template.import.inspect",
        _request(
            "docx.template.import.inspect",
            input=str(source),
            arguments={"expected_source_sha256": sha256_file(source)},
        ),
    )
    assert result["status"] == "failed", (filename, result)
    assert result["errors"][0]["code"] == ErrorCode.ARCHIVE_UNSAFE.value


def test_import_inspection_rejects_wrong_source_digest_without_mutation(
    project_root: Path,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    before = source.read_bytes()
    result = DocxService(project_root).execute(
        "docx.template.import.inspect",
        _request(
            "docx.template.import.inspect",
            input=str(source),
            arguments={"expected_source_sha256": "0" * 64},
        ),
    )
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.STALE_PRECONDITION.value
    assert source.read_bytes() == before


def test_import_is_canonical_private_and_reusable(
    project_root: Path,
    tmp_path: Path,
) -> None:
    service = DocxService(project_root)
    source = _builtin_pack(project_root) / "template.docx"
    before = source.read_bytes()
    destination = tmp_path / "private-pack"
    created = service.execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(destination),
            arguments={
                "expected_source_sha256": sha256_file(source),
                "manifest": {
                    "id": "private-academic",
                    "version": "1.0.0",
                    "display_name": "Private Academic",
                    "description": "A private local reference pack.",
                    "modes": ["document-spec"],
                    "role_styles": ROLE_STYLES,
                    "authoring_format": _builtin_authoring_format(source),
                    "compatibility": {
                        "document_spec_versions": ["1.0"],
                        "domain_profiles": [{"id": "academic-paper", "version": "1.0"}],
                        "template_engine_versions": [],
                        "style_profile_versions": ["template-mapped/1.0"],
                    },
                },
                "provenance": {
                    "source_kind": "local",
                    "imported_at": "2026-08-29T00:00:00Z",
                    "redistributable": False,
                },
            },
        ),
    )
    assert created["status"] == "success", created
    assert source.read_bytes() == before
    imported = created["diagnostics"]["operation_result"]["pack"]
    assert imported["provenance"]["license"] == {
        "status": "unknown", "identifier": None, "evidence": None
    }
    assert imported["provenance"]["redistributable"] is False
    assert (destination / "template.docx").read_bytes() == before
    assert (destination / "manifest.json").read_bytes() == canonical_json_bytes(
        json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    )

    local_reference = {
        "kind": "local",
        "path": str(destination),
        "expected_manifest_sha256": imported["manifest_sha256"],
    }
    read = service.execute(
        "docx.template.pack.read",
        _request("docx.template.pack.read", arguments={"pack": local_reference}),
    )
    assert read["status"] == "success", read
    output = tmp_path / "from-import.docx"
    instantiated = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(output),
            arguments={
                "pack": local_reference,
                "mode": "document-spec",
                "document_spec": _minimal_academic(),
            },
        ),
    )
    assert instantiated["status"] == "success", instantiated
    assert output.is_file()


def test_import_preserves_existing_destination_and_rejects_incomplete_network_metadata(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    destination = tmp_path / "existing-pack"
    destination.mkdir()
    sentinel = destination / "sentinel.txt"
    sentinel.write_bytes(b"existing destination must survive")
    result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(destination),
            arguments=_document_spec_import_arguments(source),
        ),
    )
    assert result["status"] != "success"
    assert sentinel.read_bytes() == b"existing destination must survive"
    assert not (destination / "manifest.json").exists()

    incomplete = _document_spec_import_arguments(source)
    incomplete["provenance"] = {
        "source_kind": "network",
        "imported_at": "2026-08-29T00:00:00Z",
        "license": {
            "status": "declared",
            "identifier": "CC-BY-4.0",
            "evidence": "https://example.invalid/license",
        },
        "redistributable": True,
        "network": {
            "original_url": "https://example.invalid/reference.docx",
            "retrieved_url": "https://cdn.example.invalid/reference.docx",
            "retrieved_at": "2026-08-29T00:00:00Z",
            "downloader": {"id": "trusted-downloader"},
            "downloaded_sha256": sha256_file(source),
        },
    }
    missing_output = tmp_path / "missing-network-pack"
    incomplete_result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(missing_output),
            arguments=incomplete,
        ),
    )
    assert incomplete_result["status"] == "invalid_request"
    assert incomplete_result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID.value
    assert not missing_output.exists()


def test_import_racing_destination_is_preserved_and_private_candidate_is_not_merged(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    destination = tmp_path / "racing-pack"
    original_publish = template_import_module.atomic_publish_directory
    sentinel = b"racing destination wins"

    def race_then_publish(candidate: Path, output: Path, **kwargs: object):
        output.mkdir()
        (output / "sentinel.txt").write_bytes(sentinel)
        return original_publish(candidate, output, **kwargs)

    monkeypatch.setattr(
        template_import_module,
        "atomic_publish_directory",
        race_then_publish,
    )
    result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(destination),
            arguments=_document_spec_import_arguments(source),
        ),
    )
    assert result["status"] != "success"
    assert (destination / "sentinel.txt").read_bytes() == sentinel
    assert sorted(path.name for path in destination.iterdir()) == ["sentinel.txt"]


def test_import_rejects_redirected_destination_parent_when_supported(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    redirected_parent = tmp_path / "redirected-parent"
    try:
        redirected_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create directory symlinks.")
    redirected_source = tmp_path / "redirected-source.docx"
    redirected_source.symlink_to(source)
    inspected = DocxService(project_root).execute(
        "docx.template.import.inspect",
        _request(
            "docx.template.import.inspect",
            input=str(redirected_source),
            arguments={"expected_source_sha256": sha256_file(source)},
        ),
    )
    assert inspected["status"] != "success"
    assert inspected["errors"][0]["code"] == ErrorCode.PATH_UNSAFE.value
    destination = redirected_parent / "blocked-pack"
    result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(destination),
            arguments=_document_spec_import_arguments(source),
        ),
    )
    assert result["status"] != "success"
    assert result["errors"][0]["code"] == ErrorCode.PATH_UNSAFE.value
    assert not (real_parent / "blocked-pack").exists()


def test_complete_network_provenance_is_recorded_without_fetching(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    arguments = _document_spec_import_arguments(source)
    arguments["provenance"] = {
        "source_kind": "network",
        "imported_at": "2026-08-29T00:00:00Z",
        "license": {
            "status": "declared",
            "identifier": "CC-BY-4.0",
            "evidence": "https://example.invalid/license",
        },
        "redistributable": True,
        "network": {
            "original_url": "https://example.invalid/reference.docx",
            "retrieved_url": "https://cdn.example.invalid/reference.docx",
            "retrieved_at": "2026-08-29T00:00:00Z",
            "downloader": {"id": "trusted-downloader", "version": "1.0"},
            "downloaded_sha256": sha256_file(source),
        },
    }
    output = tmp_path / "network-pack"
    result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(output),
            arguments=arguments,
        ),
    )
    assert result["status"] == "success", result
    provenance = result["diagnostics"]["operation_result"]["provenance"]
    assert provenance["source_kind"] == "network"
    assert provenance["network"]["downloaded_sha256"] == sha256_file(source)
    assert provenance["redistributable"] is True


def test_imported_template_mode_reuses_existing_scalar_backend(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "scalar-reference.docx"
    create_docx(
        source,
        {
            "blocks": [{"type": "paragraph", "text": "Hello {name}", "style": "Normal"}],
            "image": None,
            "header": None,
            "footer": None,
            "sections": [{"orientation": "portrait", "title": None}],
            "metadata": {"title": "Scalar reference", "subject": "", "creator": "", "keywords": ""},
            "style_profile": None,
        },
    )
    service = DocxService(project_root)
    pack_root = tmp_path / "scalar-pack"
    imported = service.execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(pack_root),
            arguments={
                "expected_source_sha256": sha256_file(source),
                "manifest": {
                    "id": "scalar-reference",
                    "version": "1.0.0",
                    "display_name": "Scalar Reference",
                    "description": "A template-mode reference.",
                    "modes": ["template"],
                    "variables": [{"name": "name", "required": True}],
                    "regions": [],
                    "role_styles": {},
                    "compatibility": {
                        "document_spec_versions": [],
                        "domain_profiles": [],
                        "template_engine_versions": ["1.0"],
                        "style_profile_versions": [],
                    },
                },
                "provenance": {
                    "source_kind": "local",
                    "imported_at": "2026-08-29T00:00:00Z",
                    "redistributable": False,
                },
            },
        ),
    )
    assert imported["status"] == "success", imported
    output = tmp_path / "scalar-output.docx"
    instantiated = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(output),
            arguments={
                "pack": {
                    "kind": "local",
                    "path": str(pack_root),
                    "expected_manifest_sha256": imported["diagnostics"]["operation_result"]["manifest_sha256"],
                },
                "mode": "template",
                "variables": {"name": "Agent"},
            },
        ),
    )
    assert instantiated["status"] == "success", instantiated
    assert b"Hello Agent" in OpcPackage.open(output).parts["word/document.xml"]


@pytest.mark.parametrize("locale", ["en-US", "zh-CN"])
def test_academic_pack_preserves_caller_language_and_mapping(
    project_root: Path,
    tmp_path: Path,
    locale: str,
) -> None:
    output = tmp_path / f"academic-{locale}.docx"
    service = DocxService(project_root)
    result = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(output),
            arguments={
                "pack": {"kind": "builtin", "id": "general-academic-paper", "version": "1.0.0"},
                "mode": "document-spec",
                "document_spec": _minimal_academic(locale),
                "verification": "enhanced",
            },
        ),
    )
    assert result["status"] == "success", result
    package = OpcPackage.open(output)
    document_text = package.parts["word/document.xml"].decode("utf-8")
    expected = "正文保持原样。" if locale == "zh-CN" else "Body text remains unchanged."
    assert expected in document_text
    assert result["diagnostics"]["operation_result"]["creation"]["styles"]["profile"]["id"] == "template-mapped"
    evidence = result["diagnostics"]["operation_result"]["rendered_evidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["visual_comparison_succeeded"] is False


def test_enhanced_instantiation_records_provider_available_render_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    provider_pdf = tmp_path / "provider.pdf"
    create_pdf(
        provider_pdf,
        {
            "metadata": {"title": "Pack evidence", "author": "", "subject": ""},
            "page_size": "Letter",
            "pages": [{"blocks": []}],
        },
    )

    class ControlledLibreOffice:
        def convert_pdf(self, input_path: Path, max_output_bytes: int) -> bytes:
            assert input_path.suffix.casefold() == ".docx"
            assert max_output_bytes == 8 * 1024 * 1024
            return provider_pdf.read_bytes()

    output = tmp_path / "enhanced.docx"
    result = DocxService(
        project_root,
        libreoffice=ControlledLibreOffice(),
    ).execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(output),
            arguments={
                "pack": {
                    "kind": "builtin",
                    "id": "general-academic-paper",
                    "version": "1.0.0",
                },
                "mode": "document-spec",
                "document_spec": _minimal_academic(),
                "verification": "enhanced",
            },
        ),
    )
    assert result["status"] == "success", result
    evidence = result["diagnostics"]["operation_result"]["rendered_evidence"]
    assert evidence["status"] == "pass"
    assert evidence["render"]["pages"] == 1
    assert evidence["layout"]["status"] == "unavailable"
    assert evidence["visual_comparison_succeeded"] is False
    assert evidence["provider_context"] == {
        "provider": "libreoffice",
        "version": None,
        "fonts": [],
    }
    warning_codes = {warning["code"] for warning in result["warnings"]}
    assert "DS_DOCX_TEMPLATE_VISUAL_BASELINE_UNAVAILABLE" in warning_codes
    visual_gate = next(
        gate for gate in result["validation"]["gates"] if gate["id"] == "visual.render"
    )
    assert visual_gate["outcome"] == "pass"


def test_pack_instantiation_rejects_style_override_and_unknown_version(
    project_root: Path,
    tmp_path: Path,
) -> None:
    spec = _minimal_academic()
    spec["style_profile"] = {"id": "professional-generic", "version": "1.0"}
    with pytest.raises(DocumentSkillsError) as captured:
        parse_docx_request(
            _request(
                "docx.template.pack.instantiate",
                output=str(tmp_path / "blocked.docx"),
                arguments={
                    "pack": {"kind": "builtin", "id": "general-academic-paper", "version": "1.0.0"},
                    "mode": "document-spec",
                    "document_spec": spec,
                },
            )
        )
    assert captured.value.code == ErrorCode.REQUEST_INVALID

    result = DocxService(project_root).execute(
        "docx.template.pack.read",
        _request(
            "docx.template.pack.read",
            arguments={"pack": {"kind": "builtin", "id": "general-academic-paper", "version": "9.9.9"}},
        ),
    )
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.INPUT_NOT_FOUND.value


def test_pack_instantiation_rejects_mode_profile_and_mapping_gaps_without_overwrite(
    project_root: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "existing.docx"
    sentinel = b"destination must survive rejected pack instantiation"
    destination.write_bytes(sentinel)
    service = DocxService(project_root)
    unsupported = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(destination),
            arguments={
                "pack": {
                    "kind": "builtin",
                    "id": "general-academic-paper",
                    "version": "1.0.0",
                },
                "mode": "template",
                "variables": {},
            },
        ),
    )
    assert unsupported["status"] == "failed"
    assert destination.read_bytes() == sentinel

    incompatible = _minimal_academic()
    incompatible["domain_profile"] = {
        "id": "technical-report",
        "version": "1.0",
        "locale": "en-US",
    }
    incompatible_result = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(destination),
            arguments={
                "pack": {
                    "kind": "builtin",
                    "id": "general-academic-paper",
                    "version": "1.0.0",
                },
                "mode": "document-spec",
                "document_spec": incompatible,
            },
        ),
    )
    assert incompatible_result["status"] == "failed"
    assert destination.read_bytes() == sentinel

    pack = tmp_path / "mapping-gap-pack"
    shutil.copytree(_builtin_pack(project_root), pack)
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["capabilities"]["role_styles"]["paragraph"]
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    local = {
        "kind": "local",
        "path": str(pack),
        "expected_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
    }
    gap_result = service.execute(
        "docx.template.pack.instantiate",
        _request(
            "docx.template.pack.instantiate",
            output=str(destination),
            arguments={
                "pack": local,
                "mode": "document-spec",
                "document_spec": _minimal_academic(),
            },
        ),
    )
    assert gap_result["status"] == "invalid_request"
    assert gap_result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID.value
    assert destination.read_bytes() == sentinel


def test_network_import_metadata_requires_matching_download_digest(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = _builtin_pack(project_root) / "template.docx"
    output = tmp_path / "network-pack"
    result = DocxService(project_root).execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(output),
            arguments={
                "expected_source_sha256": sha256_file(source),
                "manifest": {
                    "id": "network-reference",
                    "version": "1.0.0",
                    "display_name": "Network Reference",
                    "description": "Previously downloaded reference.",
                    "modes": ["document-spec"],
                    "role_styles": ROLE_STYLES,
                    "authoring_format": _builtin_authoring_format(source),
                    "compatibility": {
                        "document_spec_versions": ["1.0"],
                        "domain_profiles": [{"id": "academic-paper", "version": "1.0"}],
                        "template_engine_versions": [],
                        "style_profile_versions": ["template-mapped/1.0"],
                    },
                },
                "provenance": {
                    "source_kind": "network",
                    "imported_at": "2026-08-29T00:00:00Z",
                    "license": {"status": "declared", "identifier": "CC-BY-4.0", "evidence": "https://example.invalid/license"},
                    "redistributable": True,
                    "network": {
                        "original_url": "https://example.invalid/reference.docx",
                        "retrieved_url": "https://cdn.example.invalid/reference.docx",
                        "retrieved_at": "2026-08-29T00:00:00Z",
                        "downloader": {"id": "trusted-downloader", "version": "1.0"},
                        "downloaded_sha256": "0" * 64,
                    },
                },
            },
        ),
    )
    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == ErrorCode.STALE_PRECONDITION.value
    assert not output.exists()


def test_template_pack_rejects_missing_and_undeclared_controls_before_authoring(
    project_root: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "scalar-reference.docx"
    create_docx(
        source,
        {
            "blocks": [{"type": "paragraph", "text": "Hello {name}", "style": "Normal"}],
            "image": None,
            "header": None,
            "footer": None,
            "sections": [{"orientation": "portrait", "title": None}],
            "metadata": {
                "title": "Scalar reference",
                "subject": "",
                "creator": "",
                "keywords": "",
            },
            "style_profile": None,
        },
    )
    service = DocxService(project_root)
    pack_root = tmp_path / "scalar-pack"
    arguments = {
        "expected_source_sha256": sha256_file(source),
        "manifest": {
            "id": "scalar-controls",
            "version": "1.0.0",
            "display_name": "Scalar Controls",
            "description": "Control validation pack.",
            "modes": ["template"],
            "variables": [{"name": "name", "required": True}],
            "regions": [],
            "role_styles": {},
            "compatibility": {
                "document_spec_versions": [],
                "domain_profiles": [],
                "template_engine_versions": ["1.0"],
                "style_profile_versions": [],
            },
        },
        "provenance": {
            "source_kind": "local",
            "imported_at": "2026-08-29T00:00:00Z",
            "redistributable": False,
        },
    }
    imported = service.execute(
        "docx.template.import.create",
        _request(
            "docx.template.import.create",
            input=str(source),
            output=str(pack_root),
            arguments=arguments,
        ),
    )
    assert imported["status"] == "success", imported
    local = {
        "kind": "local",
        "path": str(pack_root),
        "expected_manifest_sha256": imported["diagnostics"]["operation_result"][
            "manifest_sha256"
        ],
    }
    for label, variables in (
        ("missing", {}),
        ("undeclared", {"name": "Agent", "extra": "blocked"}),
    ):
        output = tmp_path / f"{label}.docx"
        result = service.execute(
            "docx.template.pack.instantiate",
            _request(
                "docx.template.pack.instantiate",
                output=str(output),
                arguments={"pack": local, "mode": "template", "variables": variables},
            ),
        )
        assert result["status"] == "failed", result
        assert result["errors"][0]["details"]["diagnostic"] == (
            "DS_DOCX_TEMPLATE_CONTROL_MISMATCH"
        )
        assert not output.exists()


def _document_spec_import_arguments(source: Path) -> dict[str, object]:
    return {
        "expected_source_sha256": sha256_file(source),
        "manifest": {
            "id": "private-academic",
            "version": "1.0.0",
            "display_name": "Private Academic",
            "description": "A private local reference pack.",
            "modes": ["document-spec"],
            "role_styles": ROLE_STYLES,
            "authoring_format": _builtin_authoring_format(source),
            "compatibility": {
                "document_spec_versions": ["1.0"],
                "domain_profiles": [{"id": "academic-paper", "version": "1.0"}],
                "template_engine_versions": [],
                "style_profile_versions": ["template-mapped/1.0"],
            },
        },
        "provenance": {
            "source_kind": "local",
            "imported_at": "2026-08-29T00:00:00Z",
            "redistributable": False,
        },
    }


def _builtin_authoring_format(source: Path) -> dict[str, object]:
    manifest = json.loads((source.parent / "manifest.json").read_text(encoding="utf-8"))
    return manifest["capabilities"]["authoring_format"]
