"""Opt-in real PowerPoint consumer acceptance for generated speaker notes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from document_skills_core.formats.pptx.create import create_pptx


def _powerpoint_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            r"PowerPoint.Application\CurVer",
        ):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    os.environ.get("DOCUMENT_SKILLS_TEST_POWERPOINT") != "1"
    or not _powerpoint_registered(),
    reason="real PowerPoint consumer test is opt-in and requires PowerPoint",
)
@pytest.mark.slow
def test_powerpoint_opens_generated_speaker_notes_without_repair(
    tmp_path: Path,
) -> None:
    output = tmp_path / "powerpoint-notes.pptx"
    create_pptx(output, {
        "metadata": {"title": "Notes", "creator": "Test", "subject": ""},
        "slides": [{
            "layout": "content",
            "title": "Notes",
            "shapes": [{"text": "Body", "runs": []}],
            "table": None,
            "chart_reference": None,
            "image_reference": None,
            "notes": "PowerPoint notes consumer",
        }],
    })
    script = r"""
$ErrorActionPreference = 'Stop'
$before = @(Get-Process POWERPNT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
if ($before.Count -gt 0) {
  [pscustomobject]@{status='busy'} | ConvertTo-Json -Compress
  exit 3
}
$ppt = $null
$presentation = $null
try {
  $ppt = New-Object -ComObject PowerPoint.Application
  $presentation = $ppt.Presentations.Open($env:PPTX_NOTES_PATH, -1, 0, 0)
  $text = @()
  foreach ($shape in $presentation.Slides.Item(1).NotesPage.Shapes) {
    if ($shape.HasTextFrame -ne -1) { continue }
    if ($shape.TextFrame.HasText -ne -1) { continue }
    $text += $shape.TextFrame.TextRange.Text
  }
  [pscustomobject]@{
    status = 'pass'
    slides = $presentation.Slides.Count
    notes = ($text -join "`n")
  } | ConvertTo-Json -Compress
} finally {
  if ($presentation -ne $null) { try { $presentation.Close() } catch {} }
  if ($ppt -ne $null) { try { $ppt.Quit() } catch {} }
  foreach ($item in @($presentation, $ppt)) {
    if ($item -ne $null) {
      try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($item) | Out-Null } catch {}
    }
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
"""
    environment = dict(os.environ)
    environment["PPTX_NOTES_PATH"] = str(output)
    process = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=False,
        shell=False,
        timeout=90,
        env=environment,
    )
    if process.returncode == 3:
        pytest.skip("PowerPoint is already open; consumer probe will not attach to it")
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    result = json.loads(process.stdout.decode("utf-8-sig", errors="strict"))

    assert result["status"] == "pass"
    assert result["slides"] == 1
    assert "PowerPoint notes consumer" in result["notes"]
