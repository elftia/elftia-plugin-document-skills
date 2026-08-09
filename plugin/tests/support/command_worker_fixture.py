"""Static private-worker failure fixture for public supervisor subprocess tests."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from document_skills_core import __version__
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.worker.invoke import (
    ProviderInvocationFailure,
    invoke_provider,
)


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--invocation-id", required=True)
    return parser.parse_args()


def _payload(command, format_id):
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
    return {
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


def main():
    args = _args()
    mode = args.invocation_id.removeprefix("fixture-")
    command_data = json.loads(args.command_file.read_text(encoding="utf-8"))
    if mode == "hang":
        time.sleep(30)
    if mode == "overflow":
        os.write(1, b"x" * 262_144)
    if mode == "os-exit":
        os._exit(23)
    if mode == "crash":
        raise RuntimeError("PRIVATE worker crash")
    if mode == "invalid-result":
        args.result_file.write_text("not-json", encoding="utf-8")
        return 0
    try:
        provider_value = invoke_provider(
            "fixture-provider", "detect", _provider_callback, mode
        )
        if mode == "surrogate":
            # The real worker's schema/normalization path rejects this before
            # publishing a result. This fixture bypasses dispatch, so model the
            # same private serialization failure explicitly.
            return 70
        outcome = "ok"
        payload = _payload(command_data["command"], command_data["format"])
        if mode in {"hostile", "huge-string", "huge-int", "surrogate", "unicode"}:
            if command_data["command"] == "doctor":
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
            elif command_data["command"] == "capabilities":
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
        "invocation_id": args.invocation_id,
        "command": command_data["command"],
        "outcome": outcome,
        "payload": payload,
        "failure": failure,
    }
    try:
        args.result_file.write_bytes(render_json_bytes(envelope))
    except (TypeError, UnicodeError, ValueError):
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
