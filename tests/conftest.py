"""
Shared fixtures. Nothing here touches the network or the database, and that
is a rule rather than a coincidence: these tests exist to lock down the pure
decisions - what counts as an internship, what counts as the same job, what
counts as a closed posting - so they can run on a machine with no .env, no
Postgres and no signed-in session. Anything that needs a real site belongs in
docs/sites/ as a measurement, not here as a test.
"""

import sys
from pathlib import Path

import pytest

# The repo root, so `import scraper` works no matter where pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _Stats:
    """Stands in for crawler.stats, and records what was counted."""

    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count

    def set_value(self, key, value):
        self.values[key] = value


class _Crawler:
    def __init__(self):
        self.stats = _Stats()


@pytest.fixture
def make_checker():
    """
    A check spider with a verdict() that can be called, and nothing else.

    Built with object.__new__ rather than the constructor on purpose:
    LinkedinCheckSpider refuses to initialise without a signed-in session -
    correctly, since a run without one collects nothing - and that check has
    no business failing a unit test of the parsing. The other three would
    construct, but they go through the same door so that a future guard on
    any of them does not silently turn a test red.
    """

    def build(spider_class):
        spider = object.__new__(spider_class)
        spider.crawler = _Crawler()
        # BaseApiSpider.parse_json() calls _maybe_dump() first, which reads
        # this. Off is what a run without API_DEBUG_DUMP=1 has, and a test
        # writing files into debug/ would be a surprise.
        spider.debug_dump = False
        return spider

    return build
