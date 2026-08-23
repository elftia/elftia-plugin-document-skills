"""Callable executable detection for Poppler rendering and Tesseract OCR."""

from pathlib import Path
import re
import shutil
from typing import Any

from document_skills_core.core.capabilities import DetectionEvidence
from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.core.process import ProcessPolicy, ProcessRunner

_POPPLER_VERSION = re.compile(r"(?:pdftoppm version|version)\s+([0-9]+(?:\.[0-9]+){1,3})", re.I)
_TESSERACT_VERSION = re.compile(r"^tesseract\s+([0-9]+(?:\.[0-9]+){1,3})", re.I)


class PdfToolDetector:
    def __init__(self, project_root: Path, *, require_tesseract: bool) -> None:
        self.project_root = project_root.resolve()
        self.require_tesseract = require_tesseract
        self._accepted: dict[str, Path] = {}

    def detect(self) -> DetectionEvidence:
        self._accepted = {}
        poppler = self._probe(
            "pdftoppm",
            ["-v"],
            _POPPLER_VERSION,
        )
        if type(poppler) is DetectionEvidence:
            return poppler
        poppler_path, poppler_version = poppler
        self._accepted["pdftoppm"] = poppler_path
        if not self.require_tesseract:
            return DetectionEvidence(
                True,
                version=poppler_version,
                path=str(poppler_path),
            )
        tesseract = self._probe(
            "tesseract",
            ["--version"],
            _TESSERACT_VERSION,
        )
        if type(tesseract) is DetectionEvidence:
            return tesseract
        tesseract_path, tesseract_version = tesseract
        self._accepted["tesseract"] = tesseract_path
        return DetectionEvidence(
            True,
            version=f"poppler-{poppler_version}+tesseract-{tesseract_version}",
            path=str(tesseract_path),
        )

    def accepted_paths(self) -> dict[str, Path]:
        return dict(self._accepted)

    def diagnostics(self) -> dict[str, Any]:
        evidence = self.detect()
        return {
            "available": evidence.available,
            "version": evidence.version,
            "executables": sorted(self._accepted),
            "reason": evidence.reason,
        }

    def _probe(
        self,
        name: str,
        arguments: list[str],
        version_pattern: re.Pattern[str],
    ) -> tuple[Path, str] | DetectionEvidence:
        candidate = shutil.which(name)
        if candidate is None:
            return DetectionEvidence(
                False,
                reason=f"The required {name} executable is unavailable.",
            )
        policy = ProcessPolicy(self.project_root)
        runner = ProcessRunner(policy)
        try:
            executable = policy.allow_executable("runtime-detection", candidate)
            result = runner.run(
                "runtime-detection",
                executable,
                arguments,
                cwd=self.project_root,
                timeout_seconds=3.0,
                output_limit=16_384,
            )
        except DocumentSkillsError:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} executable failed its callability probe.",
                path=candidate,
            )
        if result.returncode != 0:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} executable rejected its version probe.",
                path=candidate,
            )
        output = "\n".join((result.stdout, result.stderr)).strip()
        match = version_pattern.search(output)
        if match is None:
            return DetectionEvidence(
                False,
                reason=f"The detected {name} version evidence was unparseable.",
                path=candidate,
            )
        return executable, match.group(1)
