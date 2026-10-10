"""LibreOffice enhancement provider tests — mock-injected present/absent/crash/timeout.

Real LibreOffice is not required for the suite. A conditional Windows test
uses a standard installation when present; other tests inject system boundaries.

Module provenance: original Elftia-authored clean-room implementation.
"""

import os
import stat
import struct
import sys
import zipfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
import tools.ci_docx_optional_evidence as optional_evidence
from tools.ci_docx_optional_requests import OPERATION_PROVIDERS

from document_skills_core.core.capabilities import (
    DetectionEvidence,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.temp_roots import OperationTempRoot
from document_skills_core.core.process import (
    ProcessPolicy,
    ProcessResult,
    ProcessRunner,
)
from document_skills_core.formats.pdf.constants import MAX_PDF_BYTES
from document_skills_core.formats.pdf.validation import reopen_pdf
from document_skills_core.formats.xlsx.constants import (
    FORMULA_STATE_RECALCULATED,
    MAX_XLSX_BYTES,
)
from document_skills_core.formats.xlsx.mapping import map_workbook
from document_skills_core.formats.xlsx.package import OpcPackage
from document_skills_core.formats.xlsx.service import XlsxService
from document_skills_core.providers import build_default_registry
from document_skills_core.providers.libreoffice import build_libreoffice_provider
from document_skills_core.providers.libreoffice.constants import (
    ACCEPTED_SUBCOMMANDS,
    FORBIDDEN_TOKENS,
    HEADLESS_PREFIX,
    USER_INSTALLATION_PREFIX,
    platform_known_paths,
)
from document_skills_core.providers.libreoffice.convert import convert_to_pdf
from document_skills_core.providers.libreoffice.detector import LibreOfficeDetector
from document_skills_core.providers.libreoffice.quota import (
    HardQuotaCapability,
    capture_directory_identity,
    validate_final_quota_tree,
)
from document_skills_core.providers.libreoffice.recalc import (
    recalculate_xlsx,
    recalculate_xlsx_artifact,
)
from document_skills_core.providers.libreoffice.runner import (
    LibreOfficeRunner,
    _build_argv,
    _forbidden_operation_token,
    _validate_argv,
)
from tools.audit_python import audit_python_source

# ---------------------------------------------------------------------------
# Fake detectors
# ---------------------------------------------------------------------------

class FakeCallableDetector:
    """A detector that always reports LibreOffice as callable."""

    def __init__(self, version="25.8.0", path="/fake/soffice"):
        self._version = version
        self._path = path

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(
            available=True, version=self._version, path=self._path
        )


class FakeAbsentDetector:
    """A detector that always reports LibreOffice as unavailable."""

    def __init__(self, reason="no soffice candidate found"):
        self._reason = reason

    def detect(self) -> DetectionEvidence:
        return DetectionEvidence(available=False, reason=self._reason)


# ---------------------------------------------------------------------------
# Fake runners
# ---------------------------------------------------------------------------

class FakeCallableRunner:
    """A runner that writes a canned output file on convert()."""

    def __init__(self, canned_data: bytes | None = None, canned_path: Path | None = None):
        if canned_path is not None and canned_data is None:
            canned_data = Path(canned_path).read_bytes()
        self._canned_data = canned_data or b"fake-output"
        self._canned_path = canned_path
        self.calls: list[dict] = []

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        self.calls.append({
            "input": str(input_path),
            "format": target_format,
            "output_dir": str(output_dir),
            "timeout": timeout_seconds,
        })
        output = output_dir / (Path(input_path).stem + "." + target_format)
        output.write_bytes(self._canned_data)
        return output
        return output


class FakeCrashingRunner:
    """A runner that raises PROVIDER_FAILED on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Fake crash during LibreOffice conversion.",
        )


class FakeHangingRunner:
    """A runner that raises PROCESS_TIMEOUT on every convert()."""

    def set_executable(self, exe):
        pass

    def convert(self, input_path, target_format, output_dir, *, timeout_seconds=None):
        raise DocumentSkillsError(
            ErrorCode.PROCESS_TIMEOUT,
            "LibreOffice exceeded its time budget.",
        )


class _TestHardQuotaSession:
    def __init__(self, root: Path, byte_limit: int, entry_limit: int) -> None:
        self.root = root
        self.output_dir = root / "output"
        self.profile_dir = root / "profile"
        self.output_dir.mkdir(mode=0o700)
        self.profile_dir.mkdir(mode=0o700)
        self.root_identity = capture_directory_identity(root)
        self.output_identity = capture_directory_identity(self.output_dir)
        self.byte_limit = byte_limit
        self.entry_limit = entry_limit

    def validate_final_tree(self, *, expected_name):
        return validate_final_quota_tree(
            root=self.root,
            root_identity=self.root_identity,
            output_dir=self.output_dir,
            output_identity=self.output_identity,
            expected_name=expected_name,
            byte_limit=self.byte_limit,
            entry_limit=self.entry_limit,
        )


class _TestHardQuotaBackend:
    def capability(self):
        return HardQuotaCapability(
            backend_id="test-enforced-tree",
            platform="test",
            reason_category="available",
            reason="Test-only bounded tree.",
            aggregate_byte_limit=True,
            entry_count_limit=True,
            private_namespace=True,
            fail_closed_activation=True,
        )

    @contextmanager
    def open(self, *, byte_limit, entry_limit=4096):
        with OperationTempRoot() as root:
            yield _TestHardQuotaSession(root, byte_limit, entry_limit)


class _RecordingTestHardQuotaBackend(_TestHardQuotaBackend):
    """Test-only backend that records both required quota activations and cleanup."""

    def __init__(self):
        self.byte_limits: list[int] = []
        self.roots: list[Path] = []

    @contextmanager
    def open(self, *, byte_limit, entry_limit=4096):
        self.byte_limits.append(byte_limit)
        with super().open(
            byte_limit=byte_limit,
            entry_limit=entry_limit,
        ) as session:
            self.roots.append(session.root)
            yield session


def _standard_windows_soffice() -> Path | None:
    return next(
        (
            candidate
            for candidate in (
                Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
                Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
            )
            if candidate.is_file()
        ),
        None,
    )


def _create_live_xls_fixture(
    project_root: Path,
    executable: Path,
    source_xlsx: Path,
    destination: Path,
) -> None:
    """Use real LibreOffice only to prepare a benign private-profile XLS fixture."""

    with OperationTempRoot() as fixture_root:
        profile_dir = fixture_root / "profile"
        output_dir = fixture_root / "output"
        profile_dir.mkdir()
        output_dir.mkdir()
        policy = ProcessPolicy(project_root)
        allowed = policy.allow_executable("libreoffice-live-fixture", executable)
        result = ProcessRunner(policy).run(
            "libreoffice-live-fixture",
            allowed,
            _build_argv(
                profile_dir,
                "--convert-to",
                "xls:MS Excel 97",
                "--outdir",
                str(output_dir),
                str(source_xlsx.resolve(strict=True)),
            ),
            cwd=project_root,
            timeout_seconds=30.0,
            output_limit=1_048_576,
        )
        assert result.returncode == 0, result.stderr
        generated = output_dir / f"{source_xlsx.stem}.xls"
        payload = generated.read_bytes()
        assert payload.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    assert not fixture_root.exists()
    destination.write_bytes(payload)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_xlsx(project_root: Path, tmp_path: Path) -> Path:
    """Create a real XLSX with formula cells (with cached values) for testing."""
    from document_skills_core.core.io.temp_roots import OperationTempRoot
    from document_skills_core.formats.xlsx.create import create_xlsx
    workbook = {
        "metadata": {},
        "sheets": [{
            "name": "Sheet1",
            "rows": [
                {"cells": [
                    {"ref": "A1", "value": "10", "type": "n"},
                    {"ref": "A2", "value": "20", "type": "n"},
                    {"ref": "A3", "formula": "SUM(A1:A2)", "cached_value": "30", "type": "n"},
                ]},
            ],
            "number_formats": [],
        }],
        "defined_names": [],
        "tables": [],
    }
    output = tmp_path / "test_input.xlsx"
    with OperationTempRoot() as private_root:
        staged = private_root / "created.xlsx"
        create_xlsx(staged, workbook)
        output.write_bytes(staged.read_bytes())
    return output


def _minimal_docx_bytes() -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>""",
        )
    return payload.getvalue()


def _minimal_pptx_bytes() -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "ppt/presentation.xml",
            """<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>""",
        )
    return payload.getvalue()


def _legacy_compound_bytes(format_id: str) -> bytes:
    marker = {
        "doc": "WordDocument",
        "xls": "Workbook",
        "ppt": "PowerPoint Document",
    }[format_id]
    free_sector = 0xFFFFFFFF
    end_of_chain = 0xFFFFFFFE
    fat_sector = 0xFFFFFFFD
    header = bytearray(512)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHH", header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 0, 0, 4096, free_sector, 0, free_sector, 0)
    struct.pack_into("<109I", header, 76, 1, *([free_sector] * 108))

    directory = bytearray(512)
    _write_cfb_directory_entry(directory, 0, "Root Entry", 5, child=1)
    _write_cfb_directory_entry(directory, 128, marker, 2)

    fat = bytearray(b"\xff" * 512)
    struct.pack_into("<II", fat, 0, end_of_chain, fat_sector)
    return bytes(header + directory + fat)


def _write_cfb_directory_entry(
    directory: bytearray,
    offset: int,
    name: str,
    object_type: int,
    *,
    child: int = 0xFFFFFFFF,
) -> None:
    encoded_name = name.encode("utf-16le") + b"\x00\x00"
    directory[offset : offset + len(encoded_name)] = encoded_name
    struct.pack_into("<HBBIII", directory, offset + 64, len(encoded_name), object_type, 1, 0xFFFFFFFF, 0xFFFFFFFF, child)
    struct.pack_into("<I", directory, offset + 116, 0xFFFFFFFE)


def _active_xlsx(path: Path) -> Path:
    from document_skills_core.formats.xlsx.create import create_xlsx

    create_xlsx(
        path,
        {
            "metadata": {},
            "sheets": [{
                "name": "Sheet1",
                "rows": [{"cells": [{
                    "ref": "A1",
                    "formula": 'WEBSERVICE("https://example.invalid")',
                    "cached_value": "",
                    "type": "str",
                }]}],
                "number_formats": [],
            }],
            "defined_names": [],
            "tables": [],
        },
    )
    return path


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

def _quota_unavailable_ci_reports():
    providers = [
        {"id": "dotnet-openxml", "available": True, "reason": None},
        {"id": "libreoffice", "available": False,
         "reason": "LibreOffice hard quota unavailable (hard_quota_backend_unavailable)"},
    ]
    operations = [
        {"operation": operation, "available": provider == "dotnet-openxml",
         "providers": [provider]}
        for operation, provider in OPERATION_PROVIDERS.items()
    ]
    return {"providers": providers}, {"providers": providers, "operations": operations}


def test_optional_ci_records_exact_quota_unavailability_and_requires_dotnet():
    doctor, capabilities = _quota_unavailable_ci_reports()
    with pytest.raises(AssertionError):
        optional_evidence._assert_optional_profile(doctor, capabilities)


@pytest.mark.parametrize("broken", ["dotnet-unavailable", "other-libreoffice-failure", "false-libreoffice-availability"])
def test_optional_ci_rejects_failures_outside_the_exact_quota_boundary(broken):
    doctor, capabilities = _quota_unavailable_ci_reports()
    if broken == "dotnet-unavailable":
        doctor["providers"][0]["available"] = False
    elif broken == "other-libreoffice-failure":
        doctor["providers"][1]["reason"] = "native launch failed"
    else:
        next(item for item in capabilities["operations"]
             if item["operation"] == "docx.render")["available"] = True
    with pytest.raises(AssertionError):
        optional_evidence._assert_optional_profile(doctor, capabilities)


@pytest.mark.skipif(os.name == "nt", reason="POSIX native LibreOffice companion")
def test_detector_selects_native_posix_companion(tmp_path):
    wrapper = tmp_path / "soffice"
    wrapper.write_bytes(b"#!/bin/sh\nexit 0\n")
    companion = tmp_path / "soffice.bin"
    companion.write_bytes(Path(sys.executable).read_bytes())

    assert LibreOfficeDetector._native_candidate(str(wrapper)) == str(companion)


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper without native companion")
def test_detector_without_native_companion_keeps_original_candidate(tmp_path):
    wrapper = tmp_path / "soffice"
    wrapper.write_bytes(b"#!/bin/sh\nexit 0\n")

    assert LibreOfficeDetector._native_candidate(str(wrapper)) == str(wrapper)


class TestConstants:
    def test_headless_prefix_contains_required_flags(self):
        assert "--headless" in HEADLESS_PREFIX
        assert "--norestore" in HEADLESS_PREFIX
        assert "--nofirststartwizard" in HEADLESS_PREFIX
        assert "--nolockcheck" not in HEADLESS_PREFIX

    def test_accepted_subcommands_excludes_cmd(self):
        assert "--cmd" not in ACCEPTED_SUBCOMMANDS
        assert "--convert-to" in ACCEPTED_SUBCOMMANDS

    def test_forbidden_tokens_include_macro_and_dde(self):
        assert "--cmd" in FORBIDDEN_TOKENS
        assert ".bas" in FORBIDDEN_TOKENS
        assert ".xba" in FORBIDDEN_TOKENS

    def test_platform_known_paths_returns_list(self):
        paths = platform_known_paths()
        assert isinstance(paths, list)
        assert len(paths) >= 1


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------


class _SupportedHardQuotaBackend:
    def capability(self) -> HardQuotaCapability:
        return HardQuotaCapability(
            backend_id="test-hard-quota",
            platform="test",
            reason_category="supported",
            reason="test backend supplies the complete hard-quota contract",
            aggregate_byte_limit=True,
            entry_count_limit=True,
            private_namespace=True,
            fail_closed_activation=True,
        )

    def open(self, **kwargs):
        raise AssertionError("detector tests must not activate the quota backend")


_SUPPORTED_HARD_QUOTA_BACKEND = _SupportedHardQuotaBackend()


class TestDetector:
    def test_detector_fails_closed_without_hard_quota_backend(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"callable-but-uncontained")

        class MustNotProbeRunner:
            def run(self, *args, **kwargs):
                raise AssertionError("version probe must wait for hard-quota support")

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        from document_skills_core.providers.libreoffice.quota import _UnsupportedHardQuotaBackend

        detector = LibreOfficeDetector(project_root, runner=MustNotProbeRunner(),
                                      quota_backend=_UnsupportedHardQuotaBackend())

        evidence = detector.detect()

        assert evidence.available is False
        assert "hard" in (evidence.reason or "").lower()
        assert "quota" in (evidence.reason or "").lower()

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows standard-install launcher integration",
    )
    def test_default_registry_reports_missing_winfsp_before_probe(
        self, project_root, monkeypatch
    ):
        monkeypatch.delenv("DOCUMENT_SKILLS_PROVIDER_PROFILE", raising=False)
        from document_skills_core.providers.libreoffice import quota_windows
        monkeypatch.setattr(quota_windows, "library_path", lambda: None)
        installed = _standard_windows_soffice()
        if installed is None:
            pytest.skip("LibreOffice is not installed in a standard Windows location")
        monkeypatch.setattr(shutil_module(), "which", lambda _name: None)

        registry = build_default_registry(project_root)
        provider = registry.providers[str(ProviderId.LIBREOFFICE)]
        state = registry.detect(provider)

        assert state["available"] is False, state
        assert state["path"] is None
        assert "hard quota" in state["reason"].lower()
        assert registry.find_callable(ProviderId.LIBREOFFICE) is False

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows standard-install LibreOffice recalculation integration",
    )
    @pytest.mark.slow
    def test_real_libreoffice_recalculation_mechanism_updates_stale_xlsx_cache(
        self,
        project_root,
        tmp_path,
    ):
        from document_skills_core.formats.xlsx.create import create_xlsx

        installed = _standard_windows_soffice()
        if installed is None:
            pytest.skip("LibreOffice is not installed in a standard Windows location")
        source = tmp_path / "stale-cache.xlsx"
        create_xlsx(
            source,
            {
                "metadata": {},
                "sheets": [
                    {
                        "name": "Inputs",
                        "rows": [
                            {
                                "cells": [
                                    {"ref": "A1", "value": "2", "type": "n"},
                                    {"ref": "A2", "value": "3", "type": "n"},
                                    {
                                        "ref": "A3",
                                        "formula": "SUM(A1:A2)",
                                        "cached_value": "999",
                                        "type": "n",
                                    },
                                    {
                                        "ref": "A4",
                                        "formula": "A3*4",
                                        "cached_value": "888",
                                        "type": "n",
                                    },
                                ]
                            }
                        ],
                        "number_formats": [],
                    },
                    {
                        "name": "Summary",
                        "rows": [
                            {
                                "cells": [
                                    {
                                        "ref": "A1",
                                        "formula": "Inputs!A4+1",
                                        "cached_value": "777",
                                        "type": "n",
                                    }
                                ]
                            }
                        ],
                        "number_formats": [],
                    },
                ],
                "defined_names": [],
                "tables": [],
            },
        )
        source_before = source.read_bytes()
        quota_backend = _RecordingTestHardQuotaBackend()
        runner = LibreOfficeRunner(
            project_root,
            executable=installed,
            runner=ProcessRunner(ProcessPolicy(project_root)),
            quota_backend=quota_backend,
        )

        recalculated = recalculate_xlsx_artifact(
            source,
            runner,
            timeout_seconds=30.0,
        )

        assert source.read_bytes() == source_before
        assert quota_backend.byte_limits == [MAX_XLSX_BYTES, MAX_XLSX_BYTES]
        assert all(not root.exists() for root in quota_backend.roots)
        assert {
            ref: record["formula"]
            for ref, record in recalculated.formulas.items()
        } == {
            "Inputs!A3": "SUM(A1:A2)",
            "Inputs!A4": "A3*4",
            "Summary!A1": "Inputs!A4+1",
        }
        assert recalculated.cached_values == {
            "Inputs!A3": "5",
            "Inputs!A4": "20",
            "Summary!A1": "21",
        }
        assert not any(
            str(value).startswith("#")
            for value in recalculated.cached_values.values()
        )

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows standard-install LibreOffice XLSX render integration",
    )
    @pytest.mark.slow
    def test_real_libreoffice_xlsx_render_provider_operation_reopens_pdf(
        self,
        project_root,
        tmp_path,
        monkeypatch,
    ):
        from document_skills_core.formats.xlsx.create import create_xlsx

        installed = _standard_windows_soffice()
        if installed is None:
            pytest.skip("LibreOffice is not installed in a standard Windows location")
        source = tmp_path / "render-source.xlsx"
        output = tmp_path / "rendered.pdf"
        create_xlsx(
            source,
            {
                "metadata": {},
                "sheets": [
                    {
                        "name": "Report",
                        "rows": [
                            {
                                "cells": [
                                    {"ref": "A1", "value": "Metric", "type": "s"},
                                    {"ref": "B1", "value": "Value", "type": "s"},
                                ]
                            },
                            {
                                "cells": [
                                    {"ref": "A2", "value": "Total", "type": "s"},
                                    {"ref": "B2", "value": "42", "type": "n"},
                                ]
                            },
                        ],
                        "number_formats": [],
                    }
                ],
                "defined_names": [],
                "tables": [],
            },
        )
        source_before = source.read_bytes()
        monkeypatch.setattr(shutil_module(), "which", lambda _name: None)
        quota_backend = _RecordingTestHardQuotaBackend()
        definition, _provider = build_libreoffice_provider(
            project_root,
            quota_backend=quota_backend,
        )
        registry = ProviderCatalog()
        registry.register_provider(definition)

        result = registry.execute(
            {
                "schema_version": "1.0",
                "operation": "xlsx.render",
                "input": str(source),
                "output": str(output),
                "arguments": {"max_sheets": 5, "max_cells_per_sheet": 50},
            }
        )

        assert result["status"] == "success", result
        assert result["provider_chain"] == ["libreoffice"]
        assert reopen_pdf(output)["pages"] >= 1
        assert source.read_bytes() == source_before
        gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
        assert gates["visual.render"]["outcome"] == "pass"
        assert gates["provider.reopen"]["outcome"] == "pass"
        assert quota_backend.byte_limits == [MAX_PDF_BYTES]
        assert all(not root.exists() for root in quota_backend.roots)

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Windows standard-install LibreOffice legacy XLS integration",
    )
    @pytest.mark.slow
    def test_real_libreoffice_legacy_xls_conversion_mechanism(
        self,
        project_root,
        tmp_path,
        monkeypatch,
    ):
        from document_skills_core.formats.xlsx.create import create_xlsx

        installed = _standard_windows_soffice()
        if installed is None:
            pytest.skip("LibreOffice is not installed in a standard Windows location")
        fixture_source = tmp_path / "legacy-fixture-source.xlsx"
        create_xlsx(
            fixture_source,
            {
                "metadata": {},
                "sheets": [
                    {
                        "name": "Legacy",
                        "rows": [
                            {
                                "cells": [
                                    {
                                        "ref": "A1",
                                        "value": "Legacy fixture",
                                        "type": "s",
                                    },
                                    {"ref": "B1", "value": "42", "type": "n"},
                                ]
                            }
                        ],
                        "number_formats": [],
                    }
                ],
                "defined_names": [],
                "tables": [],
            },
        )
        fixture_source_before = fixture_source.read_bytes()
        source = tmp_path / "legacy-input.xls"
        _create_live_xls_fixture(
            project_root,
            installed,
            fixture_source,
            source,
        )
        source_before = source.read_bytes()
        output = tmp_path / "legacy-converted.xlsx"
        monkeypatch.setattr(shutil_module(), "which", lambda _name: None)
        quota_backend = _RecordingTestHardQuotaBackend()
        _definition, provider = build_libreoffice_provider(
            project_root,
            quota_backend=quota_backend,
        )

        result = XlsxService(project_root, libreoffice=provider).execute(
            "xlsx.convert",
            {
                "schema_version": "1.0",
                "operation": "xlsx.convert",
                "input": str(source),
                "output": str(output),
                "arguments": {"source_format": "xls", "target_format": "xlsx"},
            },
        )

        assert result["status"] == "degraded", result
        assert result["provider_chain"] == ["libreoffice"]
        gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
        assert gates["conversion.legacy-provider"]["outcome"] == "pass"
        losses = result["diagnostics"]["operation_result"]["semantic_losses"]
        assert [loss["code"] for loss in losses] == ["legacy-provider-conversion"]
        assert fixture_source.read_bytes() == fixture_source_before
        assert source.read_bytes() == source_before
        workbook = map_workbook(OpcPackage.open(output))
        values = {
            cell["ref"]: cell.get("value")
            for row in workbook["sheets"][0]["rows"]
            for cell in row["cells"]
        }
        assert values == {"A1": "Legacy fixture", "B1": "42"}
        assert quota_backend.byte_limits == [MAX_XLSX_BYTES]
        assert all(not root.exists() for root in quota_backend.roots)

    def test_production_factory_shares_libreoffice_allowlist_policy(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice.exe"
        executable.write_bytes(b"placeholder")

        class ProbeRunner:
            def run(self, provider_id, executable_path, args, **kwargs):
                assert provider_id == ProviderId.LIBREOFFICE.value
                assert Path(executable_path) == executable.absolute()
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        monkeypatch.setattr(
            shutil_module(),
            "which",
            lambda name: str(executable) if name == "soffice" else None,
        )
        definition, provider = build_libreoffice_provider(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        provider.detector._runner = ProbeRunner()

        evidence = definition.detect()
        assert evidence.available is True
        assert provider.detector._policy is provider.runner._policy
        provider.runner.set_executable(evidence.path)
        assert provider.runner._runner._check_executable(
            ProviderId.LIBREOFFICE.value,
            executable,
        ) == executable.absolute()

    def test_callable_version_probe_parses_version(
        self, project_root, tmp_path, monkeypatch
    ):
        """Callable soffice --version → available with parsed version."""
        executable = tmp_path / "soffice"
        executable.write_bytes(b"callable-libreoffice")
        detector = LibreOfficeDetector(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        class FakeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, provider_id, executable, args, **kwargs):
                self.calls += 1
                assert "--version" in args
                assert kwargs["timeout_seconds"] <= 2.0
                return ProcessResult(
                    0, "LibreOffice 25.8.0.0 1234567890", "", 100
                )

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        fake_runner = FakeRunner()
        detector._runner = fake_runner
        evidence = detector.detect()
        cached = detector.detect()
        assert evidence.available is True
        assert evidence.version == "25.8.0.0"
        assert evidence.path is not None
        assert cached is evidence
        assert fake_runner.calls == 1

    def test_cached_candidate_reprobes_after_same_path_replacement(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"benign-launcher")

        class ReplacingProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ProcessResult(0, "LibreOffice 25.8.0", "", 1)
                return ProcessResult(1, "", "replacement rejected", 1)

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        probe_runner = ReplacingProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        initial = detector.detect()
        executable.write_bytes(b"unprobed-replacement-launcher")
        replaced = detector.detect()

        assert initial.available is True
        assert replaced.available is False
        assert "exited" in (replaced.reason or "")
        assert probe_runner.calls == 2

    def test_positive_cache_reprobes_after_ttl(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"stable-launcher")
        now = [100.0]

        class CountingProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        probe_runner = CountingProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
            cache_ttl_seconds=10.0,
            clock=lambda: now[0],
        )

        initial = detector.detect()
        now[0] = 109.0
        cached = detector.detect()
        now[0] = 110.0
        refreshed = detector.detect()

        assert cached is initial
        assert refreshed is not initial
        assert refreshed.available is True
        assert probe_runner.calls == 2

    def test_negative_detection_observes_later_install(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        installed = [False]

        class ProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        monkeypatch.setattr(
            shutil_module(),
            "which",
            lambda _name: str(executable) if installed[0] else None,
        )
        monkeypatch.setattr(
            "document_skills_core.providers.libreoffice.detector.platform_known_paths",
            lambda: [],
        )
        probe_runner = ProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        absent = detector.detect()
        executable.write_bytes(b"new-install")
        installed[0] = True
        available = detector.detect()

        assert absent.available is False
        assert available.available is True
        assert probe_runner.calls == 1

    def test_concurrent_detection_runs_one_effective_probe(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"stable-concurrent-launcher")
        probe_started = Event()
        release_probe = Event()

        class BlockingProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                probe_started.set()
                assert release_probe.wait(2.0)
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        probe_runner = BlockingProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(detector.detect) for _ in range(8)]
            assert probe_started.wait(2.0)
            release_probe.set()
            evidence = [future.result(timeout=2.0) for future in futures]

        assert all(item.available for item in evidence)
        assert all(item is evidence[0] for item in evidence)
        assert probe_runner.calls == 1

    def test_symlink_retarget_reprobes_candidate(
        self, project_root, tmp_path, monkeypatch
    ):
        first_target = tmp_path / "soffice-first"
        second_target = tmp_path / "soffice-second"
        candidate = tmp_path / "soffice"
        first_target.write_bytes(b"first-launcher")
        second_target.write_bytes(b"second-launcher")
        try:
            candidate.symlink_to(first_target)
        except OSError as error:
            pytest.skip(f"symlink creation is unavailable: {type(error).__name__}")

        class RetargetProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ProcessResult(0, "LibreOffice 25.8.0", "", 1)
                return ProcessResult(1, "", "retarget rejected", 1)

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(candidate))
        probe_runner = RetargetProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        initial = detector.detect()
        candidate.unlink()
        candidate.symlink_to(second_target)
        retargeted = detector.detect()

        assert initial.available is True
        assert retargeted.available is False
        assert probe_runner.calls == 2

    def test_operation_binding_rejects_replacement_before_conversion(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"probed-launcher")

        class ProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        class ReplacingOperationRunner:
            def __init__(self):
                self.set_calls = 0
                self.convert_calls = 0

            def set_executable(self, _executable):
                self.set_calls += 1
                executable.write_bytes(b"replacement-during-operation-binding")

            def convert(self, *args, **kwargs):
                self.convert_calls += 1
                raise AssertionError("unprobed replacement must not execute")

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        probe_runner = ProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        operation_runner = ReplacingOperationRunner()
        _, provider = build_libreoffice_provider(
            project_root,
            detector=detector,
            runner=operation_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        initial = detector.detect()
        result = provider.execute(
            "libreoffice.convert-pdf",
            {"input": str(tmp_path / "input.docx"), "options": {}},
        )

        assert initial.available is True
        assert result["status"] == "failed"
        assert operation_runner.set_calls == 1
        assert operation_runner.convert_calls == 0
        assert probe_runner.calls == 1

    def test_transient_probe_failure_is_not_permanently_cached(
        self, project_root, tmp_path, monkeypatch
    ):
        executable = tmp_path / "soffice"
        executable.write_bytes(b"transient-launcher")

        class RecoveringProbeRunner:
            def __init__(self):
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ProcessResult(1, "", "transient failure", 1)
                return ProcessResult(0, "LibreOffice 25.8.0", "", 1)

        monkeypatch.setattr(shutil_module(), "which", lambda _name: str(executable))
        probe_runner = RecoveringProbeRunner()
        detector = LibreOfficeDetector(
            project_root,
            runner=probe_runner,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )

        failed = detector.detect()
        recovered = detector.detect()

        assert failed.available is False
        assert recovered.available is True
        assert probe_runner.calls == 2

    def test_executable_absent_returns_unavailable(self, project_root, monkeypatch):
        import shutil as sh
        monkeypatch.setattr(sh, "which", lambda name: None)
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        detector = LibreOfficeDetector(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        evidence = detector.detect()
        assert evidence.available is False
        assert evidence.reason is not None
        assert "candidate" in evidence.reason.lower()

    def test_nonzero_exit_returns_unavailable(
        self, project_root, tmp_path, monkeypatch
    ):
        import shutil as sh
        executable = tmp_path / "soffice"
        executable.write_bytes(b"nonzero-launcher")
        monkeypatch.setattr(sh, "which", lambda _name: str(executable))

        class FakeRunner:
            def run(self, *a, **kw):
                return ProcessResult(1, "", "error", 50)

        detector = LibreOfficeDetector(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "exited" in evidence.reason

    def test_unparseable_version_returns_unavailable(
        self, project_root, tmp_path, monkeypatch
    ):
        import shutil as sh
        executable = tmp_path / "soffice"
        executable.write_bytes(b"unparseable-launcher")
        monkeypatch.setattr(sh, "which", lambda _name: str(executable))

        class FakeRunner:
            def run(self, *a, **kw):
                return ProcessResult(0, "Weird Office 1.0", "", 50)

        detector = LibreOfficeDetector(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "unparseable" in evidence.reason

    def test_timeout_returns_unavailable(
        self, project_root, tmp_path, monkeypatch
    ):
        import shutil as sh
        executable = tmp_path / "soffice"
        executable.write_bytes(b"timeout-launcher")
        monkeypatch.setattr(sh, "which", lambda _name: str(executable))

        class FakeRunner:
            def run(self, *a, **kw):
                raise DocumentSkillsError(
                    ErrorCode.PROCESS_TIMEOUT, "probe timed out"
                )

        detector = LibreOfficeDetector(
            project_root,
            quota_backend=_SUPPORTED_HARD_QUOTA_BACKEND,
        )
        detector._runner = FakeRunner()
        evidence = detector.detect()
        assert evidence.available is False
        assert "timeout" in evidence.reason.lower()


def shutil_module():
    import shutil
    return shutil


# ---------------------------------------------------------------------------
# Runner containment tests
# ---------------------------------------------------------------------------

class TestRunnerContainment:
    def test_runner_fails_before_launch_without_hard_quota_backend(
        self, project_root, tmp_path
    ):
        calls = 0

        class MustNotRun:
            def run(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                raise AssertionError("LibreOffice must not launch without hard quota")

        executable = tmp_path / "soffice.exe"
        executable.write_bytes(b"placeholder")
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"input")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        from document_skills_core.providers.libreoffice.quota import _UnsupportedHardQuotaBackend

        runner = LibreOfficeRunner(
            project_root,
            executable=executable,
            runner=MustNotRun(),
            quota_backend=_UnsupportedHardQuotaBackend(),
        )

        with pytest.raises(DocumentSkillsError) as failure:
            runner.convert(
                input_file,
                "pdf",
                output_dir,
                timeout_seconds=30.0,
            )

        assert failure.value.code == ErrorCode.PROVIDER_UNAVAILABLE
        assert calls == 0
        assert list(output_dir.iterdir()) == []

    def test_libreoffice_runtime_sources_pass_execution_boundary_audit(
        self, project_root
    ):
        for relative in (
            "src/document_skills_core/providers/libreoffice/detector.py",
            "src/document_skills_core/providers/libreoffice/runner.py",
        ):
            audit_python_source(
                relative,
                (project_root / relative).read_text(encoding="utf-8"),
            )

    @pytest.mark.parametrize(
        "component",
        [LibreOfficeDetector, LibreOfficeRunner],
    )
    def test_injected_process_runner_supplies_libreoffice_policy(
        self, project_root, component
    ):
        policy = ProcessPolicy(project_root)
        process_runner = ProcessRunner(policy)

        instance = component(project_root, runner=process_runner)

        assert instance._policy is policy

    @pytest.mark.parametrize(
        "component",
        [LibreOfficeDetector, LibreOfficeRunner],
    )
    def test_injected_process_runner_rejects_mismatched_libreoffice_policy(
        self, project_root, component
    ):
        process_runner = ProcessRunner(ProcessPolicy(project_root))

        with pytest.raises(ValueError, match="injected ProcessPolicy"):
            component(
                project_root,
                runner=process_runner,
                policy=ProcessPolicy(project_root),
            )

    def test_argv_is_validated_before_spawn(self):
        """Macro-execution arguments are rejected before spawning."""
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv(
                [
                    *HEADLESS_PREFIX,
                    f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                    "--cmd",
                    "macro:///Standard.Module1.Recalc",
                ]
            )
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_bas_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                "file.bas",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_xba_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                "file.xba",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_dde_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                "DDE:link",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_ddelink_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                "DDELINK:link",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_macro_uri_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                "macro:///Standard.Module1.Recalc",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_unaccept_token_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--unaccept",
                "socket,host=127.0.0.1;urp;StarOffice.ComponentContext",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_path_values_with_forbidden_words_are_accepted(self):
        safe_path = (
            "C:/workspace/operation-b26eddec36f4dea8a057800cd04380e/"
            "macro-dde-ddelink/test.xlsx"
        )
        _validate_argv([
            *HEADLESS_PREFIX,
            f"{USER_INSTALLATION_PREFIX}file:///private/profile",
            "--convert-to",
            "xlsx",
            "--outdir",
            safe_path,
            safe_path,
        ])

    @pytest.mark.parametrize("token", sorted(FORBIDDEN_TOKENS))
    def test_every_forbidden_token_is_rejected_as_bare_argument(self, token):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--convert-to",
                token,
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED
        assert exc.value.details == {"token": token}

    def test_unknown_forbidden_token_shape_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            "document_skills_core.providers.libreoffice.runner.FORBIDDEN_TOKENS",
            frozenset({"--cmd", "newshape"}),
        )
        assert _forbidden_operation_token("file-newshape-1.xlsx") == "newshape"
        assert _forbidden_operation_token("--cmd=x") == "--cmd"
        assert _forbidden_operation_token("file-cmd-1.xlsx") is None

    def test_no_accepted_subcommand_rejected(self):
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                f"{USER_INSTALLATION_PREFIX}file:///private/profile",
                "--unknown-flag",
                "file.xlsx",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_valid_convert_to_argv_accepted(self, tmp_path):
        profile_root = tmp_path / "profile with spaces #1"
        profile_root.mkdir()
        argv = _build_argv(
            profile_root,
            "--convert-to", "xlsx", "--outdir", "/tmp", "input.xlsx"
        )
        assert "--headless" in argv
        assert "--convert-to" in argv
        profile_arg = argv[len(HEADLESS_PREFIX)]
        assert profile_arg == (
            f"{USER_INSTALLATION_PREFIX}{profile_root.resolve().as_uri()}"
        )
        assert "%20" in profile_arg
        assert "%23" in profile_arg

    def test_profile_must_precede_accepted_subcommand(self):
        profile_arg = f"{USER_INSTALLATION_PREFIX}file:///private/profile"
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                "--convert-to",
                profile_arg,
                "xlsx",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_duplicate_profile_arguments_are_rejected(self):
        profile_arg = f"{USER_INSTALLATION_PREFIX}file:///private/profile"
        with pytest.raises(DocumentSkillsError) as exc:
            _validate_argv([
                *HEADLESS_PREFIX,
                profile_arg,
                profile_arg,
                "--convert-to",
                "xlsx",
            ])
        assert exc.value.code == ErrorCode.PROVIDER_FAILED

    def test_runner_uses_unique_private_live_profile_per_call(
        self, project_root, tmp_path
    ):
        profile_paths: list[Path] = []
        profile_args: list[str] = []

        class FakeProcessRunner:
            def run(self, provider_id, executable, args, **kwargs):
                profile_arg = args[len(HEADLESS_PREFIX)]
                assert profile_arg.startswith(USER_INSTALLATION_PREFIX)
                profile_uri = profile_arg[len(USER_INSTALLATION_PREFIX):]
                parsed = urlsplit(profile_uri)
                assert parsed.scheme == "file"
                assert parsed.netloc == ""
                profile_path = Path(url2pathname(parsed.path)).resolve()
                assert profile_path.is_dir()
                assert profile_path.parent.is_dir()
                if os.name != "nt":
                    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o700
                    assert stat.S_IMODE(profile_path.parent.stat().st_mode) == 0o700
                assert args[len(HEADLESS_PREFIX) + 1] == "--convert-to"
                profile_paths.append(profile_path)
                profile_args.append(profile_arg)

                target_format = args[args.index("--convert-to") + 1]
                output_dir = Path(args[args.index("--outdir") + 1])
                input_path = Path(args[-1])
                (output_dir / f"{input_path.stem}.{target_format}").write_bytes(
                    b"converted"
                )
                return ProcessResult(0, "", "", 10)

        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        executable = tmp_path / "soffice.exe"
        executable.write_bytes(b"placeholder")
        runner = LibreOfficeRunner(
            project_root,
            executable=executable,
            runner=FakeProcessRunner(),
            quota_backend=_TestHardQuotaBackend(),
        )

        runner.convert(input_file, "pdf", output_dir, timeout_seconds=30.0)
        runner.convert(input_file, "pdf", output_dir, timeout_seconds=30.0)

        assert profile_args[0] != profile_args[1]
        assert profile_paths[0] != profile_paths[1]
        assert all(not profile.exists() for profile in profile_paths)

    def test_runner_convert_uses_project_root_cwd(
        self, project_root, tmp_path, monkeypatch
    ):
        """The runner passes cwd=project_root to the ProcessRunner."""
        captured = {}

        class FakeProcessRunner:
            def run(self, provider_id, executable, args, **kwargs):
                captured["cwd"] = kwargs.get("cwd")
                captured["shell"] = False
                captured["args"] = args
                captured["timeout"] = kwargs.get("timeout_seconds")
                captured["output_limit"] = kwargs.get("output_limit")
                target_format = args[args.index("--convert-to") + 1]
                child_output_dir = Path(args[args.index("--outdir") + 1])
                child_input = Path(args[-1])
                (child_output_dir / f"{child_input.stem}.{target_format}").write_bytes(
                    b"converted"
                )
                return ProcessResult(0, "", "", 10)

        executable = tmp_path / "soffice.exe"
        executable.write_bytes(b"placeholder")
        runner = LibreOfficeRunner(
            project_root,
            executable=executable,
            runner=FakeProcessRunner(),
            quota_backend=_TestHardQuotaBackend(),
        )
        import tempfile
        outdir = Path(tempfile.gettempdir()) / "test_lo_out"
        outdir.mkdir(exist_ok=True)
        input_file = outdir / "test.xlsx"
        input_file.write_bytes(b"fake")
        runner.convert(input_file, "xlsx", outdir, timeout_seconds=17.0)
        assert captured["cwd"] == project_root.resolve()
        assert captured["shell"] is False
        assert isinstance(captured["args"], list)
        profiles = [
            value for value in captured["args"]
            if value.startswith("-env:UserInstallation=file:")
        ]
        assert len(profiles) == 1
        assert 0 < captured["timeout"] <= 17.0
        assert captured["output_limit"] > 0

    @pytest.mark.parametrize(
        "write_expected_output",
        [True, False],
        ids=["expected-artifact", "temporary-artifact"],
    )
    def test_conversion_stops_progressive_output_at_artifact_limit(
        self, project_root, tmp_path, monkeypatch, write_expected_output
    ):
        from document_skills_core.providers.libreoffice import output as output_module

        artifact_limit = 16 * 1024
        monkeypatch.setitem(output_module.OUTPUT_LIMITS, "pdf", artifact_limit)
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        expected_output = output_dir / "input.pdf"
        progressive_output = (
            expected_output
            if write_expected_output
            else output_dir / "libreoffice-partial.tmp"
        )
        completion_marker = tmp_path / "writer-completed"
        placeholder = tmp_path / "soffice.exe"
        placeholder.write_bytes(b"placeholder")

        class ProgressiveWriterProcessRunner:
            def __init__(self):
                policy = ProcessPolicy(project_root)
                self._executable = policy.allow_executable(
                    "quota-writer", sys.executable
                )
                self._runner = ProcessRunner(policy)

            def run(self, provider_id, executable, args, **kwargs):
                del provider_id, executable
                target_format = args[args.index("--convert-to") + 1]
                child_output_dir = Path(args[args.index("--outdir") + 1])
                child_input = Path(args[-1])
                expected_child_output = child_output_dir / (
                    child_input.stem + "." + target_format
                )
                child_output = (
                    expected_child_output
                    if write_expected_output
                    else child_output_dir / "libreoffice-partial.tmp"
                )
                script = (
                    "import os, pathlib, sys, time\n"
                    "output = pathlib.Path(sys.argv[1])\n"
                    "marker = pathlib.Path(sys.argv[2])\n"
                    "with output.open('wb', buffering=0) as handle:\n"
                    "    for _ in range(80):\n"
                    "        handle.write(b'x' * 4096)\n"
                    "        os.fsync(handle.fileno())\n"
                    "        time.sleep(0.025)\n"
                    "marker.write_text('complete', encoding='utf-8')\n"
                )
                runtime_check = kwargs.get("runtime_check")
                if runtime_check is None:
                    return self._runner.run(
                        "quota-writer",
                        self._executable,
                        ["-c", script, str(child_output), str(completion_marker)],
                        cwd=project_root,
                        timeout_seconds=10.0,
                        output_limit=16_384,
                    )
                return self._runner.run(
                    "quota-writer",
                    self._executable,
                    ["-c", script, str(child_output), str(completion_marker)],
                    cwd=project_root,
                    timeout_seconds=10.0,
                    output_limit=16_384,
                    runtime_check=runtime_check,
                )

        original_read_bytes = Path.read_bytes

        def reject_oversized_read(path):
            if path.resolve() == progressive_output.resolve():
                raise AssertionError("oversized output must not be read into memory")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", reject_oversized_read)
        runner = LibreOfficeRunner(
            project_root,
            executable=placeholder,
            runner=ProgressiveWriterProcessRunner(),
            quota_backend=_TestHardQuotaBackend(),
        )

        with pytest.raises(DocumentSkillsError) as exc:
            runner.convert(input_file, "pdf", output_dir, timeout_seconds=10.0)

        assert exc.value.code == ErrorCode.PROVIDER_FAILED
        assert exc.value.details["output_limit"] == artifact_limit
        assert not expected_output.exists()
        assert not completion_marker.exists()

    def test_runner_rejects_nonzero_conversion_before_accepting_output(
        self,
        project_root,
        tmp_path,
    ):
        class FakeProcessRunner:
            def __init__(self):
                self.timeout = None

            def run(self, _provider_id, _executable, args, **kwargs):
                self.timeout = kwargs.get("timeout_seconds")
                target_format = args[args.index("--convert-to") + 1]
                child_output_dir = Path(args[args.index("--outdir") + 1])
                child_input = Path(args[-1])
                (child_output_dir / f"{child_input.stem}.{target_format}").write_bytes(
                    b"must-not-publish"
                )
                return ProcessResult(3, "", "failed", 10)

        executable = tmp_path / "soffice.exe"
        executable.write_bytes(b"placeholder")
        process_runner = FakeProcessRunner()
        runner = LibreOfficeRunner(
            project_root,
            executable=executable,
            runner=process_runner,
            quota_backend=_TestHardQuotaBackend(),
        )
        source = tmp_path / "source.pptx"
        source.write_bytes(b"fake")
        output = tmp_path / "output"
        output.mkdir()

        with pytest.raises(DocumentSkillsError) as captured:
            runner.convert(source, "pdf", output)
        assert captured.value.code == ErrorCode.PROVIDER_FAILED
        assert captured.value.details["returncode"] == 3
        assert 0 < process_runner.timeout <= 30.0
        assert not (output / "source.pdf").exists()

    def test_env_sanitized_by_process_runner(self, project_root):
        """The existing ProcessRunner sanitizes env — verify via its allowlist."""
        from document_skills_core.core.process.runner import _ENV_ALLOWLIST
        assert "HOME" not in _ENV_ALLOWLIST
        assert "USERPROFILE" not in _ENV_ALLOWLIST
        assert "PATH" in _ENV_ALLOWLIST
        assert "SystemRoot" in _ENV_ALLOWLIST


# ---------------------------------------------------------------------------
# Provider factory and consultation tests
# ---------------------------------------------------------------------------

class TestProviderFactory:
    def test_factory_returns_definition_and_provider(self, project_root):
        definition, _provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(),
        )
        assert definition.id == ProviderId.LIBREOFFICE
        assert definition.execute is not None
        assert definition.required is False
        assert len(definition.capabilities) > 0

    def test_factory_with_absent_detector_detects_unavailable(self, project_root):
        definition, _provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is False

    def test_factory_with_callable_detector_detects_available(self, project_root):
        definition, _provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(version="25.8.0"),
            runner=FakeCallableRunner(),
        )
        evidence = definition.detect()
        assert evidence.available is True
        assert evidence.version == "25.8.0"

    def test_diagnostics_returns_path_and_version(self, project_root):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(version="25.8.0", path="/usr/bin/soffice"),
            runner=FakeCallableRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] == "/usr/bin/soffice"
        assert diag["version"] == "25.8.0"

    def test_diagnostics_absent_returns_reason(self, project_root):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(reason="not installed"),
            runner=FakeCallableRunner(),
        )
        diag = provider.diagnostics()
        assert diag["path"] is None
        assert diag["version"] is None
        assert "not installed" in diag["reason"]


# ---------------------------------------------------------------------------
# Consultation tests (present / absent / crash / timeout)
# ---------------------------------------------------------------------------

class TestConsultationMatrix:
    def test_recalc_present_returns_cached_values(
        self, project_root, fake_xlsx
    ):
        """With callable detector+runner, try_recalc_xlsx returns cached values."""
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        result = provider.try_recalc_xlsx(fake_xlsx)
        assert result is not None
        assert any(key.startswith("Sheet1!") for key in result)
        assert any(key.startswith("Sheet1!") for key in result)

    def test_recalc_absent_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_recalc_crash_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCrashingRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_recalc_timeout_returns_none(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeHangingRunner(),
        )
        assert provider.try_recalc_xlsx(fake_xlsx) is None

    def test_convert_pdf_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(_minimal_docx_bytes())
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"%PDF-1.4 fake"),
        )
        result = provider.try_convert_to_pdf(input_file)
        assert result is not None
        assert result.startswith(b"%PDF")

    def test_convert_pdf_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(b"fake docx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_convert_to_pdf(input_file) is None

    def test_disguised_active_xlsx_cannot_bypass_convert_pdf_preflight(
        self, project_root, tmp_path
    ):
        actual_xlsx = _active_xlsx(tmp_path / "active.xlsx")
        disguised = tmp_path / "looks-like-word.docx"
        disguised.write_bytes(actual_xlsx.read_bytes())
        runner = FakeCallableRunner(canned_data=b"%PDF-1.4 fake")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        result = provider.execute(
            "libreoffice.convert-pdf",
            {"input": str(disguised)},
        )

        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == ErrorCode.ARCHIVE_UNSAFE.value
        assert runner.calls == []

    def test_convert_pdf_consumes_snapshot_and_detects_source_replacement(
        self, project_root, tmp_path
    ):
        input_file = tmp_path / "input.docx"
        original = _minimal_docx_bytes()
        input_file.write_bytes(original)

        class ReplacingPdfRunner(FakeCallableRunner):
            def convert(
                self,
                input_path,
                target_format,
                output_dir,
                *,
                timeout_seconds=None,
            ):
                assert Path(input_path).resolve() != input_file.resolve()
                assert Path(input_path).read_bytes() == original
                replacement = tmp_path / "replacement.docx"
                replacement.write_bytes(original + b"\x00")
                os.replace(replacement, input_file)
                return super().convert(
                    input_path,
                    target_format,
                    output_dir,
                    timeout_seconds=timeout_seconds,
                )

        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=ReplacingPdfRunner(canned_data=b"%PDF-1.4 fake"),
        )

        result = provider.execute(
            "libreoffice.convert-pdf",
            {"input": str(input_file)},
        )

        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED.value
        details = result["errors"][0]["details"]
        assert details["expected_sha256"] != details["actual_sha256"]

    @pytest.mark.parametrize(
        ("operation", "payload"),
        [
            ("libreoffice.render-image", "xlsx"),
            ("libreoffice.read-legacy", "docx"),
        ],
    )
    def test_operation_matrix_uses_detected_content_not_extension(
        self, project_root, tmp_path, fake_xlsx, operation, payload
    ):
        disguised = tmp_path / (
            "spreadsheet.docx" if payload == "xlsx" else "document.doc"
        )
        disguised.write_bytes(
            fake_xlsx.read_bytes() if payload == "xlsx" else _minimal_docx_bytes()
        )
        runner = FakeCallableRunner()
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        result = provider.execute(operation, {"input": str(disguised)})

        assert result["status"] == "invalid_request"
        assert result["errors"][0]["code"] == ErrorCode.REQUEST_INVALID.value
        assert runner.calls == []

    def test_oversized_pdf_output_is_rejected_before_read_bytes(
        self, project_root, tmp_path, monkeypatch
    ):
        input_file = tmp_path / "input.docx"
        input_file.write_bytes(_minimal_docx_bytes())

        class OversizedRunner:
            def convert(self, input_path, target_format, output_dir, **kwargs):
                output = output_dir / f"{Path(input_path).stem}.{target_format}"
                with output.open("wb") as handle:
                    handle.seek(MAX_PDF_BYTES)
                    handle.write(b"x")
                return output

        original_read_bytes = Path.read_bytes

        def guarded_read_bytes(path):
            if path.suffix.casefold() == ".pdf":
                raise AssertionError("oversized provider output must not be read")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
        with pytest.raises(DocumentSkillsError) as exc:
            convert_to_pdf(input_file, OversizedRunner())
        assert exc.value.code == ErrorCode.PROVIDER_FAILED
        assert exc.value.details["output_bytes"] == MAX_PDF_BYTES + 1
        assert exc.value.details["output_limit"] == MAX_PDF_BYTES

    def test_render_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.pptx"
        input_file.write_bytes(_minimal_pptx_bytes())
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"\x89PNG fake"),
        )
        result = provider.try_render_to_image(input_file)
        assert result is not None
        assert result.startswith(b"\x89PNG")

    def test_render_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.pptx"
        input_file.write_bytes(b"fake pptx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_render_to_image(input_file) is None

    @pytest.mark.parametrize(
        "operation",
        ["libreoffice.render-image", "libreoffice.read-legacy"],
    )
    def test_xlsx_cannot_bypass_spreadsheet_preflight_through_other_operations(
        self,
        project_root,
        tmp_path,
        operation,
    ):
        input_file = tmp_path / "active.xlsx"
        input_file.write_bytes(b"unscreened xlsx")
        runner = FakeCallableRunner()
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        result = provider.execute(operation, {"input": str(input_file)})

        assert result["status"] == "invalid_request"
        assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
        assert runner.calls == []

    def test_legacy_present_returns_bytes(self, project_root, tmp_path):
        input_file = tmp_path / "input.doc"
        input_file.write_bytes(_legacy_compound_bytes("doc"))
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"PK fake docx"),
        )
        result = provider.try_read_legacy(input_file)
        assert result is not None
        assert result.startswith(b"PK")

    def test_legacy_absent_returns_none(self, project_root, tmp_path):
        input_file = tmp_path / "input.doc"
        input_file.write_bytes(b"fake doc")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        assert provider.try_read_legacy(input_file) is None

    def test_legacy_required_preserves_success_and_unavailable_errors(
        self, project_root, tmp_path
    ):
        input_file = tmp_path / "input.xls"
        input_file.write_bytes(_legacy_compound_bytes("xls"))
        _, callable_provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_data=b"PK fake xlsx"),
        )
        assert callable_provider.convert_legacy_required(
            input_file,
            target_format="xlsx",
        ).startswith(b"PK")
        _, absent_provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        with pytest.raises(DocumentSkillsError) as exc:
            absent_provider.convert_legacy_required(
                input_file,
                target_format="xlsx",
            )
        assert exc.value.code == ErrorCode.PROVIDER_UNAVAILABLE
        _, crashing_provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCrashingRunner(),
        )
        with pytest.raises(DocumentSkillsError) as crash:
            crashing_provider.convert_legacy_required(
                input_file,
                target_format="xlsx",
            )
        assert crash.value.code == ErrorCode.PROVIDER_FAILED

    def test_required_legacy_xls_conversion_uses_normal_budget(
        self, project_root, tmp_path
    ):
        input_file = tmp_path / "budgeted.xls"
        input_file.write_bytes(_legacy_compound_bytes("xls"))
        runner = FakeCallableRunner(canned_data=b"PK fake xlsx")
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        provider.convert_legacy_required(input_file, target_format="xlsx")

        assert runner.calls[-1]["timeout"] == 30.0


# ---------------------------------------------------------------------------
# XLSX service integration tests
# ---------------------------------------------------------------------------

class TestXlsxServiceIntegration:
    def _read_request(self, input_path: Path) -> dict:
        return {
            "schema_version": "1.0",
            "operation": "xlsx.read",
            "input": str(input_path),
            "arguments": {},
        }

    def test_read_with_libreoffice_marks_recalculated(
        self, project_root, fake_xlsx
    ):
        """When LibreOffice recalc succeeds, formula cells become 'recalculated'."""
        _, libreoffice = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        service = XlsxService(project_root, libreoffice=libreoffice)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        assert result["status"] in ("success", "degraded")
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        summary = formula_state["summary"]
        assert summary["recalculation_provider"] == "libreoffice"
        assert summary["no_unverified_claimed_recalculated"] is True
        has_recalculated = any(
            cell["state"] == FORMULA_STATE_RECALCULATED
            for cell in formula_state["cells"].values()
        )
        assert has_recalculated

    def test_read_formula_analysis_and_recalc_consume_one_snapshot(
        self, project_root, fake_xlsx, monkeypatch
    ):
        from document_skills_core.formats.xlsx import read_operation

        observed: dict[str, Path] = {}
        original_read = read_operation.read_xlsx
        original_analysis = read_operation.validate_formula_analysis

        def recording_read(path, arguments):
            observed["read"] = Path(path).resolve()
            return original_read(path, arguments)

        def recording_analysis(path, validation, **kwargs):
            observed["analysis"] = Path(path).resolve()
            return original_analysis(path, validation, **kwargs)

        monkeypatch.setattr(read_operation, "read_xlsx", recording_read)
        monkeypatch.setattr(
            read_operation,
            "validate_formula_analysis",
            recording_analysis,
        )
        runner = FakeCallableRunner(canned_path=fake_xlsx)
        _, libreoffice = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )

        result = XlsxService(project_root, libreoffice=libreoffice).execute(
            "xlsx.read",
            self._read_request(fake_xlsx),
        )

        assert result["status"] in {"success", "degraded"}
        provider_input = Path(runner.calls[0]["input"]).resolve()
        assert observed["read"] == observed["analysis"] == provider_input
        assert provider_input != fake_xlsx.resolve()

    def test_read_rechecks_source_after_provider_atomic_replacement(
        self, project_root, fake_xlsx, tmp_path
    ):
        original = fake_xlsx.read_bytes()

        class ReplacingRunner(FakeCallableRunner):
            def convert(
                self,
                input_path,
                target_format,
                output_dir,
                *,
                timeout_seconds=None,
            ):
                assert Path(input_path).resolve() != fake_xlsx.resolve()
                assert Path(input_path).read_bytes() == original
                replacement = tmp_path / "atomic-replacement.xlsx"
                replacement.write_bytes(original + b"\x00")
                os.replace(replacement, fake_xlsx)
                return super().convert(
                    input_path,
                    target_format,
                    output_dir,
                    timeout_seconds=timeout_seconds,
                )

        _, libreoffice = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=ReplacingRunner(canned_data=original),
        )
        service = XlsxService(project_root, libreoffice=libreoffice)

        result = service.execute("xlsx.read", self._read_request(fake_xlsx))

        assert result["status"] == "failed"
        assert result["errors"][0]["code"] == ErrorCode.VALIDATION_FAILED.value
        details = result["errors"][0]["details"]
        assert details["expected_sha256"] != details["actual_sha256"]

    def test_read_without_libreoffice_preserves_core(self, project_root, fake_xlsx):
        """Without LibreOffice, the Core result is byte-identical."""
        service_core = XlsxService(project_root)
        result_core = service_core.execute("xlsx.read", self._read_request(fake_xlsx))

        _, libreoffice_absent = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        service_absent = XlsxService(project_root, libreoffice=libreoffice_absent)
        result_absent = service_absent.execute("xlsx.read", self._read_request(fake_xlsx))

        core_summary = result_core["diagnostics"]["operation_result"]["formula_state"]["summary"]
        absent_summary = result_absent["diagnostics"]["operation_result"]["formula_state"]["summary"]
        assert core_summary["recalculation_provider"] == "unavailable"
        assert absent_summary["recalculation_provider"] == "unavailable"
        assert (
            result_absent["diagnostics"]["operation_result"]["formula_state"]["cells"]
            == result_core["diagnostics"]["operation_result"]["formula_state"]["cells"]
        )

    def test_read_with_crashing_libreoffice_falls_back_to_core(
        self, project_root, fake_xlsx
    ):
        """When LibreOffice crashes, recalculation_provider is None (Core fallback)."""
        _, libreoffice_crash = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCrashingRunner(),
        )
        service = XlsxService(project_root, libreoffice=libreoffice_crash)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        formula_state = result["diagnostics"]["operation_result"]["formula_state"]
        summary = formula_state["summary"]
        assert summary["recalculation_provider"] == "unavailable"
        assert all(
            cell["state"] != FORMULA_STATE_RECALCULATED
            for cell in formula_state["cells"].values()
        )

    def test_read_with_timeout_libreoffice_falls_back_to_core(
        self, project_root, fake_xlsx
    ):
        _, libreoffice_timeout = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeHangingRunner(),
        )
        service = XlsxService(project_root, libreoffice=libreoffice_timeout)
        result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        summary = result["diagnostics"]["operation_result"]["formula_state"]["summary"]
        assert summary["recalculation_provider"] == "unavailable"

    def test_slow_recalculation_uses_short_auto_and_normal_required_budgets(
        self, project_root, fake_xlsx, tmp_path
    ):
        class SimulatedFourSecondRunner(FakeCallableRunner):
            def convert(
                self,
                input_path,
                target_format,
                output_dir,
                *,
                timeout_seconds=None,
            ):
                self.calls.append(
                    {
                        "input": str(input_path),
                        "format": target_format,
                        "output_dir": str(output_dir),
                        "timeout": timeout_seconds,
                    }
                )
                if timeout_seconds is None or timeout_seconds < 4.0:
                    raise DocumentSkillsError(
                        ErrorCode.PROCESS_TIMEOUT,
                        "Simulated four-second recalculation exceeded its budget.",
                    )
                output = output_dir / (Path(input_path).stem + "." + target_format)
                output.write_bytes(self._canned_data)
                return output

        runner = SimulatedFourSecondRunner(canned_path=fake_xlsx)
        _, libreoffice = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=runner,
        )
        service = XlsxService(project_root, libreoffice=libreoffice)

        auto_result = service.execute("xlsx.read", self._read_request(fake_xlsx))
        required_output = tmp_path / "required-recalculated.xlsx"
        required_result = service.execute(
            "xlsx.recalculate",
            {
                "schema_version": "1.0",
                "operation": "xlsx.recalculate",
                "input": str(fake_xlsx),
                "output": str(required_output),
                "arguments": {},
                "options": {"fidelity": "core", "in_place": False},
            },
        )

        assert auto_result["diagnostics"]["operation_result"]["recalculation"][
            "outcome"
        ] == "unavailable"
        assert required_result["status"] == "success"
        assert [call["timeout"] for call in runner.calls] == [3.0, 30.0, 30.0]


# ---------------------------------------------------------------------------
# Provider execute dispatcher tests
# ---------------------------------------------------------------------------

class TestProviderExecuteDispatcher:
    def test_execute_recalc_returns_canonical_result(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(canned_path=fake_xlsx),
        )
        result = provider.execute("libreoffice.recalc-xlsx", {
            "schema_version": "1.0",
            "operation": "libreoffice.recalc-xlsx",
            "input": str(fake_xlsx),
        })
        assert result["schema_version"] == "1.0"
        assert result["status"] == "success"
        assert result["operation"] == "libreoffice.recalc-xlsx"
        assert set(result) == {
            "schema_version", "status", "operation", "provider_chain",
            "requested_fidelity", "achieved_fidelity", "degraded",
            "degradations", "artifacts", "validation", "warnings",
            "errors", "diagnostics",
        }

    def test_execute_absent_returns_failed(self, project_root, fake_xlsx):
        _, provider = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        result = provider.execute("libreoffice.recalc-xlsx", {
            "schema_version": "1.0",
            "operation": "libreoffice.recalc-xlsx",
            "input": str(fake_xlsx),
        })
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# find_callable catalog tests
# ---------------------------------------------------------------------------

class TestFindCallable:
    def test_find_callable_returns_true_with_callable_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_libreoffice_provider(
            project_root,
            detector=FakeCallableDetector(),
            runner=FakeCallableRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.LIBREOFFICE) is True

    def test_find_callable_returns_false_with_absent_provider(self, project_root):
        registry = ProviderCatalog()
        definition, _ = build_libreoffice_provider(
            project_root,
            detector=FakeAbsentDetector(),
            runner=FakeCallableRunner(),
        )
        registry.register_provider(definition)
        assert registry.find_callable(ProviderId.LIBREOFFICE) is False

    def test_find_callable_returns_false_for_unregistered(self, project_root):
        registry = ProviderCatalog()
        assert registry.find_callable(ProviderId.LIBREOFFICE) is False


# ---------------------------------------------------------------------------
# No-macro-argv assertion tests
# ---------------------------------------------------------------------------

class TestNoMacroArgv:
    def test_recalc_uses_private_ods_round_trip_only(self, project_root, fake_xlsx):
        """Recalculation uses only the two bounded conversion stages."""
        canned_xlsx = fake_xlsx
        runner = FakeCallableRunner(canned_path=canned_xlsx)
        recalculate_xlsx(fake_xlsx, runner, timeout_seconds=3.0)
        assert [call["format"] for call in runner.calls] == ["ods", "xlsx"]
        assert Path(runner.calls[1]["input"]).suffix == ".ods"
        assert all(
            not Path(call["output_dir"]).exists()
            for call in runner.calls
        )
