"""Static pipe-worker failure fixture for public supervisor process tests."""

import json
import os
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from document_skills_core import __version__  # noqa: E402
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode  # noqa: E402
from document_skills_core.core.contracts.serialization import render_json_bytes  # noqa: E402
from document_skills_core.public_cli.protocol import validate_command_envelope  # noqa: E402
from document_skills_core.worker.invoke import (  # noqa: E402
    ProviderInvocationFailure,
    invoke_provider,
)
from document_skills_core.worker.private_workspace import (  # noqa: E402
    bind_inherited_workspace,
)


_FRAME_PREFIX = b"DOCUMENT_SKILLS_WORKER_FRAME_V1 "
_INPUT_LIMIT = 65_536


def _read_command():
    if any(Path.cwd().iterdir()):
        raise ValueError("private workspace must be empty before worker dispatch")
    encoded = sys.stdin.buffer.read(_INPUT_LIMIT + 1)
    if not encoded or len(encoded) > _INPUT_LIMIT:
        raise ValueError("private command pipe is empty or oversized")
    return validate_command_envelope(json.loads(encoded.decode("ascii")))


def _payload(command, format_id, workspace_identity):
    if command == "doctor":
        return {
            "schema_version": "1.0",
            "status": "healthy",
            "project_version": __version__,
            "format": format_id,
            "runtime": [],
            "providers": [],
            "errors": [],
        }
    if command == "capabilities":
        return {
            "schema_version": "1.0",
            "format": format_id,
            "operations": [],
            "providers": [],
            "validation": {
                "package": "available",
                "schema": "unavailable",
                "visual": "unavailable",
            },
        }
    payload = {
        "schema_version": "1.0",
        "status": "success",
        "operation": "docx.fixture",
        "provider_chain": ["fixture-provider"],
        "requested_fidelity": "core",
        "achieved_fidelity": "core",
        "degraded": False,
        "degradations": [],
        "artifacts": [],
        "validation": {
            "schema_version": "1.0",
            "status": "not_run",
            "gates": [],
        },
        "warnings": [],
        "errors": [],
        "diagnostics": {},
    }
    if workspace_identity is not None:
        actual = os.stat(".", follow_symlinks=False)
        payload["diagnostics"] = {
            "actual_cwd_identity": [actual.st_dev, actual.st_ino],
            "held_workspace_identity": list(workspace_identity),
        }
    return payload


def _provider_callback(mode):
    if mode == "text-noise":
        print("PRIVATE callback body")
        print("PRIVATE callback error", file=sys.stderr)
    elif mode == "binary-noise":
        os.write(1, b"\x00PRIVATE-OUT")
        os.write(2, b"\x00PRIVATE-ERR")
    elif mode == "typed":
        raise DocumentSkillsError(ErrorCode.PATH_UNSAFE, "PRIVATE typed message")
    elif mode == "system-exit":
        raise SystemExit(7)
    elif mode == "interrupt":
        raise KeyboardInterrupt()
    elif mode == "base":
        raise GeneratorExit()
    elif mode == "ordinary":
        raise RuntimeError("PRIVATE exception")
    elif mode == "hostile":
        return {"value": object()}
    elif mode == "huge-string":
        return {"value": "x" * 3_000_000}
    elif mode == "huge-int":
        return {"value": 10**5000}
    elif mode == "surrogate":
        return {"value": "\ud800"}
    elif mode == "unicode":
        return {"value": "portable \U0001f642"}
    return {"ok": True}


def _record_provider_dispatch(mode, command_data):
    if mode != "moved-outside":
        return
    request_index = command_data["argv"].index("--request") + 1
    request_path = Path(command_data["argv"][request_index])
    if not request_path.is_absolute():
        request_path = Path(command_data["invocation_base"]) / request_path
    request = json.loads(request_path.read_text(encoding="utf-8"))
    Path(request["provider_dispatch_sentinel"]).write_bytes(b"dispatched")


def _emit(envelope):
    sys.stdout.flush()
    sys.stderr.flush()
    sys.stdout.buffer.write(b"\n" + _FRAME_PREFIX + render_json_bytes(envelope))
    sys.stdout.buffer.flush()


def main():
    workspace_identity = bind_inherited_workspace(sys.argv[1:], PROJECT_ROOT)
    command_data = _read_command()
    mode = command_data["invocation_id"].removeprefix("fixture-")
    _record_provider_dispatch(mode, command_data)
    if mode == "hang":
        time.sleep(30)
    if mode == "overflow":
        os.write(1, b"x" * 3_000_000)
    if mode == "os-exit":
        os._exit(23)
    if mode == "crash":
        raise RuntimeError("PRIVATE worker crash")
    if mode == "invalid-result":
        sys.stdout.buffer.write(b"\n" + _FRAME_PREFIX + b"not-json\n")
        return 0
    try:
        provider_value = invoke_provider(
            "fixture-provider", "detect", _provider_callback, mode
        )
        if mode == "surrogate":
            return 70
        outcome = "ok"
        payload = _payload(
            command_data["command"],
            command_data["format"],
            workspace_identity,
        )
        if mode in {"hostile", "huge-string", "huge-int", "unicode"}:
            if command_data["command"] in {"doctor", "capabilities"}:
                payload["providers"] = [
                    {
                        "id": "fixture-provider",
                        "available": True,
                        "version": provider_value["value"],
                        "reason": None,
                        "required": False,
                        "path": None,
                    }
                ]
            else:
                payload["diagnostics"]["provider_value"] = provider_value["value"]
        failure = None
    except ProviderInvocationFailure as error:
        outcome = "provider_failure"
        payload = None
        failure = {
            "category": error.category,
            "phase": error.phase,
            "provider": error.provider_id,
            "exception_class": error.exception_class,
        }
    envelope = {
        "protocol_version": "1.0",
        "invocation_id": command_data["invocation_id"],
        "command": command_data["command"],
        "outcome": outcome,
        "payload": payload,
        "failure": failure,
    }
    try:
        _emit(envelope)
    except (TypeError, UnicodeError, ValueError):
        return 70
    if mode == "trailing-noise":
        os.write(1, b"PRIVATE trailing bytes\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
