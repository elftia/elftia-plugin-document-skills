"""Opt-in real PowerPoint editable-math consumer acceptance for B6."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from document_skills_core.formats.pptx.create import create_pptx
from document_skills_core.formats.pptx.read import read_pptx
from tests.test_pptx_equation import _supported_deck


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
def test_powerpoint_recognizes_every_generated_equation_as_editable_math_zone(
    tmp_path: Path,
) -> None:
    output = tmp_path / "powerpoint-equations.pptx"
    create_pptx(output, _supported_deck())
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
  $presentation = $ppt.Presentations.Open($env:PPTX_B6_PATH, -1, 0, 0)
  $mathNames = @()
  $mathZones = 0
  foreach ($slide in $presentation.Slides) {
    foreach ($shape in $slide.Shapes) {
      if ($shape.HasTextFrame -ne -1) { continue }
      if ($shape.Name -notlike 'eq-*') { continue }
      try {
        $count = $shape.TextFrame2.TextRange.MathZones.Count
      } catch {
        $count = 0
      }
      if ($count -gt 0) {
        $mathZones += $count
        $mathNames += $shape.Name
      }
    }
  }
  [pscustomobject]@{
    status = 'pass'
    mathZones = $mathZones
    names = @($mathNames | Sort-Object)
    slides = $presentation.Slides.Count
  } | ConvertTo-Json -Compress
  $presentation.SaveCopyAs($env:PPTX_B6_ROUNDTRIP, 24)
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
    environment["PPTX_B6_PATH"] = str(output)
    roundtrip = tmp_path / "powerpoint-roundtrip.pptx"
    environment["PPTX_B6_ROUNDTRIP"] = str(roundtrip)
    process = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
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

    assert result == {
        "status": "pass",
        "mathZones": 6,
        "names": [
            "eq-fraction",
            "eq-greek",
            "eq-matrix",
            "eq-root",
            "eq-scripts",
            "eq-sum",
        ],
        "slides": 1,
    }
    assert roundtrip.is_file()
    projected, warnings = read_pptx(roundtrip, {})
    assert warnings == []
    equations = [
        shape["equation"]
        for shape in projected["slides"][0]["shapes"]
        if shape["type"] == "equation"
    ]
    assert len(equations) == 6
    assert all(item["readback"] == {"status": "pass"} for item in equations)
