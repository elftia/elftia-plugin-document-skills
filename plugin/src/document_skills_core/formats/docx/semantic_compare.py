"""Stable-ID semantic comparison for spec/output and before/after DOCX."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
)

from .contracts import ParsedDocxRequest
from .constants import qn
from .document_manifest import project_document_manifest
from .equations import project_equations
from .mapping import document_stories
from .package import OpcPackage
from .projection import project_images, project_sections, project_story, project_tables
from .references import project_references
from .results import read_validation, success_result
from .semantic_nodes import ALL_NODE_TYPES, semantic_node_for
from .structural_diff import summarize_structural_diff
from .style_profiles import public_style_profile

_MAX_NODES = 10_000
_MAX_TEXT = 1_000_000


def semantic_compare_operation(request: ParsedDocxRequest) -> dict[str, Any]:
    assert request.input_path is not None
    current_record = file_record(request.input_path, "input")
    current_package = OpcPackage.open(request.input_path)
    current = _project(current_package)
    artifacts = [current_record.as_dict()]
    guards = [current_record]
    if request.arguments["mode"] == "spec-output":
        comparison, resource_guards = _compare_spec(
            request.arguments["report"],
            current,
        )
        guards.extend(resource_guards)
    else:
        baseline_path = request.arguments["baseline"]
        baseline_record = file_record(baseline_path, "input")
        if baseline_record.sha256 != request.arguments["expected_baseline_sha256"]:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Semantic comparison baseline precondition did not match.",
                details={"reason": "baseline-sha256"},
            )
        baseline_package = OpcPackage.open(baseline_path)
        comparison = _compare_documents(
            baseline_package,
            _project(baseline_package),
            current_package,
            current,
            allowed=set(request.arguments["allowed_changes"]),
        )
        artifacts.append(baseline_record.as_dict())
        guards.append(baseline_record)
    for guard in guards:
        assert_source_preserved(guard.path, guard.sha256)
    validation = read_validation(
        "operation.semantic-compare-executed",
        {"semantic_comparison": comparison},
    )
    validation["gates"].append(
        gate_record(
            "operation.semantic-compare-result",
            "pass" if comparison["status"] == "pass" else "fail",
            required=False,
            evidence={
                "status": comparison["status"],
                "missing": len(comparison["missing"]),
                "unexpected": len(comparison["unexpected"]),
                "changed": len(comparison["changed"]),
                "degraded": len(comparison["degraded"]),
            },
        )
    )
    return success_result(
        request,
        artifacts=artifacts,
        operation_result={"semantic_comparison": comparison},
        warnings=[],
        validation=validation,
    )


def _compare_spec(
    report: dict[str, Any],
    actual: dict[str, Any],
) -> tuple[dict[str, Any], list[Any]]:
    expected_nodes, guards = _expected_nodes(report)
    comparison = _compare_projections(
        {
            "nodes": {node["node_id"]: node for node in expected_nodes},
            "order": [node["node_id"] for node in expected_nodes],
            "duplicates": [],
            "domain_profile": report.get("domain_profile"),
            "style_profile": public_style_profile(report.get("style_profile")),
            "sections": [section["orientation"] for section in report["sections"]],
        },
        actual,
        allowed=set(),
    )
    comparison.update({"mode": "spec-output", "expected": len(expected_nodes)})
    return comparison, guards


def _compare_documents(
    baseline_package: OpcPackage,
    baseline: dict[str, Any],
    current_package: OpcPackage,
    current: dict[str, Any],
    *,
    allowed: set[str],
) -> dict[str, Any]:
    comparison = _compare_projections(baseline, current, allowed=allowed)
    before_parts = set(baseline_package.parts)
    after_parts = set(current_package.parts)
    shared = before_parts & after_parts
    changed_parts = {
        name
        for name in shared
        if baseline_package.part_hashes[name] != current_package.part_hashes[name]
    }
    manifest = baseline_package.compare_preservation(
        current_package,
        allowed_changed=changed_parts,
        allowed_added=after_parts - before_parts,
        allowed_removed=before_parts - after_parts,
    )
    comparison.update(
        {
            "mode": "before-after",
            "expected": len(baseline["nodes"]),
            "structural_diff": summarize_structural_diff(
                baseline_package,
                current_package,
            ),
            "preservation_manifest": manifest.as_dict(),
        }
    )
    return comparison


def _compare_projections(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    allowed: set[str],
) -> dict[str, Any]:
    expected_ids = set(expected["nodes"])
    actual_ids = set(actual["nodes"])
    missing_all = [
        {
            "node_id": node_id,
            "expected_type": expected["nodes"][node_id]["node_type"],
        }
        for node_id in expected["order"]
        if node_id not in actual_ids
    ]
    unexpected_all = [
        {
            "node_id": node_id,
            "actual_type": actual["nodes"][node_id]["node_type"],
        }
        for node_id in actual["order"]
        if node_id not in expected_ids
    ]
    changed_all = []
    for node_id in expected["order"]:
        if node_id not in actual_ids:
            continue
        fields = _field_changes(expected["nodes"][node_id], actual["nodes"][node_id])
        if fields:
            changed_all.append({"node_id": node_id, "fields": fields})
    filtered_expected_order = [item for item in expected["order"] if item not in allowed]
    filtered_actual_order = [item for item in actual["order"] if item not in allowed]
    if filtered_expected_order != filtered_actual_order:
        changed_all.append(
            {
                "node_id": "$order",
                "fields": {
                    "order": {
                        "expected": filtered_expected_order,
                        "actual": filtered_actual_order,
                    }
                },
            }
        )
    for field in ("domain_profile", "style_profile", "sections"):
        if expected[field] != actual[field]:
            changed_all.append(
                {
                    "node_id": "$document",
                    "fields": {
                        field: {
                            "expected": expected[field],
                            "actual": actual[field],
                        }
                    },
                }
            )
    allowed_items = [
        {**item, "kind": kind}
        for kind, items in (
            ("missing", missing_all),
            ("unexpected", unexpected_all),
            ("changed", changed_all),
        )
        for item in items
        if item["node_id"] in allowed
    ]
    missing = [item for item in missing_all if item["node_id"] not in allowed]
    unexpected = [item for item in unexpected_all if item["node_id"] not in allowed]
    changed = [item for item in changed_all if item["node_id"] not in allowed]
    degraded = [
        {"code": "DOCX_SEMANTIC_DUPLICATE_NODE_ID", "node_id": node_id}
        for node_id in sorted(set(expected["duplicates"] + actual["duplicates"]))
    ]
    status = "pass" if not (missing or unexpected or changed or degraded) else "fail"
    return {
        "status": status,
        "missing": missing,
        "unexpected": unexpected,
        "changed": changed,
        "degraded": degraded,
        "allowed": allowed_items,
    }


def _expected_nodes(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    result = []
    guards = []
    for block in report["blocks"]:
        node = {
            "node_id": block["node_id"],
            "node_type": block["node_type"],
            "style": block.get("style"),
        }
        if block["type"] in {"heading", "paragraph", "reference"}:
            node["text"] = block["text"]
        if block["type"] == "heading":
            node["heading_level"] = block["level"]
        elif block["type"] == "table":
            node["rows"] = block["rows"]
        elif block["type"] == "image":
            record = file_record(block["path"], f"expected-resource:{block['node_id']}")
            guards.append(record)
            node.update({"alt_text": block["alt_text"], "sha256": record.sha256})
        elif block["type"] == "equation":
            node["linear"] = block["linear"]
        result.append(node)
    return result, guards


def _project(package: OpcPackage) -> dict[str, Any]:
    body = document_stories(package, include_headers_footers=False)[0]
    paragraphs, truncated = project_story(
        package,
        body,
        paragraph_limit=_MAX_NODES,
        text_limit=_MAX_TEXT,
    )
    tables, table_truncated = project_tables(
        body.root,
        table_limit=1_000,
        row_limit=10_000,
        text_limit=_MAX_TEXT,
    )
    if truncated["paragraphs"] or truncated["text"] or table_truncated:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Semantic comparison projection exceeded its safety limits.",
        )
    paragraph_map = {
        item["node_id"]: item for item in paragraphs if item.get("node_id") is not None
    }
    table_map = {
        item["node_id"]: item for item in tables if item.get("node_id") is not None
    }
    image_map = {
        item["node_id"]: item
        for item in project_images(package, body)
        if item.get("node_id") is not None
    }
    equation_map = {item["node_id"]: item for item in project_equations(body)}
    reference_map = {
        item["node_id"]: item for item in project_references(body)["bindings"]
    }
    order = []
    nodes: dict[str, dict[str, Any]] = {}
    duplicates = []
    body_node = package.xml("word/document.xml").find(qn("w", "body"))
    if body_node is None:
        raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "DOCX body is missing.")
    for child in body_node:
        semantic = semantic_node_for(child, allowed_types=ALL_NODE_TYPES)
        if semantic is None:
            continue
        node_id = semantic.node_id
        if node_id in nodes:
            duplicates.append(node_id)
            continue
        order.append(node_id)
        paragraph = paragraph_map.get(node_id, {})
        node = {
            "node_id": node_id,
            "node_type": semantic.node_type,
            "style": paragraph.get("style"),
        }
        if node_id in table_map:
            table = table_map[node_id]
            node["style"] = table["style"]
            node["rows"] = [
                [
                    "".join(item["text"] for item in cell["paragraphs"])
                    for cell in row["cells"]
                ]
                for row in table["rows"]
            ]
        elif node_id in image_map:
            image = image_map[node_id]
            node.update(
                {
                    "alt_text": image["alt_text"],
                    "sha256": package.part_hashes.get(image["target_part"] or ""),
                }
            )
        elif node_id in equation_map:
            node["linear"] = equation_map[node_id]["linear"]
        else:
            node["text"] = (
                reference_map[node_id]["display_text"]
                if node_id in reference_map
                else paragraph.get("text", "")
            )
            if semantic.node_type == "heading":
                node["heading_level"] = paragraph.get("heading_level")
        nodes[node_id] = node
    if len(nodes) > _MAX_NODES:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Semantic comparison node count exceeds its limit.",
        )
    manifest = project_document_manifest(package) or {}
    return {
        "nodes": nodes,
        "order": order,
        "duplicates": duplicates,
        "domain_profile": manifest.get("domain_profile"),
        "style_profile": manifest.get("style_profile"),
        "sections": [item["orientation"] for item in project_sections(package)],
    }


def _field_changes(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for field in sorted(set(expected) | set(actual)):
        if field == "node_id":
            continue
        if expected.get(field) != actual.get(field):
            result[field] = {
                "expected": expected.get(field),
                "actual": actual.get(field),
            }
    return result
