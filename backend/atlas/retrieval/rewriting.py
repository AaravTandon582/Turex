"""Turning a follow-up question into one that can be searched on its own.

Retrieval sees one string. "What about the second one?" carries almost no searchable content —
the words that matter are in the previous turn, not this one — so searching it literally
returns passages about ordinality and nothing about the subject. The reader experiences that as
the assistant forgetting what they were just discussing.

So a follow-up is rewritten into a standalone question before it is searched. The *answer* is
still generated from the original wording, because the user asked what they asked; only the
search string changes.

Two things keep this from making matters worse:

- A question that already stands alone is left exactly as it is. Most are. Rewriting a good
  question is a chance to lose the very term that would have found the passage.
- If the rewrite fails, is empty, or comes back absurdly long, the original is used. A broken
  rewrite must degrade to today's behaviour, never to a worse search.
"""

from __future__ import annotations

import re

from atlas.ai.base import ChatMessage, ChatProvider, ChatRequest, Role
from atlas.core.logging import get_logger

logger = get_logger(__name__)

MAX_REWRITE_CHARS = 400
"""A rewritten query longer than this is the model answering rather than rewriting."""

REWRITE_SYSTEM = """
You rewrite a follow-up question so it can be understood on its own, for a search engine that
sees only the question and none of the conversation.

Replace pronouns and references — "it", "that one", "the second", "this approach" — with the
thing they refer to, taken from the conversation. Keep the user's own terminology: their words
are what will match the document.

Do not answer the question. Do not add detail that was not there. Do not explain what you
changed. Reply with the rewritten question alone, on one line.

If the question already stands on its own, reply with it unchanged.
""".strip()

# Words and shapes that only make sense with a previous turn behind them.
_DEPENDENT = re.compile(
    r"\b(it|its|that|those|these|this|they|them|their|the (?:former|latter|first|second|third|"
    r"last|other|same)|there|then|also|instead|too)\b",
    re.IGNORECASE,
)

# A very short question is nearly always a follow-up: "why?", "and the results?"
SHORT_QUESTION_WORDS = 4


def needs_rewriting(question: str, has_history: bool) -> bool:
    """Whether this question is likely to be meaningless to a search engine on its own.

    Deliberately conservative. A rewrite costs a model call and risks losing a good search
    term, so it only happens when the question visibly leans on something already said.
    """
    if not has_history:
        return False

    words = question.split()
    if len(words) <= SHORT_QUESTION_WORDS:
        return True
    return bool(_DEPENDENT.search(question))


def _clean(candidate: str, fallback: str) -> str:
    """Accept a rewrite only if it looks like a question rather than an answer.

    The multi-line check comes first, before whitespace is collapsed. Doing it the other way
    round — as this did at first — folds "Rewritten: X\nExplanation: …" into one line and then
    looks for a newline that is no longer there, so the guard never fires and the explanation
    becomes the search query.
    """
    if candidate.strip().count("\n") > 0:
        return fallback

    text = " ".join(candidate.split())
    # Models occasionally wrap the result in quotes or prefix it with a label.
    text = re.sub(r"^(?:rewritten(?: question)?|query)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip('"').strip("'").strip()

    if not text or len(text) > MAX_REWRITE_CHARS:
        return fallback
    return text


async def rewrite_for_search(
    *,
    provider: ChatProvider,
    question: str,
    history: list[ChatMessage],
    max_turns: int = 4,
) -> str:
    """Return a standalone version of `question`, or the original if it does not need one.

    Never raises. A rewrite that fails falls back to the question as asked, because a failed
    rewrite must leave retrieval no worse than it was.
    """
    if not needs_rewriting(question, has_history=bool(history)):
        return question

    recent = history[-max_turns:]
    transcript = "\n".join(f"{turn.role.value}: {turn.content[:600]}" for turn in recent)

    try:
        result = await provider.complete(
            ChatRequest(
                system=REWRITE_SYSTEM,
                messages=[
                    ChatMessage(
                        role=Role.user,
                        content=f"Conversation so far:\n{transcript}\n\nFollow-up: {question}",
                    )
                ],
                max_output_tokens=200,
                effort="low",
            )
        )
    except Exception as exc:
        # Any provider fault at all: the question still works, just less well.
        logger.info(
            "query rewriting failed; searching the question as asked",
            extra={"error": str(exc)[:120]},
        )
        return question

    rewritten = _clean(result.text, question)
    if rewritten != question:
        logger.info(
            "rewrote a follow-up for search",
            extra={
                "original_words": len(question.split()),
                "rewritten_words": len(rewritten.split()),
            },
        )
    return rewritten
