"""Saying what actually went wrong with a model call.

Every upstream failure used to arrive as one sentence: *"Atlas couldn't reach the AI service.
Try again in a moment."* That is true of a dropped connection and false of everything else, and
the difference matters to whoever reads it.

It cost real time. A key whose credits had run out answered `402` on every request, Atlas
reported a reachability problem, and the quiz looked like broken code — the service was
perfectly reachable and no amount of retrying was going to change the answer.

So the status code is classified once, here, and the message says what the reader can do:

| Status | What it means | Retrying helps? |
|---|---|---|
| 401, 403 | the key is wrong, expired, or not allowed this model | no |
| 402 | the account is out of credit | no |
| 404 | the model name does not exist on this endpoint | no |
| 413, 422 | the request was too large or malformed | no |
| 429 | too many requests, for now | yes, later |
| 5xx, network | the service is genuinely having trouble | yes |
"""

from __future__ import annotations

from dataclasses import dataclass

CREDITS_EXHAUSTED = 402
UNAUTHORIZED = frozenset({401, 403})
NOT_FOUND = 404
TOO_LARGE = frozenset({413, 422})
RATE_LIMITED = 429


@dataclass(frozen=True, slots=True)
class Failure:
    """What to tell the user, and whether anything is worth trying."""

    message: str
    retryable: bool
    """Whether the *same* request could succeed later. Drives both the message and whether a
    fallback model is worth attempting."""

    exhausted: bool = False
    """Specifically out of credit, which the readiness endpoint reports separately: it is the
    one failure an operator can fix directly, and the one most likely to be mistaken for a bug.
    """

    account_wide: bool = False
    """True when the failure is about the *account*, not the model.

    A rate limit is the whole key being throttled, so trying a different model is another
    request against the same limit — the opposite of backing off. Everything else, including a
    dropped connection that keeps dropping, is worth trying another model for: it may be that
    model's upstream rather than the service.

    This distinction was originally drawn as "retryable", which conflated two different
    questions and got the answer wrong for connection errors — one flaky model then failed
    every request while three working fallbacks sat unused.
    """


def classify(status: int | None, detail: str = "") -> Failure:
    """Turn an upstream status into something worth showing someone.

    `detail` is inspected only to catch a mislabelled credit failure — some gateways answer
    `429` or `500` for an empty balance, and the body is the only place that says so. Nothing
    else depends on the body's wording, because that wording is the vendor's to change.
    """
    body = detail.lower()
    out_of_credit = (
        "insufficient credit" in body
        or "insufficient_quota" in body
        or "exceeded your current quota" in body
    )

    if status == CREDITS_EXHAUSTED or out_of_credit:
        return Failure(
            "The AI service has no credit left, so Atlas can't generate this. "
            "Top up the account behind ATLAS_OPENAI_API_KEY, or set OPENAI_MODEL to a free "
            "model. Everything that doesn't need a model still works.",
            retryable=False,
            exhausted=True,
        )

    if status in UNAUTHORIZED:
        return Failure(
            "The AI service rejected Atlas's API key. Check OPENAI_API_KEY, and that the key "
            "is allowed to use the configured model.",
            retryable=False,
        )

    if status == NOT_FOUND:
        return Failure(
            "The AI service doesn't offer the model Atlas is configured to use. "
            "Check OPENAI_MODEL.",
            retryable=False,
        )

    if status in TOO_LARGE:
        return Failure(
            "That request was too large for the AI service to accept. Try a shorter passage.",
            retryable=False,
        )

    if status == RATE_LIMITED:
        return Failure(
            "Atlas is being rate limited by the AI service. Try again in a minute.",
            retryable=True,
            account_wide=True,
        )

    return Failure("Atlas couldn't reach the AI service. Try again in a moment.", retryable=True)
