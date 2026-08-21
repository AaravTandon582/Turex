"""The documentation is checked against the code, not trusted.

Docs drift silently: an endpoint gets renamed, a limit gets tuned, and the prose keeps saying
what used to be true. That is worse than no documentation, because someone acts on it.

These assert the claims that are cheap to verify mechanically. Prose that needs judgement is
left to review — the point is to catch the statements that became false without anyone noticing.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPOSITORY / "docs"


def normalise(path: str) -> str:
    """Collapse path parameters, so `{id}` and `{paper_id}` compare equal."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def documented_endpoints() -> set[str]:
    text = (DOCS / "api.md").read_text()
    return {normalise(path) for path in re.findall(r"\| `(/[A-Za-z0-9/{}_-]+)`", text)}


def implemented_endpoints(app: Any) -> set[str]:
    return {normalise(path.replace("/api/v1", "")) for path in app.openapi()["paths"]}


class TestApiReference:
    async def test_no_endpoint_is_documented_that_does_not_exist(self, app: Any) -> None:
        """The failure that matters most: documentation for a feature that is not there."""
        invented = sorted(documented_endpoints() - implemented_endpoints(app))
        assert not invented, f"documented but not implemented: {invented}"

    async def test_no_endpoint_exists_that_is_not_documented(self, app: Any) -> None:
        """The other direction, which is how two endpoints slipped in undocumented.

        `health` and `ready` are described in prose rather than in the endpoint tables, so they
        are named here. Anything else added to this list should be a deliberate decision, not a
        way to silence the test.
        """
        prose_documented = {"/health", "/ready"}
        undocumented = sorted(
            implemented_endpoints(app) - documented_endpoints() - prose_documented
        )
        assert not undocumented, f"implemented but undocumented: {undocumented}"

    async def test_the_comparison_is_actually_comparing_something(self, app: Any) -> None:
        """Guards the guard — a broken regex would make the test above pass trivially."""
        assert len(documented_endpoints()) > 30
        assert len(implemented_endpoints(app)) > 30


class TestSecurityDocMatchesTheCode:
    """Numbers in the security document are the ones a reader will quote back."""

    def test_the_documented_rate_limits_are_the_configured_ones(self) -> None:
        from turex.security import policy

        text = (DOCS / "security.md").read_text()
        for limit, label in [
            (policy.LOGIN_PER_ACCOUNT, "login per account"),
            (policy.LOGIN_PER_ADDRESS, "login per address"),
            (policy.REGISTRATION_PER_ADDRESS, "registration"),
            (policy.MODEL_CALLS_PER_USER, "model calls"),
        ]:
            assert str(limit.requests) in text, (
                f"{label} count ({limit.requests}) is not in the doc"
            )

    def test_the_documented_grace_window_is_the_configured_one(self) -> None:
        from turex.core.config import Settings

        window = Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://localhost/turex_test",
            secret_key="a-test-secret-key-that-is-long-enough",
        ).refresh_grace_seconds
        assert f"{window}-second grace" in (DOCS / "security.md").read_text()


class TestEvaluationDocMatchesTheThresholds:
    """The published numbers must clear the floors the suite enforces.

    Checked as an inequality rather than a string match, because it catches both directions:
    a document quoting a score better than anything guaranteed, and thresholds raised above
    what was actually measured.
    """

    def test_the_published_scores_clear_the_enforced_floors(self) -> None:
        from evaluation.thresholds import MINIMUM_MRR, MINIMUM_RECALL_AT_3

        text = (DOCS / "evaluation.md").read_text()

        recall = re.search(r"\| recall@3 \| (\d+)% \|", text)
        mrr = re.search(r"\| MRR \| ([\d.]+) \|", text)
        assert recall and mrr, "evaluation.md no longer publishes recall@3 and MRR"

        assert int(recall.group(1)) / 100 >= MINIMUM_RECALL_AT_3, (
            f"documented recall@3 {recall.group(1)}% is below the enforced floor "
            f"{MINIMUM_RECALL_AT_3:.0%}"
        )
        assert float(mrr.group(1)) >= MINIMUM_MRR, (
            f"documented MRR {mrr.group(1)} is below the enforced floor {MINIMUM_MRR}"
        )
