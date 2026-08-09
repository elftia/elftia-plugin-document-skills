"""Static one-shot command worker; never owns public stdout."""

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from document_skills_core.cli import _dispatch, parse_command
from document_skills_core.core.contracts.schemas import SchemaCatalog
from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.public_cli.protocol import (
    MAX_COMMAND_BYTES,
    MAX_WORKER_BYTES,
    PROTOCOL_VERSION,
    read_bounded_json,
    validate_command_envelope,
)
from document_skills_core.worker.invoke import ProviderInvocationFailure


def _parse_bootstrap() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--command-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--invocation-id", required=True)
    return parser.parse_args()


def _contained_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    command = args.command_file.resolve(strict=True)
    result = args.result_file.resolve(strict=False)
    if (
        command.parent != result.parent
        or command.name != "command.json"
        or result.name != "result.json"
        or command.parent.parent.name != ".document-skills-tmp"
        or not command.is_relative_to(PROJECT_ROOT)
    ):
        raise ValueError("private protocol paths are not contained")
    return command, result


def _failure(
    invocation_id: str,
    command: str,
    error: BaseException,
) -> dict[str, Any]:
    if isinstance(error, ProviderInvocationFailure):
        return {
            "protocol_version": PROTOCOL_VERSION,
            "invocation_id": invocation_id,
            "command": command,
            "outcome": "provider_failure",
            "payload": None,
            "failure": {
                "category": error.category,
                "phase": error.phase,
                "provider": error.provider_id,
                "exception_class": error.exception_class,
            },
        }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "invocation_id": invocation_id,
        "command": command,
        "outcome": "runtime_failure",
        "payload": None,
        "failure": {
            "category": "worker_failure",
            "phase": "dispatch",
            "provider": None,
            "exception_class": type(error).__name__[:64],
        },
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    rendered = render_json_bytes(payload)
    if len(rendered) > MAX_WORKER_BYTES:
        raise ValueError("private worker result exceeds its ceiling")
    temporary = path.with_name("result.tmp")
    with temporary.open("xb") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run() -> int:
    args = _parse_bootstrap()
    command_name = "run"
    try:
        command_path, result_path = _contained_paths(args)
        envelope = validate_command_envelope(
            read_bounded_json(command_path, MAX_COMMAND_BYTES),
            args.invocation_id,
        )
        command_name = envelope["command"]
        parsed = parse_command(envelope["argv"])
        if parsed.command != command_name:
            raise ValueError("parsed command differs from private binding")
        catalog = SchemaCatalog(PROJECT_ROOT)
        payload = _dispatch(
            parsed,
            envelope["format"],
            PROJECT_ROOT,
            catalog,
            invocation_base=Path(envelope["invocation_base"]),
        )
        catalog.validate(
            {
                "doctor": "doctor-report",
                "capabilities": "capability-report",
                "run": "operation-result",
                "validate": "validation-report",
            }[command_name],
            payload,
        )
        worker = {
            "protocol_version": PROTOCOL_VERSION,
            "invocation_id": args.invocation_id,
            "command": command_name,
            "outcome": "ok",
            "payload": payload,
            "failure": None,
        }
    except BaseException as error:
        worker = _failure(args.invocation_id, command_name, error)
        result_path = args.result_file.resolve(strict=False)
    try:
        _atomic_write(result_path, worker)
    except BaseException:
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
