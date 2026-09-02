"""Adversarial strategy-3 consumer evidence and trust-contract regressions."""

from __future__ import annotations

from copy import deepcopy
import ctypes
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


def _office_observation(
    *,
    raw: set[int] | frozenset[int] = frozenset(),
    matching: set[int] | frozenset[int] = frozenset(),
    unresolved: set[int] | frozenset[int] = frozenset(),
) -> office_module._OfficeProcessObservation:
    raw_ids = frozenset(raw)
    matching_ids = frozenset(matching)
    unresolved_ids = frozenset(unresolved)
    return office_module._OfficeProcessObservation(
        raw_process_ids=raw_ids,
        matching_process_ids=matching_ids,
        nonmatching_process_ids=raw_ids - matching_ids - unresolved_ids,
        unresolved_process_ids=unresolved_ids,
    )


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


class _HeldOfficeProcess:
    def __init__(
        self,
        *,
        process_id: int = 5150,
        creation_filetime: int = 123,
        image_name: str = "WINWORD.EXE",
        running: bool | None = True,
    ) -> None:
        self.process_id = process_id
        self.creation_filetime = creation_filetime
        self.image_name = image_name
        self.running = running
        self.closed = False
        self.close_calls = 0
        self.terminate_calls = 0
        self.wait_calls = 0

    def __enter__(self) -> "_HeldOfficeProcess":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def is_running(self) -> bool | None:
        return self.running

    def terminate(self) -> bool:
        self.terminate_calls += 1
        if self.running is not True:
            return False
        self.running = False
        return True

    def wait(self, _timeout_ms: int) -> bool | None:
        self.wait_calls += 1
        if self.running is None:
            return None
        return not self.running


class _WinApiFunction:
    def __init__(self, callback: Callable[..., int]) -> None:
        self._callback = callback
        self.argtypes: list[object] = []
        self.restype: object | None = None

    def __call__(self, *args: object) -> int:
        return self._callback(*args)


class _FakeUser32:
    def __init__(
        self,
        *,
        enum_result: int,
        invoke_callback: bool,
        owner_lookup_succeeds: bool = True,
        owner: int = 5150,
        visible: bool = False,
        last_error: int = 0,
    ) -> None:
        def enum_windows(callback: Callable[[int, int], bool], _parameter: int) -> int:
            if invoke_callback:
                callback(700, 0)
            ctypes.set_last_error(last_error)
            return enum_result

        def get_owner(_window: int, owner_pointer: object) -> int:
            if not owner_lookup_succeeds:
                return 0
            owner_pointer._obj.value = owner  # type: ignore[attr-defined]
            return 1

        self.EnumWindows = _WinApiFunction(enum_windows)
        self.GetWindowThreadProcessId = _WinApiFunction(get_owner)
        self.IsWindowVisible = _WinApiFunction(
            lambda _window: int(visible)
        )


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
def test_timeout_cleans_bound_dcom_server_outside_worker_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "owned-dcom.docx"
    _write_docx(artifact, "Owned DCOM cleanup")
    child_output = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )

    class UnresponsiveProcess:
        pid = 4242
        returncode = None

        def __init__(self) -> None:
            self.calls = 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd="powershell.exe",
                    timeout=timeout,
                    output=child_output,
                    stderr=b"",
                )
            return child_output, b""

    terminated: list[int] = []
    trusted = {"available": True, "application": "word", "version": "16.0"}
    monkeypatch.setattr(office_module.subprocess, "Popen", lambda *args, **kwargs: UnresponsiveProcess())
    monkeypatch.setattr(office_module, "detect_office", lambda _application: trusted)
    process_snapshots = iter(
        (
            _office_observation(raw={77}, matching={77}),
            _office_observation(raw={77, 5150}, matching={77, 5150}),
            _office_observation(raw={77, 5150}, matching={77, 5150}),
            _office_observation(raw={77}, matching={77}),
        )
    )
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(process_snapshots),
    )
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)

    held = _HeldOfficeProcess()
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda _process_id: held,
    )

    def terminate(
        process_id: int,
        *,
        target: _HeldOfficeProcess | None = None,
    ) -> dict[str, Any]:
        terminated.append(process_id)
        if target is not None:
            assert target is held
            assert target.terminate() is True
            assert target.wait(5_000) is True
            return {
                "descendants_cleaned": True,
                "cleanup_category": "handle-tree-complete",
                "target_terminated": True,
                "target_exited": True,
            }
        return {
            "descendants_cleaned": True,
            "cleanup_category": "taskkill-complete",
        }

    monkeypatch.setattr(office_module, "_terminate_tree", terminate)

    evidence = office_module.open_with_office("word", artifact, 0.01)

    assert evidence["outcome"] == "fail"
    assert evidence["category"] == "timeout"
    assert terminated == [4242, 5150]


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_never_infers_ownership_from_fresh_headless_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0"}\n'
    )
    terminated: list[int] = []
    waited: list[frozenset[int]] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(
        office_module,
        "_wait_for_unbound_office_processes_exit",
        lambda _application, process_ids, _baseline: (
            waited.append(process_ids) or False
        ),
    )
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: (
            terminated.append(process_id)
            or {
                "descendants_cleaned": True,
                "cleanup_category": "taskkill-complete",
            }
        ),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert waited == [frozenset({5150})]
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_accepts_unbound_word_after_observed_natural_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":0,"window_handle":0,"process_start_filetime":0}\n'
        b'{"outcome":"pass","application":"word","version":"16.0"}\n'
    )
    terminated: list[int] = []
    observations = iter(
        (
            _office_observation(raw={5150}, matching={5150}),
            _office_observation(),
        )
    )
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is True
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_rejects_additional_unbound_candidate_during_exit_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":0,"window_handle":0,"process_start_filetime":0}\n'
        b'{"outcome":"pass","application":"word","version":"16.0"}\n'
    )
    terminated: list[int] = []
    observations = iter(
        (
            _office_observation(raw={5150}, matching={5150}),
            _office_observation(raw={5151}, matching={5151}),
        )
    )
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_unbound_office_exit_wait_is_bounded_for_persistent_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._wait_for_unbound_office_processes_exit(
        "word",
        frozenset({5150}),
        _office_observation(),
        timeout_seconds=0,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize(
    "exit_observation",
    [
        pytest.param(None, id="enumeration-unknown"),
        pytest.param(
            _office_observation(raw={5150}),
            id="candidate-image-drift",
        ),
        pytest.param(
            _office_observation(raw={5150}, unresolved={5150}),
            id="candidate-image-unresolved",
        ),
    ],
)
def test_office_cleanup_rejects_unbound_candidate_when_exit_observation_is_untrusted(
    monkeypatch: pytest.MonkeyPatch,
    exit_observation: office_module._OfficeProcessObservation | None,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":0,"window_handle":0,"process_start_filetime":0}\n'
        b'{"outcome":"pass","application":"word","version":"16.0"}\n'
    )
    terminated: list[int] = []
    observations = iter(
        (
            _office_observation(raw={5150}, matching={5150}),
            exit_observation,
        )
    )
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_accepts_owned_process_natural_exit_without_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: True)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is True
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_rejects_unverifiable_window_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: None)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: (
            terminated.append(process_id)
            or {
                "descendants_cleaned": True,
                "cleanup_category": "taskkill-complete",
            }
        ),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_fails_closed_when_baseline_enumeration_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        None,
        b"",
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_open_does_not_launch_when_baseline_observation_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "baseline-unknown.docx"
    _write_docx(artifact, "Baseline unknown")
    trusted = {"available": True, "application": "word", "version": "16.0"}
    monkeypatch.setattr(office_module, "detect_office", lambda _application: trusted)
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: None,
    )

    def reject_launch(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Office worker must not launch without a trusted baseline")

    monkeypatch.setattr(office_module.subprocess, "Popen", reject_launch)

    evidence = office_module.open_with_office("word", artifact, 0.01)

    assert evidence == {
        **trusted,
        "outcome": "fail",
        "category": "office-process-observation-unavailable",
    }


def test_office_process_observation_preserves_enumeration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(office_module, "_enumerate_process_ids", lambda: None)

    assert office_module._office_process_ids("word") is None


def test_office_process_observation_uses_independent_snapshot_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(office_module, "_enumerate_process_ids", lambda: [5150])
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: None)
    monkeypatch.setattr(
        office_module,
        "_snapshot_processes",
        lambda: {5150: (77, "WINWORD.EXE")},
    )

    observation = office_module._office_process_ids("word")

    assert observation is not None
    assert observation.raw_process_ids == {5150}
    assert observation.matching_process_ids == {5150}
    assert observation.unresolved_process_ids == set()


def test_office_process_observation_resolves_bound_candidate_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_enumerate_process_ids",
        lambda: [77, 5150, 88],
    )

    def image_name(process_id: int) -> str:
        lookups.append(process_id)
        return "WINWORD.EXE" if process_id == 5150 else "OTHER.EXE"

    monkeypatch.setattr(office_module, "_process_image_name", image_name)

    observation = office_module._office_process_ids(
        "word",
        priority_process_id=5150,
    )

    assert observation is not None
    assert lookups[0] == 5150
    assert observation.matching_process_ids == {5150}


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_fails_closed_when_current_enumeration_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: None,
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        b"",
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_fails_closed_when_pretermination_recheck_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    observations = iter(
        (_office_observation(raw={5150}, matching={5150}), None)
    )
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(observations),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: (
            terminated.append(process_id)
            or {
                "descendants_cleaned": True,
                "cleanup_category": "taskkill-complete",
            }
        ),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize("baseline_lookup", ["none", "exception"])
def test_office_cleanup_preserves_unresolved_baseline_pid(
    monkeypatch: pytest.MonkeyPatch,
    baseline_lookup: str,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    state = {"lookup_count": 0, "terminated": False}

    def enumerate_processes() -> list[int]:
        return [] if state["terminated"] else [5150]

    def image_name(_process_id: int) -> str | None:
        state["lookup_count"] += 1
        if state["lookup_count"] == 1:
            if baseline_lookup == "exception":
                raise OSError("baseline image lookup unavailable")
            return None
        return "WINWORD.EXE"

    monkeypatch.setattr(office_module, "_enumerate_process_ids", enumerate_processes)
    monkeypatch.setattr(office_module, "_process_image_name", image_name)
    monkeypatch.setattr(office_module, "_snapshot_processes", lambda: {})
    baseline = office_module._office_process_ids("word")
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)

    def terminate(process_id: int) -> dict[str, Any]:
        terminated.append(process_id)
        state["terminated"] = True
        return {
            "descendants_cleaned": True,
            "cleanup_category": "taskkill-complete",
        }

    monkeypatch.setattr(office_module, "_terminate_tree", terminate)

    cleaned = office_module._cleanup_owned_office_process("word", baseline, payload)

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize("current_lookup", ["none", "exception"])
def test_office_cleanup_fails_closed_on_current_candidate_image_lookup(
    monkeypatch: pytest.MonkeyPatch,
    current_lookup: str,
) -> None:
    terminated: list[int] = []

    observation_count = 0

    def enumerate_processes() -> list[int]:
        nonlocal observation_count
        observation_count += 1
        return [] if observation_count == 1 else [5150]

    monkeypatch.setattr(
        office_module,
        "_enumerate_process_ids",
        enumerate_processes,
    )

    def image_name(_process_id: int) -> str | None:
        if current_lookup == "exception":
            raise OSError("current image lookup unavailable")
        return None

    monkeypatch.setattr(office_module, "_process_image_name", image_name)
    monkeypatch.setattr(office_module, "_snapshot_processes", lambda: {})
    baseline = office_module._office_process_ids("word")
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        baseline,
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
        ),
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_accepts_candidate_exiting_during_image_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(([], [5150], [], []))
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_enumerate_process_ids",
        lambda: next(observations),
    )
    monkeypatch.setattr(office_module, "_process_image_name", lambda _process_id: None)
    monkeypatch.setattr(office_module, "_snapshot_processes", lambda: {})
    baseline = office_module._office_process_ids("word")
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        baseline,
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
        ),
    )

    assert cleaned is True
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_bound_office_exit_wait_accepts_transient_unresolved_then_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        (
            _office_observation(raw={5150}, unresolved={5150}),
            _office_observation(),
        )
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    exited = office_module._wait_for_office_process_exit(
        "powerpoint",
        5150,
        timeout_seconds=1,
    )

    assert exited is True
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize("recheck_lookup", ["none", "exception"])
def test_office_cleanup_fails_closed_on_pretermination_candidate_image_lookup(
    monkeypatch: pytest.MonkeyPatch,
    recheck_lookup: str,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    observations = iter(([], [5150], [5150]))
    monkeypatch.setattr(
        office_module,
        "_enumerate_process_ids",
        lambda: next(observations),
    )
    lookup_count = 0

    def image_name(_process_id: int) -> str | None:
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count >= 3:
            if recheck_lookup == "exception":
                raise OSError("pretermination image lookup unavailable")
            return None
        return "WINWORD.EXE"

    monkeypatch.setattr(office_module, "_process_image_name", image_name)
    monkeypatch.setattr(office_module, "_snapshot_processes", lambda: {})
    baseline = office_module._office_process_ids("word")
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process("word", baseline, payload)

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_terminates_fully_bound_fresh_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[tuple[int, _HeldOfficeProcess]] = []
    observations = iter(([], [5150], [5150]))
    monkeypatch.setattr(
        office_module,
        "_enumerate_process_ids",
        lambda: next(observations),
    )
    monkeypatch.setattr(
        office_module,
        "_process_image_name",
        lambda _process_id: "WINWORD.EXE",
    )
    baseline = office_module._office_process_ids("word")
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    held = _HeldOfficeProcess()
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda _process_id: held,
        raising=False,
    )

    def terminate(
        process_id: int,
        *,
        target: _HeldOfficeProcess,
    ) -> dict[str, Any]:
        terminated.append((process_id, target))
        assert target.terminate() is True
        assert target.wait(5_000) is True
        return {
            "descendants_cleaned": True,
            "cleanup_category": "handle-tree-complete",
            "target_terminated": True,
            "target_exited": True,
        }

    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        terminate,
    )

    cleaned = office_module._cleanup_owned_office_process("word", baseline, payload)

    assert cleaned is True
    assert terminated == [(5150, held)]
    assert held.wait_calls == 1
    assert held.closed is True


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_rejects_process_object_swap_after_initial_identity_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    swapped = _HeldOfficeProcess(creation_filetime=456)
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda _process_id: swapped,
        raising=False,
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id, **_kwargs: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []
    assert swapped.closed is True


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_accepts_target_exit_before_exact_handle_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    exited = _HeldOfficeProcess(running=False)
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda _process_id: exited,
        raising=False,
    )
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id, **_kwargs: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is True
    assert terminated == []
    assert exited.closed is True


def test_bound_office_tree_terminates_parent_before_held_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int | bool]] = []

    class OrderedHeld(_HeldOfficeProcess):
        def terminate(self) -> bool:
            events.append(("terminate", self.process_id))
            return super().terminate()

        def wait(self, timeout_ms: int) -> bool | None:
            events.append(("wait", self.process_id))
            return super().wait(timeout_ms)

    target = OrderedHeld()
    descendant = OrderedHeld(process_id=6001, image_name="CHILD.EXE")
    snapshot = {
        5150: (4242, "WINWORD.EXE"),
        6001: (5150, "CHILD.EXE"),
    }

    def processes() -> dict[int, tuple[int, str]]:
        events.append(("snapshot-parent-running", target.running is True))
        return snapshot

    monkeypatch.setattr(office_module, "_snapshot_processes", processes)
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda process_id: descendant if process_id == 6001 else None,
    )

    result = office_module._terminate_tree(5150, target=target)

    assert result == {
        "descendants_cleaned": True,
        "cleanup_category": "handle-tree-complete",
        "target_terminated": True,
        "target_exited": True,
    }
    assert events.count(("snapshot-parent-running", True)) == 2
    assert events.index(("terminate", 5150)) < events.index(("terminate", 6001))
    assert target.wait_calls == 1
    assert descendant.wait_calls == 1
    assert descendant.close_calls == 1


def test_bound_office_tree_closes_every_open_handle_before_failed_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _HeldOfficeProcess()
    opened = _HeldOfficeProcess(process_id=6001, image_name="FIRST.EXE")
    snapshot = {
        5150: (4242, "WINWORD.EXE"),
        6001: (5150, "FIRST.EXE"),
        6002: (5150, "SECOND.EXE"),
    }
    monkeypatch.setattr(office_module, "_snapshot_processes", lambda: snapshot)
    monkeypatch.setattr(
        office_module,
        "_open_held_office_process",
        lambda process_id: opened if process_id == 6001 else None,
    )

    with target:
        result = office_module._terminate_tree(5150, target=target)

    assert result == {
        "descendants_cleaned": False,
        "cleanup_category": "handle-tree-incomplete",
        "target_terminated": False,
        "target_exited": False,
    }
    assert target.terminate_calls == 0
    assert opened.terminate_calls == 0
    assert opened.close_calls == 1
    assert target.close_calls == 1


@pytest.mark.skipif(os.name != "nt", reason="visible-window checks are Windows-only")
@pytest.mark.parametrize(
    ("user32", "expected"),
    [
        (
            _FakeUser32(
                enum_result=0,
                invoke_callback=False,
                last_error=5,
            ),
            None,
        ),
        (
            _FakeUser32(
                enum_result=0,
                invoke_callback=True,
                owner_lookup_succeeds=False,
            ),
            None,
        ),
        (
            _FakeUser32(
                enum_result=0,
                invoke_callback=True,
                visible=True,
            ),
            True,
        ),
        (
            _FakeUser32(
                enum_result=1,
                invoke_callback=True,
                owner=777,
            ),
            False,
        ),
    ],
)
def test_visible_window_observation_is_explicitly_tristate(
    monkeypatch: pytest.MonkeyPatch,
    user32: _FakeUser32,
    expected: bool | None,
) -> None:
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda _name, **_kwargs: user32,
    )

    assert office_module._has_visible_window(5150) is expected


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
def test_office_cleanup_rejects_failed_visible_window_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    user32 = _FakeUser32(
        enum_result=0,
        invoke_callback=False,
        last_error=5,
    )
    terminated: list[int] = []
    monkeypatch.setattr(ctypes, "WinDLL", lambda _name, **_kwargs: user32)
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id, **_kwargs: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize(
    ("payload", "window_owner", "image_name"),
    [
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150}\n',
            5150,
            "WINWORD.EXE",
        ),
        (
            b'{"event":"identity","application":"excel","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n',
            5150,
            "WINWORD.EXE",
        ),
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5151,"window_handle":701,"process_start_filetime":124}\n',
            5150,
            "WINWORD.EXE",
        ),
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n',
            5151,
            "WINWORD.EXE",
        ),
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n',
            5150,
            "POWERPNT.EXE",
        ),
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
            b'{"outcome":"pass","application":"word","version":"17.0"}\n',
            5150,
            "WINWORD.EXE",
        ),
        (
            b'{"event":"identity","application":"word","version":"16.0",'
            b'"process_id":5150,"window_handle":700,"process_start_filetime":124}\n',
            5150,
            "WINWORD.EXE",
        ),
    ],
)
def test_office_cleanup_rejects_incomplete_ambiguous_or_inconsistent_identity(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    window_owner: int,
    image_name: str,
) -> None:
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: False)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: window_owner)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: image_name)
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(),
        payload,
    )

    assert cleaned is False
    assert terminated == []


@pytest.mark.skipif(os.name != "nt", reason="Office process ownership is Windows-only")
@pytest.mark.parametrize(
    ("baseline", "visible", "expected_clean"),
    [({5150}, False, True), (set(), True, False)],
)
def test_owned_office_cleanup_never_terminates_preexisting_or_visible_process(
    monkeypatch: pytest.MonkeyPatch,
    baseline: set[int],
    visible: bool,
    expected_clean: bool,
) -> None:
    payload = (
        b'{"event":"identity","application":"word","version":"16.0",'
        b'"process_id":5150,"window_handle":700,"process_start_filetime":123}\n'
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        office_module,
        "_office_process_ids",
        lambda _application, **_kwargs: _office_observation(
            raw={5150}, matching={5150}
        ),
    )
    monkeypatch.setattr(office_module, "_has_visible_window", lambda _pid: visible)
    monkeypatch.setattr(office_module, "_window_process_id", lambda _handle: 5150)
    monkeypatch.setattr(office_module, "_process_image_name", lambda _pid: "WINWORD.EXE")
    monkeypatch.setattr(office_module, "_process_start_filetime", lambda _pid: 123)
    monkeypatch.setattr(office_module, "_wait_for_office_process_exit", lambda *_args: False)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda process_id: terminated.append(process_id),
    )

    cleaned = office_module._cleanup_owned_office_process(
        "word",
        _office_observation(raw=baseline, matching=baseline),
        payload,
    )

    assert cleaned is expected_clean
    assert terminated == []


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


@pytest.mark.skipif(os.name != "nt", reason="mocked COM process timeout is Windows-only")
def test_post_termination_drain_error_returns_typed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "drain-error.docx"
    _write_docx(artifact, "Drain error")

    class DrainErrorProcess:
        pid = 4242
        returncode = None

        def __init__(self) -> None:
            self.calls = 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd="powershell.exe",
                    timeout=timeout,
                    output=b"bounded-child-output",
                    stderr=b"bounded-child-error",
                )
            raise OSError("post-termination-drain-failed")

    process = DrainErrorProcess()
    trusted = {"available": True, "application": "word", "version": "16.0"}
    monkeypatch.setattr(office_module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(office_module, "detect_office", lambda _application: trusted)
    monkeypatch.setattr(
        office_module,
        "_terminate_tree",
        lambda _pid: {
            "descendants_cleaned": False,
            "cleanup_category": "taskkill-error",
        },
    )

    report = qualify_artifact(
        format_id="docx",
        operation="docx.create",
        artifact=artifact,
        expectations={"text": ["Drain error"]},
        office_policy="auto",
        office_detector=lambda _application: trusted,
        office_runner=office_module.open_with_office,
        timeout_seconds=0.01,
    )

    validate_consumer_report(report)
    evidence = report["office"]["evidence"]
    assert report["status"] == "fail"
    assert evidence["category"] == "timeout"
    assert evidence["application"] == "word"
    assert evidence["version"] == "16.0"
    assert evidence["descendants_cleaned"] is False
    assert evidence["cleanup_category"] == "taskkill-error"
    assert evidence["post_termination_drain"] == "error"
    assert evidence["stdout_bytes"] == len(b"bounded-child-output")
    assert evidence["stderr_bytes"] == len(b"bounded-child-error")
    assert process.calls == 2


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
