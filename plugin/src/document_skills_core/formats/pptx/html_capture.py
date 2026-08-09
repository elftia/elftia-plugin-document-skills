"""Python-owned private capture envelope for the checked-in browser adapter."""

import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Any, TYPE_CHECKING

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner
from .scene import SceneDeck, parse_scene_deck

if TYPE_CHECKING:
    from document_skills_core.providers.html_browser.detector import HtmlBrowserDetector

CAPTURE_TIMEOUT_SECONDS = 45.0
CAPTURE_STDOUT_BYTES = 16_384
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_HTML_BYTES = 8 * 1024 * 1024
_CAPTURE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class HtmlDeckCapture:
    def __init__(
        self,
        project_root: Path,
        detector: "HtmlBrowserDetector",
        *,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.detector = detector
        self.policy = ProcessPolicy(self.project_root)
        self.runner = runner or ProcessRunner(self.policy)

    def capture(
        self,
        html_path: Path,
        private_root: Path,
        fallback_policy: str,
        capture_visuals: bool = False,
    ) -> SceneDeck:
        if html_path.is_symlink():
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "HTML input symlinks are not accepted.",
                status="invalid_request",
            )
        source = html_path.resolve(strict=True)
        if (
            source.is_symlink()
            or not source.is_file()
            or source.stat().st_size <= 0
            or source.stat().st_size > MAX_HTML_BYTES
        ):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "HTML input is missing, linked, empty, or exceeds its byte ceiling.",
                status="invalid_request",
            )
        browser = self.detector.require_browser_path()
        node = shutil.which("node")
        if node is None:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Managed Node.js is unavailable.",
                status="unavailable",
            )
        executable = self.policy.allow_executable("html-browser", node)
        script = self.policy.allow_script(
            "html-browser", self.project_root / "runtime" / "node" / "html_capture.mjs"
        )
        root = private_root.resolve(strict=True)
        if not root.is_relative_to(self.project_root):
            raise DocumentSkillsError(
                ErrorCode.PATH_UNSAFE,
                "HTML capture root must remain inside the managed project root.",
            )
        nonce = secrets.token_hex(32)
        scene_path = root / "scene.json"
        assets_dir = root / "assets"
        profile_root = root / "browser-profile"
        try:
            result = self.runner.run(
                "html-browser",
                executable,
                [str(script)],
                script=script,
                stdin_json={
                    "protocol_version": "1.0",
                    "command": "capture",
                    "nonce": nonce,
                    "token": secrets.token_hex(32),
                    "html_path": str(source),
                    "private_root": str(root),
                    "scene_path": str(scene_path),
                    "assets_dir": str(assets_dir),
                    "profile_root": str(profile_root),
                    "browser_executable": str(browser),
                    "fallback_policy": fallback_policy,
                    "capture_visuals": capture_visuals,
                },
                cwd=root,
                timeout_seconds=CAPTURE_TIMEOUT_SECONDS,
                output_limit=CAPTURE_STDOUT_BYTES,
            )
        except DocumentSkillsError:
            raise
        payload = _capture_status(result.json(), nonce)
        if result.returncode != 0 or payload["ok"] is not True:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "HTML browser capture failed safely.",
                details={"reason": payload["reason"]},
            )
        if scene_path.is_symlink() or not scene_path.is_file():
            raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, "Private scene result is missing.")
        scene_bytes = scene_path.stat().st_size
        if scene_bytes <= 0 or scene_bytes > MAX_CAPTURE_BYTES or scene_bytes != payload["scene_bytes"]:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Private scene result violates its byte binding.",
            )
        try:
            raw = json.loads(scene_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Private scene result is invalid JSON.",
            ) from error
        scene = parse_scene_deck(raw, assets_dir, scene_bytes)
        if scene.observed["asset_bytes"] != payload["asset_bytes"]:
            raise DocumentSkillsError(
                ErrorCode.PROVIDER_FAILED,
                "Private scene result violates its asset byte binding.",
            )
        return scene


def _capture_status(value: Any, nonce: str) -> dict[str, Any]:
    fields = {
        "protocol_version",
        "command",
        "nonce",
        "ok",
        "scene_bytes",
        "asset_bytes",
        "reason",
    }
    if type(value) is not dict or set(value) != fields:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "HTML capture returned an invalid private status envelope.",
        )
    if (
        value["protocol_version"] != "1.0"
        or value["command"] != "capture"
        or value["nonce"] != nonce
        or type(value["ok"]) is not bool
        or type(value["scene_bytes"]) is not int
        or type(value["asset_bytes"]) is not int
        or type(value["reason"]) not in {str, type(None)}
        or not 0 <= value["scene_bytes"] <= MAX_CAPTURE_BYTES
        or not 0 <= value["asset_bytes"] <= MAX_CAPTURE_BYTES
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "HTML capture status binding failed.",
        )
    success_binding = (
        value["ok"] is True
        and value["scene_bytes"] > 0
        and value["reason"] is None
    )
    failure_binding = (
        value["ok"] is False
        and value["scene_bytes"] == 0
        and value["asset_bytes"] == 0
        and type(value["reason"]) is str
        and _CAPTURE_REASON.fullmatch(value["reason"]) is not None
    )
    if not success_binding and not failure_binding:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "HTML capture status success/failure binding failed.",
        )
    return value
