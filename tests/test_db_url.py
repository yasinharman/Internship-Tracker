"""
The one-word url problem that reads like a missing driver.

Hosting panels hand out `postgres://`; SQLAlchemy dropped that alias in 1.4
and fails with "Can't load plugin: sqlalchemy.dialects:postgres", which sends
people looking for a driver they already have.
"""

import pytest

from scraper.models import normalize_db_url


def test_the_panels_scheme_is_rewritten():
    assert normalize_db_url("postgres://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_the_correct_scheme_is_left_alone():
    url = "postgresql://u:p@host:5432/db"
    assert normalize_db_url(url) == url


def test_only_the_scheme_changes():
    # A password containing the word must survive untouched.
    url = "postgres://user:postgres://@host:5432/db"
    assert normalize_db_url(url) == "postgresql://user:postgres://@host:5432/db"


@pytest.mark.parametrize("url", [
    "postgresql+psycopg2://u:p@host/db",
    "sqlite:///local.db",
])
def test_other_urls_pass_through(url):
    assert normalize_db_url(url) == url
