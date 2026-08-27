"""
LINK THE SAME OPENING ADVERTISED ON TWO BOARDS
==============================================

    python -m pipeline.dedupe_jobs             mark duplicates
    python -m pipeline.dedupe_jobs --dry-run   show what would be marked, change nothing

techcareer.net belongs to kariyer.net and carries the same ads, so one opening
arrives under two different urls. `url` is UNIQUE and correctly so - the two
pages really are different resources - which means the pipeline stores two
rows and the dashboard shows the job twice. Measured on 146 real postings:
3 pairs, one of them kariyer.net + Indeed rather than the sister site.

WHAT COUNTS AS THE SAME JOB
---------------------------
Same normalised title AND same normalised company AND different source sites.

Normalisation is `pipelines.canonical` - Turkish-aware lowercasing plus
separator flattening - which already exists because "YARI ZAMANLI".lower()
produces a dotless i that matches nothing.

The cross-site condition is the conservative part, and it is the point. Two
ads with the same title from the same company on ONE board are usually two
genuine openings (different teams, different districts) or the board's own
repost, and this project's rule is never to lose a posting. Across boards, an
identical title and company is the syndication described above. There were
zero same-site collisions in the measured data, so the restriction costs
nothing today and rules out a whole class of wrong merges.

Company names that differ between boards ("X A.Ş." vs "X") simply will not
match, and the job stays listed twice. That is the safe direction to fail.

WHAT IT DOES NOT DO
-------------------
Nothing is deleted or merged. The oldest row wins - stable across runs, unlike
anything based on which crawl happened to finish first - and the others get
`duplicate_of` pointing at it. Both rows keep their own url, so an application
link is never lost. Re-runnable: a pairing that no longer holds is cleared.
"""

import argparse
import sys
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

from scraper.models import JobPost, db_connect
from scraper.pipelines import canonical

load_dotenv()

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")


def signature(posting):
    return canonical(posting.job_title or ""), canonical(posting.company or "")


def find_duplicates(postings):
    """
    Returns {duplicate_row_id: canonical_row_id} for cross-site collisions.
    """
    groups = defaultdict(list)
    for posting in postings:
        groups[signature(posting)].append(posting)

    pairs = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        if len({m.source_site for m in members}) < 2:
            # One board's own repeat - could be two real openings. Leave both.
            continue

        # created_at can be equal down to the second when two spiders run back
        # to back, so id breaks the tie and keeps the choice deterministic.
        members.sort(key=lambda m: (m.created_at, m.id))
        keeper = members[0]
        for other in members[1:]:
            pairs[other.id] = keeper.id

    return pairs


def main():
    parser = argparse.ArgumentParser(
        description="Link postings that are the same job on another board."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change and write nothing.",
    )
    args = parser.parse_args()

    session = sessionmaker(bind=db_connect())()

    try:
        postings = session.query(JobPost).all()
        by_id = {p.id: p for p in postings}
        pairs = find_duplicates(postings)

        newly_marked, cleared = [], []

        for posting in postings:
            wanted = pairs.get(posting.id)
            if posting.duplicate_of == wanted:
                continue
            if wanted is None:
                cleared.append(posting)
            else:
                newly_marked.append((posting, by_id[wanted]))
            if not args.dry_run:
                posting.duplicate_of = wanted

        for duplicate, keeper in newly_marked:
            print(f"  duplicate: {duplicate.job_title}")
            print(f"      hidden  id={duplicate.id:<5} {duplicate.source_site}")
            print(f"      kept    id={keeper.id:<5} {keeper.source_site}")

        for posting in cleared:
            print(f"  no longer a duplicate: id={posting.id} {posting.job_title}")

        if not args.dry_run:
            session.commit()

        total = sum(1 for p in postings if pairs.get(p.id))
        print(
            f"\n{len(newly_marked)} newly marked, {len(cleared)} cleared - "
            f"{total} of {len(postings)} postings are duplicates."
        )
        if args.dry_run:
            print("(dry run - nothing was written)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
