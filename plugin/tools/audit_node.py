"""Python façade for the locked Acorn Node runtime-source policy."""

import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess


def is_runtime_node(relative: str) -> bool:
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    return bool(parts) and parts[0] in {"runtime", "src", "skills", "providers"}


def audit_node_source(project_root: Path, relative: str, source: str) -> None:
    if not is_runtime_node(relative):
        return
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node is unavailable for the locked AST policy")
    parser = project_root / "tools" / "node_policy.mjs"
    completed = subprocess.run(
        [node, str(parser)],
        input=json.dumps(
            {"relative": relative, "source": source},
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError("Locked Node AST parser returned invalid JSON") from error
    if completed.returncode != 0 or result.get("ok") is not True:
        category = str(result.get("category") or result.get("error") or "policy")
        raise AssertionError(f"Node runtime policy rejected {relative}: {category}")
