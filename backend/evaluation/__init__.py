"""Measurement for the claims Atlas makes.

Kept out of the `atlas` package deliberately: nothing here runs in a request, and the API
should not carry a benchmark corpus into production. It imports from `atlas`, never the
reverse.

Run it with `python -m evaluation` from `backend/`.
"""
