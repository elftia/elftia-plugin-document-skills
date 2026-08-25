"""Public capability, unavailable, budget, and representative HTML conversion tests."""

import json
from pathlib import Path
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
from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.html_capture import _capture_status
from document_skills_core.public_cli.protocol import PublicCommand
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor


def _public(project_root: Path, cwd: Path, *arguments: str, check: bool = True):
    process = subprocess.run(
        [
            "uv", "run", "--project", str(project_root), "--frozen", "python",
            str(project_root / "skills/document-pptx/scripts/run.py"), *arguments,
        ],
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        shell=False,
        timeout=90,
    )
    if check:
        assert process.returncode == 0, process.stdout
    assert process.stderr == ""
    return json.loads(process.stdout)


def _html(path: Path) -> None:
    path.write_text(
        """<!doctype html><meta charset="utf-8"><style>
        *{box-sizing:border-box}html,body{margin:0}.slide{position:relative;width:1920px;height:1080px;background:rgb(255,255,255)}
        h1{position:absolute;left:100px;top:100px;width:1000px;height:100px;margin:0;font:700 64px Arial;color:rgb(10,20,30)}
        .box{position:absolute;left:100px;top:300px;width:500px;height:300px;background:rgb(20,80,200);border-radius:24px}
        </style><section class="slide"><h1 data-pptx-id="title">Editable title</h1><div class="box" data-pptx-id="box"></div></section>""",
        encoding="utf-8",
    )


def test_capability_is_always_reported_but_unavailable_provider_is_not_callable(project_root: Path, tmp_path: Path):
    output = tmp_path / "never-created.pptx"
    registry = ProviderCatalog()
    registry.register_provider(Provider(
        id=ProviderId.HTML_BROWSER,
        version="1.62.1",
        detect=lambda: DetectionEvidence(False, reason="browser unavailable"),
        execute=lambda _operation, _request: pytest.fail("unavailable provider executed"),
        capabilities=[Capability("pptx.create.from-html", "core")],
    ))
    report = build_capabilities(project_root, "pptx", registry)
    operation = report["operations"][0]
    assert operation["operation"] == "pptx.create.from-html"
    assert operation["available"] is False
    with pytest.raises(DocumentSkillsError) as exc:
        registry.execute({
            "operation": "pptx.create.from-html",
            "input": str(tmp_path / "deck.html"),
            "output": str(output),
            "options": {"fidelity": "core"},
            "arguments": {},
        })
    assert exc.value.status == "unavailable"
    assert not output.exists()


def test_provider_operations_have_private_public_budgets_without_relaxing_existing_commands(project_root: Path, tmp_path: Path):
    html_request = tmp_path / "html.json"
    html_request.write_text(json.dumps({"operation": "pptx.create.from-html"}), encoding="utf-8")
    normal_request = tmp_path / "normal.json"
    normal_request.write_text(json.dumps({"operation": "pptx.read"}), encoding="utf-8")
    mutation_requests = []
    for name, operation in (
        ("create", "pptx.create"),
        ("markdown", "pptx.create.from-markdown"),
        ("edit", "pptx.edit"),
    ):
        request = tmp_path / f"{name}.json"
        request.write_text(json.dumps({"operation": operation}), encoding="utf-8")
        mutation_requests.append(request)
    schema_request = tmp_path / "schema.json"
    schema_request.write_text(json.dumps({"operation": "pptx.validate.schema"}), encoding="utf-8")
    convert_request = tmp_path / "convert.json"
    convert_request.write_text(
        json.dumps({"operation": "pptx.convert.pdf"}),
        encoding="utf-8",
    )
    legacy_request = tmp_path / "legacy.json"
    legacy_request.write_text(
        json.dumps({"operation": "pptx.convert.legacy"}),
        encoding="utf-8",
    )
    render_request = tmp_path / "render.json"
    render_request.write_text(
        json.dumps({"operation": "pptx.render"}),
        encoding="utf-8",
    )
    supervisor = PublicCommandSupervisor(project_root, timeout_seconds=8.0)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(html_request))),
        tmp_path,
    ) == (60.0, 1_048_576)
    for request in mutation_requests:
        assert supervisor._command_limits(
            PublicCommand("run", ("run", "--request", str(request))),
            tmp_path,
        ) == (45.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(schema_request))),
        tmp_path,
    ) == (45.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(convert_request))),
        tmp_path,
    ) == (60.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(legacy_request))),
        tmp_path,
    ) == (60.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(render_request))),
        tmp_path,
    ) == (150.0, 2_097_152)
    assert supervisor._command_limits(
        PublicCommand("run", ("run", "--request", str(normal_request))),
        tmp_path,
    ) == (8.0, 2_097_152)


def test_private_capture_status_is_exact_and_nonce_bound():
    nonce = "a" * 64
    status = {
        "protocol_version": "1.0",
        "command": "capture",
        "nonce": nonce,
        "ok": True,
        "scene_bytes": 1024,
        "asset_bytes": 512,
        "reason": None,
    }
    assert _capture_status(status, nonce) == status
    with pytest.raises(DocumentSkillsError):
        _capture_status({**status, "nonce": "b" * 64}, nonce)
    with pytest.raises(DocumentSkillsError):
        _capture_status({**status, "extra": True}, nonce)


def test_public_html_conversion_creates_native_editable_shapes(project_root: Path, tmp_path: Path):
    capabilities = _public(project_root, tmp_path, "capabilities", "--json")
    operation = next(item for item in capabilities["operations"] if item["operation"] == "pptx.create.from-html")
    if not operation["available"]:
        pytest.skip(operation["reason"])
    source = tmp_path / "deck.html"
    output = tmp_path / "deck.pptx"
    _html(source)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema_version": "1.0",
        "operation": "pptx.create.from-html",
        "input": str(source),
        "output": str(output),
        "arguments": {},
        "options": {"fidelity": "core"},
    }), encoding="utf-8")
    result = _public(
        project_root,
        tmp_path,
        "run",
        "--request",
        str(request),
        check=False,
    )
    assert result["status"] in {"success", "degraded"}
    assert result["artifacts"]
    assert result["provider_chain"] == ["html-browser"]
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["operation.consumer-package-conformance"]["outcome"] == "pass"
    assert gates["operation.scene-package-correspondence"]["outcome"] == "pass"
    assert gates["operation.scene-package-correspondence"]["evidence"]["objects"] == 2
    assert output.exists()
    assert source.is_file()


def test_public_fixture_reopens_with_editable_counts_and_repeats_exact_hash(
    project_root: Path,
    tmp_path: Path,
):
    capabilities = _public(project_root, tmp_path, "capabilities", "--json")
    operation = next(
        item for item in capabilities["operations"]
        if item["operation"] == "pptx.create.from-html"
    )
    if not operation["available"]:
        pytest.skip(operation["reason"])
    source = project_root / "tests/fixtures/html-native-deck.html"
    outputs = [tmp_path / "first.pptx", tmp_path / "second.pptx"]
    results = []
    for index, output in enumerate(outputs, 1):
        request = tmp_path / f"create-{index}.json"
        request.write_text(
            json.dumps({
                "schema_version": "1.0",
                "operation": "pptx.create.from-html",
                "input": str(source),
                "output": str(output),
                "arguments": {"metadata": {
                    "title": "Repository-authored HTML fixture",
                    "creator": "Elftia",
                    "subject": "",
                }},
                "options": {"fidelity": "core"},
            }),
            encoding="utf-8",
        )
        results.append(
            _public(
                project_root,
                tmp_path,
                "run",
                "--request",
                str(request),
                check=False,
            )
        )

    assert all(result["status"] in {"success", "degraded"} for result in results)
    assert all(result["artifacts"] for result in results)
    assert all(output.exists() for output in outputs)
    identities = [
        next(
            gate["evidence"]["sha256"]
            for gate in result["validation"]["gates"]
            if gate["id"] == "artifact.exists-size"
        )
        for result in results
    ]
    assert identities[0] == identities[1]
    assert all(
        next(
            gate for gate in result["validation"]["gates"]
            if gate["id"] == "operation.consumer-package-conformance"
        )["outcome"] == "pass"
        for result in results
    )


def test_public_nested_wrappers_shape_fallback_and_pseudo_layers_are_truthful(
    project_root: Path,
    tmp_path: Path,
):
    capabilities = _public(project_root, tmp_path, "capabilities", "--json")
    operation = next(
        item for item in capabilities["operations"]
        if item["operation"] == "pptx.create.from-html"
    )
    if not operation["available"]:
        pytest.skip(operation["reason"])
    image_name = "review-image.png"
    (tmp_path / image_name).write_bytes(
        (project_root / "tests/fixtures/html-native-image.png").read_bytes()
    )
    source = tmp_path / "review-cases.html"
    source.write_text(
        f"""<!doctype html><meta charset="utf-8"><style>
        *{{box-sizing:border-box}}html,body{{margin:0}}.slide{{position:relative;width:1920px;height:1080px}}
        .outer{{position:absolute;left:40px;top:50px;width:900px;height:400px}}.inner{{position:relative;width:100%;height:100%}}
        .shape{{position:absolute;left:20px;top:30px;width:180px;height:90px;background:rgb(10,20,30)}}
        .text{{position:absolute;left:220px;top:30px;width:260px;height:90px;font:28px Arial}}
        img{{position:absolute;left:500px;top:30px;width:120px;height:80px}}
        .asym{{position:absolute;left:1000px;top:80px;width:300px;height:200px;background:white;
          border-top:2px solid red;border-right:20px dashed blue;border-radius:5px 40px 60px 10px}}
        .card{{position:absolute;left:100px;top:550px;width:500px;height:300px;background:white;font:24px Arial}}
        .card::before{{content:'BEFORE';position:absolute;left:20px;top:30px;width:100px;height:30px;font:20px Arial}}
        .card::after{{content:'AFTER';position:absolute;right:10px;bottom:10px;width:90px;height:25px;font:18px Arial}}
        .complex{{position:absolute;left:800px;top:550px;width:200px;height:120px;background:white}}
        .complex::before{{content:'C';position:absolute;left:0;top:0;background-image:linear-gradient(red,blue)}}
        </style><section class="slide"><div class="outer"><div class="inner">
        <div class="shape" data-pptx-id="nested-shape"></div>
        <div class="text" data-pptx-id="nested-text">Editable</div>
        <img data-pptx-id="nested-image" src="{image_name}">
        </div></div><div class="asym" data-pptx-id="asym-shape"></div>
        <div class="card" data-pptx-id="card">Body</div>
        <div class="complex" data-pptx-id="complex"></div></section>""",
        encoding="utf-8",
    )
    output = tmp_path / "review-cases.pptx"
    request = tmp_path / "review-cases.json"
    request.write_text(
        json.dumps({
            "schema_version": "1.0",
            "operation": "pptx.create.from-html",
            "input": str(source),
            "output": str(output),
            "arguments": {"fallback_policy": "element-rasterize"},
            "options": {"fidelity": "core"},
        }),
        encoding="utf-8",
    )
    result = _public(
        project_root,
        tmp_path,
        "run",
        "--request",
        str(request),
        check=False,
    )
    assert result["status"] in {"success", "degraded"}
    assert result["artifacts"]
    gates = {gate["id"]: gate for gate in result["validation"]["gates"]}
    assert gates["operation.consumer-package-conformance"]["outcome"] == "pass"
    assert gates["operation.scene-package-correspondence"]["outcome"] == "pass"
    assert gates["operation.scene-package-correspondence"]["evidence"] == {
        "slides": 1,
        "objects": 9,
        "media": 3,
        "one_to_one_manifest": True,
        "finite_in_bounds_geometry": True,
        "deterministic_ids": True,
    }
    assert output.exists()


def _public_run_request(
    project_root: Path,
    tmp_path: Path,
    name: str,
    payload: dict[str, object],
):
    request = tmp_path / f"{name}.json"
    request.write_text(json.dumps(payload), encoding="utf-8")
    return _public(project_root, tmp_path, "run", "--request", str(request))
