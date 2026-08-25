"""Provider-neutral scalar planner and contained core-node backend."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.process import ProcessPolicy, ProcessRunner

from .constants import qn
from .mapping import (
    TextGroup,
    TextRef,
    document_stories,
    iter_paragraphs,
    map_paragraph,
    protected_comment_text,
    semantic_tree_digest,
)
from .package import OpcPackage, PreservationManifest

TOKEN_PATTERN = re.compile(
    r"\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}"
)


@dataclass(frozen=True)
class TemplateOccurrence:
    variable: str
    source_start: int
    source_end: int
    output_start: int
    output_end: int
    value: str
    formatting_anchor: bytes


@dataclass(frozen=True)
class TemplateExpectation:
    part: str
    paragraph_index: int
    group_index: int
    source_text: str
    expected_text: str
    expected_node_texts: tuple[str, ...]
    occurrences: tuple[TemplateOccurrence, ...]


@dataclass(frozen=True)
class TemplateStoryOracle:
    part: str
    semantic_sha256: str


@dataclass(frozen=True)
class TemplatePlan:
    used: tuple[str, ...]
    missing: tuple[str, ...]
    unused: tuple[str, ...]
    protected: tuple[str, ...]
    changed_parts: tuple[str, ...]
    expectations: tuple[TemplateExpectation, ...]
    story_oracles: tuple[TemplateStoryOracle, ...]

    def as_dict(self) -> dict[str, Any]:
        counts = Counter(
            occurrence.variable
            for expectation in self.expectations
            for occurrence in expectation.occurrences
        )
        return {
            "used": list(self.used),
            "missing": list(self.missing),
            "unused": list(self.unused),
            "protected": list(self.protected),
            "planned_changed_parts": list(self.changed_parts),
            "occurrence_counts": dict(sorted(counts.items())),
        }


def plan_template(
    package: OpcPackage,
    variables: dict[str, str],
    *,
    required_story_parts: set[str] | None = None,
) -> TemplatePlan:
    used: set[str] = set()
    protected: set[str] = set()
    changed_parts = set(required_story_parts or set())
    raw_expectations: list[
        tuple[str, int, int, TextGroup, tuple[re.Match[str], ...]]
    ] = []
    stories = document_stories(package)
    for story in stories:
        part_used: set[str] = set()
        for paragraph_index, paragraph in enumerate(iter_paragraphs(story.root)):
            mapped = map_paragraph(paragraph)
            for group_index, group in enumerate(mapped.groups):
                tokens = _valid_tokens(group.text)
                part_used.update(tokens)
                matches = tuple(TOKEN_PATTERN.finditer(group.text))
                if matches:
                    raw_expectations.append(
                        (
                            story.part,
                            paragraph_index,
                            group_index,
                            group,
                            matches,
                        )
                    )
            protected.update(
                match.group(1)
                for match in TOKEN_PATTERN.finditer(mapped.protected_text)
            )
        if part_used:
            changed_parts.add(story.part)
            used.update(part_used)
    protected.update(
        match.group(1)
        for match in TOKEN_PATTERN.finditer(protected_comment_text(package))
    )
    missing = used - set(variables)
    unused = set(variables) - used
    if protected.intersection(variables):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "A supplied template variable occurs only within a protected DOCX boundary.",
            status="enhancement_required",
            details={
                "protected_variables": sorted(protected.intersection(variables)),
                "recommended_providers": ["dotnet-openxml"],
            },
        )
    if missing:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template variables are missing; no output was produced.",
            details={"missing_variables": sorted(missing)},
        )
    expectations = tuple(
        _build_expectation(
            part,
            paragraph_index,
            group_index,
            group,
            matches,
            variables,
        )
        for part, paragraph_index, group_index, group, matches in raw_expectations
    )
    mutable_nodes: dict[str, set[int]] = {}
    for raw, expectation in zip(raw_expectations, expectations, strict=True):
        part, _paragraph_index, _group_index, group, _matches = raw
        nodes = mutable_nodes.setdefault(part, set())
        for reference, expected_text in zip(
            group.refs,
            expectation.expected_node_texts,
            strict=True,
        ):
            reference.node.text = expected_text
            nodes.add(id(reference.node))
    story_oracles = tuple(
        TemplateStoryOracle(
            story.part,
            semantic_tree_digest(
                story.root,
                ignore_text_space_for=mutable_nodes.get(story.part, set()),
            ),
        )
        for story in stories
        if story.part in changed_parts
    )
    return TemplatePlan(
        tuple(sorted(used)),
        tuple(sorted(missing)),
        tuple(sorted(unused)),
        tuple(sorted(protected)),
        tuple(sorted(changed_parts)),
        expectations,
        story_oracles,
    )


def apply_template_with_node(
    project_root: Path,
    source: Path,
    destination: Path,
    *,
    variables: dict[str, str],
    plan: TemplatePlan,
) -> tuple[PreservationManifest, dict[str, Any]]:
    source_package = OpcPackage.open(source)
    policy = ProcessPolicy(project_root)
    executable = policy.allow_executable("core-node", "node")
    script = policy.allow_script(
        "core-node",
        project_root / "runtime" / "node" / "docx_template.mjs",
    )
    result = ProcessRunner(policy).run(
        "core-node",
        executable,
        [str(script)],
        script=script,
        stdin_json={
            "protocol_version": "1.0",
            "input": str(source),
            "output": str(destination),
            "variables": {name: variables[name] for name in plan.used},
            "approved_tokens": list(plan.used),
        },
        cwd=project_root,
        timeout_seconds=6.0,
        output_limit=65_536,
    )
    if result.returncode != 0:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "The internal DOCX template backend failed safely.",
            details={
                "provider": "core-node",
                "returncode": result.returncode,
                "stderr": result.stderr[:512],
            },
        )
    envelope = result.json()
    expected_fields = {
        "protocol_version",
        "status",
        "backend",
        "version",
        "approved_token_count",
        "bytes",
    }
    if type(envelope) is not dict or set(envelope) != expected_fields:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "The internal DOCX template backend returned an invalid envelope.",
        )
    if (
        envelope["protocol_version"] != "1.0"
        or envelope["status"] != "success"
        or envelope["backend"] != "docxtemplater"
        or envelope["version"] != "3.69.3"
        or envelope["approved_token_count"] != len(plan.used)
        or type(envelope["bytes"]) is not int
    ):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "The internal DOCX template backend response did not match its binding.",
        )
    output_package = OpcPackage.open(destination)
    manifest = source_package.compare_preservation(
        output_package,
        allowed_changed=set(plan.changed_parts),
    )
    return manifest, {
        "backend": envelope["backend"],
        "version": envelope["version"],
        "duration_ms": result.duration_ms,
    }


def _valid_tokens(text: str) -> set[str]:
    matches = list(TOKEN_PATTERN.finditer(text))
    scrubbed = TOKEN_PATTERN.sub("", text)
    if "{" in scrubbed or "}" in scrubbed:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Template contains syntax outside the approved scalar identifier grammar.",
            status="invalid_request",
        )
    return {match.group(1) for match in matches}


def _build_expectation(
    part: str,
    paragraph_index: int,
    group_index: int,
    group: TextGroup,
    matches: tuple[re.Match[str], ...],
    variables: dict[str, str],
) -> TemplateExpectation:
    rendered: list[str] = []
    occurrences: list[TemplateOccurrence] = []
    source_cursor = 0
    output_cursor = 0
    for match in matches:
        prefix = group.text[source_cursor : match.start()]
        rendered.append(prefix)
        output_cursor += len(prefix)
        variable = match.group(1)
        value = variables[variable]
        anchor = _source_anchor(group, match.start())
        if anchor is None:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Template planner could not bind a formatting anchor.",
                details={
                    "part": part,
                    "paragraph_index": paragraph_index,
                    "group_index": group_index,
                    "variable": variable,
                },
            )
        occurrences.append(
            TemplateOccurrence(
                variable,
                match.start(),
                match.end(),
                output_cursor,
                output_cursor + len(value),
                value,
                formatting_signature(anchor.run),
            )
        )
        rendered.append(value)
        output_cursor += len(value)
        source_cursor = match.end()
    rendered.append(group.text[source_cursor:])
    return TemplateExpectation(
        part,
        paragraph_index,
        group_index,
        group.text,
        "".join(rendered),
        _expected_node_texts(group, matches, variables),
        tuple(occurrences),
    )


def _expected_node_texts(
    group: TextGroup,
    matches: tuple[re.Match[str], ...],
    variables: dict[str, str],
) -> tuple[str, ...]:
    texts = [reference.original for reference in group.refs]
    for match in sorted(matches, key=lambda item: item.start(), reverse=True):
        affected = [
            index
            for index, reference in enumerate(group.refs)
            if reference.end > match.start() and reference.start < match.end()
        ]
        if not affected:
            raise RuntimeError("planned template token has no text nodes")
        first_index, last_index = affected[0], affected[-1]
        first = group.refs[first_index]
        last = group.refs[last_index]
        first_start = match.start() - first.start
        last_end = match.end() - last.start
        replacement = variables[match.group(1)]
        if first_index == last_index:
            current = texts[first_index]
            texts[first_index] = (
                current[:first_start] + replacement + current[last_end:]
            )
            continue
        texts[first_index] = texts[first_index][:first_start] + replacement
        for index in affected[1:-1]:
            texts[index] = ""
        texts[last_index] = texts[last_index][last_end:]
    return tuple(texts)


def _source_anchor(group: TextGroup, position: int) -> TextRef | None:
    return next(
        (
            reference
            for reference in group.refs
            if reference.start <= position < reference.end
        ),
        next(
            (
                reference
                for reference in group.refs
                if reference.start == position
            ),
            None,
        ),
    )


def formatting_signature(run: Element) -> bytes:
    properties = run.find(qn("w", "rPr"))
    return b"" if properties is None else tostring(properties, encoding="utf-8")
