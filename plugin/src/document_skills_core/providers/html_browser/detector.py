"""Closed local Chromium-family detector with a real bounded launch probe."""

import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Any

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner

PLAYWRIGHT_CORE_VERSION = "1.62.1"
_PROBE_TIMEOUT_SECONDS = 20.0
_PROBE_OUTPUT_BYTES = 16_384
_BROWSER_VERSION = re.compile(r"^\d+(?:\.\d+){1,3}$")


class HtmlBrowserDetector:
    def __init__(
        self,
        project_root: Path,
        *,
        candidate_paths: tuple[Path, ...] | None = None,
        node_path: str | None = None,
        runner: Any | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.policy = ProcessPolicy(self.project_root)
        self.runner = runner or ProcessRunner(self.policy)
        self.candidate_paths = candidate_paths or _platform_candidates()
        self.node_path = node_path
        self._accepted_browser: Path | None = None

    def detect(self) -> DetectionEvidence:
        try:
            node = self._find_node()
            self._require_locked_library()
            browser = self._find_browser()
            browser_version = self._launch_probe(node, browser)
            self._accepted_browser = browser
            return DetectionEvidence(
                True,
                version=(
                    f"playwright-core {PLAYWRIGHT_CORE_VERSION}; "
                    f"Chromium engine {browser_version}"
                )[:256],
                path=str(browser),
            )
        except DocumentSkillsError as error:
            self._accepted_browser = None
            return DetectionEvidence(False, reason=str(error)[:512])

    def require_browser_path(self) -> Path:
        if self._accepted_browser is None:
            evidence = self.detect()
            if not evidence.available or self._accepted_browser is None:
                raise DocumentSkillsError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    evidence.reason or "HTML browser provider is unavailable.",
                    status="unavailable",
                )
        return self._accepted_browser

    def _find_node(self) -> Path:
        found = self.node_path or shutil.which("node")
        if not found:
            _unavailable("Managed Node.js is unavailable.")
        try:
            return Path(found).resolve(strict=True)
        except OSError:
            _unavailable("Managed Node.js evidence is invalid.")

    def _require_locked_library(self) -> None:
        manifest = self.project_root / "node_modules" / "playwright-core" / "package.json"
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1_048_576:
            _unavailable("Locked playwright-core runtime is unavailable.")
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _unavailable("Locked playwright-core runtime is invalid.")
        if package.get("name") != "playwright-core" or package.get("version") != PLAYWRIGHT_CORE_VERSION:
            _unavailable("Locked playwright-core version does not match policy.")

    def _find_browser(self) -> Path:
        invalid_evidence = False
        for candidate in self.candidate_paths:
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    invalid_evidence = invalid_evidence or candidate.exists()
                    continue
                resolved = candidate.resolve(strict=True)
                if resolved != candidate.resolve(strict=False):
                    invalid_evidence = True
                    continue
                return resolved
            except OSError:
                invalid_evidence = True
        if invalid_evidence:
            _unavailable("Browser executable evidence is invalid.")
        _unavailable("No supported local Chromium-family browser was found.")

    def _launch_probe(self, node: Path, browser: Path) -> str:
        executable = self.policy.allow_executable("html-browser", node)
        script = self.policy.allow_script(
            "html-browser", self.project_root / "runtime" / "node" / "html_capture.mjs"
        )
        private_base = self.project_root / ".document-skills-tmp"
        private_base.mkdir(mode=0o700, exist_ok=True)
        try:
            with TemporaryDirectory(prefix="browser-probe-", dir=private_base) as root:
                result = self.runner.run(
                    "html-browser",
                    executable,
                    [str(script)],
                    script=script,
                    stdin_json={
                        "protocol_version": "1.0",
                        "command": "probe",
                        "executable_path": str(browser),
                        "profile_root": root,
                    },
                    cwd=Path(root),
                    timeout_seconds=_PROBE_TIMEOUT_SECONDS,
                    output_limit=_PROBE_OUTPUT_BYTES,
                )
        except DocumentSkillsError as error:
            if error.code == ErrorCode.PROCESS_TIMEOUT:
                _unavailable("Browser launch probe timed out.")
            _unavailable("Browser launch probe failed.")
        try:
            payload = result.json()
        except DocumentSkillsError:
            _unavailable("Browser launch probe returned invalid evidence.")
        if type(payload) is not dict or set(payload) != {
            "protocol_version",
            "command",
            "ok",
            "browser_version",
            "reason",
        }:
            _unavailable("Browser launch probe returned invalid evidence.")
        if (
            result.returncode != 0
            or payload["protocol_version"] != "1.0"
            or payload["command"] != "probe"
            or payload["ok"] is not True
            or type(payload["browser_version"]) is not str
        ):
            _unavailable("Browser launch probe failed.")
        browser_version = payload["browser_version"]
        if not _BROWSER_VERSION.fullmatch(browser_version):
            _unavailable("Browser version evidence is invalid.")
        return browser_version


def _platform_candidates() -> tuple[Path, ...]:
    if sys.platform == "win32":
        roots = [
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        suffixes = (
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("Microsoft", "Edge", "Application", "msedge.exe"),
            ("Chromium", "Application", "chrome.exe"),
        )
        return tuple(dict.fromkeys(
            Path(root, *suffix)
            for root in roots
            if root
            for suffix in suffixes
        ))
    if sys.platform == "darwin":
        return (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        )
    found = [
        shutil.which(name)
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge")
    ]
    return tuple(Path(value) for value in found if value)


def _unavailable(message: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        message,
        status="unavailable",
    )
