"""
RUN BY HAND, NEVER BY main.py.

    python -m tools.save_session indeed|linkedin   capture a signed-in session
    python -m tools.migrate                        add missing columns/indexes

Neither belongs in the crawl: save_session opens a VISIBLE browser and waits
for a person to sign in, and migrate changes the schema, which is not
something a scheduled run should do on its own.

The scraper's own diagnostic lives with the code it diagnoses instead:
`python -m scraper.tls_probe` - it imports three of the transport modules
directly.
"""
