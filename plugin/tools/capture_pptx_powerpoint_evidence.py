"""Capture hash-bound native-object and render evidence from real PowerPoint."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from document_skills_core.formats.pptx.png_compare import (
    compare_png,
    inspect_png,
    visual_thresholds,
)


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_TOOL_RELATIVE = "tools/capture_pptx_powerpoint_evidence.py"
_MAX_ARTIFACT_BYTES = 4_000_000
_MAX_EVIDENCE_BYTES = 32_768
_RECIPE = (
    "First run uv run --project plugin --frozen python -m "
    "tools.prepare_pptx_svg_roundtrip --source "
    "plugin/tests/fixtures/pptx/ecosystem_bc/svg/roundtrip-source.pptx "
    "--contract-root <presentation-contract-root> --output <roundtrip.pptx>; "
    "then run uv run --project plugin --frozen python -m "
    "tools.capture_pptx_powerpoint_evidence --source "
    "plugin/tests/fixtures/pptx/ecosystem_bc/svg/roundtrip-source.pptx "
    "--roundtrip <roundtrip.pptx> --output "
    "plugin/tests/fixtures/pptx/ecosystem_bc/expected/visual/"
    "b5-powerpoint-consumer.json"
)

_POWERSHELL_CAPTURE = r"""
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Read-Shape {
  param([object] $Shape)
  $record = [ordered]@{
    msoType = [int]$Shape.Type
    name = [string]$Shape.Name
  }
  try {
    if ([int]$Shape.HasTextFrame -eq -1) {
      $record.hasTextFrame = $true
      if ([int]$Shape.TextFrame.HasText -eq -1) {
        $record.text = [string]$Shape.TextFrame.TextRange.Text
      } else {
        $record.text = ""
      }
    }
  } catch {}
  try {
    if ([int]$Shape.HasTable -eq -1) {
      $record.hasTable = $true
      $rows = @()
      for ($row = 1; $row -le [int]$Shape.Table.Rows.Count; $row++) {
        $cells = @()
        for ($column = 1; $column -le [int]$Shape.Table.Columns.Count; $column++) {
          $cells += [string]$Shape.Table.Cell($row, $column).Shape.TextFrame.TextRange.Text
        }
        $rows += ,$cells
      }
      $record.tableCells = $rows
    }
  } catch {}
  try {
    if ([int]$Shape.HasChart -eq -1) {
      $record.hasChart = $true
      $record.chartType = [int]$Shape.Chart.ChartType
    }
  } catch {}
  if ([int]$Shape.Type -eq 6) {
    $children = @()
    for ($index = 1; $index -le [int]$Shape.GroupItems.Count; $index++) {
      $children += ,(Read-Shape $Shape.GroupItems.Item($index))
    }
    $record.children = $children
  }
  return $record
}

function Read-Deck {
  param(
    [object] $Application,
    [string] $Path,
    [string] $PngPath
  )
  $presentation = $null
  try {
    $presentation = $Application.Presentations.Open($Path, -1, 0, 0)
    $shapes = @()
    $slide = $presentation.Slides.Item(1)
    for ($index = 1; $index -le [int]$slide.Shapes.Count; $index++) {
      $shapes += ,(Read-Shape $slide.Shapes.Item($index))
    }
    $null = $slide.Export($PngPath, "PNG", 1920, 1080)
    return [ordered]@{
      slideCount = [int]$presentation.Slides.Count
      topLevelShapes = $shapes
      renderPng = $PngPath
    }
  } finally {
    if ($null -ne $presentation) {
      try { $presentation.Close() } catch {}
    }
  }
}

$application = $null
try {
  $application = New-Object -ComObject PowerPoint.Application
  $application.AutomationSecurity = 3
  $application.DisplayAlerts = 1
  $source = Read-Deck $application $env:DS_CAPTURE_SOURCE $env:DS_CAPTURE_SOURCE_PNG
  $roundtrip = Read-Deck $application $env:DS_CAPTURE_ROUNDTRIP $env:DS_CAPTURE_ROUNDTRIP_PNG
  [ordered]@{
    available = $true
    application = "Microsoft PowerPoint"
    version = [string]$application.Version
    source = $source
    roundtrip = $roundtrip
  } | ConvertTo-Json -Compress -Depth 30
} catch {
  [ordered]@{
    available = $false
    reason = ($_.Exception.GetType().FullName + ": " + $_.Exception.Message)
  } | ConvertTo-Json -Compress -Depth 10
} finally {
  if ($null -ne $application) {
    try { $application.Quit() } catch {}
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--roundtrip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _file_record(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    if not 0 < len(payload) <= _MAX_ARTIFACT_BYTES:
        raise ValueError(f"artifact is empty or exceeds capture policy: {path}")
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _capture(source: Path, roundtrip: Path) -> tuple[dict[str, object], bytes, bytes]:
    if sys.platform != "win32":
        return {"available": False, "reason": "PowerPoint COM requires Windows."}, b"", b""
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return {"available": False, "reason": "powershell.exe is unavailable."}, b"", b""
    with tempfile.TemporaryDirectory(prefix="pptx-powerpoint-capture-") as temporary:
        render_root = Path(temporary)
        source_png = render_root / "source.png"
        roundtrip_png = render_root / "roundtrip.png"
        environment = os.environ.copy()
        environment.update({
            "DS_CAPTURE_SOURCE": str(source),
            "DS_CAPTURE_ROUNDTRIP": str(roundtrip),
            "DS_CAPTURE_SOURCE_PNG": str(source_png),
            "DS_CAPTURE_ROUNDTRIP_PNG": str(roundtrip_png),
        })
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _POWERSHELL_CAPTURE,
            ],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            reason = completed.stderr.strip() or "PowerPoint capture process failed."
            return {"available": False, "reason": reason[:1_000]}, b"", b""
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return {"available": False, "reason": "PowerPoint capture returned no JSON."}, b"", b""
        observation = json.loads(lines[-1])
        if not observation.get("available"):
            return observation, b"", b""
        return observation, source_png.read_bytes(), roundtrip_png.read_bytes()


def _walk_shapes(shapes: list[dict[str, object]]) -> list[dict[str, object]]:
    walked: list[dict[str, object]] = []
    for shape in shapes:
        walked.append(shape)
        children = shape.get("children", [])
        if isinstance(children, list):
            walked.extend(_walk_shapes(children))
    return walked


def _deck_projection(observed: dict[str, object], artifact: dict[str, object]) -> dict[str, object]:
    shapes = observed["topLevelShapes"]
    assert isinstance(shapes, list)
    walked = _walk_shapes(shapes)
    chart = next((item for item in walked if item.get("hasChart") is True), None)
    table = next((item for item in walked if item.get("hasTable") is True), None)
    return {
        "artifact": artifact,
        "chartType": chart.get("chartType") if chart else None,
        "slideCount": observed["slideCount"],
        "tableCells": table.get("tableCells") if table else [],
        "topLevelShapes": shapes,
    }


def _assertions(source: dict[str, object], roundtrip: dict[str, object]) -> dict[str, object]:
    source_shapes = _walk_shapes(source["topLevelShapes"])
    roundtrip_shapes = _walk_shapes(roundtrip["topLevelShapes"])
    observed = source_shapes + roundtrip_shapes
    source_types = [item["msoType"] for item in source["topLevelShapes"]]
    roundtrip_types = [item["msoType"] for item in roundtrip["topLevelShapes"]]
    checks = {
        "chartEditable": any(item.get("hasChart") is True for item in observed),
        "groupEditable": all(any(item.get("msoType") == 6 for item in shapes) for shapes in (source_shapes, roundtrip_shapes)),
        "nativePictureReadback": all(any(item.get("msoType") == 13 for item in shapes) for shapes in (source_shapes, roundtrip_shapes)),
        "shapeEditable": all(any(item.get("msoType") == 1 for item in shapes) for shapes in (source_shapes, roundtrip_shapes)),
        "tableEditable": all(any(item.get("hasTable") is True for item in shapes) for shapes in (source_shapes, roundtrip_shapes)),
        "textEditable": all(any(item.get("text") == "Round trip" for item in shapes) for shapes in (source_shapes, roundtrip_shapes)),
    }
    return {
        **{key: "pass" if value else "fail" for key, value in checks.items()},
        "topLevelObjectTypesEqual": source_types == roundtrip_types,
    }


def _render_record(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        **inspect_png(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _build_evidence(
    source: Path,
    roundtrip: Path,
    observation: dict[str, object],
    source_png: bytes,
    roundtrip_png: bytes,
) -> dict[str, object]:
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_id = str(uuid.uuid4())
    tool_path = Path(__file__).resolve()
    base: dict[str, object] = {
        "capture": {
            "capturedAt": captured_at,
            "runId": run_id,
            "tool": {
                "path": _TOOL_RELATIVE,
                "sha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
            },
        },
        "consumer": {
            "application": "Microsoft PowerPoint",
            "method": "COM read-only open, native object readback, and PNG export",
            "outcome": "not_run",
            "platform": "windows-x64" if sys.platform == "win32" else sys.platform,
            "version": None,
        },
        "releaseBytePolicy": {
            "checkedInSource": "svg/roundtrip-source.pptx",
            "observationOnly": ["roundtrip.pptx", "scene-bundle/", "renders/"],
            "renderBytesIncluded": False,
        },
        "schemaVersion": 2,
        "source": {"artifact": _file_record(source)},
        "roundtrip": {"artifact": _file_record(roundtrip)},
    }
    if not observation.get("available"):
        base["consumer"]["reason"] = str(observation.get("reason", "PowerPoint unavailable."))
        return base
    source_projection = _deck_projection(observation["source"], _file_record(source))
    roundtrip_projection = _deck_projection(observation["roundtrip"], _file_record(roundtrip))
    assertions = _assertions(source_projection, roundtrip_projection)
    metrics = compare_png(source_png, roundtrip_png)
    successful = (
        all(value == "pass" for key, value in assertions.items() if key != "topLevelObjectTypesEqual")
        and assertions["topLevelObjectTypesEqual"] is True
        and metrics["within_thresholds"] is True
    )
    base.update({
        "assertions": assertions,
        "consumer": {
            **base["consumer"],
            "outcome": "pass" if successful else "fail",
            "version": observation["version"],
        },
        "renderComparison": {
            "metrics": metrics,
            "roundtripPng": _render_record(roundtrip_png),
            "sourcePng": _render_record(source_png),
            "thresholds": visual_thresholds(),
            "tool": "document_skills_core.formats.pptx.png_compare.compare_png",
        },
        "roundtrip": roundtrip_projection,
        "shapeTypeLegend": {
            "1": "msoAutoShape",
            "3": "msoChart",
            "6": "msoGroup",
            "13": "msoPicture",
            "19": "msoTable",
        },
        "source": source_projection,
    })
    return base


def _write_evidence(output: Path, evidence: dict[str, object]) -> None:
    payload = (json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > _MAX_EVIDENCE_BYTES:
        raise ValueError("PowerPoint evidence exceeds capture policy.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    manifest = {
        "expected_consumers": ["document-skills", "powerpoint"],
        "expected_operation": "pptx.scene.export,pptx.create.from-svg",
        "fixture_id": "B-SVG-04",
        "format": "json",
        "invariants": [
            "only executable PowerPoint COM capture can record a pass outcome",
            "source and round-trip artifacts, renders, tool, run, and time are hash-bound",
            "group, text, table, chart, and picture remain native objects",
            "temporary render and round-trip bytes are excluded from release bytes",
        ],
        "license": "GPL-3.0",
        "origin": (
            "Elftia-authored observation captured by the hash-bound PowerPoint tool; "
            f"run {evidence['capture']['runId']}."
        ),
        "path": "expected/visual/b5-powerpoint-consumer.json",
        "purpose": "Auditable Microsoft PowerPoint native-object and visual round-trip evidence for B-SVG-04.",
        "recipe": _RECIPE,
        "redistributable": True,
        "resource_limits": {"maxBytes": _MAX_EVIDENCE_BYTES},
        "schemaVersion": 1,
        "security_classification": "benign-consumer-evidence",
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "sizeBytes": len(payload),
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    args = _parse_args()
    source = args.source.resolve(strict=True)
    roundtrip = args.roundtrip.resolve(strict=True)
    output = args.output.resolve()
    observation, source_png, roundtrip_png = _capture(source, roundtrip)
    evidence = _build_evidence(source, roundtrip, observation, source_png, roundtrip_png)
    _write_evidence(output, evidence)
    print(json.dumps({
        "consumer_outcome": evidence["consumer"]["outcome"],
        "output": str(output),
        "run_id": evidence["capture"]["runId"],
    }, sort_keys=True))
    return 0 if evidence["consumer"]["outcome"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
