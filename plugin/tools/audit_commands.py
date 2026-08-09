"""Audit every agent-surface command against the frozen uv-only contract."""

from collections.abc import Iterable
from pathlib import Path
import re
from typing import Any

from .command_discovery import CommandDiscovery
from .frozen_uv import FrozenUvGrammar

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})([^`]*)$")
_SHELL_FENCE_LANGUAGES = {
    "bash",
    "bat",
    "batch",
    "cmd",
    "console",
    "powershell",
    "ps1",
    "pwsh",
    "sh",
    "shell",
    "terminal",
    "zsh",
}


def audit_agent_commands(root: Path) -> dict[str, Any]:
    inspected: list[str] = []
    discovery = CommandDiscovery()
    grammar = FrozenUvGrammar()
    surfaces = [root / "README.md", *sorted((root / "skills").glob("*/SKILL.md"))]
    for path in surfaces:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        fenced, prose = _markdown_surfaces(text)
        for line_number, command, continued in fenced:
            discovered = discovery.discover(command)
            _require(
                discovered is not None
                or not discovery.looks_command_like(command),
                f"Command-like Markdown cannot be proven safe at "
                f"{relative}:{line_number}: {command}",
            )
            if discovered is None:
                continue
            _require(
                not continued and grammar.authorize(discovered),
                f"Agent command is outside the exact frozen uv families at "
                f"{relative}:{line_number}: {command}",
            )
            inspected.append(f"{relative}:{line_number}:{discovered.original}")
        for command in _inline_code_spans(prose):
            discovered = discovery.discover(command)
            _require(
                discovered is not None
                or not discovery.looks_command_like(command),
                f"Command-like Markdown cannot be proven safe at "
                f"{relative}:inline: {command}",
            )
            if discovered is None:
                continue
            _require(
                grammar.authorize(discovered),
                f"Agent command is outside the exact frozen uv families at "
                f"{relative}:inline: {command}",
            )
            inspected.append(f"{relative}:inline:{discovered.original}")
    _require(inspected, "No agent-visible commands were audited")
    return {"status": "pass", "command_count": len(inspected)}


def _markdown_surfaces(text: str) -> tuple[list[tuple[int, str, bool]], str]:
    fenced: list[tuple[int, str, bool]] = []
    prose: list[str] = []
    active_delimiter = ""
    shell_fence = False
    pending: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if not active_delimiter and fence:
            active_delimiter = fence.group(1)
            language = fence.group(2).strip().split(maxsplit=1)[0].lower()
            shell_fence = language in _SHELL_FENCE_LANGUAGES
            pending = []
            continue
        if active_delimiter and fence and fence.group(1)[0] == active_delimiter[0]:
            fenced.extend(
                (start, command, continued)
                for start, command, continued in _join_continuations(pending)
            )
            active_delimiter = ""
            shell_fence = False
            pending = []
            continue
        if active_delimiter:
            pending.append((line_number, line))
        else:
            prose.append(line)
    _require(not active_delimiter, "Unclosed Markdown command fence")
    return fenced, "\n".join(prose)


def _join_continuations(
    lines: list[tuple[int, str]]
) -> Iterable[tuple[int, str, bool]]:
    start = 0
    pieces: list[str] = []
    had_continuation = False
    for line_number, line in lines:
        stripped = line.strip()
        if not pieces:
            start = line_number
        continuation = bool(stripped) and stripped[-1] in {"\\", "`", "^"}
        had_continuation = had_continuation or continuation
        pieces.append(stripped[:-1].rstrip() if continuation else stripped)
        if not continuation:
            command = " ".join(piece for piece in pieces if piece)
            if command:
                yield start, command, had_continuation
            pieces = []
            had_continuation = False
    if pieces:
        yield start, " ".join(piece for piece in pieces if piece), had_continuation


def _inline_code_spans(text: str) -> Iterable[str]:
    index = 0
    while index < len(text):
        if text[index] != "`" or _is_escaped(text, index):
            index += 1
            continue
        run = 1
        while index + run < len(text) and text[index + run] == "`":
            run += 1
        delimiter = "`" * run
        end = text.find(delimiter, index + run)
        if end < 0:
            index += run
            continue
        content = text[index + run : end]
        yield re.sub(r"\s+", " ", content).strip()
        index = end + run


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 1


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)
