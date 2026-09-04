"""Optional OpenXML SDK schema-gate state tests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import threading

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.process import ProcessResult
from document_skills_core.formats.pptx.schema_validation import (
    validate_schema_gate,
    with_schema_gate,
)
from document_skills_core.providers.dotnet.detector import DotnetOpenXmlDetector
from document_skills_core.providers.dotnet.runner import DotnetOpenXmlRunner
import document_skills_core.providers.dotnet.service as dotnet_service_module
from document_skills_core.providers.dotnet.service import (
    DotnetOpenXmlProvider,
    build_dotnet_provider,
)


class _Provider:
    def __init__(
        self,
        evidence: DetectionEvidence,
        result: dict[str, object] | None,
    ) -> None:
        self.evidence = evidence
        self.result = result

    def detect(self) -> DetectionEvidence:
        return self.evidence

    def try_validate_schema(self, _path: Path) -> dict[str, object] | None:
        return self.result


class _CountingDetector(DotnetOpenXmlDetector):
    def __init__(self) -> None:
        self.calls = 0

    def detect(self) -> DetectionEvidence:
        self.calls += 1
        return DetectionEvidence(
            available=True,
            version="3.0.0",
            path="C:/fixture/dotnet.exe",
        )


class _SchemaRunner(DotnetOpenXmlRunner):
    def __init__(self) -> None:
        self.bound_paths: list[str | Path] = []

    def bind_authorized_executable(self, executable: str | Path) -> None:
        self.bound_paths.append(executable)

    def run(
        self,
        subcommand: str,
        *,
        stdin_payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
        output_limit: int | None = None,
    ) -> ProcessResult:
        del stdin_payload, timeout_seconds, output_limit
        assert subcommand == "--schema-validate"
        return ProcessResult(
            0,
            json.dumps({"valid": True, "errors": []}),
            "",
            1,
        )


@dataclass(frozen=True)
class _FixtureExecutableBinding:
    path: Path
    identity: str


class _DistinctPathDetector(DotnetOpenXmlDetector):
    def __init__(self) -> None:
        self.labels: dict[int, str] = {}
        self.calls = 0
        self._lock = threading.Lock()

    def select(self, label: str) -> None:
        with self._lock:
            self.labels[threading.get_ident()] = label

    def detect(self) -> DetectionEvidence:
        with self._lock:
            self.calls += 1
            label = self.labels[threading.get_ident()]
        return DetectionEvidence(
            available=True,
            version=f"3.0.{label}",
            path=f"C:/fixture/dotnet-{label}.exe",
        )


class _BarrierBindingRunner(DotnetOpenXmlRunner):
    def __init__(self, barrier: threading.Barrier) -> None:
        self.barrier = barrier
        self._shared_binding: _FixtureExecutableBinding | None = None
        self.launches: dict[int, list[_FixtureExecutableBinding]] = {}
        self._lock = threading.Lock()

    def bind_authorized_executable(
        self,
        executable: str | Path,
    ) -> _FixtureExecutableBinding:
        path = Path(executable)
        binding = _FixtureExecutableBinding(
            path=path,
            identity=f"identity:{path.name}",
        )
        self._shared_binding = binding
        self.barrier.wait(timeout=5)
        return binding

    def run(
        self,
        subcommand: str,
        *,
        executable: _FixtureExecutableBinding | None = None,
        stdin_payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
        output_limit: int | None = None,
    ) -> ProcessResult:
        del stdin_payload, timeout_seconds, output_limit
        assert subcommand == "--schema-validate"
        binding = executable or self._shared_binding
        assert binding is not None
        with self._lock:
            self.launches.setdefault(threading.get_ident(), []).append(binding)
        return ProcessResult(
            0,
            json.dumps({"valid": True, "errors": []}),
            "",
            1,
        )


def test_schema_gate_is_optional_unavailable_when_provider_is_absent(tmp_path: Path) -> None:
    provider = _Provider(
        DetectionEvidence(False, reason="OpenXML SDK is absent."),
        None,
    )
    gate = validate_schema_gate(tmp_path / "candidate.pptx", provider)
    report = with_schema_gate(_report(), gate)

    assert gate["outcome"] == "unavailable"
    assert gate["required"] is False
    assert report["status"] == "pass"


def test_schema_gate_passes_and_becomes_required_when_provider_runs(tmp_path: Path) -> None:
    provider = _Provider(
        DetectionEvidence(True, version="3.0.0"),
        {"valid": True, "errors": []},
    )
    gate = validate_schema_gate(tmp_path / "candidate.pptx", provider)
    report = with_schema_gate(_report(), gate)

    assert gate["outcome"] == "pass"
    assert gate["required"] is True
    assert gate["version"] == "3.0.0"
    assert report["status"] == "pass"


def test_schema_gate_detects_and_authorizes_real_dotnet_provider_once(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.pptx"
    candidate.write_bytes(b"PK bounded fixture")
    detector = _CountingDetector()
    runner = _SchemaRunner()
    provider = DotnetOpenXmlProvider(
        tmp_path,
        detector=detector,
        runner=runner,
    )

    gate = validate_schema_gate(candidate, provider)

    assert gate["outcome"] == "pass"
    assert gate["version"] == "3.0.0"
    assert detector.calls == 1
    assert runner.bound_paths == ["C:/fixture/dotnet.exe"]


def test_public_pptx_schema_command_reuses_one_authorized_detection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = tmp_path / "candidate.pptx"
    candidate.write_bytes(b"PK bounded fixture")
    detector = _CountingDetector()
    runner = _SchemaRunner()
    definition, _provider = build_dotnet_provider(
        tmp_path,
        detector=detector,
        runner=runner,
    )
    definition.capabilities = [
        Capability("pptx.validate.schema", "enhanced", validation_strength=3)
    ]
    registry = ProviderCatalog()
    registry.register_provider(definition)
    monkeypatch.setattr(
        dotnet_service_module,
        "validate_schema",
        lambda _path, _runner, max_errors=100: {
            "valid": True,
            "errors": [],
        },
    )

    result = registry.execute(
        {
            "schema_version": "1.0",
            "operation": "pptx.validate.schema",
            "input": str(candidate),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_errors": 100},
        }
    )

    assert result["status"] == "success"
    assert detector.calls == 1
    assert runner.bound_paths == ["C:/fixture/dotnet.exe"]


def test_dotnet_operation_lease_resets_after_nested_and_exceptional_commands(
    tmp_path: Path,
) -> None:
    detector = _CountingDetector()
    runner = _SchemaRunner()
    provider = DotnetOpenXmlProvider(tmp_path, detector=detector, runner=runner)

    with provider.operation_lease():
        provider.detect()
        with provider.operation_lease():
            provider.detect()
    assert detector.calls == 1
    assert runner.bound_paths == ["C:/fixture/dotnet.exe"]

    try:
        with provider.operation_lease():
            provider.detect()
            raise RuntimeError("injected command failure")
    except RuntimeError:
        pass
    with provider.operation_lease():
        provider.detect()

    assert detector.calls == 3
    assert runner.bound_paths == [
        "C:/fixture/dotnet.exe",
        "C:/fixture/dotnet.exe",
        "C:/fixture/dotnet.exe",
    ]


def test_dotnet_operation_lease_isolates_concurrent_commands(tmp_path: Path) -> None:
    detector = _CountingDetector()
    runner = _SchemaRunner()
    provider = DotnetOpenXmlProvider(tmp_path, detector=detector, runner=runner)
    barrier = threading.Barrier(2)

    def command() -> None:
        with provider.operation_lease():
            barrier.wait(timeout=5)
            provider.detect()
            provider.detect()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(command) for _index in range(2)]
        for future in futures:
            future.result(timeout=10)

    assert detector.calls == 2
    assert runner.bound_paths == [
        "C:/fixture/dotnet.exe",
        "C:/fixture/dotnet.exe",
    ]


def test_dotnet_operation_lease_keeps_distinct_launch_bindings_per_command(
    tmp_path: Path,
) -> None:
    detector = _DistinctPathDetector()
    runner = _BarrierBindingRunner(threading.Barrier(2))
    provider = DotnetOpenXmlProvider(tmp_path, detector=detector, runner=runner)
    candidate = tmp_path / "candidate.pptx"
    candidate.write_bytes(b"PK bounded fixture")

    def command(label: str) -> tuple[int, DetectionEvidence]:
        detector.select(label)
        thread_id = threading.get_ident()
        with provider.operation_lease():
            evidence = provider.detect()
            provider.validate_schema(candidate, 100)
            provider.validate_schema(candidate, 100)
        return thread_id, evidence

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(command, label)
            for label in ("A", "B")
        }
        results = {
            label: future.result(timeout=10)
            for label, future in futures.items()
        }

    assert detector.calls == 2
    for label, (thread_id, evidence) in results.items():
        expected_path = Path(f"C:/fixture/dotnet-{label}.exe")
        assert Path(evidence.path or "") == expected_path
        assert runner.launches[thread_id] == [
            _FixtureExecutableBinding(
                path=expected_path,
                identity=f"identity:{expected_path.name}",
            ),
            _FixtureExecutableBinding(
                path=expected_path,
                identity=f"identity:{expected_path.name}",
            ),
        ]


def test_registry_resets_entered_leases_when_later_hook_entry_fails() -> None:
    state = {"active": False}

    @contextmanager
    def entered_lease():
        state["active"] = True
        try:
            yield
        finally:
            state["active"] = False

    @contextmanager
    def failing_lease():
        raise RuntimeError("injected lease entry failure")
        yield

    registry = ProviderCatalog()
    registry.register_provider(
        Provider(
            id=ProviderId.CORE_PYTHON,
            version="fixture",
            detect=lambda: DetectionEvidence(True),
            execute=lambda _operation, _request: {},
            capabilities=[Capability("fixture.operation", "core")],
            operation_lease=entered_lease,
        )
    )
    registry.register_provider(
        Provider(
            id=ProviderId.CORE_NODE,
            version="fixture",
            detect=lambda: DetectionEvidence(True),
            execute=lambda _operation, _request: {},
            capabilities=[],
            operation_lease=failing_lease,
        )
    )

    try:
        registry.execute(
            {
                "operation": "fixture.operation",
                "options": {"fidelity": "core"},
            }
        )
    except RuntimeError:
        pass

    assert state["active"] is False


def test_schema_gate_fails_required_on_invalid_document_or_provider_failure(
    tmp_path: Path,
) -> None:
    invalid = _Provider(
        DetectionEvidence(True, version="3.0.0"),
        {"valid": False, "errors": [{"description": "invalid"}]},
    )
    failed = _Provider(DetectionEvidence(True, version="3.0.0"), None)

    invalid_gate = validate_schema_gate(tmp_path / "candidate.pptx", invalid)
    failed_gate = validate_schema_gate(tmp_path / "candidate.pptx", failed)

    assert invalid_gate["outcome"] == "fail"
    assert invalid_gate["evidence"]["error_count"] == 1
    assert failed_gate["outcome"] == "fail"
    assert with_schema_gate(_report(), invalid_gate)["status"] == "fail"
    assert with_schema_gate(_report(), failed_gate)["status"] == "fail"


def _report() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "pass",
        "gates": [{
            "duration_ms": 0,
            "evidence": {"reason": "not configured"},
            "id": "schema.full",
            "outcome": "unavailable",
            "required": False,
            "validator": "document-skills-core",
            "version": None,
            "warnings": [],
        }],
    }
