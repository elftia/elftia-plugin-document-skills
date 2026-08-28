"""JavaScript/Launch/URI/GoToR/Named action tree classification (INERT).

Actions are classified by type and NEVER executed, followed, or fetched.
Inspection inventories them; all other operations fail closed on them.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any, Iterator

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObjectModel


_ACTION_TYPES = frozenset({
    "/JavaScript",
    "/Launch",
    "/URI",
    "/GoToR",
    "/Named",
    "/GoTo",
})
_DANGEROUS_ACTIONS = frozenset({"JavaScript", "Launch", "URI", "GoToR", "Named"})
_EXECUTABLE_MIMES = frozenset({
    "application/x-msdownload",
    "application/x-dosexec",
    "application/x-executable",
    "application/x-sh",
    "application/x-bat",
    "application/x-csh",
})
_EXECUTABLE_EXTENSIONS = frozenset({
    ".bat",
    ".cmd",
    ".com",
    ".csh",
    ".exe",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
})
_MAX_SECURITY_GRAPH_DEPTH = 64
_MAX_SECURITY_GRAPH_NODES = 1_000_000


@dataclass(frozen=True)
class ActionClassification:
    """Classification of a PDF action tree."""
    kind: str  # JavaScript, Launch, URI, GoToR, Named, GoTo, Unknown
    source_obj: int | None
    is_external: bool
    is_executable: bool
    description: str


def classify_actions(model: PdfObjectModel) -> list[ActionClassification]:
    """Walk the reachable object graph and classify all action trees inertly."""
    actions: list[ActionClassification] = []
    for dictionary, source_obj in _reachable_dictionaries(model):
        if dictionary.get("/S") in _ACTION_TYPES:
            actions.append(_classify_action_dict(dictionary, source_obj))
    return actions


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
    return any(c.kind in _DANGEROUS_ACTIONS for c in classifications)


def has_executable_embedded_files(model: PdfObjectModel) -> bool:
    """Check reachable embedded files for executable type, name, or bytes."""
    for dictionary, _source_obj in _reachable_dictionaries(model):
        object_type = dictionary.get("/Type")
        if object_type == "/EmbeddedFile":
            mime = dictionary.get("/Subtype", "")
            if (
                isinstance(mime, str)
                and mime.removeprefix("/").casefold() in _EXECUTABLE_MIMES
            ):
                return True
        embedded_files = _resolved_dictionary(model, dictionary.get("/EF"))
        if embedded_files is None:
            continue
        filenames = [dictionary.get("/UF"), dictionary.get("/F")]
        if any(_has_executable_extension(value) for value in filenames):
            return True
        if any(
            _embedded_payload(model, value).startswith(b"MZ")
            for value in embedded_files.entries.values()
        ):
            return True
    return False


def _resolved_dictionary(model: PdfObjectModel, value: Any) -> PdfDict | None:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    if isinstance(value, tuple):
        value = value[0]
    return value if isinstance(value, PdfDict) else None


def _embedded_payload(model: PdfObjectModel, value: Any) -> bytes:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[1], bytes)
    ):
        return value[1]
    return b""


def _has_executable_extension(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    filename = value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return any(filename.endswith(extension) for extension in _EXECUTABLE_EXTENSIONS)


def _reachable_dictionaries(
    model: PdfObjectModel,
) -> Iterator[tuple[PdfDict, int | None]]:
    """Yield Catalog-reachable dictionaries with bounded, cycle-safe traversal."""
    stack: list[tuple[Any, int | None, int]] = [(model.catalog_ref, None, 0)]
    seen_references: set[tuple[int, int]] = set()
    seen_containers: set[int] = set()
    visited_nodes = 0
    while stack:
        value, source_obj, depth = stack.pop()
        if depth > _MAX_SECURITY_GRAPH_DEPTH:
            _unsafe_graph("PDF security graph exceeds the maximum depth.")
        if isinstance(value, IndirectReference):
            reference = (value.obj_num, value.gen_num)
            if reference in seen_references:
                continue
            seen_references.add(reference)
            visited_nodes += 1
            if visited_nodes > _MAX_SECURITY_GRAPH_NODES:
                _unsafe_graph("PDF security graph exceeds the maximum node count.")
            target = model.get_object(value)
            stack.append((target.value, target.obj_num, depth + 1))
            continue
        if isinstance(value, tuple):
            value = value[0]
        if not isinstance(value, (PdfDict, list)):
            continue
        identity = id(value)
        if identity in seen_containers:
            continue
        seen_containers.add(identity)
        visited_nodes += 1
        if visited_nodes > _MAX_SECURITY_GRAPH_NODES:
            _unsafe_graph("PDF security graph exceeds the maximum node count.")
        if isinstance(value, PdfDict):
            yield value, source_obj
            children = list(value.entries.values())
        else:
            children = list(value)
        stack.extend(
            (child, source_obj, depth + 1)
            for child in reversed(children)
        )


def _unsafe_graph(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
