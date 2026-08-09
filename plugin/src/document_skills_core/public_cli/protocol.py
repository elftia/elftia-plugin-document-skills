"""Exact private command and worker envelopes."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "1.0"
MAX_COMMAND_BYTES = 65_536
MAX_WORKER_BYTES = 2_097_152
MAX_INVOCATION_BASE_BYTES = 32_768
COMMANDS = frozenset({"doctor", "capabilities", "run", "validate"})


@dataclass(frozen=True)
class PublicCommand:
    name: str
    argv: tuple[str, ...]


def parse_public_command(argv: list[str] | None) -> PublicCommand:
    parser = argparse.ArgumentParser(prog="document-skill")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", required=True)
    capabilities = commands.add_parser("capabilities")
    capabilities.add_argument("--json", action="store_true", required=True)
    run = commands.add_parser("run")
    run.add_argument("--request", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--input", required=True)
    validate.add_argument("--json", action="store_true", required=True)
    namespace = parser.parse_args(argv)
    actual = tuple(argv if argv is not None else [])
    if not actual:
        import sys

        actual = tuple(sys.argv[1:])
    return PublicCommand(namespace.command, actual)


def command_envelope(
    invocation_id: str,
    command: PublicCommand,
    format_id: str,
    invocation_base: Path,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "invocation_id": invocation_id,
        "command": command.name,
        "format": format_id,
        "argv": list(command.argv),
        "invocation_base": str(invocation_base),
    }


def validate_command_envelope(value: Any, invocation_id: str) -> dict[str, Any]:
    expected = {
        "protocol_version",
        "invocation_id",
        "command",
        "format",
        "argv",
        "invocation_base",
    }
    if type(value) is not dict or set(value) != expected:
        raise ValueError("invalid command envelope fields")
    if value["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("unsupported private protocol")
    if value["invocation_id"] != invocation_id:
        raise ValueError("private nonce mismatch")
    if value["command"] not in COMMANDS:
        raise ValueError("unknown private command")
    if value["format"] not in {"docx", "xlsx", "pptx", "pdf"}:
        raise ValueError("unknown private format")
    if type(value["argv"]) is not list or any(type(item) is not str for item in value["argv"]):
        raise TypeError("private argv must be a string list")
    value["invocation_base"] = str(
        validate_invocation_base(value["invocation_base"])
    )
    return value


def validate_invocation_base(value: Any) -> Path:
    if type(value) is not str or not value:
        raise TypeError("private invocation base must be a non-empty string")
    if len(value.encode("utf-8", errors="strict")) > MAX_INVOCATION_BASE_BYTES:
        raise ValueError("private invocation base exceeds its byte ceiling")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("private invocation base must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("private invocation base must be a directory")
    return resolved


def validate_worker_envelope(
    value: Any,
    invocation_id: str,
    command: str,
) -> dict[str, Any]:
    expected = {
        "protocol_version",
        "invocation_id",
        "command",
        "outcome",
        "payload",
        "failure",
    }
    if type(value) is not dict or set(value) != expected:
        raise ValueError("invalid worker envelope fields")
    if (
        value["protocol_version"] != PROTOCOL_VERSION
        or value["invocation_id"] != invocation_id
        or value["command"] != command
    ):
        raise ValueError("worker envelope binding mismatch")
    if value["outcome"] not in {
        "ok",
        "provider_failure",
        "runtime_failure",
        "cancelled",
    }:
        raise ValueError("invalid worker outcome")
    if value["outcome"] == "ok":
        if type(value["payload"]) is not dict or value["failure"] is not None:
            raise ValueError("invalid successful worker envelope")
    else:
        if value["payload"] is not None or type(value["failure"]) is not dict:
            raise ValueError("invalid failed worker envelope")
        allowed = {"category", "phase", "provider", "exception_class"}
        if set(value["failure"]) != allowed:
            raise ValueError("invalid private failure fields")
    return value


def read_bounded_json(path: Path, ceiling: int) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("private result is missing or a link")
    size = path.stat().st_size
    if size <= 0 or size > ceiling:
        raise ValueError("private result exceeds its byte ceiling")
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    decoder = json.JSONDecoder()
    value, end = decoder.raw_decode(text)
    if text[end:].strip():
        raise ValueError("private result contains multiple values")
    return value
