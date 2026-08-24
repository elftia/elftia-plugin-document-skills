import json
from pathlib import Path
import shutil

import pytest

from document_skills_core.core.io.portable_paths import PORTABLE_PATH_POLICY
from tests.support.provenance_review_fixture import bind_test_review
from tools.audit import run_audits
from tools.audit_node import audit_node_source
from tools.audit_python import audit_python_source
from tools.command_discovery import CommandDiscovery
from tools.frozen_uv import FrozenUvGrammar
from tools.regenerate_provenance import (
    regenerate,
    xlsx_shared_data_profile,
    xlsx_shared_module_profile,
)
from tools.release_inventory import release_inventory
from tools.supply_chain import build_sbom, canonical_json


PYTHON_DEFINITION_SURFACE_CASES = [
    "def load(loader=__import__): return loader('mcp')\n",
    "@__import__('mcp').decorate\ndef f(): pass\n",
    (
        "builtins_ref=__builtins__\n"
        "loader=builtins_ref.__import__\n"
        "module=loader('mcp')\n"
    ),
    "def f(value: __builtins__['__import__']): pass\n",
    "def f() -> __builtins__.__import__: pass\n",
    "class C(__builtins__['eval']('Base')): pass\n",
    "class C(metaclass=__builtins__.__import__('mcp').Meta): pass\n",
    (
        "root=__builtins__\n"
        "loader=root['__import__']\n"
        "alias=loader\n"
        "alias('mcp')\n"
    ),
]
PYTHON_LAMBDA_AND_BUILTINS_MAPPING_CASES = [
    'loader=(lambda fn=__import__: fn)(); loader("mcp")\n',
    'loader=(lambda *, fn=__import__: fn)(); loader("mcp")\n',
    (
        'root=__builtins__; loader=root.get("__import__"); '
        'loader("mcp")\n'
    ),
    (
        'loader=dict.__getitem__(__builtins__, "__import__"); '
        'loader("mcp")\n'
    ),
    (
        'root=__builtins__; lookup=root.get; alias=lookup; '
        'loader=alias("__import__"); loader("mcp")\n'
    ),
    (
        'lookup=dict.get; alias=lookup; root=__builtins__; '
        'loader=alias(root, "__import__"); loader("mcp")\n'
    ),
    (
        'lookup=dict.__getitem__; root=__builtins__; key="__im"+"port__"; '
        'loader=lookup(root, key); loader("mcp")\n'
    ),
    (
        'loader=(lambda lookup=__builtins__.get: '
        'lookup("__import__"))(); loader("mcp")\n'
    ),
    (
        'loader=(lambda *, lookup=dict.__getitem__: '
        'lookup(__builtins__, "__import__"))(); loader("mcp")\n'
    ),
    "def acquire(key): return __builtins__.get(key)\n",
    (
        "import builtins\n"
        'loader=dict.get(builtins, "eval"); loader("1+1")\n'
    ),
]
PYTHON_RETURN_AND_CONTAINER_CASES = [
    (
        "def namespace():\n"
        "    return __builtins__\n"
        "root = namespace()\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "root = (__builtins__,)[0]\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "def namespace():\n"
        "    return __builtins__\n"
        "alias = namespace\n"
        "root = alias()\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "root = [(__builtins__,)][0][0]\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "root = {'namespace': __builtins__}['namespace']\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "root, = {__builtins__}\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
    (
        "def namespace_record():\n"
        "    return {'namespace': __builtins__}\n"
        "record = namespace_record()\n"
        "root = record.get('namespace')\n"
        "loader = root.get('__import__')\n"
        "loader('mcp')\n"
    ),
]

NODE_GLOBAL_FLOW_CASES = [
    "const loader=globalThis.eval; loader('1+1');\n",
    "const { eval: loader } = globalThis; loader('1+1');\n",
    "const loader=Reflect.get(globalThis,'eval'); loader('1+1');\n",
    "const loader=(()=>{}).constructor; loader('return 1')();\n",
    "const root=global; const loader=root['ev'+'al']; loader('1+1');\n",
    "const root=self; const {eval: loader}=root; loader('1+1');\n",
    "const key='eval'; const root=window; const loader=root[key]; loader('1+1');\n",
    "const reflect=Reflect; const getter=reflect.get; getter({}, 'x');\n",
    "const maker=Function; const alias=maker; alias('return 1')();\n",
]

COMMAND_PREFIX_CASES = [
    '$env:PATH="C:\\tmp"; node runtime/node/health.mjs',
    "set PATH=C:\\tmp && node runtime/node/health.mjs",
    "setx PATH C:\\tmp && node runtime/node/health.mjs",
    "export PATH=/tmp; node runtime/node/health.mjs",
]

PORTABLE_HELPER_CASES = [
    ".VENV/provider.txt",
    "Node_Modules/provider.txt",
    ".venv./provider.txt",
    "runtime/.venv/provider.txt",
    "runtime/Ｎｏｄｅ＿Ｍｏｄｕｌｅｓ/provider.txt",
    "runtime/.ＶＥＮＶ/provider.txt",
    "runtime/node_modules /provider.txt",
]
FORBIDDEN_PATH_CASES = [
    ".VENV/provider.txt",
    "Node_Modules/provider.txt",
    "runtime/.venv/provider.txt",
    "runtime/Ｎｏｄｅ＿Ｍｏｄｕｌｅｓ/provider.txt",
    "runtime/.ＶＥＮＶ/provider.txt",
]


@pytest.mark.parametrize("source", PYTHON_DEFINITION_SURFACE_CASES)
def test_python_definition_surfaces_and_builtins_flow_reject(source):
    with pytest.raises(AssertionError):
        audit_python_source("src/document_skills_core/fixture.py", source)


@pytest.mark.parametrize("source", PYTHON_LAMBDA_AND_BUILTINS_MAPPING_CASES)
def test_python_lambda_and_builtins_mapping_flow_reject(source):
    with pytest.raises(AssertionError):
        audit_python_source("src/document_skills_core/fixture.py", source)


@pytest.mark.parametrize("source", PYTHON_RETURN_AND_CONTAINER_CASES)
def test_python_return_and_literal_container_flow_reject(source):
    with pytest.raises(AssertionError):
        audit_python_source("src/document_skills_core/fixture.py", source)


def test_python_safe_definition_surfaces_and_local_flow_pass():
    audit_python_source(
        "src/document_skills_core/fixture.py",
        (
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n"
            "import re\n"
            "def local(value: Path | None = None) -> Path | None:\n"
            "    return value\n"
            "@dataclass(frozen=True)\n"
            "class Item:\n"
            "    value: str = 'safe'\n"
            "alias = local\n"
            "pattern_factory = re.compile\n"
            "pattern = pattern_factory(r'^[a-z]+$')\n"
            "data = {'value': Item('ok'), '__import__': 'plain data'}\n"
            "plain_get = data.get\n"
            "plain_item = dict.__getitem__\n"
            "plain_get('__import__')\n"
            "plain_item(data, '__import__')\n"
            "safe_lambda = lambda fn=local, *, value='ok': fn(value)\n"
            "safe_lambda()\n"
            "result = alias(data['value'].value)\n"
            "def local_record():\n"
            "    return {'__import__': 'plain data', 'items': ('safe',)}\n"
            "record = local_record()\n"
            "plain_loader_text = record.get('__import__')\n"
            "plain_item_text = record['items'][0]\n"
            "ordinary = [{'value': plain_loader_text}, (plain_item_text,), {'safe'}]\n"
            "first = ordinary[0]['value']\n"
        ),
    )


@pytest.mark.parametrize("source", NODE_GLOBAL_FLOW_CASES)
def test_node_global_reflection_and_constructor_flow_reject(project_root, source):
    with pytest.raises(AssertionError):
        audit_node_source(project_root, "runtime/node/fixture.mjs", source)


def test_node_safe_local_binding_and_plain_data_pass(project_root):
    audit_node_source(
        project_root,
        "runtime/node/fixture.mjs",
        (
            "const data={value:1};\n"
            "const {value}=data;\n"
            "function local(item){return item;}\n"
            "const alias=local;\n"
            "alias(value);\n"
        ),
    )


@pytest.mark.parametrize("source", COMMAND_PREFIX_CASES)
def test_platform_environment_prefixes_are_discovered_and_rejected(source):
    discovered = CommandDiscovery().discover(source)
    assert discovered is not None
    assert discovered.effective_executable.casefold() == "node"
    assert FrozenUvGrammar().authorize(discovered) is False


def test_safe_quoted_unicode_uv_control_stays_authorized():
    source = (
        'uv run --project "<project-root>" --frozen python '
        '"<skill-dir>/scripts/run.py" run --request '
        '"C:\\工作 文件\\请求.json"'
    )
    discovered = CommandDiscovery().discover(source)
    assert discovered is not None
    assert FrozenUvGrammar().authorize(discovered) is True


def test_consumer_gate_provenance_uses_current_direct_evidence(project_root):
    manifest, _digest = regenerate(project_root)
    records = {record["module"]: record for record in manifest["modules"]}
    expected_tests = [
        "tests/test_consumer_validation.py",
        "tests/test_consumer_validation_strategy3.py",
        "tests/test_cross_format_transactions.py",
    ]
    for path in (
        "consumer_validation/office.py",
        "consumer_validation/pdf_evidence.py",
        "tests/test_consumer_validation_strategy3.py",
        "tests/test_cross_format_transactions.py",
    ):
        record = records[path]
        assert record["requirement_source"] == (
            "Rasen document-skills-consumer-gates-and-truthful-contracts"
        )
        assert "Strategy-4" in record["modifications"]
        assert record["artifact_tests"] == expected_tests

    shared_consumer = records["tests/test_consumer_validation.py"]
    assert shared_consumer["requirement_source"] == (
        "Rasen document-skills-consumer-gates-and-truthful-contracts + "
        "document-skills-core-xlsx"
    )
    assert "Strategy-4" in shared_consumer["modifications"]
    assert "Shared Core XLSX" in shared_consumer["modifications"]
    assert set(expected_tests) < set(shared_consumer["artifact_tests"])

    for path in (
        "tests/fixtures/recipes/docx_fixtures.py",
        "tests/test_docx_fixtures.py",
    ):
        record = records[path]
        assert "document-skills-consumer-gates-and-truthful-contracts" in (
            record["requirement_source"]
        )
        assert "nested frozen-uv" in record["modifications"]
        assert "tests/test_docx_fixtures.py" in record["artifact_tests"]

    generator = records["tools/regenerate_provenance.py"]
    assert "document-skills-consumer-gates-and-truthful-contracts" in (
        generator["requirement_source"]
    )
    assert "Strategy-4" in generator["modifications"]
    assert "tests/test_strategy3.py" in generator["artifact_tests"]


def test_xlsx_provenance_uses_current_direct_evidence(project_root):
    manifest, _digest = regenerate(project_root)
    records = {record["module"]: record for record in manifest["modules"]}
    expected_tests = [
        "tests/test_xlsx_contracts.py",
        "tests/test_xlsx_operations.py",
        "tests/test_xlsx_pivot.py",
        "tests/test_xlsx_provider_qa.py",
        "tests/test_xlsx_public.py",
        "tests/test_xlsx_recalculation.py",
        "tests/test_supply_chain.py",
    ]
    for path in (
        "src/document_skills_core/formats/xlsx/render_operation.py",
        "skills/document-xlsx/scripts/run.py",
        "tests/test_xlsx_provider_qa.py",
    ):
        record = records[path]
        assert record["requirement_source"] == "Rasen document-skills-core-xlsx"
        assert "Core XLSX" in record["modifications"]
        assert record["artifact_tests"] == expected_tests


def test_shared_xlsx_provenance_composes_requirements_and_direct_evidence(
    project_root,
):
    manifest, _digest = regenerate(project_root)
    records = {record["module"]: record for record in manifest["modules"]}
    expected_paths = {
        "src/document_skills_core/core/io/ooxml_security.py",
        "src/document_skills_core/core/process/executable.py",
        "src/document_skills_core/core/process/runner.py",
        "src/document_skills_core/core/process/windows_handles.py",
        "src/document_skills_core/formats/pdf/byte_preflight.py",
        "src/document_skills_core/providers/defaults.py",
        "src/document_skills_core/providers/dotnet/constants.py",
        "src/document_skills_core/providers/dotnet/detector.py",
        "src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj",
        "src/document_skills_core/providers/dotnet/helper/Program.cs",
        "src/document_skills_core/providers/dotnet/helper/packages.lock.json",
        "src/document_skills_core/providers/dotnet/runner.py",
        "src/document_skills_core/providers/dotnet/schema.py",
        "src/document_skills_core/providers/dotnet/service.py",
        "src/document_skills_core/providers/libreoffice/constants.py",
        "src/document_skills_core/providers/libreoffice/convert.py",
        "src/document_skills_core/providers/libreoffice/detector.py",
        "src/document_skills_core/providers/libreoffice/input_snapshot.py",
        "src/document_skills_core/providers/libreoffice/legacy.py",
        "src/document_skills_core/providers/libreoffice/output.py",
        "src/document_skills_core/providers/libreoffice/quota.py",
        "src/document_skills_core/providers/libreoffice/recalc.py",
        "src/document_skills_core/providers/libreoffice/render.py",
        "src/document_skills_core/providers/libreoffice/runner.py",
        "src/document_skills_core/providers/libreoffice/service.py",
        "src/document_skills_core/public_cli/supervisor.py",
        "tests/test_consumer_validation.py",
        "tests/test_dotnet_provider.py",
        "tests/test_html_provenance.py",
        "tests/test_input_snapshot_security.py",
        "tests/test_libreoffice_hard_quota.py",
        "tests/test_libreoffice_provider.py",
        "tests/test_process_executable_identity.py",
        "tests/test_runtime.py",
        "tests/test_safety.py",
        "tests/test_strategy2.py",
        "tests/test_strategy3.py",
        "tests/test_structure.py",
        "tests/test_supply_chain.py",
        "tests/test_truthful_results.py",
        "tools/audit.py",
        "tools/audit_execution.py",
        "tools/provenance_records.py",
        "tools/python_policy_definitions.py",
        "tools/regenerate_provenance.py",
        "tools/release_inventory.py",
        "tools/supply_chain.py",
    }
    profiled_paths = {
        path for path in records if xlsx_shared_module_profile(path)
    }
    assert profiled_paths == expected_paths
    assert len(profiled_paths) == 47
    xlsx_requirement = "Rasen document-skills-core-xlsx"
    html_xlsx_requirement = (
        "Rasen html-to-editable-pptx + document-skills-core-xlsx"
    )
    html_paths = {
        "src/document_skills_core/providers/defaults.py",
        "src/document_skills_core/public_cli/supervisor.py",
        "tests/test_html_provenance.py",
        "tests/test_runtime.py",
        "tests/test_supply_chain.py",
        "tools/provenance_records.py",
        "tools/supply_chain.py",
    }
    required_evidence = {
        "tests/test_xlsx_contracts.py",
        "tests/test_xlsx_operations.py",
        "tests/test_xlsx_provider_qa.py",
        "tests/test_xlsx_public.py",
        "tests/test_xlsx_recalculation.py",
        "tests/test_dotnet_provider.py",
        "tests/test_dotnet_xlsx_schema_real.py",
        "tests/test_input_snapshot_security.py",
        "tests/test_libreoffice_hard_quota.py",
        "tests/test_libreoffice_provider.py",
        "tests/test_process_executable_identity.py",
        "tests/test_runtime.py",
        "tests/test_safety.py",
        "tests/test_supply_chain.py",
    }
    atomic_launch_only_paths = {
        "src/document_skills_core/core/process/executable.py",
        "src/document_skills_core/core/process/windows_handles.py",
        "tests/test_process_executable_identity.py",
    }
    atomic_launch_composed_paths = {
        "src/document_skills_core/core/process/runner.py",
        "src/document_skills_core/providers/dotnet/detector.py",
        "src/document_skills_core/providers/dotnet/runner.py",
        "src/document_skills_core/providers/dotnet/service.py",
        "src/document_skills_core/providers/libreoffice/detector.py",
    }
    assert (
        atomic_launch_only_paths | atomic_launch_composed_paths
    ) <= expected_paths
    assert len(atomic_launch_only_paths | atomic_launch_composed_paths) == 8
    shared_description = (
        "Shared Core XLSX provider execution, managed CLI supervision, and exact "
        "supply-chain policy for bounded OpenXML validation and LibreOffice rendering."
    )
    atomic_launch_description = (
        "Identity-bound top-level native executable launch: Windows hashes and resolves "
        "one followed handle, then holds canonical parent and executable handles through "
        "CreateProcess; Linux executes the verified fd via /proc/self/fd with pass_fds. "
        "Pre-lease identity drift and detector-to-operation races fail closed; final-window "
        "same-path replacement cannot redirect the pinned launch object. Windows share "
        "mode blocks hardlink-alias writes, and partial handle acquisition closes each "
        "owned handle exactly once. Identity capture or change, non-Linux POSIX or script "
        "native-unavailable cases, and spawn failures use sanitized typed categories "
        "without raw OS details. The binding excludes argv-selected helpers and the "
        "dynamic DLL or dependency closure."
    )
    for path in expected_paths:
        requirement = (
            "Rasen html-to-editable-pptx + "
            "document-skills-consumer-gates-and-truthful-contracts + "
            "document-skills-core-xlsx"
            if path == "tools/regenerate_provenance.py"
            else (
                "Rasen document-skills-consumer-gates-and-truthful-contracts + "
                "document-skills-core-xlsx"
            )
            if path == "tests/test_consumer_validation.py"
            else html_xlsx_requirement
            if path in html_paths
            else xlsx_requirement
        )
        record = records[path]
        assert record["requirement_source"] == requirement
        if path in atomic_launch_only_paths:
            assert record["modifications"] == atomic_launch_description
        elif path in atomic_launch_composed_paths:
            assert record["modifications"] == (
                f"{shared_description} {atomic_launch_description}"
            )
        elif path.endswith("packages.lock.json"):
            assert "Exact NuGet dependency lock" in record["modifications"]
        else:
            assert "Shared Core XLSX" in record["modifications"]
        assert required_evidence <= set(record["artifact_tests"])


def test_shared_xlsx_nuget_data_provenance_is_exact_and_composed(project_root):
    manifest, _digest = regenerate(project_root)
    records = {
        record["artifact"]: record
        for record in manifest["data_classifications"]
    }
    html_xlsx_requirement = (
        "Rasen html-to-editable-pptx + document-skills-core-xlsx"
    )
    expected_requirements = {
        "THIRD_PARTY_NOTICES.md": html_xlsx_requirement,
        "provenance/dependency-allowlist.json": html_xlsx_requirement,
        "provenance/dependency-licenses.json": html_xlsx_requirement,
        "provenance/runtime-source-allowlist.json": (
            "Rasen document-skills-core-xlsx"
        ),
        "sbom.cdx.json": html_xlsx_requirement,
    }
    nuget_description = (
        "Exact NuGet dependency lock, allowlist, license, notice, and SBOM evidence "
        "for the bounded OpenXML helper used by Core XLSX schema validation."
    )
    runtime_description = (
        "Strict value-flow runtime file inventory for the Core XLSX Python source set "
        "and its execution-boundary audit."
    )
    expected_descriptions = {
        "THIRD_PARTY_NOTICES.md": nuget_description,
        "provenance/dependency-allowlist.json": nuget_description,
        "provenance/dependency-licenses.json": nuget_description,
        "provenance/runtime-source-allowlist.json": runtime_description,
        "sbom.cdx.json": nuget_description,
    }
    profiled_paths = {
        path for path in records if xlsx_shared_data_profile(path)
    }
    assert profiled_paths == set(expected_requirements)
    assert len(profiled_paths) == 5
    required_evidence = {
        "tests/test_xlsx_contracts.py",
        "tests/test_xlsx_operations.py",
        "tests/test_xlsx_provider_qa.py",
        "tests/test_xlsx_public.py",
        "tests/test_xlsx_recalculation.py",
        "tests/test_dotnet_provider.py",
        "tests/test_dotnet_xlsx_schema_real.py",
        "tests/test_input_snapshot_security.py",
        "tests/test_libreoffice_hard_quota.py",
        "tests/test_process_executable_identity.py",
        "tests/test_runtime.py",
        "tests/test_safety.py",
        "tests/test_supply_chain.py",
    }
    for path, requirement in expected_requirements.items():
        record = records[path]
        assert record["requirement_source"] == requirement
        if requirement == html_xlsx_requirement:
            assert record["modifications"].endswith(expected_descriptions[path])
        else:
            assert record["modifications"] == expected_descriptions[path]
        assert required_evidence <= set(record["artifact_tests"])

    modules = {record["module"]: record for record in manifest["modules"]}
    lock = modules[
        "src/document_skills_core/providers/dotnet/helper/packages.lock.json"
    ]
    assert lock["requirement_source"] == "Rasen document-skills-core-xlsx"
    assert lock["modifications"] == nuget_description
    assert required_evidence <= set(lock["artifact_tests"])


@pytest.mark.parametrize("relative", PORTABLE_HELPER_CASES)
def test_portable_path_helper_rejects_all_aliases(relative):
    with pytest.raises(ValueError):
        PORTABLE_PATH_POLICY.require_release_safe(relative)


@pytest.mark.parametrize("relative", FORBIDDEN_PATH_CASES)
def test_forbidden_aliases_remain_in_inventory_before_rejection(
    project_root, tmp_path, relative
):
    root = _release_copy(project_root, tmp_path / _case_name(relative))
    target = _artifact_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("forbidden release bytes\n", encoding="utf-8")
    normalized = target.relative_to(root).as_posix()
    assert normalized in release_inventory(root)
    with pytest.raises(ValueError):
        PORTABLE_PATH_POLICY.require_release_safe(normalized)
    manifest, _digest = regenerate(root)
    mapped = {
        *(record["module"] for record in manifest["modules"]),
        *(record["artifact"] for record in manifest["data_classifications"]),
    }
    assert normalized in mapped
    with pytest.raises(ValueError):
        build_sbom(root)


@pytest.mark.parametrize("local_root", [".venv", "node_modules"])
def test_exact_root_local_generated_state_is_independently_excluded(
    project_root, tmp_path, local_root
):
    root = _release_copy(project_root, tmp_path / local_root.replace(".", "dot"))
    target = root / local_root / "local-only.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("generated local state\n", encoding="utf-8")
    assert target.relative_to(root).as_posix() not in release_inventory(root)


@pytest.mark.parametrize(
    ("relative", "payload", "expected_check", "expected_detail"),
    [
        (
            "src/document_skills_core/__init__.py",
            "\ndef load(loader=__import__): return loader('mcp')\n",
            "execution_boundary",
            "Dangerous builtin identity referenced: __import__",
        ),
        (
            "src/document_skills_core/__init__.py",
            "\n@__import__('mcp').decorate\ndef decorated(): pass\n",
            "execution_boundary",
            "Dangerous builtin identity referenced: __import__",
        ),
        (
            "src/document_skills_core/__init__.py",
            (
                "\nbuiltins_ref=__builtins__\n"
                "loader=builtins_ref.__import__\n"
                "loader('mcp')\n"
            ),
            "execution_boundary",
            "Dangerous loader/reflection attribute: __import__",
        ),
        (
            "src/document_skills_core/__init__.py",
            '\nloader=(lambda fn=__import__: fn)(); loader("mcp")\n',
            "execution_boundary",
            "Dangerous builtin identity referenced: __import__",
        ),
        (
            "src/document_skills_core/__init__.py",
            (
                '\nroot=__builtins__; loader=root.get("__import__"); '
                'loader("mcp")\n'
            ),
            "execution_boundary",
            "Builtin namespace loader/reflection lookup is forbidden",
        ),
        (
            "src/document_skills_core/__init__.py",
            (
                '\nloader=dict.__getitem__(__builtins__, "__import__"); '
                'loader("mcp")\n'
            ),
            "execution_boundary",
            "Builtin namespace loader/reflection lookup is forbidden",
        ),
        (
            "src/document_skills_core/__init__.py",
            (
                "\ndef namespace():\n"
                "    return __builtins__\n"
                "root = namespace()\n"
                "loader = root.get('__import__')\n"
                "loader('mcp')\n"
            ),
            "execution_boundary",
            "Builtin namespace loader/reflection lookup is forbidden",
        ),
        (
            "src/document_skills_core/__init__.py",
            (
                "\nroot = (__builtins__,)[0]\n"
                "loader = root.get('__import__')\n"
                "loader('mcp')\n"
            ),
            "execution_boundary",
            "Builtin namespace loader/reflection lookup is forbidden",
        ),
        (
            "runtime/node/health.mjs",
            "\nconst loader=globalThis.eval; loader('1+1');\n",
            "execution_boundary",
            "dangerous Node binding flow:runtime/node/health.mjs",
        ),
        (
            "runtime/node/health.mjs",
            "\nconst {eval: loader}=globalThis; loader('1+1');\n",
            "execution_boundary",
            "dangerous Node binding flow:runtime/node/health.mjs",
        ),
        (
            "runtime/node/health.mjs",
            "\nconst loader=Reflect.get(globalThis,'eval'); loader('1+1');\n",
            "execution_boundary",
            "dangerous Node callable flow:runtime/node/health.mjs",
        ),
        (
            "runtime/node/health.mjs",
            "\nconst loader=(()=>{}).constructor; loader('return 1')();\n",
            "execution_boundary",
            "dangerous Node binding flow:runtime/node/health.mjs",
        ),
        (
            "README.md",
            '\n```powershell\n$env:PATH="C:\\tmp"; node runtime/node/health.mjs\n```\n',
            "commands",
            "Agent command is outside the exact frozen uv families",
        ),
        (
            "README.md",
            "\n```cmd\nset PATH=C:\\tmp && node runtime/node/health.mjs\n```\n",
            "commands",
            "Agent command is outside the exact frozen uv families",
        ),
        (
            "README.md",
            "\n```shell\nexport PATH=/tmp; node runtime/node/health.mjs\n```\n",
            "commands",
            "Agent command is outside the exact frozen uv families",
        ),
    ],
)
def test_full_rebound_audit_rejects_attempt3_semantic_bypasses(
    project_root, tmp_path, relative, payload, expected_check, expected_detail
):
    root = _release_copy_with_node_runtime(
        project_root, tmp_path / _case_name(payload)
    )
    target = root / relative
    target.write_text(
        target.read_text(encoding="utf-8") + payload,
        encoding="utf-8",
    )
    (root / "sbom.cdx.json").write_text(
        canonical_json(build_sbom(root)),
        encoding="utf-8",
    )
    bind_test_review(root)
    report = run_audits(root)
    assert report["status"] == "fail"
    assert report["errors"] == [
        {
            "check": expected_check,
            "message": report["errors"][0]["message"],
        }
    ]
    assert expected_detail in report["errors"][0]["message"]
    assert "Locked Node AST parser returned invalid JSON" not in report["errors"][0]["message"]
    for check, result in report["checks"].items():
        assert result["status"] == ("fail" if check == expected_check else "pass")


@pytest.mark.parametrize("relative", FORBIDDEN_PATH_CASES)
def test_full_rebound_audit_rejects_attempt3_portable_roots(
    project_root, tmp_path, relative
):
    root = _release_copy(project_root, tmp_path / _case_name(relative))
    target = _artifact_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("forbidden release bytes\n", encoding="utf-8")
    bind_test_review(root)
    report = run_audits(root)
    assert report["status"] == "fail"
    failed = {error["check"] for error in report["errors"]}
    assert {"inventory", "provenance", "sbom"} <= failed


def _release_copy(project_root: Path, destination: Path) -> Path:
    return Path(
        shutil.copytree(
            project_root,
            destination,
            ignore=shutil.ignore_patterns(
                ".venv",
                "node_modules",
                "__pycache__",
                ".pytest_cache",
                ".document-skills-tmp",
            ),
        )
    )


def _release_copy_with_node_runtime(
    project_root: Path,
    destination: Path,
) -> Path:
    root = _release_copy(project_root, destination)
    source = project_root / "node_modules" / "acorn"
    assert source.is_dir(), "Focused rebound tests require the locked Acorn install"
    lock = json.loads((project_root / "package-lock.json").read_text(encoding="utf-8"))
    expected = lock["packages"]["node_modules/acorn"]["version"]
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == expected
    shutil.copytree(source, root / "node_modules" / "acorn")
    return root


def _case_name(value: str) -> str:
    return str(abs(hash(value)))


def _artifact_path(root: Path, relative: str) -> Path:
    return root.joinpath(*relative.replace("\\", "/").split("/"))
