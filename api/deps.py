"""
ONE ENGINE, BUILT ONCE, SHARED BY EVERY REQUEST
===============================================

Streamlit called create_engine() inside a @st.cache_data function, so the
engine's lifetime was tied to a cache entry. A long-running ASGI process wants
the opposite: one engine held for the life of the process, handing out pooled
connections.
"""

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from scraper.models import normalize_db_url


class DatabaseNotConfigured(RuntimeError):
    """
    DATABASE_URL is missing.

    Deliberately its own type rather than a generic error: main.py turns it
    into a 503 carrying the same instructions Streamlit used to print on the
    page, so a misconfigured deployment says what to fix instead of showing a
    stack trace about a missing driver.
    """

    MESSAGE = (
        "DATABASE_URL ayarlanmamış. Yerel çalıştırma için .env dosyasına, "
        "sunucuda ise bu servisin Coolify ortam değişkenlerine ekleyin. "
        "Biçim: postgresql://kullanici:parola@host:5432/veritabani"
    )

    def __init__(self):
        super().__init__(self.MESSAGE)


# How long to wait for the TCP handshake before giving up on Postgres.
#
# Not a tuning knob - a correctness one. psycopg2 defaults to the operating
# system's connect timeout, which is around two minutes, so when the database
# host is unreachable (a firewall rule, a moved server, a Tailscale link that
# is down) every request including /api/health hangs instead of answering.
# A health check that hangs reads as "the process is gone" to whatever is
# watching it, which is the wrong call-out: the process is fine and the
# database is not.
CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    DATABASE_URL is required and has no fallback.

    The value app.py used to default to embedded a real password, which meant
    the password lived in a public repository and a misconfigured deployment
    quietly connected somewhere unintended instead of failing.

    pool_pre_ping because this process outlives its connections: Postgres (or
    anything between it and us) drops idle ones, and without the ping the
    first request after a quiet night fails on a stale socket.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise DatabaseNotConfigured()

    # Same `postgres://` rewrite the scraper does - the dashboard is usually
    # handed the identical connection string from the hosting panel.
    return create_engine(
        normalize_db_url(db_url),
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT},
    )


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session():
    """FastAPI dependency: one read-only session per request."""
    session: Session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
