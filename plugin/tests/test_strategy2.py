import json
from pathlib import Path
import shutil
import subprocess

import pytest

from document_skills_core.core.capabilities import (
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.capabilities.reports import build_capabilities
from document_skills_core.core.contracts import SchemaCatalog
from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY
from document_skills_core.providers import build_default_registry
from tools.audit_node import audit_node_source
from tools.audit_python import audit_python_source
from tools.audit import run_audits
from tools.command_discovery import CommandDiscovery
from tools.frozen_uv import FrozenUvGrammar
from tools.provenance_records import (
    CURRENT_REVIEW_ARTIFACT,
    validate_metadata_exclusion,
)
from tests.support.provenance_review_fixture import bind_test_review


@pytest.mark.parametrize("command", ["doctor", "capabilities", "run"])
@pytest.mark.parametrize(
    "mode",
    [
        "text-noise",
        "binary-noise",
        "typed",
        "system-exit",
        "interrupt",
        "base",
        "ordinary",
        "hang",
        "overflow",
        "os-exit",
        "crash",
        "invalid-result",
        "trailing-noise",
        "hostile",
        "huge-string",
        "huge-int",
        "surrogate",
        "unicode",
    ],
)
# Slow tier: every node spawns a real uv/python public process that copies
# and cold-imports the source tree, and the assertion is the supervisor's
# timeout classification under deliberately tight budgets. Worker spawn
# latency under parallel test load turns that into a false
# DS_PROCESS_TIMEOUT, so it runs serially with the other subprocess-budget
# tests.
@pytest.mark.slow
def test_public_supervisor_is_one_json_protocol(project_root, command, mode):
    uv = shutil.which("uv")
    assert uv is not None
    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "tests" / "support" / "public_supervisor_fixture.py"),
            mode,
            command,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=300,
    )
    assert completed.stdout.count(b"\n") == 1
    assert completed.stderr == b""
    assert b"PRIVATE" not in completed.stdout
    payload = json.loads(completed.stdout)
    schema = {
        "doctor": "doctor-report",
        "capabilities": "capability-report",
        "run": "operation-result",
    }[command]
    SchemaCatalog(project_root).validate(schema, payload)
    if mode in {"text-noise", "binary-noise", "unicode"}:
        assert completed.returncode == 0
    else:
        assert completed.returncode == 2
        if command == "run":
            expected = "DS_PROCESS_TIMEOUT" if mode == "hang" else "DS_PROVIDER_FAILED"
            assert payload["errors"][0]["code"] == expected
            if mode == "typed":
                details = payload["errors"][0]["details"]
                assert details["reason_category"] == "provider_exception"
                assert details["exception_class"] == "DocumentSkillsError"


def test_public_supervisor_rejects_redirected_private_base_before_spawn(
    project_root: Path,
    tmp_path: Path,
):
    uv = shutil.which("uv")
    assert uv is not None
    sandbox = tmp_path / "project"
    shutil.copytree(project_root / "src", sandbox / "src")
    shutil.copytree(project_root / "schemas", sandbox / "schemas")
    support = sandbox / "tests" / "support"
    support.mkdir(parents=True)
    shutil.copy2(
        project_root / "tests" / "support" / "command_worker_fixture.py",
        support / "command_worker_fixture.py",
    )
    redirected = sandbox / "redirected-private-base"
    redirected.mkdir()
    try:
        (sandbox / ".document-skills-tmp").symlink_to(
            redirected,
            target_is_directory=True,
        )
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {type(error).__name__}")

    completed = subprocess.run(
        [
            uv,
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "tests" / "support" / "public_supervisor_fixture.py"),
            "text-noise",
            "run",
            str(sandbox),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=15,
    )

    assert completed.returncode == 2, completed.stdout.decode("utf-8", errors="replace")
    assert completed.stdout.count(b"\n") == 1
    assert completed.stderr == b""
    assert list(redirected.iterdir()) == []
    payload = json.loads(completed.stdout)
    SchemaCatalog(sandbox).validate("operation-result", payload)


def test_default_provider_identity_and_detection_only_capabilities(project_root):
    registry = build_default_registry(project_root)
    doctor = subprocess.run(
        [
            shutil.which("uv"),
            "run",
            "--project",
            str(project_root),
            "--frozen",
            "python",
            str(project_root / "skills" / "document-docx" / "scripts" / "run.py"),
            "doctor",
            "--json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    doctor_state = {item["id"]: item for item in json.loads(doctor.stdout)["providers"]}
    capability = build_capabilities(project_root, "docx", registry)
    capability_state = {item["id"]: item for item in capability["providers"]}
    assert "core-node-protocol" not in doctor.stdout
    assert doctor_state["core-node"]["available"] is True
    assert capability_state["core-node"]["available"] is True
    assert (
        doctor_state["core-node"]["version"] == capability_state["core-node"]["version"]
    )
    operations = {item["operation"]: item for item in capability["operations"]}
    assert set(operations) == {
        "docx.create",
        "docx.comments.add",
        "docx.comments.read",
        "docx.comments.resolve",
        "docx.compare.semantic",
        "docx.compare.visual",
        "docx.convert.legacy",
        "docx.convert.pdf",
        "docx.edit",
        "docx.edit.replace-text",
        "docx.inspect.accessibility",
        "docx.inspect.structure",
        "docx.layout.repair",
        "docx.merge",
        "docx.read",
        "docx.render",
        "docx.revisions.apply",
        "docx.revisions.read",
            "docx.template.apply",
            "docx.template.import.create",
            "docx.template.import.inspect",
            "docx.template.pack.instantiate",
            "docx.template.pack.list",
            "docx.template.pack.read",
            "docx.validate.schema",
        }
    assert operations["docx.template.apply"]["providers"] == ["core-node"]
    assert all(
        operations[operation]["available"]
        for operation in (
            "docx.create",
            "docx.compare.semantic",
            "docx.edit",
            "docx.edit.replace-text",
            "docx.inspect.accessibility",
            "docx.inspect.structure",
            "docx.merge",
            "docx.read",
            "docx.template.apply",
        )
    )
    expected_schema = (
        "available"
        if capability_state["dotnet-openxml"]["available"]
        else "unavailable"
    )
    assert capability["validation"]["schema"] == expected_schema
    assert capability["validation"]["visual"] == "unavailable"


def test_validation_capabilities_are_format_scoped_and_callable(project_root):
    def catalog(available=True, validators=None, callable_provider=True):
        result = ProviderCatalog()
        result.register_provider(
            Provider(
                ProviderId.CORE_PYTHON,
                "1",
                detect=lambda: DetectionEvidence(available, version="1"),
                execute=(lambda _op, _req: {}) if callable_provider else None,
                capabilities=[
                    Capability("xlsx.validate.schema", "enhanced"),
                    Capability("pptx.render", "enhanced"),
                ],
                validators=validators
                or {"schema": lambda: {}, "visual": lambda: {}},
            )
        )
        return result

    registry = catalog()
    assert build_capabilities(project_root, "docx", registry)["validation"] == {
        "package": "available",
        "schema": "unavailable",
        "visual": "unavailable",
    }
    assert build_capabilities(project_root, "pdf", registry)["validation"] == {
        "package": "available",
        "schema": "unavailable",
        "visual": "unavailable",
    }
    assert build_capabilities(project_root, "xlsx", registry)["validation"] == {
        "package": "available",
        "schema": "available",
        "visual": "unavailable",
    }
    assert build_capabilities(project_root, "pptx", registry)["validation"] == {
        "package": "available",
        "schema": "unavailable",
        "visual": "available",
    }
    assert build_capabilities(project_root, "xlsx", catalog(available=False))[
        "validation"
    ]["schema"] == "unavailable"
    assert build_capabilities(
        project_root,
        "xlsx",
        catalog(validators={"schema": None, "visual": lambda: {}}),
    )["validation"]["schema"] == "unavailable"
    assert build_capabilities(
        project_root, "xlsx", catalog(callable_provider=False)
    )["validation"]["schema"] == "unavailable"


def test_catalog_requires_callable_and_available_detector(project_root):
    def catalog(evidence, execute):
        result = ProviderCatalog()
        result.register_provider(
            Provider(
                ProviderId.CORE_PYTHON,
                "1",
                detect=lambda: evidence,
                execute=execute,
                capabilities=[Capability("docx.fixture", "core")],
                required=True,
            )
        )
        return result

    available = DetectionEvidence(True, version="1")
    unavailable = DetectionEvidence(False, reason="absent")
    assert (
        build_capabilities(
            project_root, "docx", catalog(available, lambda _op, _req: {})
        )["operations"][0]["available"]
        is True
    )
    assert (
        build_capabilities(
            project_root, "docx", catalog(unavailable, lambda _op, _req: {})
        )["operations"][0]["available"]
        is False
    )
    assert (
        build_capabilities(project_root, "docx", catalog(available, None))["operations"]
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "loader = __import__\n",
        "box = [eval]\n",
        "def give():\n    return globals\n",
        "__loader__.load_module('x')\n",
        "import importlib\nload = importlib.import_module\n",
        "import builtins\nload = builtins.__dict__['__import__']\n",
        "import operator\nload = operator.attrgetter('__import__')\n",
    ],
)
def test_python_dangerous_identity_as_value_is_rejected(source):
    with pytest.raises(AssertionError):
        audit_python_source("src/document_skills_core/fixture.py", source)


def test_python_benign_local_alias_and_plain_data_pass():
    audit_python_source(
        "src/document_skills_core/fixture.py",
        "def local(value):\n    return value\nalias = local\ndata = {'x': 1}\nvalue = data['x']\n",
    )


@pytest.mark.parametrize(
    "source",
    [
        "import { createRequire as loader } from 'node:module';\nconst x = loader;\n",
        "const loader = require;\n",
        "const loader = Function;\n",
        "const x = import('./dynamic.mjs');\n",
        "import vm from 'node:vm';\n",
        "const spec = '@modelcontextprotocol/' + 'sdk';\n",
    ],
)
def test_node_dangerous_identity_as_value_is_rejected(project_root, source):
    with pytest.raises(AssertionError):
        audit_node_source(project_root, "runtime/node/fixture.mjs", source)


@pytest.mark.parametrize(
    "source",
    [
        "env node runtime/node/health.mjs",
        "command node runtime/node/health.mjs",
        "PATH=/tmp node runtime/node/health.mjs",
        "cmd /c node runtime/node/health.mjs",
        "pwsh -Command node runtime/node/health.mjs",
        "& node runtime/node/health.mjs",
        'uv run --project "<project-root>" --frozen python '
        '"<skill-dir>/scripts/run.py" run --request request.json;node',
    ],
)
def test_effective_command_wrappers_and_operators_reject(source):
    command = CommandDiscovery().discover(source)
    assert command is not None
    assert FrozenUvGrammar().authorize(command) is False


def test_frozen_uv_grammar_accepts_quoted_windows_unicode_path():
    source = (
        'uv run --project "<project-root>" --frozen python '
        '"<skill-dir>/scripts/run.py" run --request '
        '"C:\\工作 文件\\request.json"'
    )
    command = CommandDiscovery().discover(source)
    assert command is not None
    assert FrozenUvGrammar().authorize(command) is True


@pytest.mark.parametrize(
    "relative",
    [
        "runtime/Bin/provider.dat",
        ".VENV/provider.txt",
        "runtime/Obj./provider.txt",
        "runtime/BUILD /provider.txt",
        "runtime\\Node_Modules\\provider.txt",
        "runtime/.PyTest_Cache/provider.txt",
    ],
)
def test_portable_forbidden_components_reject(relative):
    with pytest.raises(ValueError):
        PORTABLE_PATH_POLICY.require_release_safe(relative)


def _release_copy(project_root, tmp_path):
    destination = tmp_path / "release"
    shutil.copytree(
        project_root,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".document-skills-tmp",
        ),
    )
    return destination


def test_complete_rebound_audit_baseline_passes(project_root, tmp_path):
    root = _release_copy(project_root, tmp_path)
    bind_test_review(root)
    report = run_audits(root)
    assert report["status"] == "pass", report["errors"]


def test_current_review_is_exact_hashless_review_metadata(project_root):
    from tools.regenerate_provenance import _is_metadata

    review_path = CURRENT_REVIEW_ARTIFACT
    assert _is_metadata(review_path) is True
    validate_metadata_exclusion(
        project_root,
        {
            "artifact": review_path,
            "classification": "self-referential-audit-metadata",
            "reason": (
                "The current report binds the exact mapping digest, so hashing "
                "its own final bytes in that mapping would be circular."
            ),
            "reviewer": "Strategy-2 current-review test reviewer",
            "review_evidence": [review_path],
        },
        {"Strategy-2 current-review test reviewer"},
    )


def test_current_review_is_exact_metadata_and_mapping_stays_stable(
    project_root,
    tmp_path,
):
    from tools.regenerate_provenance import regenerate

    expected_review = CURRENT_REVIEW_ARTIFACT
    previous_review = (
        "provenance/reviews/"
        "document-skills-0.5.3-pptx-b7-merge-review.md"
    )
    root = _release_copy(project_root, tmp_path)
    manifest, mapping_before = regenerate(root)
    metadata_paths = {
        record["artifact"] for record in manifest["metadata_exclusions"]
    }
    assert metadata_paths == {
        "provenance/audit-report.json",
        "provenance/modules.json",
        expected_review,
    }
    data_paths = {
        record["artifact"] for record in manifest["data_classifications"]
    }
    assert previous_review in data_paths

    report_path = root / expected_review
    report_path.write_bytes(report_path.read_bytes() + b"\npost-review binding bytes\n")
    _manifest_after, mapping_after = regenerate(root)
    assert mapping_after == mapping_before


@pytest.mark.parametrize(
    "review_path",
    [
        "provenance/reviews/clean-room-parity-and-hardening-review-cycle-round-1.md",
        "provenance/reviews/core-docx-review-cycle-round-1.md",
        "provenance/reviews/core-pptx-review-cycle-round-1.md",
        "provenance/reviews/document-skills-0.5.1-consumer-gates-implementation-audit.md",
        "provenance/reviews/document-skills-0.5.2-ci-repair-and-version-bump-review.md",
        "provenance/reviews/document-skills-0.5.3-packaging-hygiene-review.md",
        "provenance/reviews/document-skills-core-xlsx-completion-review-cycle-round-1.md",
        "provenance/reviews/foundation-review-cycle-round-1.md",
        "provenance/reviews/libreoffice-enhancement-review-cycle-round-1.md",
        "provenance/reviews/openxml-dotnet-enhancement-review-cycle-round-1.md",
        "provenance/reviews/document-skills-0.5.3-pptx-b5-merge-review.md",
        "provenance/reviews/document-skills-0.5.3-pptx-b6-merge-review.md",
        "provenance/reviews/document-skills-0.5.3-pptx-b7-merge-review.md",
        "provenance/reviews/document-skills-readme-system-review.md",
    ],
)
def test_historical_reviews_are_hash_pinned_data_not_metadata(
    project_root, review_path
):
    from tools.regenerate_provenance import _is_metadata

    assert _is_metadata(review_path) is False
    with pytest.raises(
        AssertionError,
        match="outside the exact self-reference allowlist",
    ):
        validate_metadata_exclusion(
            project_root,
            {
                "artifact": review_path,
                "classification": "self-referential-audit-metadata",
                "reason": (
                    "A historical report has no circular dependency on the "
                    "current mapping and must retain an exact content hash."
                ),
                "reviewer": "Strategy-2 historical-review test reviewer",
                "review_evidence": [review_path],
            },
            {"Strategy-2 historical-review test reviewer"},
        )


@pytest.mark.parametrize(
    "metadata_path",
    [
        "provenance/audit-report.json",
        "provenance/modules.json",
        CURRENT_REVIEW_ARTIFACT,
    ],
)
def test_is_metadata_accepts_only_digest_cycle_paths(metadata_path):
    from tools.regenerate_provenance import _is_metadata

    assert _is_metadata(metadata_path) is True


@pytest.mark.parametrize(
    ("relative", "payload", "expected_check"),
    [
        (
            "src/document_skills_core/__init__.py",
            "\nloader = __import__\n",
            "execution_boundary",
        ),
        (
            "runtime/node/health.mjs",
            "\nconst loader = createRequire;\n",
            "execution_boundary",
        ),
        (
            "README.md",
            "\n```shell\nenv node runtime/node/health.mjs\n```\n",
            "commands",
        ),
        (
            "runtime/Bin/provider.txt",
            "provider bytes\n",
            "inventory",
        ),
    ],
)
def test_complete_rebound_audit_rejects_semantic_variants(
    project_root, tmp_path, relative, payload, expected_check
):
    root = _release_copy(project_root, tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (target.read_text(encoding="utf-8") if target.exists() else "") + payload,
        encoding="utf-8",
    )
    bind_test_review(root)
    report = run_audits(root)
    assert report["status"] == "fail"
    assert any(error["check"] == expected_check for error in report["errors"])
