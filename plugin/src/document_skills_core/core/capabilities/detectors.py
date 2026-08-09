"""Bounded, side-effect-free runtime and optional-provider detection."""

import json
from pathlib import Path
import shutil
from typing import Any

from ..contracts.errors import DocumentSkillsError
from ..process import ProcessPolicy, ProcessRunner
from .catalog import DetectionEvidence
from .dotnet import detect_dotnet_openxml, detect_dotnet_runtime
from .provider_state import (
    FAILED_DETECTOR_REASON,
    INVALID_DETECTOR_REASON,
    normalize_detector_state,
    unavailable_detector_state,
)

_NODE_PROTOCOL_TIMEOUT_SECONDS = 6.0


class RuntimeDetectors:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.policy = ProcessPolicy(self.project_root)
        self.runner = ProcessRunner(self.policy)

    def all(self) -> list[dict[str, Any]]:
        detectors = (
            ("uv", True, self.detect_uv),
            ("python-lock", True, self.detect_python_lock),
            ("node", True, self.detect_node),
            ("node-lock", True, self.detect_node_lock),
            ("dotnet-runtime", False, self.detect_dotnet_runtime),
        )
        return [
            self._safe_detector(component_id, required, detector)
            for component_id, required, detector in detectors
        ]

    def detect_uv(self) -> dict[str, Any]:
        return self._detect_command("uv", ["uv"], ["--version"], required=True)

    def detect_python_lock(self) -> dict[str, Any]:
        lock = self.project_root / "uv.lock"
        if not lock.is_file() or lock.stat().st_size == 0:
            return self._state("python-lock", False, True, reason="uv.lock is missing or empty")
        uv = shutil.which("uv")
        if uv is None:
            return self._state(
                "python-lock", False, True, reason="uv is unavailable, so lock parity cannot be checked"
            )
        try:
            executable = self.policy.allow_executable("runtime-detection", uv)
            result = self.runner.run(
                "runtime-detection",
                executable,
                ["lock", "--check", "--offline", "--project", str(self.project_root)],
                timeout_seconds=2.0,
                output_limit=16_384,
            )
            available = result.returncode == 0
            return self._state(
                "python-lock",
                available,
                True,
                version="uv.lock",
                reason=None if available else "uv reports pyproject.toml/uv.lock drift",
                path=lock.name,
            )
        except DocumentSkillsError as error:
            return self._state("python-lock", False, True, reason=str(error), path=lock.name)

    def detect_node(self) -> dict[str, Any]:
        return self._detect_command("node", ["node"], ["--version"], required=True)

    def detect_node_lock(self) -> dict[str, Any]:
        manifest = self.project_root / "package.json"
        lock = self.project_root / "package-lock.json"
        if not manifest.is_file() or not lock.is_file():
            return self._state("node-lock", False, True, reason="package manifest or lock is missing")
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
            locked = json.loads(lock.read_text(encoding="utf-8"))
            locked_root = locked["packages"][""]
            parity = (
                package["name"] == locked["name"]
                and package["version"] == locked["version"]
                and package.get("dependencies", {}) == locked_root.get("dependencies", {})
            )
        except (json.JSONDecodeError, KeyError) as error:
            return self._state("node-lock", False, True, reason=f"invalid lock metadata: {error}")
        reason = None if parity else "package name/version differs from package-lock"
        return self._state("node-lock", parity, True, version=str(locked.get("lockfileVersion")), reason=reason)

    def detect_node_protocol(self) -> dict[str, Any]:
        node = shutil.which("node")
        script = self.project_root / "runtime" / "node" / "health.mjs"
        if node is None:
            return self._state("core-node", False, True, reason="managed Node.js is unavailable")
        try:
            executable = self.policy.allow_executable("core-node", node)
            allowed_script = self.policy.allow_script("core-node", script)
            result = self.runner.run(
                "core-node",
                executable,
                [str(allowed_script)],
                script=allowed_script,
                stdin_json={"protocol_version": "1.0", "operation": "health"},
                timeout_seconds=_NODE_PROTOCOL_TIMEOUT_SECONDS,
                output_limit=16_384,
            )
            payload = result.json()
            available = (
                result.returncode == 0
                and payload.get("ok") is True
                and payload.get("provider") == "core-node"
                and payload.get("protocol_version") == "1.0"
            )
            return self._state(
                "core-node",
                available,
                True,
                version=payload.get("node_version"),
                reason=None if available else "Node health protocol failed",
            )
        except DocumentSkillsError as error:
            return self._state("core-node", False, True, reason=str(error))

    def detect_node_provider(self) -> DetectionEvidence:
        return self._evidence(self.detect_node_protocol())

    def detect_libreoffice_provider(self) -> DetectionEvidence:
        return self._evidence(
            self.detect_optional(
                "libreoffice", ["soffice", "libreoffice"], ["--version"]
            )
        )

    def detect_openxml_provider(self) -> DetectionEvidence:
        return self._evidence(self.detect_dotnet_openxml())

    def detect_optional(
        self, component_id: str, executable_names: list[str], args: list[str]
    ) -> dict[str, Any]:
        return self._detect_command(component_id, executable_names, args, required=False)

    def detect_dotnet_runtime(self) -> dict[str, Any]:
        return detect_dotnet_runtime(self.policy, self.runner)

    def detect_dotnet_openxml(self) -> dict[str, Any]:
        return detect_dotnet_openxml(
            self.project_root,
            self.policy,
            self.runner,
            self.detect_dotnet_runtime(),
        )

    def _detect_command(
        self,
        component_id: str,
        executable_names: list[str],
        args: list[str],
        *,
        required: bool,
    ) -> dict[str, Any]:
        found = next((shutil.which(name) for name in executable_names if shutil.which(name)), None)
        if found is None:
            return self._state(
                component_id,
                False,
                required,
                reason=f"{'/'.join(executable_names)} was not found on the managed PATH",
            )
        try:
            executable = self.policy.allow_executable("runtime-detection", found)
            result = self.runner.run(
                "runtime-detection", executable, args, timeout_seconds=2.0, output_limit=16_384
            )
            version = (result.stdout or result.stderr).strip().splitlines()[0][:256]
            available = result.returncode == 0
            return self._state(
                component_id,
                available,
                required,
                version=version or None,
                reason=None if available else f"version probe exited {result.returncode}",
                path=Path(found).name,
            )
        except DocumentSkillsError as error:
            return self._state(component_id, False, required, reason=str(error))

    def _safe_detector(
        self,
        component_id: str,
        required: bool,
        detector: Any,
    ) -> dict[str, Any]:
        try:
            state = detector()
        except Exception as error:
            return unavailable_detector_state(
                component_id,
                required=required,
                reason=FAILED_DETECTOR_REASON,
            )
        try:
            return normalize_detector_state(
                state,
                trusted_id=component_id,
                required=required,
            )
        except Exception:
            return unavailable_detector_state(
                component_id,
                required=required,
                reason=INVALID_DETECTOR_REASON,
            )

    @staticmethod
    def _file_state(component_id: str, path: Path, *, required: bool) -> dict[str, Any]:
        available = path.is_file() and path.stat().st_size > 0
        return RuntimeDetectors._state(
            component_id,
            available,
            required,
            reason=None if available else f"{path.name} is missing or empty",
            path=path.name,
        )

    @staticmethod
    def _state(
        component_id: str,
        available: bool,
        required: bool,
        *,
        version: str | None = None,
        reason: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": component_id,
            "available": available,
            "version": version,
            "reason": reason,
            "required": required,
            "path": path,
        }

    @staticmethod
    def _evidence(state: dict[str, Any]) -> DetectionEvidence:
        return DetectionEvidence(
            available=state["available"],
            version=state["version"],
            reason=state["reason"],
            path=state["path"],
        )
