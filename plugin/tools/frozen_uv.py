"""Typed authorization grammar for the documented frozen-uv commands."""

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from .command_discovery import DiscoveredCommand

_UNSAFE_PATH = re.compile(r"[\x00-\x1f;&|<>`$(){}[\]!?*%^]")


@dataclass(frozen=True)
class PathOperand:
    value: str

    @classmethod
    def parse(cls, value: str) -> "PathOperand":
        if (
            type(value) is not str
            or not value
            or value.startswith("-")
            or len(value.encode("utf-8", errors="strict")) > 4_096
            or _UNSAFE_PATH.search(value)
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
        ):
            raise ValueError("unsafe path operand")
        parts = PurePosixPath(value.replace("\\", "/")).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("dot/traversal path operand")
        return cls(value)


class FrozenUvGrammar:
    _PREFIX = (
        "uv",
        "run",
        "--project",
        "<project-root>",
        "--frozen",
        "python",
        "<skill-dir>/scripts/run.py",
    )

    def authorize(self, command: DiscoveredCommand) -> bool:
        if command.wrappers or command.assignments or command.unsafe_tokens:
            return False
        tokens = command.tokens
        if tokens == ("uv", "sync", "--project", "<project-root>", "--frozen"):
            return True
        if tokens[: len(self._PREFIX)] != self._PREFIX:
            return False
        tail = tokens[len(self._PREFIX) :]
        if tail in (("doctor", "--json"), ("capabilities", "--json")):
            return True
        if len(tail) == 3 and tail[:2] == ("run", "--request"):
            return self._safe_operand(tail[2])
        if (
            len(tail) == 4
            and tail[:2] == ("validate", "--input")
            and tail[3] == "--json"
        ):
            return self._safe_operand(tail[2])
        return False

    @staticmethod
    def _safe_operand(value: str) -> bool:
        try:
            PathOperand.parse(value)
        except (TypeError, UnicodeError, ValueError):
            return False
        return True
