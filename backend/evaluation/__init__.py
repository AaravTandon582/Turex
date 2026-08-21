"""Measurement for the claims Turex makes.

Kept out of the `turex` package deliberately: nothing here runs in a request, and the API
should not carry a benchmark corpus into production. It imports from `turex`, never the
reverse.

Run it with `python -m evaluation` from `backend/`.
"""
