"""Genuine .NET 8 and project-local OpenXML validator probing."""

from pathlib import Path
import shutil
from typing import Any

from ..contracts.errors import DocumentSkillsError
from ..process import ProcessPolicy, ProcessRunner


def detect_dotnet_runtime(
    policy: ProcessPolicy,
    runner: ProcessRunner,
) -> dict[str, Any]:
    found = shutil.which("dotnet")
    if found is None:
        return _state("dotnet-runtime", False, reason="dotnet was not found on the managed PATH")
    try:
        executable = policy.allow_executable("runtime-detection", found)
        result = runner.run(
            "runtime-detection",
            executable,
            ["--list-runtimes"],
            timeout_seconds=2.0,
            output_limit=32_768,
        )
    except DocumentSkillsError as error:
        return _state("dotnet-runtime", False, reason=str(error))
    runtime_line = next(
        (
            line.strip()
            for line in result.stdout.splitlines()
            if line.startswith("Microsoft.NETCore.App 8.")
        ),
        None,
    )
    available = result.returncode == 0 and runtime_line is not None
    return _state(
        "dotnet-runtime",
        available,
        version=runtime_line,
        reason=None if available else "Microsoft.NETCore.App 8.x is not installed",
        path=Path(found).name,
    )


def detect_dotnet_openxml(
    project_root: Path,
    policy: ProcessPolicy,
    runner: ProcessRunner,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    if not runtime["available"]:
        return _state(
            "dotnet-openxml",
            False,
            reason=runtime["reason"],
            path=runtime["path"],
        )
    provider_root = project_root / "runtime" / "dotnet" / "openxml"
    probe = provider_root / "OpenXmlProbe.dll"
    assembly = provider_root / "DocumentFormat.OpenXml.dll"
    if not probe.is_file() or not assembly.is_file():
        return _state(
            "dotnet-openxml",
            False,
            reason=(
                "The accepted project-local OpenXML probe and "
                "DocumentFormat.OpenXml assembly are not installed"
            ),
        )
    found = shutil.which("dotnet")
    if found is None:
        return _state("dotnet-openxml", False, reason="dotnet is unavailable")
    try:
        executable = policy.allow_executable("dotnet-openxml-probe", found)
        allowed_probe = policy.allow_script("dotnet-openxml-probe", probe)
        result = runner.run(
            "dotnet-openxml-probe",
            executable,
            ["exec", str(allowed_probe), "--probe-json"],
            script=allowed_probe,
            timeout_seconds=2.0,
            output_limit=16_384,
        )
        payload = result.json()
        valid = (
            result.returncode == 0
            and payload.get("protocol_version") == "1.0"
            and payload.get("runtime_major") == 8
            and isinstance(payload.get("openxml_version"), str)
            and payload.get("assembly_loaded") is True
        )
        return _state(
            "dotnet-openxml",
            valid,
            version=payload.get("openxml_version") if valid else None,
            reason=(
                None
                if valid
                else "The project-local OpenXML probe did not verify .NET 8 and the assembly"
            ),
            path=probe.name,
        )
    except (DocumentSkillsError, AttributeError) as error:
        return _state(
            "dotnet-openxml",
            False,
            reason=f"OpenXML verification failed: {type(error).__name__}",
            path=probe.name,
        )


def _state(
    component_id: str,
    available: bool,
    *,
    version: str | None = None,
    reason: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "available": available,
        "version": version,
        "reason": reason,
        "required": False,
        "path": path,
    }
