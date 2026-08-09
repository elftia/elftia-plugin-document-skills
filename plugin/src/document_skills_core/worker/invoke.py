"""Provider-origin exception collapse inside the isolated worker."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderInvocationFailure(Exception):
    provider_id: str
    phase: str
    category: str
    exception_class: str


def invoke_provider(
    provider_id: str,
    phase: str,
    callback: Any,
    *args: Any,
) -> Any:
    try:
        return callback(*args)
    except BaseException as error:
        raise ProviderInvocationFailure(
            provider_id=provider_id[:128],
            phase=phase,
            category="provider_exception",
            exception_class=type(error).__name__[:64],
        ) from None
