"""Getting a validated object out of a text model.

Both vendors offer a native structured-output mode, but they offer different ones, and this
package's whole point is that nothing above `base.py` knows which vendor is configured (see
`docs/decisions.md` D3). So the JSON is asked for in the prompt and validated here.

That makes the model's output untrusted input, which is the right way to treat it anyway.
Everything below is written for a response that is malformed, truncated, wrapped in prose, or
fenced in Markdown — all of which happen — and for the case where it is simply not JSON at
all, which raises rather than quietly returning nothing.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from atlas.core.errors import ProviderUnavailableError

T = TypeVar("T", bound=BaseModel)

JSON_INSTRUCTION = """
Reply with JSON and nothing else. No prose before it, no Markdown fence around it, no trailing
commentary. If you cannot produce any entries, reply with an empty array.
""".strip()


def parse_items(raw: str, item_type: type[T]) -> list[T]:
    """Read a JSON array of `item_type` out of a model response.

    Entries that do not validate are dropped rather than failing the batch: nine usable
    flashcards and one malformed one should produce nine cards. A response containing no JSON
    array at all is a different failure — the model did not do the task — and raises.
    """

    array = _extract_array(raw)
    if array is None:
        raise ProviderUnavailableError(
            "The model did not return usable study material. Try again.",
            detail=f"no JSON array in a response of {len(raw)} characters",
        )

    items: list[T] = []
    for entry in array:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(item_type.model_validate(entry))
        except ValidationError:
            continue
    return items


def _extract_array(raw: str) -> list[object] | None:
    """Find the first balanced JSON array in a string.

    Scanning for balance rather than slicing between the first `[` and last `]`, because a
    truncated response often has an opening bracket and no closing one, and because brackets
    inside string values would otherwise throw the slice off.
    """

    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ``` — drop the fence markers, keep everything between them.
        text = text.split("\n", 1)[-1].removesuffix("```").strip()

    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, list) else None

    return None
