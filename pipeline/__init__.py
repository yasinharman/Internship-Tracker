"""
WHAT HAPPENS AFTER THE POSTINGS ARE STORED.

main.py runs these three in order and the order is load-bearing - see
run_post_crawl() there for why dedupe comes before classify, and why notify
sits between them. Each one is also runnable on its own:

    python -m pipeline.dedupe_jobs --dry-run
    python -m pipeline.notify_watchlist --dry-run
    python -m pipeline.classify_jobs --dry-run

They read and write `job_posts` through scraper.models, which stays the only
description of the schema. Every one of them takes --dry-run, and none of
them deletes a row: a wrong call is always one UPDATE away from reversal.
"""
