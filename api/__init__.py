"""
HTTP layer for the dashboard.

The board used to be a Streamlit script that opened its own connection and
pulled the whole table into pandas. It is now a React app, which cannot talk
to Postgres, so the reading half of that script lives here instead - split
into `queries.py` (the rules about WHICH rows count) and `main.py` (the
routes). `MultiwebsiteScraper.models` stays the only place the schema is
described.
"""
