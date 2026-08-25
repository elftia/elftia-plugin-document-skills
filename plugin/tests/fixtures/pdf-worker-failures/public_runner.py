"""Public-process harness for PDF-specific worker failure fixtures."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from document_skills_core.core.contracts.serialization import render_json_bytes  # noqa: E402
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor  # noqa: E402


def main() -> int:
    mode, request = sys.argv[1:3]
    payload, success = PublicCommandSupervisor(
        PROJECT_ROOT,
        worker_script=Path(__file__).with_name("worker.py"),
        timeout_seconds=0.5 if mode == "hang" else 8.0,
        output_limit=32_768,
        nonce_factory=lambda: f"pdf-{mode}",
    ).run("pdf", ["run", "--request", request])
    sys.stdout.buffer.write(render_json_bytes(payload))
    failed = payload.get("status") in {
        "failed",
        "fail",
        "invalid_request",
        "unavailable",
    }
    return 0 if success and not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
