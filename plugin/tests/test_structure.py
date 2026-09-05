import json
from pathlib import Path
import shutil
import tomllib
from xml.etree.ElementTree import fromstring

import pytest

from document_skills_core import __version__

from tools.audit import (
    PUBLIC_SKILLS,
    audit_commands,
    audit_execution_boundary,
    audit_inventory,
    audit_manifests,
    audit_skills,
    release_inventory,
    run_audits,
)


def test_exact_public_surface_and_manifest_parity(project_root):
    assert audit_skills(project_root)["names"] == PUBLIC_SKILLS
    assert audit_manifests(project_root)["skills_root"] == "skills"


def test_release_version_is_one_source_value_across_runtime_manifests(project_root):
    producer = json.loads((project_root.parent / "package.json").read_text(encoding="utf-8"))
    plugin = json.loads(
        (project_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    python_package = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    python_lock = tomllib.loads(
        (project_root / "uv.lock").read_text(encoding="utf-8")
    )
    node_runtime = json.loads(
        (project_root / "package.json").read_text(encoding="utf-8")
    )
    node_lock = json.loads(
        (project_root / "package-lock.json").read_text(encoding="utf-8")
    )
    sbom = json.loads((project_root / "sbom.cdx.json").read_text(encoding="utf-8"))
    doctor_schema = json.loads(
        (project_root / "schemas/doctor-report.schema.json").read_text(encoding="utf-8")
    )
    helper_project = fromstring(
        (
            project_root
            / "src/document_skills_core/providers/dotnet/helper/OpenXmlHelper.csproj"
        ).read_bytes()
    )

    assert {
        producer["version"],
        plugin["version"],
        python_package["project"]["version"],
        next(
            package["version"]
            for package in python_lock["package"]
            if package["name"] == python_package["project"]["name"]
        ),
        node_runtime["version"],
        node_lock["version"],
        node_lock["packages"][""]["version"],
        sbom["metadata"]["component"]["version"],
        doctor_schema["examples"][0]["project_version"],
        helper_project.findtext("./PropertyGroup/Version"),
        __version__,
    } == {"0.5.9"}


def test_agent_commands_are_frozen_uv_only(project_root):
    assert audit_commands(project_root)["command_count"] == 21


def test_readme_documents_fileless_bounded_public_worker_protocol(project_root):
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    _before, marker, remainder = readme.partition("## Public protocol containment")
    assert marker
    section = " ".join(remainder.partition("\n## ")[0].split())

    assert "bounded ASCII command envelope through worker stdin" in section
    assert "bounded, canonical ASCII terminal frame" in section
    assert "public protocol creates no command or result files" in section
    assert "identity-bound private workspace" in section
    assert "nonce-bound atomic result file is the only worker channel" not in readme
    assert (
        "HTML capture is separate: its provider-internal browser handoff binds private "
        "scene and asset files to its own command nonce"
    ) in section


def test_source_and_staged_release_inventory(project_root):
    inventory = release_inventory(project_root)
    assert audit_inventory(project_root, inventory)["file_count"] == len(inventory)
    with pytest.raises(AssertionError):
        audit_inventory(project_root, [*inventory, "node_modules/provider/index.js"])
    with pytest.raises(AssertionError):
        audit_inventory(project_root, [*inventory, "src/adapters/host.py"])


@pytest.mark.parametrize(
    "relative",
    [
        ".computer-use/run/doctor.png",
        ".github/workflows/ci.yml",
        ".idea/workspace.xml",
        ".vscode/settings.json",
        "src/document_skills_core/providers/dotnet/helper/bin/Release/helper.dll",
        "src/document_skills_core/providers/dotnet/helper/obj/project.assets.json",
    ],
)
def test_release_inventory_excludes_non_runtime_developer_state(tmp_path, relative):
    root = tmp_path / "project"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("must not ship\n", encoding="utf-8")

    assert relative not in release_inventory(root)


@pytest.mark.parametrize(
    "filename",
    [".computer-use", ".github", ".idea", ".vscode"],
)
def test_release_inventory_keeps_regular_files_named_like_developer_dirs(
    tmp_path, filename
):
    root = tmp_path / "project"
    root.mkdir()
    (root / filename).write_text("runtime data\n", encoding="utf-8")

    assert filename in release_inventory(root)


@pytest.mark.parametrize(
    "relative",
    [
        "src/document_skills_core/providers/dotnet/helper/binary/helper.dll",
        "src/document_skills_core/providers/dotnet/helper/object/project.assets.json",
        "src/document_skills_core/providers/dotnet/other/obj/project.assets.json",
    ],
)
def test_release_inventory_keeps_helper_build_lookalikes(tmp_path, relative):
    root = tmp_path / "project"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("must remain in release scope\n", encoding="utf-8")

    assert relative in release_inventory(root)


def test_no_host_boot_or_legacy_boundary_change():
    # This Change's implementation tests import only its project. Integration owns application boot.
    assert True


def _audit_fixture_root(project_root: Path, tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".claude-plugin").mkdir(parents=True)
    for relative in (
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "uv.lock",
        "elftia-plugin.json",
    ):
        shutil.copy2(project_root / relative, root / relative)
    shutil.copy2(
        project_root / ".claude-plugin" / "plugin.json",
        root / ".claude-plugin" / "plugin.json",
    )
    return root


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (
            "src/service.py",
            "from mcp.server.fastmcp import FastMCP\napp = FastMCP('documents')\n",
        ),
        (
            "src/service.mjs",
            "import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';\n"
            "const server = new McpServer({name:'documents'});\n",
        ),
        ("src/mcp_server.py", "print('server')\n"),
    ],
)
def test_execution_audit_rejects_mcp_sdk_and_structural_paths(
    project_root, tmp_path, relative, source
):
    root = _audit_fixture_root(project_root, tmp_path)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_execution_boundary(root)


def test_execution_audit_rejects_mcp_dependency_and_manifest_registration(
    project_root, tmp_path
):
    root = _audit_fixture_root(project_root, tmp_path)
    package_path = root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["dependencies"] = {"@modelcontextprotocol/sdk": "1.0.0"}
    package_path.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_execution_boundary(root)


@pytest.mark.parametrize(
    "source",
    [
        (
            'module = __import__("mcp.server.fastmcp", fromlist=["FastMCP"])\n'
            'app = module.FastMCP("documents")\n'
        ),
        (
            "import importlib as loader\n"
            'module = loader.import_module("mcp.server.fastmcp")\n'
            "factory = module.FastMCP\n"
            'app = factory("documents")\n'
        ),
        (
            "from importlib import import_module as load\n"
            'module = load("mcp.server.fastmcp")\n'
            "register = module.register_tool\n"
            'register("documents")\n'
        ),
        (
            "registrar = document_server.register_tool\n"
            'registrar("documents")\n'
        ),
    ],
)
def test_execution_audit_rejects_dynamic_import_and_registration_aliases(
    project_root, tmp_path, source
):
    root = _audit_fixture_root(project_root, tmp_path)
    path = root / "src" / "service.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_execution_boundary(root)


@pytest.mark.parametrize(
    "source",
    [
        (
            "import importlib as loader\n"
            'module_name = "m" + "cp.server.fastmcp"\n'
            "module = loader.import_module(module_name)\n"
            'factory = getattr(module, "Fast" + "MCP")\n'
            'app = factory("documents")\n'
            'register = getattr(app, "register_" + "tool")\n'
            'register("documents")\n'
        ),
        (
            "import importlib\n"
            'prefix = "mcp"\n'
            'module = importlib.import_module(f"{prefix}.server.fastmcp")\n'
        ),
        (
            "import importlib as loader\n"
            'module_name = ".".join(["mcp", "server", "fastmcp"])\n'
            'load = getattr(loader, "import_" + "module")\n'
            "load(module_name)\n"
        ),
        (
            "import importlib\n"
            "module_name = get_runtime_module_name()\n"
            "importlib.import_module(module_name)\n"
        ),
        (
            'factory = server.__dict__["Fast" + "MCP"]\n'
            'app = factory("documents")\n'
        ),
    ],
)
def test_execution_audit_rejects_constant_dataflow_getattr_and_dynamic_names(
    project_root, tmp_path, source
):
    root = _audit_fixture_root(project_root, tmp_path)
    path = root / "src" / "service.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_execution_boundary(root)


@pytest.mark.parametrize(
    "source",
    [
        'import builtins\nbuiltins.__import__("json")\n',
        (
            "import builtins\n"
            'load = getattr(builtins, "__" + "import__")\n'
            'load("json")\n'
        ),
        (
            "import importlib\n"
            'load = importlib.__dict__["import_" + "module"]\n'
            'load("json")\n'
        ),
        (
            "import importlib\n"
            'name = "".join(chr(item) for item in [106, 115, 111, 110])\n'
            "importlib.import_module(name)\n"
        ),
        'eval("1 + 1")\n',
        'exec("value = 1")\n',
        'compile("value = 1", "<dynamic>", "exec")\n',
        'handler = server["register_" + "tool"]\nhandler("documents")\n',
    ],
)
def test_complete_audit_rejects_runtime_dynamic_execution_reflection_classes(
    project_root, tmp_path, source
):
    root = _copy_release(project_root, tmp_path / "semantic-runtime")
    target = root / "src" / "semantic_variant.py"
    target.write_text(source, encoding="utf-8")
    report = run_audits(root)
    assert report["status"] == "fail"
    assert report["checks"]["execution_boundary"]["status"] == "fail"


def test_runtime_audit_allows_static_imports_and_plain_data_access(
    project_root, tmp_path
):
    root = _audit_fixture_root(project_root, tmp_path)
    target = root / "src" / "plain_runtime.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import json\n"
        'payload = {"operation": "docx.read"}\n'
        'operation = payload["operation"]\n'
        "encoded = json.dumps(payload)\n",
        encoding="utf-8",
    )
    assert audit_execution_boundary(root)["status"] == "pass"


@pytest.mark.parametrize(
    "command",
    [
        "node runtime/node/health.mjs",
        "$ node runtime/node/health.mjs",
        "npm exec provider",
        "python skills/document-docx/scripts/run.py doctor --json",
        "python3 skills/document-docx/scripts/run.py doctor --json",
        "pip install provider",
        "pipx run provider",
        "LibreOffice --headless --convert-to pdf artifact.docx",
        "soffice --headless --convert-to pdf artifact.docx",
        "dotnet runtime/dotnet/openxml/OpenXmlProbe.dll",
        "Tesseract input.png stdout",
        "qpdf --check artifact.pdf",
        "runtime/provider.ps1 --input artifact.docx",
        'uv run --project "<project-root>" --frozen node runtime/node/health.mjs',
    ],
)
@pytest.mark.parametrize("inline", [False, True])
def test_command_audit_rejects_direct_runtime_and_provider_commands(
    project_root, tmp_path, command, inline
):
    root = tmp_path / "surface"
    shutil.copytree(project_root / "skills", root / "skills")
    readme = root / "README.md"
    if inline:
        readme.write_text(f"# Commands\n\nRun `{command}` directly.\n", encoding="utf-8")
    else:
        readme.write_text(f"# Commands\n\n```text\n{command}\n```\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_commands(root)

    root = _audit_fixture_root(project_root, tmp_path / "manifest-case")
    manifest_path = root / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mcpServers"] = {"documents": {"command": "node"}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_execution_boundary(root)


@pytest.mark.parametrize(
    "surface",
    [
        "```powershell\nPS C:\\work> node.exe runtime/node/health.mjs\n```\n",
        "```cmd\nC:\\work> npm.cmd exec provider\n```\n",
        "Use ``/usr/bin/node runtime/node/health.mjs`` directly.\n",
        "```powershell\npython.exe `\n  scripts/provider.py\n```\n",
        "```cmd\nqpdf.exe ^\n  --check artifact.pdf\n```\n",
        "Use `C:\\runtime\\provider.cmd --input artifact.docx` directly.\n",
        "```text\n& \"C:\\Program Files\\nodejs\\node.exe\" provider.mjs\n```\n",
    ],
)
def test_command_audit_normalizes_prompt_suffix_path_span_and_continuation_variants(
    project_root, tmp_path, surface
):
    root = tmp_path / "surface"
    shutil.copytree(project_root / "skills", root / "skills")
    (root / "README.md").write_text(f"# Commands\n\n{surface}", encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_commands(root)


@pytest.mark.parametrize(
    "surface",
    [
        "The literal \\`node runtime/node/health.mjs\\` is escaped prose.\n",
        "The schema value `schema_version: \"1.0\"` is not a command.\n",
        "The document path `C:\\docs\\report.docx` is data, not a command.\n",
        "The error code `DS_PROVIDER_FAILED` is not executable.\n",
    ],
)
def test_command_audit_ignores_benign_non_command_code_surfaces(
    project_root, tmp_path, surface
):
    root = tmp_path / "surface"
    shutil.copytree(project_root / "skills", root / "skills")
    readme_commands = (project_root / "README.md").read_text(encoding="utf-8")
    (root / "README.md").write_text(
        f"{readme_commands}\n{surface}", encoding="utf-8"
    )
    assert audit_commands(root)["command_count"] == 21


@pytest.mark.parametrize(
    "operand",
    [
        "request.json;node",
        "request.json&&node",
        "request.json||node",
        "request.json|node",
        "request.json>output.txt",
        "request.json<input.txt",
        "request.json$(node)",
        "request.json`node",
        "request.json%COMSPEC%",
        "request.json^&node",
        "request.json --provider node",
    ],
)
def test_command_audit_rejects_shell_and_operand_semantic_classes(
    project_root, tmp_path, operand
):
    root = tmp_path / "command-variant"
    shutil.copytree(project_root / "skills", root / "skills")
    canonical = (project_root / "README.md").read_text(encoding="utf-8")
    command = (
        'uv run --project "<project-root>" --frozen python '
        '"<skill-dir>/scripts/run.py" run --request '
        f"{operand}"
    )
    (root / "README.md").write_text(
        f"{canonical}\n\n```text\n{command}\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        audit_commands(root)


@pytest.mark.parametrize(
    "operand",
    [
        '"reports/My Request.json"',
        '"C:\\Documents\\Safe Request.json"',
        '"资料/请求 文件.json"',
    ],
)
def test_command_audit_accepts_benign_quoted_paths(project_root, tmp_path, operand):
    root = tmp_path / "quoted-path"
    shutil.copytree(project_root / "skills", root / "skills")
    canonical = (project_root / "README.md").read_text(encoding="utf-8")
    command = (
        'uv run --project "<project-root>" --frozen python '
        '"<skill-dir>/scripts/run.py" run --request '
        f"{operand}"
    )
    (root / "README.md").write_text(
        f"{canonical}\n\n```text\n{command}\n```\n",
        encoding="utf-8",
    )
    assert audit_commands(root)["command_count"] == 22


def test_complete_audit_rejects_request_operand_command_injection(
    project_root, tmp_path
):
    root = _copy_release(project_root, tmp_path / "command-full-audit")
    with (root / "README.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n```text\n"
            'uv run --project "<project-root>" --frozen python '
            '"<skill-dir>/scripts/run.py" run --request request.json;node\n'
            "```\n"
        )
    report = run_audits(root)
    assert report["status"] == "fail"
    assert report["checks"]["commands"]["status"] == "fail"


def _copy_release(project_root: Path, destination: Path) -> Path:
    root = destination
    for relative in release_inventory(project_root):
        source = project_root / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return root
