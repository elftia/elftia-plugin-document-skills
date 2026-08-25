"""Quote-aware discovery of effective commands in documentation surfaces."""

from dataclasses import dataclass
from pathlib import Path
import re

_WRAPPERS = {
    "call",
    "cmd",
    "command",
    "env",
    "nice",
    "nohup",
    "powershell",
    "pwsh",
    "sudo",
    "time",
}
_KNOWN_EXECUTABLES = {
    "bash",
    "bun",
    "cmd",
    "deno",
    "dotnet",
    "libreoffice",
    "node",
    "nodejs",
    "npm",
    "npx",
    "pdftoppm",
    "pip",
    "pip3",
    "pipx",
    "pnpm",
    "powershell",
    "pwsh",
    "python",
    "python3",
    "qpdf",
    "sh",
    "soffice",
    "tesseract",
    "uv",
    "yarn",
}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.DOTALL)
_POWERSHELL_ASSIGNMENT = re.compile(
    r"^\$env:[A-Za-z_][A-Za-z0-9_]*=.*$", re.IGNORECASE | re.DOTALL
)
_EXECUTABLE_PATH = re.compile(
    r"(?i)^(?:\.{0,2}[/\\])?(?:bin|runtime|providers?|scripts?)[/\\].+"
)
_PROMPTS = (
    re.compile(r"^(?:\([^)]+\)\s*)?PS\s+[^>]*>\s*", re.IGNORECASE),
    re.compile(r"^(?:\([^)]+\)\s*)?PS>\s*", re.IGNORECASE),
    re.compile(r"^[A-Za-z]:\\[^>]*>\s*"),
    re.compile(r"^(?:\$|#|>)\s+"),
)


@dataclass(frozen=True)
class DiscoveredCommand:
    original: str
    tokens: tuple[str, ...]
    effective_executable: str
    wrappers: tuple[str, ...]
    assignments: tuple[str, ...]
    unsafe_tokens: tuple[str, ...]


class CommandDiscovery:
    def discover(self, source: str) -> DiscoveredCommand | None:
        candidate = re.sub(r"\s+", " ", source.strip())
        for pattern in _PROMPTS:
            updated = pattern.sub("", candidate, count=1)
            if updated != candidate:
                candidate = updated.strip()
                break
        if not candidate or candidate.startswith(("# ", "//")):
            return None
        tokens, unsafe = self._tokenize(candidate)
        if not tokens:
            return None
        cursor = 0
        assignments: list[str] = []
        wrappers: list[str] = []
        while cursor < len(tokens):
            token = tokens[cursor]
            head = self._basename(tokens[cursor])
            if _ASSIGNMENT.fullmatch(token) or _POWERSHELL_ASSIGNMENT.fullmatch(
                token
            ):
                assignments.append(token)
                cursor += 1
                cursor = self._skip_prefix_operators(tokens, cursor)
                continue
            if head in {"export", "set", "setx"}:
                wrappers.append(head)
                cursor = self._consume_environment_prefix(
                    tokens, cursor + 1, head, assignments
                )
                cursor = self._skip_prefix_operators(tokens, cursor)
                continue
            if tokens[cursor] == "&":
                wrappers.append("&")
                cursor += 1
                continue
            if head not in _WRAPPERS:
                break
            wrappers.append(head)
            cursor += 1
            if head == "env":
                while cursor < len(tokens) and _ASSIGNMENT.fullmatch(tokens[cursor]):
                    assignments.append(tokens[cursor])
                    cursor += 1
            elif head == "cmd" and cursor < len(tokens) and tokens[cursor].casefold() in {
                "/c",
                "/k",
            }:
                wrappers.append(tokens[cursor].casefold())
                cursor += 1
            elif head in {"powershell", "pwsh"}:
                wrappers.extend(tokens[cursor:])
                cursor = len(tokens)
        executable = tokens[cursor] if cursor < len(tokens) else ""
        has_arguments = cursor + 1 < len(tokens)
        if (
            not self._looks_executable(executable, has_arguments=has_arguments)
            and not wrappers
            and not assignments
        ):
            return None
        return DiscoveredCommand(
            original=candidate,
            tokens=tuple(tokens),
            effective_executable=executable,
            wrappers=tuple(wrappers),
            assignments=tuple(assignments),
            unsafe_tokens=tuple(unsafe),
        )

    def looks_command_like(self, source: str) -> bool:
        candidate = source.strip()
        for pattern in _PROMPTS:
            candidate = pattern.sub("", candidate, count=1).strip()
        if not candidate or candidate.startswith(("# ", "//")):
            return False
        tokens, unsafe = self._tokenize(candidate)
        if not tokens:
            return False
        first = tokens[0]
        head = self._basename(first)
        return (
            head in _WRAPPERS | {"export", "set", "setx"}
            or bool(_ASSIGNMENT.fullmatch(first))
            or bool(_POWERSHELL_ASSIGNMENT.fullmatch(first))
            or self._looks_executable(first, has_arguments=len(tokens) > 1)
            or (
                bool(unsafe)
                and any(
                    self._looks_executable(
                        token, has_arguments=index + 1 < len(tokens)
                    )
                    for index, token in enumerate(tokens)
                )
            )
        )

    @staticmethod
    def _consume_environment_prefix(
        tokens: list[str],
        cursor: int,
        kind: str,
        assignments: list[str],
    ) -> int:
        if kind == "export":
            while cursor < len(tokens) and _ASSIGNMENT.fullmatch(tokens[cursor]):
                assignments.append(tokens[cursor])
                cursor += 1
            return cursor
        if kind == "set":
            if cursor < len(tokens) and _ASSIGNMENT.fullmatch(tokens[cursor]):
                assignments.append(tokens[cursor])
                return cursor + 1
            return cursor
        start = cursor
        while cursor < len(tokens) and tokens[cursor] not in {"&&", "||", ";"}:
            cursor += 1
        if cursor > start:
            assignments.append(" ".join(tokens[start:cursor]))
        return cursor

    @staticmethod
    def _skip_prefix_operators(tokens: list[str], cursor: int) -> int:
        while cursor < len(tokens) and tokens[cursor] in {"&&", "||", ";"}:
            cursor += 1
        return cursor

    @staticmethod
    def _tokenize(command: str) -> tuple[list[str], list[str]]:
        tokens: list[str] = []
        unsafe: list[str] = []
        current: list[str] = []
        quote = ""
        index = 0
        while index < len(command):
            char = command[index]
            if quote:
                if char == quote:
                    quote = ""
                else:
                    current.append(char)
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if char.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
                index += 1
                continue
            pair = command[index : index + 2]
            if pair in {"&&", "||", ">>", "<<", "$(", "${", "2>"}:
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(pair)
                unsafe.append(pair)
                index += 2
                continue
            if char in ";&|<>`":
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(char)
                unsafe.append(char)
                index += 1
                continue
            if char in {"$", "\r", "\n", "\0"}:
                unsafe.append(char)
            current.append(char)
            index += 1
        if current:
            tokens.append("".join(current))
        if quote:
            unsafe.append("unterminated-quote")
        return tokens, unsafe

    @classmethod
    def _looks_executable(
        cls, value: str, *, has_arguments: bool = False
    ) -> bool:
        if not value:
            return False
        unquoted = value.strip("\"'")
        basename = cls._basename(unquoted)
        suffix = Path(basename).suffix.casefold()
        normalized = (
            basename[: -len(suffix)]
            if suffix in {".exe", ".cmd", ".bat", ".com"}
            else basename
        )
        return (
            normalized in _KNOWN_EXECUTABLES
            or suffix in {".bat", ".cmd", ".com", ".exe", ".ps1", ".py", ".sh"}
            or (
                has_arguments
                and unquoted.startswith(("./", "../", ".\\", "..\\", "/"))
            )
            or (
                has_arguments
                and bool(re.match(r"^[A-Za-z]:[/\\]", unquoted))
            )
            or _EXECUTABLE_PATH.fullmatch(unquoted) is not None
        )

    @staticmethod
    def _basename(value: str) -> str:
        return re.split(r"[/\\]", value.strip("\"'"))[-1].casefold()
