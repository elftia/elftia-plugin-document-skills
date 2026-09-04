"""Real public-process harness for the static private worker fixture."""

from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

source_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(source_root / "src"))

from document_skills_core.core.contracts.serialization import render_json_bytes  # noqa: E402
from document_skills_core.public_cli.supervisor import PublicCommandSupervisor  # noqa: E402

mode, command = sys.argv[1:3]
temporary_root = None if len(sys.argv) == 4 else TemporaryDirectory()
root = (
    Path(sys.argv[3]).resolve()
    if temporary_root is None
    else Path(temporary_root.name).resolve()
)
if root == source_root:
    raise ValueError("fixture worker cannot replace the source project worker")
if temporary_root is not None:
    shutil.copytree(source_root / "src", root / "src")
    shutil.copytree(source_root / "schemas", root / "schemas")
worker = root / "src" / "document_skills_core" / "worker" / "main.py"
shutil.copy2(source_root / "tests" / "support" / "command_worker_fixture.py", worker)
argv = {
    "doctor": ["doctor", "--json"],
    "capabilities": ["capabilities", "--json"],
    "run": ["run", "--request", "fixture-request.json"],
}[command]
private_root = root / ".document-skills-tmp" / f"invocation-fixture-{mode}"
# Only the hang mode needs a deliberately short budget. Every other mode
# expects the worker to terminate on its own, so it inherits the product's
# default cold-start worker budget; a tighter fixture budget turned a cold
# spawn under parallel test load into a false DS_PROCESS_TIMEOUT.
supervisor_options = {"timeout_seconds": 0.25} if mode == "hang" else {}
try:
    payload, success = PublicCommandSupervisor(
        root,
        output_limit=32_768,
        nonce_factory=lambda: f"fixture-{mode}",
        **supervisor_options,
    ).run("docx", argv)
finally:
    # POSIX production intentionally leaves this known empty random directory.
    # The fixture removes only its exact per-case leaf so repeated tests isolate.
    if private_root.is_dir():
        private_root.rmdir()
    if temporary_root is not None:
        temporary_root.cleanup()
sys.stdout.buffer.write(render_json_bytes(payload))
raise SystemExit(0 if success else 2)
