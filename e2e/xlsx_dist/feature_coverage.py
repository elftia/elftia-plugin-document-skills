"""Validate XLSX feature evidence against collected tests and real assertions."""

from __future__ import annotations

import ast
from collections import defaultdict
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


DIST_PREFIX = "dist/document-skills/"
EVIDENCE_TIERS = {
    "dist-e2e",
    "focused-service",
    "public-subprocess",
    "real-provider",
}
EVIDENCE_ROLES = {"availability", "behavior"}
HIGH_RISK_DIST_OPERATIONS = {
    "xlsx.convert",
    "xlsx.create",
    "xlsx.edit",
    "xlsx.inspect.structure",
    "xlsx.pivot.create",
    "xlsx.read",
    "xlsx.summary.aggregate",
    "xlsx.template.instantiate",
}


def validate_feature_coverage(
    truth_table: dict[str, Any],
    coverage: dict[str, Any],
    *,
    repository_root: Path,
    dist_root: Path,
) -> dict[str, dict[str, Any]]:
    """Return exact feature evidence after validating every declared seam."""

    assert coverage["schema_version"] == "2.0"
    assert set(coverage) == {
        "schema_version",
        "dist_e2e_nodeids",
        "feature_evidence",
    }
    available = {
        f"{operation}/{feature}"
        for operation, record in truth_table["operations"].items()
        for feature in record.get("available", [])
    }
    evidence_by_feature = coverage["feature_evidence"]
    assert set(evidence_by_feature) == available

    dist_nodeids = coverage["dist_e2e_nodeids"]
    assert len(dist_nodeids) == len(set(dist_nodeids))
    assert all(nodeid.startswith("e2e/xlsx_dist/") for nodeid in dist_nodeids)

    behavior_uses: dict[str, set[str]] = defaultdict(set)
    all_nodeids: set[str] = set(dist_nodeids)
    dist_operations: set[str] = set()
    for feature_id, record in sorted(evidence_by_feature.items()):
        assert set(record) == {"evidence", "requires_provider"}, feature_id
        requires_provider = record["requires_provider"]
        assert requires_provider is None or (
            isinstance(requires_provider, str) and len(requires_provider) >= 8
        ), feature_id
        evidence = record["evidence"]
        assert isinstance(evidence, list) and evidence, feature_id
        assert len({item["nodeid"] for item in evidence}) == len(evidence), feature_id
        roles = {item["role"] for item in evidence}
        assert "behavior" in roles, feature_id
        if requires_provider is not None:
            assert "availability" in roles, feature_id
        else:
            assert roles == {"behavior"}, feature_id

        operation = feature_id.rsplit("/", 1)[0]
        for item in evidence:
            assert set(item) == {"assertion", "nodeid", "role", "tier"}, feature_id
            tier = item["tier"]
            role = item["role"]
            nodeid = item["nodeid"]
            assertion = item["assertion"]
            assert tier in EVIDENCE_TIERS, feature_id
            assert role in EVIDENCE_ROLES, feature_id
            assert isinstance(assertion, str) and len(assertion) >= 8, feature_id
            _validate_tier_path(tier, nodeid)
            _validate_assertion_anchor(
                repository_root,
                dist_root,
                nodeid,
                assertion,
            )
            all_nodeids.add(nodeid)
            if role == "behavior":
                behavior_uses[nodeid].add(feature_id)
                if tier == "dist-e2e":
                    assert nodeid in dist_nodeids, feature_id
                    dist_operations.add(operation)
            if tier == "real-provider":
                assert requires_provider is not None, feature_id
                assert role == "behavior", feature_id

    overbroad = {
        nodeid: sorted(features)
        for nodeid, features in behavior_uses.items()
        if len(features) > 12
    }
    assert not overbroad, overbroad
    assert HIGH_RISK_DIST_OPERATIONS <= dist_operations
    assert len({
        item["nodeid"]
        for record in evidence_by_feature.values()
        for item in record["evidence"]
        if item["tier"] == "dist-e2e" and item["role"] == "behavior"
    }) >= 3

    _collect_nodeids(repository_root, dist_root, all_nodeids)
    return evidence_by_feature


def _validate_tier_path(tier: str, nodeid: str) -> None:
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    if tier == "dist-e2e":
        assert path.startswith("e2e/xlsx_dist/test_xlsx_dist_e2e.py")
        return
    assert path.startswith(f"{DIST_PREFIX}tests/"), nodeid
    filename = Path(path).name
    if tier == "public-subprocess":
        assert filename == "test_xlsx_public.py" or filename.endswith("_public.py")
    elif tier == "real-provider":
        assert filename == "test_dotnet_xlsx_schema_real.py"
    else:
        assert filename.startswith("test_xlsx_")
        assert not filename.endswith("_public.py")


def _validate_assertion_anchor(
    repository_root: Path,
    dist_root: Path,
    nodeid: str,
    assertion_anchor: str,
) -> None:
    relative, *qualname = nodeid.split("::")
    assert qualname, nodeid
    normalized = relative.replace("\\", "/")
    if normalized.startswith(DIST_PREFIX):
        path = dist_root / normalized[len(DIST_PREFIX):]
    else:
        path = repository_root / normalized
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = _find_function(tree, qualname[0].split("[", 1)[0])
    assert function is not None, nodeid
    assert_sources = [
        ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
        for node in ast.walk(function)
        if isinstance(node, ast.Assert)
    ]
    normalized_anchor = "".join(assertion_anchor.split())
    assert any(
        normalized_anchor in "".join(source.split())
        for source in assert_sources
    ), (
        nodeid,
        assertion_anchor,
    )


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _collect_nodeids(
    repository_root: Path,
    dist_root: Path,
    nodeids: set[str],
) -> None:
    environment = os.environ.copy()
    environment.update({
        "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    e2e = sorted(nodeid for nodeid in nodeids if nodeid.startswith("e2e/"))
    release = sorted(
        nodeid[len(DIST_PREFIX):]
        for nodeid in nodeids
        if nodeid.startswith(DIST_PREFIX)
    )
    for cwd, selected in ((repository_root, e2e), (dist_root, release)):
        if not selected:
            continue
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                *selected,
            ],
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=False,
            shell=False,
            timeout=60,
        )
        assert process.returncode == 0, process.stdout.decode(
            "utf-8", errors="replace"
        )[-4000:]
