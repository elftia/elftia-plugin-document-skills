"""XLSX formula recalculation via headless convert-to-xlsx (no macro).

LibreOffice recalculates formulas on load by default. This module stages
the input XLSX, invokes ``soffice --convert-to xlsx``, and reads the
recomputed cached values from the converted file via the existing reader.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from ...core.io.temp_roots import OperationTempRoot
from ...formats.xlsx.mapping import map_workbook
from ...formats.xlsx.package import OpcPackage
from .runner import LibreOfficeRunner


def recalculate_xlsx(
    input_xlsx: Path,
    runner: LibreOfficeRunner,
) -> dict[str, Any]:
    """Recalculate XLSX formulas via headless convert-to-xlsx.

    Returns a dict mapping ``sheet!cell`` references to their recalculated
    cached value strings. NO macro is executed.
    """
    with OperationTempRoot() as private_root:
        staged_input = private_root / "input.xlsx"
        staged_input.write_bytes(Path(input_xlsx).read_bytes())
        output_dir = private_root / "output"
        output_dir.mkdir()
        converted = runner.convert(
            staged_input,
            "xlsx",
            output_dir,
        )
        return _extract_cached_values(converted)


def _extract_cached_values(converted_xlsx: Path) -> dict[str, Any]:
    """Read the converted XLSX and extract cached values for formula cells."""
    package = OpcPackage.open(converted_xlsx)
    workbook = map_workbook(package)
    result: dict[str, Any] = {}
    for sheet in workbook["sheets"]:
        sheet_name = sheet["name"]
        for row in sheet.get("rows", []):
            for cell in row.get("cells", []):
                formula = cell.get("formula")
                if formula:
                    ref = f"{sheet_name}!{cell['ref']}"
                    result[ref] = cell.get("cached_value")
    return result
