"""Static one-shot command worker with one bounded pipe terminal frame."""

import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from document_skills_core.cli import _dispatch, parse_command  # noqa: E402
from document_skills_core.core.contracts.schemas import SchemaCatalog  # noqa: E402
from document_skills_core.public_cli.protocol import (  # noqa: E402
    MAX_COMMAND_BYTES,
    PROTOCOL_VERSION,
    encode_worker_terminal_frame,
    validate_command_envelope,
)
from document_skills_core.worker.invoke import ProviderInvocationFailure  # noqa: E402
from document_skills_core.worker.private_workspace import (  # noqa: E402
    bind_inherited_workspace,
)


def _read_command() -> dict[str, Any]:
    encoded = sys.stdin.buffer.read(MAX_COMMAND_BYTES + 1)
    if not encoded or len(encoded) > MAX_COMMAND_BYTES:
        raise ValueError("private command pipe is empty or oversized")
    value = json.loads(encoded.decode("ascii", errors="strict"))
    return validate_command_envelope(value)


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


def _dispatch_command(envelope: dict[str, Any]) -> dict[str, Any]:
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
    return payload


def run() -> int:
    try:
        bind_inherited_workspace(sys.argv[1:], PROJECT_ROOT)
        envelope = _read_command()
    except BaseException:
        return 70
    invocation_id = envelope["invocation_id"]
    command_name = envelope["command"]
    try:
        worker = {
            "protocol_version": PROTOCOL_VERSION,
            "invocation_id": invocation_id,
            "command": command_name,
            "outcome": "ok",
            "payload": _dispatch_command(envelope),
            "failure": None,
        }
    except BaseException as error:
        worker = _failure(invocation_id, command_name, error)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout.buffer.write(encode_worker_terminal_frame(worker))
        sys.stdout.buffer.flush()
    except BaseException:
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
