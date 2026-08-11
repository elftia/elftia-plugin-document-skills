"""Adversarial strategy-3 consumer evidence and trust-contract regressions."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, BinaryIO, Callable

from jsonschema import ValidationError
import pytest

from consumer_validation.contracts import validate_consumer_report
from consumer_validation.harness import qualify_artifact
import consumer_validation.harness as harness_module
import consumer_validation.office as office_module
import consumer_validation.pdf as pdf_module


Mutation = Callable[[], None]


class _TrackedReader:
    def __init__(self, handle: BinaryIO, mutation: Mutation) -> None:
        self._handle = handle
        self._mutation = mutation
        self._mutated = False
        self.returned_bytes = 0

    def __enter__(self) -> "_TrackedReader":
        self._handle.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._handle.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def read(self, size: int = -1) -> bytes:
        payload = self._handle.read(size)
        self.returned_bytes += len(payload)
        if not self._mutated:
            self._mutated = True
            self._mutation()
        return payload


def test_pdf_second_evidence_growth_returns_strict_resource_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    _write_pdf(artifact, "Stable bounded candidate")
    initial_bytes = artifact.stat().st_size
    policy_limit = initial_bytes + 32
    original_qualify = harness_module.qualify_pdf

    def qualify_then_grow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_qualify(*args, **kwargs)
        with artifact.open("ab") as handle:
            handle.write(b"x" * 33)
        return result

    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", policy_limit)
    monkeypatch.setattr(harness_module, "qualify_pdf", qualify_then_grow)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["pdf.resource-bounds"]
    assert report["status"] == "fail"
    assert report["portable"]["outcome"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-resource-limit",
        "bytes": initial_bytes + 33,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["category"] == "artifact-byte-limit"
    assert assertion["evidence"]["maximum"] == policy_limit


def test_pdf_evidence_read_uses_one_bounded_sentinel_on_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "growing.pdf"
    _write_pdf(artifact, "Grow while hashing")
    initial_bytes = artifact.stat().st_size
    policy_limit = initial_bytes + 16
    original_open = Path.open
    tracked: list[_TrackedReader] = []

    def grow() -> None:
        with original_open(artifact, "ab") as handle:
            handle.write(b"g" * 64)

    def patched_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        handle = original_open(path, *args, **kwargs)
        if path == artifact and args and args[0] == "rb":
            reader = _TrackedReader(handle, grow)
            tracked.append(reader)
            return reader
        return handle

    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", policy_limit)
    monkeypatch.setattr(pdf_module, "_EVIDENCE_CHUNK_BYTES", 32, raising=False)
    monkeypatch.setattr(Path, "open", patched_open)

    observe = getattr(pdf_module, "observe_pdf_artifact")
    observation = observe(artifact)

    assert observation.outcome == "resource-limit"
    assert observation.evidence["category"] == "artifact-byte-limit"
    assert observation.evidence["sentinel_bytes"] == 1
    assert len(tracked) == 1
    assert tracked[0].returned_bytes == policy_limit + 1


@pytest.mark.parametrize("mutation_kind", ["grow", "truncate"])
def test_pdf_mutation_during_second_evidence_is_typed_and_schema_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    replacement = tmp_path / "replacement.pdf"
    _write_pdf(artifact, "Stable bounded candidate")
    _write_pdf(replacement, "Replacement candidate")
    initial_bytes = artifact.stat().st_size
    policy_limit = max(initial_bytes, replacement.stat().st_size) + 256
    original_open = Path.open
    target_open_count = 0

    def mutate() -> None:
        if mutation_kind == "grow":
            with original_open(artifact, "ab") as handle:
                handle.write(b"bounded-growth")
        elif mutation_kind == "truncate":
            with original_open(artifact, "r+b") as handle:
                handle.truncate(max(1, initial_bytes // 2))
        else:
            raise AssertionError(f"unsupported in-place mutation: {mutation_kind}")

    def patched_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal target_open_count
        handle = original_open(path, *args, **kwargs)
        if path == artifact and args and args[0] == "rb":
            target_open_count += 1
            if target_open_count == 2:
                return _TrackedReader(handle, mutate)
        return handle

    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", policy_limit)
    monkeypatch.setattr(pdf_module, "_EVIDENCE_CHUNK_BYTES", 32, raising=False)
    monkeypatch.setattr(Path, "open", patched_open)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        expectations={"text": ["Stable bounded candidate"]},
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    assert report["portable"]["outcome"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-non-exact-observation",
        "bytes": None,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["category"] == "artifact-mutated-during-evidence"
    assert assertion["evidence"]["phase"] == "post-consumer"


def test_pdf_replacement_during_second_evidence_is_typed_and_schema_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    replacement = tmp_path / "replacement.pdf"
    _write_pdf(artifact, "Stable bounded candidate")
    _write_pdf(replacement, "Replacement candidate")
    initial_bytes = artifact.stat().st_size
    policy_limit = max(initial_bytes, replacement.stat().st_size) + 256
    original_open = Path.open
    target_open_count = 0

    def patched_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal target_open_count
        if path == artifact and args and args[0] == "rb":
            target_open_count += 1
            if target_open_count == 2:
                os.replace(replacement, artifact)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", policy_limit)
    monkeypatch.setattr(Path, "open", patched_open)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        expectations={"text": ["Stable bounded candidate"]},
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-non-exact-observation",
        "bytes": None,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["category"] == "artifact-replaced-before-evidence"
    assert assertion["evidence"]["phase"] == "post-consumer"


@pytest.mark.parametrize("mutation_kind", ["grow", "truncate", "replace", "delete"])
def test_pdf_change_between_evidence_points_is_typed_and_schema_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    replacement = tmp_path / "replacement.pdf"
    _write_pdf(artifact, "Stable bounded candidate")
    _write_pdf(replacement, "Replacement candidate")
    initial_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    original_qualify = harness_module.qualify_pdf

    def qualify_then_change(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_qualify(*args, **kwargs)
        if mutation_kind == "grow":
            with artifact.open("ab") as handle:
                handle.write(b"bounded-growth")
        elif mutation_kind == "truncate":
            with artifact.open("r+b") as handle:
                handle.truncate(max(1, artifact.stat().st_size // 2))
        elif mutation_kind == "replace":
            os.replace(replacement, artifact)
        else:
            artifact.unlink()
        return result

    policy_limit = max(artifact.stat().st_size, replacement.stat().st_size) + 256
    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", policy_limit)
    monkeypatch.setattr(harness_module, "qualify_pdf", qualify_then_change)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        expectations={"text": ["Stable bounded candidate"]},
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    if mutation_kind == "delete":
        assert report["artifact"] == {
            "path": str(artifact),
            "sha256": None,
            "sha256_status": "not-computed-non-exact-observation",
            "bytes": None,
        }
    else:
        assert report["artifact"]["sha256"] != initial_sha256
    assert assertion["outcome"] == "fail"
    expected_category = (
        "artifact-unavailable-before-evidence"
        if mutation_kind == "delete"
        else "artifact-changed-between-evidence-points"
    )
    assert assertion["evidence"]["category"] == expected_category
    assert assertion["evidence"]["phase"] == "post-consumer"


def test_pdf_repeated_initial_mutation_returns_typed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    _write_pdf(artifact, "Unstable bounded candidate")
    initial_bytes = artifact.stat().st_size
    original_open = Path.open
    tracked: list[_TrackedReader] = []

    def grow() -> None:
        with original_open(artifact, "ab") as handle:
            handle.write(b"bounded-growth")

    def patched_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        handle = original_open(path, *args, **kwargs)
        if path == artifact and args and args[0] == "rb" and len(tracked) < 2:
            reader = _TrackedReader(handle, grow)
            tracked.append(reader)
            return reader
        return handle

    monkeypatch.setattr(pdf_module, "_MAX_ARTIFACT_BYTES", initial_bytes + 256)
    monkeypatch.setattr(pdf_module, "_EVIDENCE_CHUNK_BYTES", 32, raising=False)
    monkeypatch.setattr(Path, "open", patched_open)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-non-exact-observation",
        "bytes": None,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["category"] == "artifact-mutated-during-evidence"
    assert assertion["evidence"]["phase"] == "initial-retry"
    assert len(tracked) == 2


@pytest.mark.parametrize("mutation_kind", ["replace", "delete"])
def test_pdf_repeated_stat_to_open_change_returns_typed_unknown_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_kind: str,
) -> None:
    artifact = tmp_path / "candidate.pdf"
    _write_pdf(artifact, "Repeated pathname change")
    replacement_bytes = artifact.read_bytes()
    original_open = Path.open
    target_open_count = 0

    def patched_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal target_open_count
        if path == artifact and args and args[0] == "rb":
            target_open_count += 1
            if mutation_kind == "replace":
                replacement = tmp_path / f"replacement-{target_open_count}.pdf"
                replacement.write_bytes(replacement_bytes + bytes([target_open_count]))
                os.replace(replacement, artifact)
            else:
                artifact.unlink()
                try:
                    return original_open(path, *args, **kwargs)
                except FileNotFoundError:
                    artifact.write_bytes(replacement_bytes)
                    raise
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", patched_open)

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-non-exact-observation",
        "bytes": None,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["identity_status"] == "unavailable-non-exact-observation"
    assert assertion["evidence"]["phase"] == "initial-retry"
    assert target_open_count == 2


def test_pdf_missing_across_bounded_attempts_returns_typed_unknown_identity(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "missing.pdf"

    report = qualify_artifact(
        format_id="pdf",
        operation="pdf.create",
        artifact=artifact,
        office_policy="off",
    )

    validate_consumer_report(report)
    assertion = _portable_assertions(report)["consumer.source-preservation"]
    assert report["status"] == "fail"
    assert report["artifact"] == {
        "path": str(artifact),
        "sha256": None,
        "sha256_status": "not-computed-non-exact-observation",
        "bytes": None,
    }
    assert assertion["outcome"] == "fail"
    assert assertion["evidence"]["category"] == "artifact-unavailable-before-evidence"
    assert assertion["evidence"]["identity_status"] == "unavailable-non-exact-observation"
    assert assertion["evidence"]["phase"] == "initial-retry"


@pytest.mark.parametrize(
    ("child_output", "forbidden"),
    [
        (
            b'{"event":"identity","application":"word","version":"16.TOPSECRET"}\n',
            ["16.TOPSECRET", "TOPSECRET"],
        ),
        (
            b'{"event":"identity","application":"excel","version":"99.9"}\n',
            ["excel", "99.9"],
        ),
        (b'{"event":"identity","application":"word","version":"16!0"}\n', ["16!0"]),
        (
            b'{"event":"identity","application":"word","version":"'
            + b"9" * 5000
            + b'"}\n',
            ["9999999999999999"],
        ),
    ],
)
@pytest.mark.skipif(os.name != "nt", reason="mocked COM process timeout is Windows-only")
def test_timeout_report_uses_trusted_detection_identity_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child_output: bytes,
    forbidden: list[str],
) -> None:
    artifact = tmp_path / "trusted-identity.docx"
    _write_docx(artifact, "Trusted identity")

    class UnresponsiveProcess:
        pid = 4242
        returncode = None

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(
                cmd="powershell.exe",
                timeout=timeout,
                output=child_output,
                stderr=b"bounded-stderr",
            )

    trusted = {"available": True, "application": "word", "version": "16.0"}
    monkeypatch.setattr(office_module.subprocess, "Popen", lambda *args, **kwargs: UnresponsiveProcess())
    monkeypatch.setattr(office_module, "detect_office", lambda _application: trusted)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda _pid: {
            "descendants_cleaned": True,
            "cleanup_category": "taskkill-complete",
        },
    )

    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=artifact,
        expectations={"text": ["Trusted identity"]},
        office_policy="auto",
        office_detector=lambda _application: trusted,
        office_runner=office_module.open_with_office,
        timeout_seconds=0.01,
    )

    validate_consumer_report(report)
    serialized = json.dumps(report, sort_keys=True)
    assert report["office"]["evidence"]["application"] == "word"
    assert report["office"]["evidence"]["version"] == "16.0"
    assert report["office"]["evidence"]["version_status"] == "trusted-detection"
    for value in forbidden:
        assert value not in serialized


@pytest.mark.skipif(os.name != "nt", reason="mocked COM process timeout is Windows-only")
def test_timeout_without_trusted_version_is_explicitly_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "unknown-version.docx"
    _write_docx(artifact, "Unknown trusted version")
    child_output = b'{"event":"identity","application":"word","version":"16.TOPSECRET"}\n'

    class UnresponsiveProcess:
        pid = 4242
        returncode = None

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(
                cmd="powershell.exe",
                timeout=timeout,
                output=child_output,
                stderr=b"",
            )

    detection = {"available": True, "application": "word"}
    monkeypatch.setattr(office_module.subprocess, "Popen", lambda *args, **kwargs: UnresponsiveProcess())
    monkeypatch.setattr(office_module, "detect_office", lambda _application: detection)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda _pid: {
            "descendants_cleaned": False,
            "cleanup_category": "taskkill-incomplete",
        },
    )

    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=artifact,
        expectations={"text": ["Unknown trusted version"]},
        office_policy="auto",
        office_detector=lambda _application: detection,
        office_runner=office_module.open_with_office,
        timeout_seconds=0.01,
    )

    validate_consumer_report(report)
    serialized = json.dumps(report, sort_keys=True)
    assert report["office"]["evidence"]["version"] == "unknown"
    assert report["office"]["evidence"]["version_status"] == "unknown-redacted"
    assert "16.TOPSECRET" not in serialized
    assert "TOPSECRET" not in serialized


@pytest.mark.parametrize(
    ("detection", "expected_version", "expected_status"),
    [
        (
            {"available": True, "application": "word", "version": "16.0"},
            "16.0",
            "trusted-detection",
        ),
        (
            {"available": True, "application": "word"},
            "unknown",
            "unknown-redacted",
        ),
    ],
)
def test_timeout_projection_is_platform_neutral_and_child_identity_free(
    detection: dict[str, Any],
    expected_version: str,
    expected_status: str,
) -> None:
    child_output = b'{"event":"identity","application":"excel","version":"TOPSECRET"}\n'

    evidence = office_module.project_timeout_evidence(
        application="word",
        detection=detection,
        termination={
            "descendants_cleaned": False,
            "cleanup_category": "taskkill-timeout",
        },
        drain_status="timeout",
        stdout=child_output,
        stderr=b"bounded-stderr",
    )

    serialized = json.dumps(evidence, sort_keys=True)
    assert evidence["application"] == "word"
    assert evidence["version"] == expected_version
    assert evidence["version_status"] == expected_status
    assert evidence["descendants_cleaned"] is False
    assert evidence["cleanup_category"] == "taskkill-timeout"
    assert evidence["post_termination_drain"] == "timeout"
    assert "excel" not in serialized
    assert "TOPSECRET" not in serialized


@pytest.mark.skipif(os.name != "nt", reason="taskkill escalation is Windows-only")
@pytest.mark.parametrize(
    ("failure_kind", "expected_category"),
    [("timeout", "taskkill-timeout"), ("error", "taskkill-error")],
)
def test_taskkill_failure_returns_schema_valid_bounded_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_category: str,
) -> None:
    artifact = tmp_path / "taskkill-timeout.docx"
    _write_docx(artifact, "Taskkill timeout")

    class UnresponsiveProcess:
        pid = 4242
        returncode = None

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(
                cmd="powershell.exe",
                timeout=timeout,
                output=b"bounded-child-output",
                stderr=b"bounded-child-error",
            )

    trusted = {"available": True, "application": "word", "version": "16.0"}

    def taskkill_failure(*args: Any, **kwargs: Any) -> Any:
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(cmd="taskkill.exe", timeout=10)
        raise OSError("bounded-taskkill-error")

    monkeypatch.setattr(office_module.subprocess, "Popen", lambda *args, **kwargs: UnresponsiveProcess())
    monkeypatch.setattr(office_module.subprocess, "run", taskkill_failure)
    monkeypatch.setattr(office_module, "detect_office", lambda _application: trusted)
    monkeypatch.setattr(office_module, "_open_descendant_handles", lambda _pid: [])

    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=artifact,
        expectations={"text": ["Taskkill timeout"]},
        office_policy="auto",
        office_detector=lambda _application: trusted,
        office_runner=office_module.open_with_office,
        timeout_seconds=0.01,
    )

    validate_consumer_report(report)
    evidence = report["office"]["evidence"]
    assert report["status"] == "fail"
    assert evidence["category"] == "timeout"
    assert evidence["cleanup_category"] == expected_category
    assert evidence["descendants_cleaned"] is False
    assert evidence["post_termination_drain"] == "timeout"


def test_ordinary_office_result_keeps_truthful_completed_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "completed.docx"
    _write_docx(artifact, "Completed result")
    trusted = {"available": True, "application": "word", "version": "16.0"}

    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=artifact,
        expectations={"text": ["Completed result"]},
        office_policy="auto",
        office_detector=lambda _application: trusted,
        office_runner=lambda _application, _artifact, _timeout: {
            "outcome": "pass",
            "application": "word",
            "version": "16.0",
            "read_only": True,
            "saved": False,
            "macros": "disabled",
            "external_updates": "disabled",
        },
    )

    validate_consumer_report(report)
    evidence = report["office"]["evidence"]
    assert report["status"] == "pass"
    assert evidence["application"] == "word"
    assert evidence["version"] == "16.0"
    assert evidence["read_only"] is True
    assert evidence["saved"] is False


def test_nullable_digest_is_only_valid_for_pdf_artifact_byte_limit_failure() -> None:
    intended = _nullable_resource_report()
    validate_consumer_report(intended)

    invalid_reports: list[dict[str, Any]] = []
    portable_pass = deepcopy(intended)
    portable_pass["status"] = "pass"
    portable_pass["portable"]["outcome"] = "pass"
    invalid_reports.append(portable_pass)

    other_format = deepcopy(intended)
    other_format["format"] = "docx"
    invalid_reports.append(other_format)

    non_resource = deepcopy(intended)
    non_resource["portable"]["assertions"][0]["evidence"]["category"] = "parse-error"
    invalid_reports.append(non_resource)

    without_status = deepcopy(intended)
    del without_status["artifact"]["sha256_status"]
    invalid_reports.append(without_status)

    string_with_null_status = deepcopy(intended)
    string_with_null_status["artifact"]["sha256"] = "a" * 64
    invalid_reports.append(string_with_null_status)

    at_limit = deepcopy(intended)
    at_limit["artifact"]["bytes"] = 64
    at_limit["portable"]["assertions"][0]["evidence"]["actual"] = 64
    invalid_reports.append(at_limit)

    below_limit = deepcopy(intended)
    below_limit["artifact"]["bytes"] = 63
    below_limit["portable"]["assertions"][0]["evidence"]["actual"] = 63
    invalid_reports.append(below_limit)

    contradictory_bytes = deepcopy(intended)
    contradictory_bytes["artifact"]["bytes"] = 66
    invalid_reports.append(contradictory_bytes)

    duplicate_resource_assertion = deepcopy(intended)
    duplicate_resource_assertion["portable"]["assertions"].append(
        deepcopy(duplicate_resource_assertion["portable"]["assertions"][0])
    )
    invalid_reports.append(duplicate_resource_assertion)

    for report in invalid_reports:
        with pytest.raises(ValidationError):
            validate_consumer_report(report)


def _portable_assertions(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in report["portable"]["assertions"]}


def _write_pdf(path: Path, text: str) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _write_docx(path: Path, text: str) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    document.save(path)


def _nullable_resource_report() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format": "pdf",
        "operation": "pdf.create",
        "consumer_identity": "elftia-independent-consumer/1",
        "artifact": {
            "path": "bounded.pdf",
            "sha256": None,
            "sha256_status": "not-computed-resource-limit",
            "bytes": 65,
        },
        "status": "fail",
        "portable": {
            "consumer": "PyMuPDF-independent/2",
            "availability": "available",
            "outcome": "fail",
            "assertions": [
                {
                    "id": "pdf.resource-bounds",
                    "outcome": "fail",
                    "evidence": {
                        "actual": 65,
                        "category": "artifact-byte-limit",
                        "maximum": 64,
                    },
                    "message": "Independent assertion failed: pdf.resource-bounds",
                }
            ],
            "warnings": [],
            "evidence": {},
        },
        "office": {
            "consumer": "microsoft-office-com/1",
            "availability": "not_requested",
            "outcome": "not_run",
            "assertions": [],
            "warnings": [],
            "evidence": {"reason": "not-office"},
        },
        "office_acceptance": False,
        "warnings": [],
    }
