"""Tests for the executable, truthful PDF provider-profile harness."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools import pdf_provider_profile as profile_harness
from tools.pdf_provider_profile import (
    PROFILES,
    ProfileFailure,
    assess_profile,
    parse_args,
    receipt_exit_code,
)


def _capabilities(
    *,
    render: bool = False,
    ocr: bool = False,
    pypdf: bool = True,
    pypdf_version: str | None = "6.16.2",
    pypdf_reason: str | None = None,
) -> dict[str, object]:
    operations = [
        {
            "operation": "pdf.create",
            "available": True,
            "providers": ["core-python"],
            "reason": None,
        },
        {
            "operation": "pdf.edit",
            "available": True,
            "providers": ["core-python"],
            "reason": None,
        },
        {
            "operation": "pdf.rewrite.apply",
            "available": True,
            "providers": ["core-python"],
            "reason": None,
        },
        {
            "operation": "pdf.render",
            "available": render,
            "providers": ["poppler"] if render else [],
            "reason": None
            if render
            else "No accepted provider implementation is available.",
        },
        {
            "operation": "pdf.ocr",
            "available": ocr,
            "providers": ["tesseract-ocr"] if ocr else [],
            "reason": None
            if ocr
            else "No accepted provider implementation is available.",
        },
        {
            "operation": "pdf.encrypt",
            "available": pypdf,
            "providers": ["pypdf"] if pypdf else [],
            "reason": None
            if pypdf
            else "No accepted provider implementation is available.",
        },
        {
            "operation": "pdf.decrypt",
            "available": pypdf,
            "providers": ["pypdf"] if pypdf else [],
            "reason": None
            if pypdf
            else "No accepted provider implementation is available.",
        },
        {
            "operation": "pdf.compress",
            "available": pypdf,
            "providers": ["pypdf"] if pypdf else [],
            "reason": None
            if pypdf
            else "No accepted provider implementation is available.",
        },
    ]
    providers = [
        {
            "id": "core-python",
            "available": True,
            "version": "0.1.0",
            "path": None,
            "reason": None,
        },
        {
            "id": "poppler",
            "available": render,
            "version": "24.02.0" if render else None,
            "path": "pdftoppm" if render else None,
            "reason": None if render else "missing",
        },
        {
            "id": "tesseract-ocr",
            "available": ocr,
            "version": "poppler-24.02.0+tesseract-5.3.4" if ocr else None,
            "path": "tesseract" if ocr else None,
            "reason": None if ocr else "missing",
        },
        {
            "id": "pypdf",
            "available": pypdf,
            "version": pypdf_version,
            "path": None,
            "reason": pypdf_reason,
        },
    ]
    return {"schema_version": "1.0", "operations": operations, "providers": providers}


@pytest.mark.parametrize("profile", PROFILES)
def test_parser_selects_each_named_profile(profile: str) -> None:
    assert parse_args(["--profile", profile]).profile == profile


def test_parser_rejects_unknown_profile() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--profile", "accidental-host-tools"])


def test_missing_provider_is_a_machine_readable_unavailable_requirement() -> None:
    requirements, unavailable = assess_profile("render", _capabilities())

    assert requirements == unavailable
    assert unavailable[0]["operation"] == "pdf.render"
    assert unavailable[0]["provider"] == "poppler"
    assert unavailable[0]["available"] is False


def test_strict_mode_makes_unavailable_receipt_nonzero() -> None:
    optional = {"status": "unavailable", "strict": False}
    required = {"status": "unavailable", "strict": True}

    assert receipt_exit_code(optional) == 0
    assert receipt_exit_code(required) != 0
    assert receipt_exit_code({"status": "failed", "strict": False}) != 0


@pytest.mark.parametrize(
    ("version", "reason"),
    [
        (None, "The locked pypdf AES runtime is not installed."),
        ("7.0.0", "The installed pypdf version does not match policy."),
    ],
)
def test_pypdf_unavailability_retains_machine_readable_policy_reason(
    version: str | None,
    reason: str,
) -> None:
    requirements, unavailable = assess_profile(
        "full",
        _capabilities(pypdf=False, pypdf_version=version, pypdf_reason=reason),
    )

    pypdf_requirements = [item for item in requirements if item["provider"] == "pypdf"]
    pypdf_unavailable = [item for item in unavailable if item["provider"] == "pypdf"]
    assert pypdf_unavailable == pypdf_requirements
    assert [item["operation"] for item in pypdf_unavailable] == [
        "pdf.encrypt",
        "pdf.decrypt",
        "pdf.compress",
    ]
    assert all(item["version"] == version for item in pypdf_unavailable)
    assert all(item["reason"] == reason for item in pypdf_unavailable)


@pytest.mark.parametrize(
    ("failure", "reason_code"),
    [
        (
            ProfileFailure("public_smoke_failed", "provider crashed"),
            "public_smoke_failed",
        ),
        (subprocess.TimeoutExpired(["worker"], 1), "harness_exception"),
        (
            ProfileFailure("public_cli_malformed", "malformed result"),
            "public_cli_malformed",
        ),
    ],
)
def test_available_smoke_failures_are_failed_not_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    reason_code: str,
) -> None:
    def fail_profile(
        profile: str, project_root: Path, *, strict: bool
    ) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(profile_harness, "run_profile", fail_profile)

    exit_code = profile_harness.main(["--profile", "full", "--strict"])

    receipt = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert receipt["status"] == "failed"
    assert receipt["reason"]["code"] == reason_code
    assert receipt["smokes"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1.0", "operations": "invalid", "providers": []},
        {"schema_version": "1.0", "operations": [], "providers": []},
        {
            "schema_version": "1.0",
            "operations": [
                {"operation": "pdf.render", "available": "yes", "providers": []}
            ],
            "providers": [{"id": "poppler", "available": False}],
        },
    ],
)
def test_malformed_capability_reports_fail_closed(payload: dict[str, object]) -> None:
    with pytest.raises(ProfileFailure) as caught:
        assess_profile("render", payload)

    assert caught.value.code == "capability_report_malformed"


def test_core_only_profile_runs_real_public_smokes(project_root: Path) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools/pdf_provider_profile.py"),
            "--profile",
            "core-only",
            "--strict",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=180,
    )

    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    receipt = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert receipt["status"] == "pass"
    assert receipt["profile"] == "core-only"
    assert [smoke["id"] for smoke in receipt["smokes"]] == [
        "core-create",
        "core-edit",
        "core-rewrite",
        "core-forms",
    ]
    optional = {
        item["operation"]: item
        for item in receipt["requirements"]
        if item["operation"] in {"pdf.render", "pdf.ocr"}
    }
    assert set(optional) == {"pdf.render", "pdf.ocr"}
    assert all(item["available"] is False for item in optional.values())
    assert all(item["reason"] for item in optional.values())


def test_full_profile_runs_available_pypdf_smokes_before_reporting_unavailable(
    project_root: Path,
    tmp_path: Path,
) -> None:
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = dict(os.environ)
    environment["PATH"] = str(empty_path)

    process = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools/pdf_provider_profile.py"),
            "--profile",
            "full",
            "--strict",
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=180,
    )

    assert process.returncode == 2
    assert process.stderr == b""
    receipt = json.loads(process.stdout.decode("utf-8", errors="strict"))
    assert receipt["status"] == "unavailable"
    assert receipt["reason"]["operations"] == ["pdf.ocr", "pdf.render"]
    assert [binding["operation"] for binding in receipt["reason"]["bindings"]] == [
        "pdf.render",
        "pdf.ocr",
    ]
    assert all(
        binding["provider"] and binding["reason"]
        for binding in receipt["reason"]["bindings"]
    )
    pypdf_smokes = [
        smoke for smoke in receipt["smokes"] if smoke["provider"] == "pypdf"
    ]
    assert pypdf_smokes == [
        {
            "id": "encrypt",
            "operation": "pdf.encrypt",
            "provider": "pypdf",
            "status": "pass",
        },
        {
            "id": "decrypt",
            "operation": "pdf.decrypt",
            "provider": "pypdf",
            "status": "pass",
        },
        {
            "id": "compress",
            "operation": "pdf.compress",
            "provider": "pypdf",
            "status": "pass",
        },
    ]
