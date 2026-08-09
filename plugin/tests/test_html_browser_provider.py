"""Optional HTML browser provider detection and launch-probe tests."""

import json
from pathlib import Path

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessResult
from document_skills_core.providers.html_browser import HtmlBrowserDetector


class FakeRunner:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.probe_cwd: Path | None = None

    def run(self, _provider, _executable, args, **kwargs):
        self.probe_cwd = kwargs["cwd"]
        if self.mode == "timeout":
            raise DocumentSkillsError(ErrorCode.PROCESS_TIMEOUT, "timeout")
        payload = {
            "protocol_version": "1.0",
            "command": "probe",
            "ok": self.mode in {"success", "version-failure"},
            "browser_version": (
                "invalid" if self.mode == "version-failure"
                else "150.0.0.0" if self.mode == "success"
                else None
            ),
            "reason": None if self.mode in {"success", "version-failure"} else "browser_launch_failed",
        }
        if self.mode == "invalid-evidence":
            payload["extra"] = True
        return ProcessResult(0, json.dumps(payload), "", 2)


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    manifest = project / "node_modules" / "playwright-core" / "package.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "playwright-core", "version": "1.62.1"}),
        encoding="utf-8",
    )
    script = project / "runtime" / "node" / "html_capture.mjs"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("// fixture", encoding="utf-8")
    node = tmp_path / "node.exe"
    browser = tmp_path / "chrome.exe"
    node.write_bytes(b"node")
    browser.write_bytes(b"browser")
    return project, node, browser


def test_detector_accepts_exact_library_and_bounded_launch_evidence(tmp_path: Path):
    project, node, browser = _project(tmp_path)
    runner = FakeRunner()
    evidence = HtmlBrowserDetector(
        project,
        candidate_paths=(browser,),
        node_path=str(node),
        runner=runner,
    ).detect()
    assert evidence.available is True
    assert evidence.path == str(browser.resolve())
    assert "playwright-core 1.62.1" in (evidence.version or "")
    assert runner.probe_cwd is not None
    assert not runner.probe_cwd.exists()


def test_detector_reports_missing_node_library_and_browser(tmp_path: Path):
    project, node, browser = _project(tmp_path)
    missing_node = HtmlBrowserDetector(
        project,
        candidate_paths=(browser,),
        node_path=str(tmp_path / "missing-node"),
        runner=FakeRunner(),
    ).detect()
    assert missing_node.available is False
    assert "Node.js evidence" in (missing_node.reason or "")

    (project / "node_modules" / "playwright-core" / "package.json").unlink()
    missing_library = HtmlBrowserDetector(
        project,
        candidate_paths=(browser,),
        node_path=str(node),
        runner=FakeRunner(),
    ).detect()
    assert missing_library.available is False
    assert "playwright-core" in (missing_library.reason or "")

    _project(tmp_path)
    missing_browser = HtmlBrowserDetector(
        project,
        candidate_paths=(tmp_path / "missing-browser",),
        node_path=str(node),
        runner=FakeRunner(),
    ).detect()
    assert missing_browser.available is False
    assert "No supported" in (missing_browser.reason or "")


def test_detector_rejects_invalid_executable_evidence(tmp_path: Path):
    project, node, _browser = _project(tmp_path)
    invalid = tmp_path / "chrome-directory"
    invalid.mkdir()
    evidence = HtmlBrowserDetector(
        project,
        candidate_paths=(invalid,),
        node_path=str(node),
        runner=FakeRunner(),
    ).detect()
    assert evidence.available is False
    assert evidence.reason == "Browser executable evidence is invalid."


def test_detector_contains_version_launch_timeout_and_invalid_result(tmp_path: Path):
    project, node, browser = _project(tmp_path)
    cases = {
        "version-failure": "version evidence is invalid",
        "launch-failure": "launch probe failed",
        "timeout": "timed out",
        "invalid-evidence": "invalid evidence",
    }
    for mode, reason in cases.items():
        runner = FakeRunner(mode)
        evidence = HtmlBrowserDetector(
            project,
            candidate_paths=(browser,),
            node_path=str(node),
            runner=runner,
        ).detect()
        assert evidence.available is False
        assert reason in (evidence.reason or "").casefold()
        if runner.probe_cwd is not None:
            assert not runner.probe_cwd.exists()


def test_real_detector_is_truthful_and_bounded(project_root: Path):
    evidence = HtmlBrowserDetector(project_root).detect()
    assert type(evidence.available) is bool
    if evidence.available:
        assert evidence.path is not None
        assert Path(evidence.path).is_file()
        assert evidence.reason is None
    else:
        assert evidence.reason
