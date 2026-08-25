"""Injected PDF provider failures behind the real private worker protocol."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

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
from document_skills_core.public_cli.protocol import (  # noqa: E402
    MAX_COMMAND_BYTES,
    MAX_WORKER_BYTES,
    read_bounded_json,
    validate_command_envelope,
)
from document_skills_core.worker import main as worker_main  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--invocation-id", required=True)
    return parser.parse_args()


def _request_operation(args: argparse.Namespace) -> str:
    command = args.command_file.resolve(strict=True)
    result = args.result_file.resolve(strict=False)
    if command.parent != result.parent or command.name != "command.json" or result.name != "result.json":
        raise ValueError("fixture protocol paths are not contained")
    envelope = validate_command_envelope(
        read_bounded_json(command, MAX_COMMAND_BYTES),
        args.invocation_id,
    )
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
    return operation


def _provider_catalog(mode: str, operation: str) -> ProviderCatalog:
    provider_id = ProviderId.POPPLER if operation == "pdf.render" else ProviderId.TESSERACT_OCR

    def execute(_operation: str, _request: dict) -> dict:
        if mode == "provider-exception":
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


def main() -> int:
    args = _args()
    mode = args.invocation_id.removeprefix("pdf-")
    operation = _request_operation(args)
    private_root = args.command_file.resolve(strict=True).parent
    (private_root / "private-artifact.bin").write_bytes(b"PRIVATE topsecret")
    print("PRIVATE worker stdout topsecret", flush=True)
    print("PRIVATE worker stderr api_key", file=sys.stderr, flush=True)
    if mode == "malformed":
        args.result_file.write_bytes(b"not-json")
        return 0
    if mode == "oversized":
        args.result_file.write_bytes(b"x" * (MAX_WORKER_BYTES + 1))
        return 0
    cli_module.build_default_registry = lambda _root: _provider_catalog(mode, operation)
    return worker_main.run()


if __name__ == "__main__":
    raise SystemExit(main())
