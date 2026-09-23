"""
MEASURE A LOCAL MODEL ON POSTINGS THAT ARE ALREADY LABELLED
===========================================================

    python -m tools.eval_classifier --snapshot
        freeze the labelled rows into backups/eval-labelled.json, once

    python -m tools.eval_classifier --model qwen3.5:9b --limit 3
        smoke test: does the server return the schema at all

    python -m tools.eval_classifier --model qwen3.5:9b
        run the model over every frozen row and compare with the stored label

    python -m tools.eval_classifier --diff backups/eval-a.json backups/eval-b.json
        the postings two runs decided differently - the same model twice is
        the stability check, two models is the comparison

WRITES NOTHING TO THE DATABASE. The snapshot is read in a READ ONLY
transaction, and every result goes to a file in backups/ (gitignored: it is
scraped text).

WHY NOT `pipeline.classify_jobs --compare`
------------------------------------------
It reads load_unclassified(), and by now every row with a description has
been classified - so it sees 0 rows (docs/pipeline.md, "One change is needed
first"). Clearing job_category to make rows comparable would throw away the
stored verdicts, which are the only reference there is.

The reference is `gpt-5.4-mini`'s stored verdict, not the truth. The same
model moved borderline postings between runs (27/12/91 vs 29/13/88), so a
disagreement is something to read, not a score to subtract.

WHY A FROZEN SNAPSHOT
---------------------
The checks rewrite job_description when they pass, and the seven-day rule
changes which rows are active. Reading the database afresh for each model
would let the input move between two runs that are meant to differ in the
model alone. So the rows are frozen once, and every run reads the file.

ONE VARIABLE
------------
The prompt, DESCRIPTION_CHARS and the schema are imported from
scraper.classifier rather than copied, so they cannot drift; the prompt's hash
is written into every result file, and --diff says so when it differs.

Every model also gets the same REQUEST below. A local server otherwise uses
each model's own defaults: Qwen3.5 and Gemma 4 reason before answering unless
told not to, and each ships its own temperature. Left unset, those would be a
second and a third variable hidden behind the model name. Reasoning ON is a
separate question for later, asked of the winner alone.

REQUEST is scraper.classifier.LOCAL_REQUEST itself, not a copy: the nightly
`local` provider sends the same dict, so a model is measured the way it runs.

LOCAL ONLY
----------
.env holds the real OpenAI key, and the SDK reads OPENAI_API_KEY and
OPENAI_BASE_URL from the environment. So the client is built here, with a
throwaway key and a base URL that must point at this machine - a mistyped
flag cannot turn a measurement into an API bill.
"""

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from scraper.fields import ORDER as FIELD_ORDER
from scraper.classifier import (
    DESCRIPTION_CHARS,
    LOCAL_BASE_URL,
    LOCAL_REQUEST,
    SYSTEM_PROMPT,
    PostingFields,
    build_user_text,
)

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "backups" / "eval-labelled.json"
RESULTS_DIR = ROOT / "backups"

DEFAULT_BASE_URL = LOCAL_BASE_URL                   # Ollama
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# The vocabulary, since 23.09.2026: scraper/fields.py rather than the old
# it|general_program|other. Two things changed about what a disagreement
# COSTS. A posting is no longer hidden for its field, so "wrongly hidden" is
# now about is_internship alone; and a posting carries up to three fields, so
# two verdicts are compared as sets - equal, overlapping, or disjoint.
CATEGORIES = list(FIELD_ORDER)

# What every candidate is sent besides the prompt. Changing it is a new
# experiment, and every model has to be re-run under it.
REQUEST = LOCAL_REQUEST

PROMPT_SHA = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:16]


#####################################################
# SNAPSHOT                                          #
#####################################################
def take_snapshot(path, force):
    if path.exists() and not force:
        sys.exit(
            f"{path} already exists - every run so far was measured on it. "
            f"Pass --force to replace it, and then re-run every model."
        )

    # Imported here, not at the top: a model run needs neither the database
    # nor .env, and pipeline.classify_jobs loads .env - real key included -
    # into the environment as a side effect of being imported.
    from dotenv import load_dotenv
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from pipeline.classify_jobs import NO_DESCRIPTION
    from scraper.models import JobPost, db_connect

    load_dotenv(ROOT / ".env")
    session = sessionmaker(bind=db_connect())()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        postings = (
            session.query(JobPost)
            .filter(JobPost.job_category.isnot(None))
            .filter(JobPost.job_description.isnot(None))
            .filter(JobPost.job_description.notin_(NO_DESCRIPTION))
            .order_by(JobPost.id)
            .all()
        )
        rows = [
            {
                "id": p.id,
                "source_site": p.source_site,
                "job_title": p.job_title,
                "company": p.company,
                "location": p.location,
                "job_description": p.job_description,
                "job_category": p.job_category,
                "fields": sorted(f.field for f in (p.fields or [])) or (
                    [p.job_category] if p.job_category else []),
                "is_internship": p.is_internship,
                "category_reason": p.category_reason,
                "classified_at": p.classified_at.isoformat() if p.classified_at else None,
            }
            for p in postings
        ]
    finally:
        session.close()

    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {"taken_at": datetime.now(timezone.utc).isoformat(), "rows": rows},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    counts = ", ".join(
        f"{c}: {sum(1 for r in rows if r['job_category'] == c)}" for c in CATEGORIES
    )
    print(f"{len(rows)} labelled rows frozen into {path} - {counts}")


#####################################################
# ONE MODEL OVER THE SNAPSHOT                       #
#####################################################
def check_local(base_url):
    host = urlparse(base_url).hostname
    if host not in LOCAL_HOSTS:
        sys.exit(
            f"{base_url} is not this machine. This tool only measures local "
            f"models; see LOCAL ONLY at the top of the file."
        )


def make_client(base_url):
    from openai import OpenAI

    # max_retries=0: a retried request would be timed as one slow posting and
    # hide the failure. The long timeout is for the first request, which
    # loads the model into VRAM.
    return OpenAI(base_url=base_url, api_key="local", max_retries=0, timeout=300)


def server_version(base_url):
    """Ollama's own version, for the record. None from any other server."""
    import httpx

    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        return httpx.get(f"{root}/api/version", timeout=3).json().get("version")
    except Exception:
        return None


def classify_one(client, model, row):
    started = time.monotonic()
    completion = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_text(row)},
        ],
        response_format=PostingFields,
        **REQUEST,
    )
    seconds = time.monotonic() - started

    message = completion.choices[0].message
    if message.parsed is None:
        raise ValueError(f"no parsed output: {message.content!r:.200}")

    # Ollama returns any reasoning in a field of its own. With reasoning off
    # it should be empty; recording its length is how that is checked rather
    # than assumed.
    reasoning = (message.model_extra or {}).get("reasoning") or ""
    usage = completion.usage
    return message.parsed, {
        "seconds": round(seconds, 3),
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "reasoning_chars": len(reasoning),
    }


def run_model(model, base_url, snapshot_path, limit):
    check_local(base_url)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    rows = snapshot["rows"][:limit] if limit else snapshot["rows"]
    client = make_client(base_url)

    # The first request loads the model, which takes seconds and happens once
    # a night. Timed on its own so it does not inflate the per-posting figure.
    print(f"loading {model} at {base_url} ...", flush=True)
    started = time.monotonic()
    try:
        classify_one(client, model, rows[0])
    except Exception as error:
        sys.exit(f"the first request failed, nothing measured: {type(error).__name__}: {error}")
    load_seconds = round(time.monotonic() - started, 1)

    results = []
    for n, row in enumerate(rows, 1):
        entry = {
            "id": row["id"],
            "source_site": row["source_site"],
            "job_title": row["job_title"],
            "company": row["company"],
            "stored": row["job_category"],
            "stored_fields": row.get("fields") or [],
            "stored_internship": row.get("is_internship"),
            "stored_reason": row["category_reason"],
        }
        try:
            verdict, measured = classify_one(client, model, row)
            entry.update(category=verdict.fields[0], fields=list(verdict.fields),
                         is_internship=verdict.is_internship,
                         reason=verdict.reason, **measured)
            shown = (f"{','.join(entry['stored_fields'])[:24]:<26} -> "
                     f"{','.join(verdict.fields)[:24]:<26} {measured['seconds']:5.1f}s")
        except Exception as error:
            entry["error"] = f"{type(error).__name__}: {error}"[:300]
            shown = f"FAILED  {entry['error'][:80]}"
        results.append(entry)
        print(f"  {n:>3}/{len(rows)}  {shown}  {row['job_title']}", flush=True)

    meta = {
        "model": model,
        "base_url": base_url,
        "server_version": server_version(base_url),
        "request": REQUEST,
        "description_chars": DESCRIPTION_CHARS,
        "prompt_sha": PROMPT_SHA,
        "snapshot": str(snapshot_path),
        "snapshot_taken_at": snapshot["taken_at"],
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "load_seconds": load_seconds,
        "rows": len(rows),
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    out = RESULTS_DIR / f"eval-{safe}-{stamp}.json"
    out.write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    report(meta, results)
    print(f"\nsaved to {out}")


#####################################################
# REPORT                                            #
#####################################################
def tally(results):
    """
    Splits the answered rows by what a disagreement COSTS, because the kinds
    are not worth the same.

    Since 23.09.2026 a posting is not hidden for its field, so the expensive
    error changed. WRONGLY HIDDEN is now a posting stored as an internship
    that this model calls something else - the student never sees it. MISSED
    is a stored field the model did not give: the posting is on the board but
    not in the list that student is filtering for. EXTRA is the reverse, a
    field the model added - a row of noise in somebody else's list, which is
    the cheapest of the three.
    """
    answered = [r for r in results if "fields" in r]

    def stored_set(row):
        return set(row.get("stored_fields") or [])

    def given_set(row):
        return set(row.get("fields") or [])

    return {
        "answered": answered,
        "failed": [r for r in results if "error" in r],
        "agreed": [r for r in answered if stored_set(r) == given_set(r)],
        "overlapping": [
            r for r in answered
            if stored_set(r) != given_set(r) and stored_set(r) & given_set(r)
        ],
        "disjoint": [
            r for r in answered
            if stored_set(r) and given_set(r) and not (stored_set(r) & given_set(r))
        ],
        "missed": [r for r in answered if stored_set(r) - given_set(r)],
        "extra": [r for r in answered if given_set(r) - stored_set(r)],
        "wrongly_hidden": [
            r for r in answered
            if r.get("stored_internship") is not False and r.get("is_internship") is False
        ],
        "newly_shown": [
            r for r in answered
            if r.get("stored_internship") is False and r.get("is_internship") is not False
        ],
    }


def percentile(values, share):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def report(meta, results):
    groups = tally(results)
    answered = groups["answered"]

    print(f"\n{'=' * 70}")
    print(f"{meta['model']}  (server {meta['server_version'] or 'version unknown'})")
    print(f"prompt {meta['prompt_sha']}  DESCRIPTION_CHARS {meta['description_chars']}"
          f"  request {meta['request']}")
    print(f"{'=' * 70}")

    print(f"\nfields: stored vs {meta['model']}")
    print(f"  identical       {len(groups['agreed'])} of {len(answered)}")
    print(f"  overlapping     {len(groups['overlapping'])}   (share a field, not the same set)")
    print(f"  DISJOINT        {len(groups['disjoint'])}   <- no field in common")
    print(f"  missed a field  {len(groups['missed'])}")
    print(f"  added a field   {len(groups['extra'])}")

    print(f"\nWRONGLY HIDDEN  {len(groups['wrongly_hidden'])}   <- called it not an internship")
    print(f"newly shown     {len(groups['newly_shown'])}")
    print(f"failed          {len(groups['failed'])}")

    worst = sorted(
        ((len(set(r['stored_fields']) ^ set(r['fields'])), r) for r in groups['disjoint']),
        key=lambda pair: -pair[0],
    )[:10]
    if worst:
        print(f"\n{'-' * 70}\nDISJOINT - not one field in common")
        for _, row in worst:
            print(f"  {row['job_title'][:60]}")
            print(f"      stored {','.join(row['stored_fields'])}"
                  f"  ->  {','.join(row['fields'])}")
            print(f"      {row['reason'][:150]}")

    for title, key in (
        ("WRONGLY HIDDEN - stored as an internship, this model says it is not",
         "wrongly_hidden"),
        ("NEWLY SHOWN - stored as not an internship, this model shows it",
         "newly_shown"),
    ):
        if not groups[key]:
            continue
        print(f"\n{'-' * 70}\n{title}\n{'-' * 70}")
        for r in groups[key]:
            print(f"\n  {r['job_title']}  [{r['company']}]  id={r['id']} {r['source_site']}")
            print(f"      stored  {r['stored']:<16} {r['stored_reason']}")
            print(f"      model   {r['category']:<16} {r['reason']}")

    for r in groups["failed"]:
        print(f"\n  !! id={r['id']} {r['job_title']}: {r['error']}")

    if answered:
        seconds = [r["seconds"] for r in answered]
        prompt_tokens = [r["prompt_tokens"] for r in answered if r["prompt_tokens"]]
        completion_tokens = [r["completion_tokens"] for r in answered if r["completion_tokens"]]
        print(f"\n{'-' * 70}")
        print(f"load {meta['load_seconds']}s, then per posting: median "
              f"{statistics.median(seconds):.2f}s, p95 {percentile(seconds, 0.95):.2f}s, "
              f"total {sum(seconds):.0f}s for {len(answered)}")
        if prompt_tokens:
            print(f"prompt tokens max {max(prompt_tokens)} (Ollama cuts silently past its "
                  f"context, 4096 by default)")
        if completion_tokens:
            print(f"completion tokens median {statistics.median(completion_tokens):.0f}, "
                  f"max {max(completion_tokens)}")
        print(f"reasoning chars max {max(r['reasoning_chars'] for r in answered)} "
              f"(0 = reasoning really was off)")


#####################################################
# TWO RUNS SIDE BY SIDE                             #
#####################################################
def diff(path_a, path_b):
    a = json.loads(Path(path_a).read_text(encoding="utf-8"))
    b = json.loads(Path(path_b).read_text(encoding="utf-8"))

    for key in ("prompt_sha", "description_chars", "request", "snapshot_taken_at"):
        if a["meta"][key] != b["meta"][key]:
            print(f"!! {key} differs ({a['meta'][key]} vs {b['meta'][key]}) - "
                  f"these two runs differ in more than the model")

    name_a, name_b = a["meta"]["model"], b["meta"]["model"]
    by_id = {r["id"]: r for r in b["results"] if "category" in r}
    split = [
        (r, by_id[r["id"]]) for r in a["results"]
        if "category" in r and r["id"] in by_id
        and r["category"] != by_id[r["id"]]["category"]
    ]

    print(f"\n{len(split)} of {len(by_id)} postings decided differently")
    for left, right in split:
        print(f"\n  {left['job_title']}  [{left['company']}]  id={left['id']}"
              f"  stored {left['stored']}")
        print(f"      {name_a:<20} {left['category']:<16} {left['reason']}")
        print(f"      {name_b:<20} {right['category']:<16} {right['reason']}")


#####################################################
# ENTRY POINT                                       #
#####################################################
def main():
    parser = argparse.ArgumentParser(
        description="Measure a local model against the stored labels. Writes "
                    "nothing to the database."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", action="store_true",
                      help="Freeze the labelled rows into a file.")
    mode.add_argument("--model", help="Run this model over the frozen rows.")
    mode.add_argument("--diff", nargs=2, metavar="RESULT",
                      help="Print the postings two result files disagree on.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"A local OpenAI-compatible server (default {DEFAULT_BASE_URL}).")
    parser.add_argument("--rows", type=Path, default=SNAPSHOT,
                        help="The frozen rows to read or write.")
    parser.add_argument("--limit", type=int, help="Only the first N rows.")
    parser.add_argument("--force", action="store_true",
                        help="With --snapshot: replace an existing snapshot.")
    args = parser.parse_args()

    if args.snapshot:
        take_snapshot(args.rows, args.force)
    elif args.diff:
        diff(*args.diff)
    else:
        run_model(args.model, args.base_url, args.rows, args.limit)


if __name__ == "__main__":
    main()
