"""Predeclared authorization and composition for PDF edit mutations."""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_mutation_plan import form_fill_object_plan
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import walk_pages


@dataclass(frozen=True)
class MutationPlan:
    """Object identities one primitive is allowed to mutate."""

    primitive: str
    changed: frozenset[int]
    added: frozenset[int]
    removed: frozenset[int]
    replace_document: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "primitive": self.primitive,
            "changed_objects": sorted(self.changed),
            "added_objects": sorted(self.added),
            "removed_objects": sorted(self.removed),
            "replace_document": self.replace_document,
        }


def declare_mutation_plan(
    model: PdfObjectModel,
    primitive: dict[str, Any],
) -> MutationPlan:
    """Declare object authorization before the primitive writer runs."""
    primitive_type = primitive["type"]
    if primitive_type in {"merge", "split", "page_insert", "page_sequence"}:
        objects = frozenset(model.objects)
        return MutationPlan(primitive_type, objects, frozenset(), objects, True)
    pages = walk_pages(model)
    maximum = max(max(model.objects), model.trailer.size - 1)
    if primitive_type == "rotate":
        changed = {pages[number - 1].obj_num for number in primitive["pages"]}
        return _plan(primitive_type, changed)
    if primitive_type == "watermark":
        selected = [pages[number - 1] for number in primitive["pages"]]
        changed = {page.obj_num for page in selected}
        changed.update(page.contents[0].obj_num for page in selected if page.contents)
        added = range(maximum + 1, maximum + len(selected) + 4)
        return _plan(primitive_type, changed, added=added)
    if primitive_type == "redact_text":
        page = pages[primitive["page"] - 1]
        return _plan(primitive_type, {ref.obj_num for ref in page.contents})
    if primitive_type == "annotation":
        return _annotation_plan(model, primitive, pages)
    if primitive_type == "metadata_update":
        changed = {model.catalog_ref.obj_num}
        if model.trailer.info is not None:
            changed.add(model.trailer.info.obj_num)
        catalog = model.get_object(model.catalog_ref).value
        if isinstance(catalog, PdfDict):
            metadata = catalog.get("/Metadata")
            if isinstance(metadata, IndirectReference):
                changed.add(metadata.obj_num)
        return _plan(primitive_type, changed, added={maximum + 1, maximum + 2})
    if primitive_type == "page_labels":
        changed = {model.catalog_ref.obj_num}
        labels = model.get_object(model.catalog_ref).value
        if isinstance(labels, PdfDict):
            labels = labels.get("/PageLabels")
            if isinstance(labels, IndirectReference):
                changed.add(labels.obj_num)
                removed = {labels.obj_num} if primitive["action"] == "clear" else set()
            else:
                removed = set()
        else:
            removed = set()
        return _plan(primitive_type, changed, added={maximum + 1}, removed=removed)
    if primitive_type == "outline":
        changed = _catalog_graph(model, "/Outlines") | {model.catalog_ref.obj_num}
        return _plan(
            primitive_type, changed, added={maximum + 1, maximum + 2},
            removed=changed - {model.catalog_ref.obj_num},
        )
    if primitive_type == "form_fill":
        changed, added, removed = form_fill_object_plan(model, primitive)
        return _plan(primitive_type, changed, added=added, removed=removed)
    return _plan(primitive_type, set())


def build_manifest(
    input_hashes: dict[int, str],
    output_hashes: dict[int, str],
    *,
    changed: set[int],
    added: set[int],
    removed: set[int],
) -> dict[str, Any]:
    """Bind output hashes to an explicit writer-supplied mutation plan."""
    input_keys = set(input_hashes)
    output_keys = set(output_hashes)
    actual_added = output_keys - input_keys
    actual_removed = input_keys - output_keys
    actual_changed = {
        number
        for number in input_keys & output_keys
        if input_hashes[number] != output_hashes[number]
    }
    unexpected_changed = actual_changed - changed
    unexpected_added = actual_added - added
    unexpected_removed = actual_removed - removed
    if unexpected_changed or unexpected_added or unexpected_removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit observed an object mutation outside its declared plan.",
            details={
                "unexpected_changed_objects": sorted(unexpected_changed),
                "unexpected_added_objects": sorted(unexpected_added),
                "unexpected_removed_objects": sorted(unexpected_removed),
            },
        )
    planned_changed = changed & output_keys
    planned_added = added & output_keys
    planned_removed = removed & input_keys
    preserved = (input_keys & output_keys) - planned_changed
    return {
        "changed_objects": sorted(planned_changed),
        "added_objects": sorted(planned_added),
        "removed_objects": sorted(planned_removed),
        "preserved_objects": sorted(preserved),
        "input_hashes": {str(key): value for key, value in input_hashes.items()},
        "expected_output_hashes": {
            str(key): value for key, value in output_hashes.items()
        },
        "output_hashes": {str(key): value for key, value in output_hashes.items()},
    }


def authorize_step_manifest(
    plan: MutationPlan,
    manifest: dict[str, Any],
    input_hashes: dict[int, str],
    output_hashes: dict[int, str],
) -> dict[str, Any]:
    """Reject observed changes outside the predeclared primitive plan."""
    declared_changed = _object_set(manifest, "changed_objects")
    declared_added = _object_set(manifest, "added_objects")
    declared_removed = _object_set(manifest, "removed_objects")
    actual_changed = {
        number
        for number in set(input_hashes) & set(output_hashes)
        if input_hashes[number] != output_hashes[number]
    }
    actual_added = set(output_hashes) - set(input_hashes)
    actual_removed = set(input_hashes) - set(output_hashes)
    unexpected = manifest.get("unexpected_mismatches", []) if plan.replace_document else []
    if not plan.replace_document:
        _require_subset(plan, actual_changed, actual_added, actual_removed)
        _require_subset(plan, declared_changed, declared_added, declared_removed)
        if not actual_changed <= declared_changed:
            _reject_unplanned(plan, changed=actual_changed - declared_changed)
        if actual_added != declared_added or actual_removed != declared_removed:
            _reject_unplanned(
                plan,
                added=actual_added ^ declared_added,
                removed=actual_removed ^ declared_removed,
            )
    if not unexpected:
        _assert_expected_hashes(manifest, output_hashes)
    normalized = dict(manifest)
    if plan.replace_document:
        normalized["expected_output_hashes"] = dict(
            manifest.get("expected_output_hashes", manifest.get("output_hashes", {}))
        )
        normalized["output_hashes"] = dict(manifest.get("output_hashes", {}))
    else:
        normalized["expected_output_hashes"] = {
            str(number): digest for number, digest in sorted(output_hashes.items())
        }
        normalized["output_hashes"] = dict(normalized["expected_output_hashes"])
    normalized["mutation_plan"] = plan.as_dict()
    normalized["candidate_object_numbers"] = sorted(output_hashes)
    return normalized


def aggregate_manifests(
    original_hashes: dict[int, str],
    step_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose step plans without deriving permissions from the final diff."""
    final_hashes = {
        int(number): digest
        for number, digest in step_manifests[-1]["expected_output_hashes"].items()
    }
    final_numbers = set(step_manifests[-1]["candidate_object_numbers"])
    replace_indexes = [
        index
        for index, manifest in enumerate(step_manifests)
        if manifest["mutation_plan"]["replace_document"]
    ]
    if replace_indexes:
        base_index = replace_indexes[-1]
        base = step_manifests[base_index]
        changed = set(base["changed_objects"])
        added = set(base["added_objects"])
        removed = set(base["removed_objects"])
        preserved = set(base["preserved_objects"])
        for manifest in step_manifests[base_index + 1:]:
            changed.update(manifest["changed_objects"])
            added.update(manifest["added_objects"])
            removed.update(manifest["removed_objects"])
            preserved.difference_update(changed | removed)
        changed &= final_numbers
        added &= final_numbers
        input_manifest = dict(base["input_hashes"])
    else:
        changed, added, removed = _compose_identity_plans(
            set(original_hashes),
            step_manifests,
        )
        changed &= final_numbers
        added &= final_numbers
        preserved = set(original_hashes) - changed - removed
        mismatched_preserved = {
            number
            for number in preserved
            if original_hashes[number] != final_hashes[number]
        }
        if mismatched_preserved:
            _reject_unplanned(
                MutationPlan("aggregate", frozenset(), frozenset(), frozenset()),
                changed=mismatched_preserved,
            )
        input_manifest = {
            str(number): digest for number, digest in sorted(original_hashes.items())
        }
    result = {
        "changed_objects": sorted(changed),
        "added_objects": sorted(added),
        "removed_objects": sorted(removed),
        "preserved_objects": sorted(preserved),
        "input_hashes": input_manifest,
        "expected_output_hashes": {
            str(number): digest for number, digest in sorted(final_hashes.items())
        },
        "output_hashes": {
            str(number): digest for number, digest in sorted(final_hashes.items())
        },
        "primitive_plans": [manifest["mutation_plan"] for manifest in step_manifests],
        "unexpected_mismatches": sorted({
            number
            for manifest in step_manifests
            for number in manifest.get("unexpected_mismatches", [])
        }),
    }
    if replace_indexes:
        result["identity_space"] = "renumbered"
    expectations = [
        manifest["metadata_expectation"]
        for manifest in step_manifests
        if isinstance(manifest.get("metadata_expectation"), dict)
    ]
    if expectations:
        result["metadata_expectation"] = expectations[-1]
    return result


def _compose_identity_plans(
    original: set[int],
    manifests: list[dict[str, Any]],
) -> tuple[set[int], set[int], set[int]]:
    """Compose declared object transitions, including transient additions."""
    changed: set[int] = set()
    added: set[int] = set()
    removed: set[int] = set()
    for manifest in manifests:
        for number in manifest["changed_objects"]:
            if number in original and number not in removed:
                changed.add(number)
        for number in manifest["added_objects"]:
            if number in removed:
                removed.remove(number)
                changed.add(number)
            elif number in original:
                changed.add(number)
            else:
                added.add(number)
        for number in manifest["removed_objects"]:
            if number in added:
                added.remove(number)
            elif number in original:
                removed.add(number)
                changed.discard(number)
    return changed, added, removed


def _annotation_plan(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    pages: list[Any],
) -> MutationPlan:
    page = pages[primitive["page"] - 1]
    changed = {page.obj_num}
    page_value = model.objects[page.obj_num].value
    annotations = page_value.get("/Annots", []) if isinstance(page_value, PdfDict) else []
    references = [item for item in annotations if isinstance(item, IndirectReference)]
    action = primitive["action"]
    if action == "add":
        return _plan("annotation", changed, added={max(model.objects) + 1})
    target = references[primitive["index"] - 1].obj_num if primitive["index"] <= len(references) else -1
    if action == "update":
        return _plan("annotation", {target})
    return _plan("annotation", changed, removed={target})


def _catalog_graph(model: PdfObjectModel, key: str) -> set[int]:
    catalog = model.get_object(model.catalog_ref).value
    root = catalog.get(key) if isinstance(catalog, PdfDict) else None
    pending = [root] if isinstance(root, IndirectReference) else []
    result: set[int] = set()
    while pending:
        reference = pending.pop()
        if reference.obj_num in result or reference.obj_num not in model.objects:
            continue
        result.add(reference.obj_num)
        pending.extend(_references(model.objects[reference.obj_num].value))
    return result


def _references(value: Any) -> list[IndirectReference]:
    if isinstance(value, IndirectReference):
        return [value]
    if isinstance(value, PdfDict):
        return [reference for item in value.entries.values() for reference in _references(item)]
    if isinstance(value, (list, tuple)):
        return [reference for item in value for reference in _references(item)]
    return []


def _plan(
    primitive: str,
    changed: Any,
    *,
    added: Any = (),
    removed: Any = (),
) -> MutationPlan:
    return MutationPlan(
        primitive,
        frozenset(changed),
        frozenset(added),
        frozenset(removed),
    )


def _object_set(manifest: dict[str, Any], field: str) -> set[int]:
    values = manifest.get(field)
    if type(values) is not list or any(type(item) is not int or item < 1 for item in values):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit preservation manifest has an invalid object set.",
            details={"field": field},
        )
    if values != sorted(set(values)):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit preservation manifest object sets must be sorted and unique.",
            details={"field": field},
        )
    return set(values)


def _require_subset(
    plan: MutationPlan,
    changed: set[int],
    added: set[int],
    removed: set[int],
) -> None:
    unexpected_changed = changed - plan.changed
    unexpected_added = added - plan.added
    unexpected_removed = removed - plan.removed
    if unexpected_changed or unexpected_added or unexpected_removed:
        _reject_unplanned(
            plan,
            changed=unexpected_changed,
            added=unexpected_added,
            removed=unexpected_removed,
        )


def _assert_expected_hashes(
    manifest: dict[str, Any],
    output_hashes: dict[int, str],
) -> None:
    expected = manifest.get("expected_output_hashes", {})
    mismatched = [
        int(number)
        for number, digest in expected.items()
        if output_hashes.get(int(number)) != digest
    ] if isinstance(expected, dict) else []
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF edit output does not match its planned object payloads.",
            details={"mismatched_objects": sorted(mismatched)},
        )


def _reject_unplanned(
    plan: MutationPlan,
    *,
    changed: set[int] | None = None,
    added: set[int] | None = None,
    removed: set[int] | None = None,
) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "PDF edit observed an object mutation outside its predeclared plan.",
        details={
            "primitive": plan.primitive,
            "unexpected_changed_objects": sorted(changed or set()),
            "unexpected_added_objects": sorted(added or set()),
            "unexpected_removed_objects": sorted(removed or set()),
        },
    )
