"""Whole-operation wall-clock budgets for optional PDF tools."""

from collections.abc import Callable
from dataclasses import dataclass, field
import time

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


@dataclass
class OperationDeadline:
    timeout_seconds: float
    clock: Callable[[], float] = time.monotonic
    _ends_at: float = field(init=False)

    def __post_init__(self) -> None:
        self._ends_at = self.clock() + self.timeout_seconds

    def check(self) -> None:
        self.remaining(self.timeout_seconds)

    def remaining(self, per_call_ceiling: float) -> float:
        remaining = self._ends_at - self.clock()
        if remaining <= 0:
            raise DocumentSkillsError(
                ErrorCode.PROCESS_TIMEOUT,
                "Optional PDF provider exceeded its whole-operation time budget.",
                details={"timeout_seconds": self.timeout_seconds},
            )
        return min(remaining, per_call_ceiling)
