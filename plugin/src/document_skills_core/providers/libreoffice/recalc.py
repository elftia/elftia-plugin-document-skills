"""XLSX formula recalculation via headless convert-to-xlsx (no macro).

LibreOffice recalculates formulas on load by default. This module stages
the input XLSX, invokes ``soffice --convert-to xlsx``, and reads the
recomputed cached values from the converted file via the existing reader.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.io.temp_roots import OperationTempRoot
from ...formats.xlsx.mapping import map_workbook
from ...formats.xlsx.package import OpcPackage
from .input_snapshot import private_libreoffice_input
from .output import read_provider_output
from .runner import LibreOfficeRunner


@dataclass(frozen=True)
class RecalculatedXlsx:
    """Contained provider output and the formula records it actually produced."""

    payload: bytes
    formulas: dict[str, dict[str, Any]]

    @property
    def cached_values(self) -> dict[str, Any]:
        return {
            ref: record.get("cached_value")
            for ref, record in self.formulas.items()
        }


def recalculate_xlsx(
    input_xlsx: Path,
    runner: LibreOfficeRunner,
) -> dict[str, Any]:
    """Recalculate XLSX formulas via headless convert-to-xlsx.

    Returns a dict mapping ``sheet!cell`` references to their recalculated
    cached value strings. NO macro is executed.
    """
    return recalculate_xlsx_artifact(input_xlsx, runner).cached_values


def recalculate_xlsx_artifact(
    input_xlsx: Path,
    runner: LibreOfficeRunner,
) -> RecalculatedXlsx:
    """Return the isolated converted artifact plus its formula/value projection."""

    with private_libreoffice_input(
        input_xlsx,
        operation="libreoffice.recalc-xlsx",
    ) as snapshot:
        return recalculate_xlsx_snapshot_artifact(snapshot.path, runner)


def recalculate_xlsx_snapshot_artifact(
    input_snapshot: Path,
    runner: LibreOfficeRunner,
) -> RecalculatedXlsx:
    """Recalculate an already screened private XLSX snapshot without restaging."""

    with OperationTempRoot() as private_root:
        output_dir = private_root / "output"
        output_dir.mkdir()
        converted = runner.convert(
            input_snapshot,
            "xlsx",
            output_dir,
        )
        formulas = _extract_formula_records(converted)
        return RecalculatedXlsx(
            payload=read_provider_output(converted, "xlsx"),
            formulas=formulas,
        )


def _extract_formula_records(converted_xlsx: Path) -> dict[str, dict[str, Any]]:
    """Read the converted XLSX and extract formula text, cached value, and type."""
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
                    result[ref] = {
                        "formula": formula,
                        "cached_value": cell.get("cached_value"),
                        "type": cell.get("type", "n"),
                    }
    return result
