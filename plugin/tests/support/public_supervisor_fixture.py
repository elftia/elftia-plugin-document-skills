"""Real public-process harness for the static private worker fixture."""

from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))

from document_skills_core.core.contracts.serialization import render_json_bytes
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor

mode, command = sys.argv[1:3]
argv = {
    "doctor": ["doctor", "--json"],
    "capabilities": ["capabilities", "--json"],
    "run": ["run", "--request", "fixture-request.json"],
}[command]
payload, success = PublicCommandSupervisor(
    root,
    worker_script=root / "tests" / "support" / "command_worker_fixture.py",
    timeout_seconds=0.25 if mode == "hang" else 8,
    output_limit=32_768,
    nonce_factory=lambda: f"fixture-{mode}",
).run("docx", argv)
sys.stdout.buffer.write(render_json_bytes(payload))
raise SystemExit(0 if success else 2)
