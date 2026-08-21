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
        "hostile",
        "huge-string",
        "huge-int",
        "surrogate",
        "unicode",
    ],
)
def test_public_supervisor_is_one_json_protocol(
    project_root, command, mode
):
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
        timeout=15,
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
            str(
                project_root
                / "skills"
                / "document-docx"
                / "scripts"
                / "run.py"
            ),
            "doctor",
            "--json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    doctor_state = {
        item["id"]: item for item in json.loads(doctor.stdout)["providers"]
    }
    capability = build_capabilities(project_root, "docx", registry)
    capability_state = {item["id"]: item for item in capability["providers"]}
    assert "core-node-protocol" not in doctor.stdout
    assert doctor_state["core-node"]["available"] is True
    assert capability_state["core-node"]["available"] is True
    assert doctor_state["core-node"]["version"] == capability_state["core-node"]["version"]
    operations = {item["operation"]: item for item in capability["operations"]}
    assert set(operations) == {
        "docx.create",
        "docx.edit.replace-text",
        "docx.inspect.structure",
        "docx.read",
        "docx.template.apply",
    }
    assert operations["docx.template.apply"]["providers"] == ["core-node"]
    assert all(item["available"] for item in operations.values())
    assert not any(
        provider in item["providers"]
        for item in operations.values()
        for provider in ("libreoffice", "dotnet-openxml")
    )
    assert capability["validation"]["schema"] == "unavailable"
    assert capability["validation"]["visual"] == "unavailable"


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
    assert build_capabilities(
        project_root, "docx", catalog(available, lambda _op, _req: {})
    )["operations"][0]["available"] is True
    assert build_capabilities(
        project_root, "docx", catalog(unavailable, lambda _op, _req: {})
    )["operations"][0]["available"] is False
    assert build_capabilities(
        project_root, "docx", catalog(available, None)
    )["operations"] == []


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
    assert run_audits(root)["status"] == "pass"


@pytest.mark.parametrize(
    "review_path",
    [
        "provenance/reviews/clean-room-parity-and-hardening-review-cycle-round-1.md",
        "provenance/reviews/core-docx-review-cycle-round-1.md",
        "provenance/reviews/document-skills-0.5.1-consumer-gates-implementation-audit.md",
        "provenance/reviews/document-skills-0.5.2-ci-repair-and-version-bump-review.md",
        "provenance/reviews/document-skills-0.5.3-packaging-hygiene-review.md",
        "provenance/reviews/foundation-review-cycle-round-1.md",
        "provenance/reviews/libreoffice-enhancement-review-cycle-round-1.md",
        "provenance/reviews/openxml-dotnet-enhancement-review-cycle-round-1.md",
    ],
)
def test_is_metadata_accepts_every_bound_review_path(review_path):
    """Both the regenerate_provenance and provenance_records allowlists must
    accept every review path that can be bound as a metadata exclusion."""
    from tools.regenerate_provenance import _is_metadata

    assert _is_metadata(review_path) is True, (
        f"_is_metadata must accept {review_path}"
    )


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
