"""Injected PDF provider failures behind the real private pipe protocol."""

import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import document_skills_core.cli as cli_module  # noqa: E402
from document_skills_core.core.capabilities import (  # noqa: E402
    Capability,
    DetectionEvidence,
    Provider,
    ProviderCatalog,
    ProviderId,
)
from document_skills_core.core.contracts import DocumentSkillsError, ErrorCode  # noqa: E402
from document_skills_core.public_cli.protocol import (  # noqa: E402
    MAX_COMMAND_BYTES,
    PROTOCOL_VERSION,
    encode_worker_terminal_frame,
    validate_command_envelope,
)
from document_skills_core.worker import fixture_static_main as worker_main  # noqa: E402
from document_skills_core.worker.private_workspace import (  # noqa: E402
    bind_inherited_workspace,
)


_LOCK_MODES = {"workspace-lock-transient", "workspace-lock-permanent"}


def _read_command() -> dict:
    if any(Path.cwd().iterdir()):
        raise ValueError("private worker cwd is not empty")
    encoded = sys.stdin.buffer.read(MAX_COMMAND_BYTES + 1)
    if not encoded or len(encoded) > MAX_COMMAND_BYTES:
        raise ValueError("private command pipe is empty or oversized")
    return validate_command_envelope(json.loads(encoded.decode("ascii")))


def _request_mode(envelope: dict) -> tuple[str, str]:
    if envelope["command"] != "run" or envelope["format"] != "pdf":
        raise ValueError("fixture accepts only public PDF run commands")
    request_index = envelope["argv"].index("--request") + 1
    request_path = Path(envelope["argv"][request_index])
    if not request_path.is_absolute():
        request_path = Path(envelope["invocation_base"]) / request_path
    request = json.loads(request_path.resolve(strict=True).read_text(encoding="utf-8"))
    operation = request.get("operation") if type(request) is dict else None
    if operation not in {"pdf.render", "pdf.ocr"}:
        raise ValueError("fixture request is not a PDF worker operation")
    return request_path.stem, operation


def _provider_catalog(mode: str, operation: str) -> ProviderCatalog:
    provider_id = (
        ProviderId.POPPLER if operation == "pdf.render" else ProviderId.TESSERACT_OCR
    )

    def execute(_operation: str, _request: dict) -> dict:
        if mode == "provider-noise":
            print("PRIVATE worker stdout topsecret", flush=True)
            print("PRIVATE worker stderr api_key", file=sys.stderr, flush=True)
            os.write(1, b"\x00PRIVATE-binary-stdout")
            os.write(2, b"\x00PRIVATE-binary-stderr")
            raise RuntimeError("PRIVATE noisy provider secret")
        if mode == "provider-typed":
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "PRIVATE typed provider secret",
            )
        if mode in {"provider-exception", *_LOCK_MODES}:
            if mode in _LOCK_MODES:
                time.sleep(0.2)
            raise RuntimeError("PRIVATE provider secret topsecret")
        if mode == "provider-crash":
            os._exit(23)
        if mode == "hang":
            time.sleep(30)
        raise RuntimeError("unsupported PDF failure fixture mode")

    catalog = ProviderCatalog()
    catalog.register_provider(
        Provider(
            id=provider_id,
            version="fixture",
            detect=lambda: DetectionEvidence(True, version="fixture"),
            execute=execute,
            capabilities=[Capability(operation, "enhanced", validation_strength=3)],
            required=False,
        )
    )
    return catalog


def _emit_bound_failure(
    envelope: dict,
    invocation_id: str,
    command: str | None = None,
) -> None:
    worker = {
        "protocol_version": PROTOCOL_VERSION,
        "invocation_id": invocation_id,
        "command": command if command is not None else envelope["command"],
        "outcome": "runtime_failure",
        "payload": None,
        "failure": {
            "category": "worker_failure",
            "phase": "dispatch",
            "provider": None,
            "exception_class": "RuntimeError",
        },
    }
    sys.stdout.buffer.write(encode_worker_terminal_frame(worker))
    sys.stdout.buffer.flush()


def main() -> int:
    bind_inherited_workspace(sys.argv[1:], PROJECT_ROOT)
    envelope = _read_command()
    mode, operation = _request_mode(envelope)
    if mode == "malformed":
        sys.stdout.buffer.write(b"\nDOCUMENT_SKILLS_WORKER_FRAME_V1 not-json\n")
        return 0
    if mode == "binding-mismatch":
        _emit_bound_failure(envelope, "wrong-private-binding")
        return 0
    if mode == "command-mismatch":
        _emit_bound_failure(envelope, envelope["invocation_id"], "doctor")
        return 0
    if mode == "oversized":
        os.write(1, b"x" * 3_000_000)
        return 0
    cli_module.build_default_registry = lambda _root: _provider_catalog(mode, operation)
    original_read = worker_main._read_command
    original_dispatch = worker_main._dispatch_command
    original_bind = worker_main.bind_inherited_workspace
    worker_main._read_command = lambda: envelope
    worker_main.bind_inherited_workspace = lambda _argv, _project_root: None
    if mode == "hostile-serialization":
        worker_main._dispatch_command = lambda _envelope: {"value": object()}
    try:
        result = worker_main.run()
        if mode == "trailing-noise":
            os.write(1, b"PRIVATE trailing bytes\n")
        return result
    finally:
        worker_main._read_command = original_read
        worker_main._dispatch_command = original_dispatch
        worker_main.bind_inherited_workspace = original_bind


if __name__ == "__main__":
    raise SystemExit(main())
