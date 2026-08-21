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

from turex.core.errors import ProviderUnavailableError
from turex.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

JSON_INSTRUCTION = """
Reply with a single JSON array and nothing else — a `[`, the entries separated by commas, then
a `]`. No prose before it, no Markdown fence around it, no trailing commentary. If you cannot
produce any entries, reply with an empty array.
""".strip()


def parse_items(raw: str, item_type: type[T]) -> list[T]:
    """Read a JSON array of `item_type` out of a model response.

    Entries that do not validate are dropped rather than failing the batch: nine usable
    flashcards and one malformed one should produce nine cards. A response containing no JSON
    array at all is a different failure — the model did not do the task — and raises.
    """

    array = _extract_array(raw)
    if array is None:
        array = _extract_objects(raw)
    if array is None:
        raise ProviderUnavailableError(
            "The model did not return usable study material. Try again.",
            detail=f"no JSON array in a response of {len(raw)} characters",
        )

    items: list[T] = []
    reasons: list[str] = []
    for entry in array:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(item_type.model_validate(entry))
        except ValidationError as invalid:
            reasons.append(
                "; ".join(
                    f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                    for error in invalid.errors()[:3]
                )
            )

    if array and not items:
        # Every entry was rejected. That is a different failure from "the model produced
        # nothing", and it must not be reported as an empty result — the caller would store
        # an empty deck and call it success. Observed live: a model that referenced its source
        # in prose instead of setting the `source` field, so all entries lacked it.
        raise ProviderUnavailableError(
            "The model's study material was not in a usable form. Try again.",
            detail=f"{len(array)} entries returned, none valid: {reasons[:2]}",
        )

    if reasons:
        logger.info(
            "structured.entries_dropped",
            extra={"kept": len(items), "dropped": len(reasons), "first_reason": reasons[0]},
        )
    return items


def _extract_objects(raw: str) -> list[object] | None:
    """Read a bare sequence of JSON objects — JSON Lines, or objects separated by commas.

    A real model asked for "JSON" returned one object per line with no enclosing brackets,
    which is a fair reading of the instruction and which the array reader rejected outright.
    Accepting it costs a few lines and turns a total failure into a normal result.
    """
    objects: list[object] = []
    for candidate in _balanced_spans(_unfence(raw), "{", "}"):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects or None


def _extract_array(raw: str) -> list[object] | None:
    """Find the first balanced JSON array in a string.

    Scanning for balance rather than slicing between the first `[` and last `]`, because a
    truncated response often has an opening bracket and no closing one, and because brackets
    inside string values would otherwise throw the slice off.
    """

    text = _unfence(raw)
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


def _unfence(raw: str) -> str:
    """Strip a Markdown code fence, which models add despite being asked not to."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].removesuffix("```").strip()
    return text


def _balanced_spans(text: str, opening: str, closing: str) -> list[str]:
    """Every balanced `opening…closing` span at the top level, ignoring brackets in strings."""
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for index, character in enumerate(text):
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
        elif character == opening:
            if depth == 0:
                start = index
            depth += 1
        elif character == closing and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                spans.append(text[start : index + 1])
                start = -1

    return spans
