"""One-write, encoding-independent JSON serialization for agent-facing stdout."""

import json
from typing import Any, TextIO

MAX_REQUEST_FILE_BYTES = 1_048_576


def dump_json(payload: Any, stream: TextIO) -> None:
    rendered = render_json_bytes(payload)
    try:
        binary = stream.buffer
    except AttributeError:
        binary = None
    if binary is not None:
        binary.write(rendered)
        binary.flush()
        return
    stream.write(rendered.decode("ascii"))
    stream.flush()


def render_json_bytes(payload: Any) -> bytes:
    """Build the complete canonical line before the first output write."""
    document = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return document.encode("ascii") + b"\n"


def load_json_file(path: str) -> Any:
    with open(path, "rb") as handle:
        payload = handle.read(MAX_REQUEST_FILE_BYTES + 1)
    if len(payload) > MAX_REQUEST_FILE_BYTES:
        raise ValueError(
            f"Request file exceeds the {MAX_REQUEST_FILE_BYTES}-byte limit."
        )
    return json.loads(payload.decode("utf-8"))
