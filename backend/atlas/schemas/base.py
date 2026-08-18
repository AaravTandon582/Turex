"""The base every request and response model inherits.

It exists for one reason: text arriving from a client is not safe to hand to PostgreSQL as-is.
A null byte in any string column raises `CharacterNotInRepertoireError` deep inside asyncpg,
which surfaces as a 500 — an unhandled server error caused by ordinary user input, on every
text field in the API at once.

Sanitising here rather than field by field is deliberate. A per-field validator has to be
remembered on every new field, and the one that gets forgotten is the one that breaks.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

# Null is rejected outright by PostgreSQL. The rest are C0 control characters that have no
# meaning in a title, a note, or a research question, and that make logs and terminals behave
# strangely. Tab, newline, and carriage return are kept: notes are Markdown and legitimately
# contain them.
_DISALLOWED = {code for code in range(0x20) if code not in (0x09, 0x0A, 0x0D)} | {0x7F}
_TRANSLATION = dict.fromkeys(_DISALLOWED)


def clean_text(value: str) -> str:
    """Remove characters that cannot be stored or displayed safely."""
    return value.translate(_TRANSLATION)


def _clean(value: Any) -> Any:
    """Walk a decoded JSON value, cleaning every string in it.

    Recursive because a string can arrive nested inside a list or a dict — the `options` array
    on a quiz answer, for instance — and a shallow pass would miss exactly those.
    """
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


class AtlasModel(BaseModel):
    """Base for every schema in Atlas."""

    @model_validator(mode="before")
    @classmethod
    def _strip_unsafe_characters(cls, data: Any) -> Any:
        # `mode="before"` so this runs ahead of field validation. Length limits then apply to
        # the cleaned text, which is what actually gets stored.
        return _clean(data)
