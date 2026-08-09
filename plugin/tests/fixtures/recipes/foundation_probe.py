"""Deterministic recipe for foundation-probe.json.

Run through the frozen uv project; stdout is the complete fixture payload.
"""

import json
import sys

sys.stdout.buffer.write(
    (
        json.dumps(
        {"document_skills_fixture": "foundation", "schema_version": "1.0"},
        separators=(",", ":"),
        sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
)
