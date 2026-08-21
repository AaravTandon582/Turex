"""The limits themselves, in one place, with the reasoning attached.

Kept together rather than scattered across the routes they apply to, because the useful
question is "what does Turex allow" and answering it should not require reading every module.
"""

from __future__ import annotations

from turex.security.rate_limit import Limit

# --- authentication -------------------------------------------------------------

LOGIN_PER_ACCOUNT = Limit(requests=8, seconds=15 * 60)
"""Per email address. Low, because a person who has forgotten their password tries three or
four times and then resets it, while an attacker needs thousands. Keyed on the account rather
than the address so rotating IPs does not reset it."""

LOGIN_PER_ADDRESS = Limit(requests=30, seconds=15 * 60)
"""Per client address, so one host cannot spray attempts across many accounts. Higher than the
per-account limit because a shared network legitimately produces several people signing in."""

REGISTRATION_PER_ADDRESS = Limit(requests=5, seconds=60 * 60)
"""Stops one host from creating accounts in bulk."""

REFRESH_PER_ADDRESS = Limit(requests=120, seconds=15 * 60)
"""Generous: a long reading session refreshes legitimately every fifteen minutes, and several
tabs multiply that."""

# --- expensive work -------------------------------------------------------------

MODEL_CALLS_PER_USER = Limit(requests=40, seconds=60 * 60)
"""Every endpoint that reaches a language model. This is a cost control as much as a security
one — an automated loop against the assistant spends real money, and on a donated key it spends
someone else's."""

UPLOADS_PER_USER = Limit(requests=60, seconds=60 * 60)
"""Ingestion is the heaviest thing Turex does per request. Sixty an hour is far above real
reading and far below what it takes to exhaust the queue."""

SEARCH_PER_USER = Limit(requests=300, seconds=60 * 60)
"""Search is cheap but hits the database on every keystroke through the debounced UI."""
