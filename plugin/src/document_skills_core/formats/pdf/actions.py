"""JavaScript/Launch/URI/GoToR/Named action tree classification (INERT).

Actions are classified by type and NEVER executed, followed, or fetched.
Inspection inventories them; all other operations fail closed on them.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any

from .object_model import IndirectReference, PdfDict, PdfObjectModel


@dataclass(frozen=True)
class ActionClassification:
    """Classification of a PDF action tree."""
    kind: str  # JavaScript, Launch, URI, GoToR, Named, GoTo, Unknown
    source_obj: int | None
    is_external: bool
    is_executable: bool
    description: str


def classify_actions(model: PdfObjectModel) -> list[ActionClassification]:
    """Walk the object graph and classify all action trees inertly."""
    actions: list[ActionClassification] = []
    for obj_num, obj in model.objects.items():
        value = obj.value
        if isinstance(value, PdfDict):
            _classify_dict_actions(model, value, obj_num, actions)
        elif isinstance(value, tuple) and isinstance(value[0], PdfDict):
            _classify_dict_actions(model, value[0], obj_num, actions)
    # Also check Catalog /OpenAction
    try:
        catalog_obj = model.get_object(model.catalog_ref)
        catalog = model.resolve(catalog_obj.value)
        if isinstance(catalog, PdfDict):
            open_action = catalog.get("/OpenAction")
            if isinstance(open_action, PdfDict):
                actions.append(_classify_action_dict(open_action, model.catalog_ref.obj_num))
            elif isinstance(open_action, IndirectReference):
                oa_obj = model.get_object(open_action)
                oa_val = model.resolve(oa_obj.value)
                if isinstance(oa_val, PdfDict):
                    actions.append(_classify_action_dict(oa_val, model.catalog_ref.obj_num))
    except Exception:
        pass
    return actions


def _classify_dict_actions(
    model: PdfObjectModel, d: PdfDict, obj_num: int, actions: list[ActionClassification]
) -> None:
    """Classify /A and /AA actions in a dictionary."""
    a = d.get("/A")
    if isinstance(a, PdfDict):
        actions.append(_classify_action_dict(a, obj_num))
    elif isinstance(a, IndirectReference):
        try:
            a_obj = model.get_object(a)
            a_val = model.resolve(a_obj.value)
            if isinstance(a_val, PdfDict):
                actions.append(_classify_action_dict(a_val, obj_num))
        except Exception:
            pass
    aa = d.get("/AA")
    if isinstance(aa, PdfDict):
        for sub_key, sub_val in aa.entries.items():
            if isinstance(sub_val, PdfDict):
                actions.append(_classify_action_dict(sub_val, obj_num))
    additional = d.get("/AdditionalActions")
    if isinstance(additional, PdfDict):
        for sub_key, sub_val in additional.entries.items():
            if isinstance(sub_val, PdfDict):
                actions.append(_classify_action_dict(sub_val, obj_num))


def _classify_action_dict(action: PdfDict, source_obj: int | None) -> ActionClassification:
    """Classify a single action dictionary."""
    action_type = action.get("/S", "")
    if action_type == "/JavaScript":
        return ActionClassification(
            kind="JavaScript",
            source_obj=source_obj,
            is_external=False,
            is_executable=True,
            description="JavaScript action — never executed by Core.",
        )
    if action_type == "/Launch":
        return ActionClassification(
            kind="Launch",
            source_obj=source_obj,
            is_external=True,
            is_executable=True,
            description="Launch action — external program, never executed.",
        )
    if action_type == "/URI":
        return ActionClassification(
            kind="URI",
            source_obj=source_obj,
            is_external=True,
            is_executable=False,
            description="URI action — external link, never fetched.",
        )
    if action_type == "/GoToR":
        return ActionClassification(
            kind="GoToR",
            source_obj=source_obj,
            is_external=True,
            is_executable=False,
            description="GoToR action — external document, never followed.",
        )
    if action_type == "/Named":
        return ActionClassification(
            kind="Named",
            source_obj=source_obj,
            is_external=True,
            is_executable=False,
            description="Named action — external, never resolved.",
        )
    if action_type == "/GoTo":
        return ActionClassification(
            kind="GoTo",
            source_obj=source_obj,
            is_external=False,
            is_executable=False,
            description="GoTo action — internal destination (inert inventory).",
        )
    return ActionClassification(
        kind="Unknown",
        source_obj=source_obj,
        is_external=False,
        is_executable=False,
        description=f"Unknown action type {action_type}.",
    )


def has_dangerous_actions(classifications: list[ActionClassification]) -> bool:
    """Check if any action is JavaScript, Launch, URI, or GoToR."""
    dangerous = {"JavaScript", "Launch", "URI", "GoToR", "Named"}
    return any(c.kind in dangerous for c in classifications)


def has_executable_embedded_files(model: PdfObjectModel) -> bool:
    """Check for embedded files with executable MIME types."""
    executable_mimes = {
        "application/x-msdownload", "application/x-dosexec",
        "application/x-executable", "application/x-sh",
        "application/x-bat", "application/x-csh",
    }
    for obj in model.objects.values():
        if isinstance(obj.value, PdfDict):
            ef = obj.value.get("/EF")
            if isinstance(ef, PdfDict):
                for _, ef_val in ef.entries.items():
                    if isinstance(ef_val, PdfDict):
                        mime = ef_val.get("/Subtype", "")
                        if isinstance(mime, str) and mime in executable_mimes:
                            return True
    return False
