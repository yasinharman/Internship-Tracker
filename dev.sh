#!/usr/bin/env bash
#
# RUN THE DASHBOARD LOCALLY
# =========================
# The board is two processes in development: Vite serves the front end with
# hot reload, and uvicorn serves /api. Vite proxies /api to uvicorn (see
# web/vite.config.ts), so the browser only ever talks to localhost:5173 and
# there is no CORS story. In production neither of these runs - FastAPI serves
# the built files itself.
#
#   ./dev.sh          use DATABASE_URL from .env
#   ./dev.sh --demo   start a throwaway Postgres with generated postings
#   ./dev.sh --build  no dev servers: build the front end and serve it exactly
#                     as production does, on 8501
#
# Ctrl-C stops everything it started.

set -euo pipefail
cd "$(dirname "$0")"

API_PORT=8000
WEB_PORT=5173
PROD_PORT=8501
DEMO_CONTAINER=ilan-panosu-demo-db
DEMO_PORT=55432
DEMO_URL="postgresql://postgres:demo@localhost:${DEMO_PORT}/jobs_demo"

MODE=serve
for arg in "$@"; do
  case "$arg" in
    --demo)  MODE=demo ;;
    --build) MODE=build ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "bilinmeyen seçenek: $arg (--demo, --build, --help)" >&2; exit 2 ;;
  esac
done

VENV=.venv/bin
if [ ! -x "$VENV/python" ]; then
  echo "!! .venv yok. Önce:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

########################################
# DEMO DATABASE                        #
########################################
# Every docker command names the context explicitly. The default context on
# this machine is the VPS, so a bare `docker run` here would start a container
# on the production server - which is emphatically not what `--demo` means.
docker_local() { docker -c default "$@"; }

start_demo_db() {
  if ! docker_local info >/dev/null 2>&1; then
    echo "!! yerel Docker çalışmıyor - --demo için gerekli" >&2
    exit 1
  fi

  if [ -n "$(docker_local ps -q -f name="^${DEMO_CONTAINER}$")" ]; then
    echo "-> demo veritabanı zaten çalışıyor"
  else
    docker_local rm -f "$DEMO_CONTAINER" >/dev/null 2>&1 || true
    echo "-> demo veritabanı başlatılıyor (postgres:15-alpine, port ${DEMO_PORT})"
    docker_local run -d --name "$DEMO_CONTAINER" \
      -e POSTGRES_PASSWORD=demo -e POSTGRES_DB=jobs_demo \
      -p "${DEMO_PORT}:5432" postgres:15-alpine >/dev/null

    for _ in $(seq 1 30); do
      docker_local exec "$DEMO_CONTAINER" pg_isready -U postgres -d jobs_demo >/dev/null 2>&1 && break
      sleep 1
    done
  fi

  # Only seed an empty database, so re-running ./dev.sh --demo keeps whatever
  # is already there instead of duplicating it.
  DATABASE_URL="$DEMO_URL" PYTHONPATH=. "$VENV/python" - <<'PY'
import os, random
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from MultiwebsiteScraper.models import Base, JobPost, db_connect

engine = db_connect()
Base.metadata.create_all(engine)

with Session(engine) as s:
    if s.scalar(select(func.count()).select_from(JobPost)):
        print("-> demo verisi zaten var, dokunulmadı")
        raise SystemExit

    random.seed(7)
    SITES = ["kariyer.net", "techcareer.net", "indeed"]
    TYPES = ["Internship", "Part-Time", "Full-Time", "Other"]
    CATS = ["it", "general_program", "other", None]
    COMPANIES = ["Trendyol", "Garanti BBVA", "İş Bankası", "Getir", "Yapı Kredi",
                 "Hepsiburada", "Turkcell", "Aselsan", "Peak Games", "Denizbank"]
    TITLES = ["Yazılım Geliştirme Stajyeri", "Backend Intern", "Data Analyst Intern",
              "Frontend Developer (Part-Time)", "IT Support Stajyeri",
              "Career Drive - IT", "Mobil Uygulama Stajyeri", "DevOps Intern",
              "QA Stajyeri", "Genel Staj Programı"]

    now, rows, n = datetime.utcnow(), [], 0
    for day in range(45):
        if day in (3, 4, 11, 19, 28):        # quiet days, so the chart has gaps
            continue
        for _ in range(random.randint(1, 9)):
            n += 1
            cat = random.choice(CATS)
            created = now - timedelta(days=day, hours=random.randint(0, 23))
            # Some of the older ones have closed, so the "Kapananlar" toggle
            # has something to reveal. Weighted by age because that is how it
            # actually goes: a posting from last week is usually still open,
            # one from six weeks ago usually is not.
            closed = (
                now - timedelta(days=random.randint(0, max(day - 1, 0)))
                if day > 7 and random.random() < day / 60
                else None
            )
            # last_seen_at must be OLDER than closed_at on a closed row.
            # Newer means "a crawl saw it after we closed it", which is the
            # signal the checks read to undo a wrong verdict - a demo row
            # asking to be reopened would be a lie about its own state.
            last_seen = closed - timedelta(hours=6) if closed else now - timedelta(days=random.randint(0, 2))
            rows.append(JobPost(
                job_title=random.choice(TITLES), company=random.choice(COMPANIES),
                location=random.choice(["İstanbul", "Ankara", "İzmir", "Remote"]),
                url=f"https://example.test/ilan/{n}", source_site=random.choice(SITES),
                created_at=created,
                is_active=True, job_type=random.choice(TYPES), job_category=cat,
                category_reason=None if cat is None else f"Başlık '{cat}' alanına işaret ediyor.",
                classified_at=None if cat is None else now,
                notified_at=now if random.random() < 0.3 else None,
                closed_at=closed,
                checked_at=now - timedelta(hours=random.randint(0, 30)),
                last_seen_at=last_seen,
            ))
    s.add_all(rows)
    s.commit()
    print(f"-> {len(rows)} örnek ilan yazıldı")
PY
  export DATABASE_URL="$DEMO_URL"
}

[ "$MODE" = demo ] && start_demo_db

########################################
# FRONT END DEPENDENCIES               #
########################################
if [ ! -d web/node_modules ]; then
  echo "-> web/node_modules yok, npm ci çalıştırılıyor"
  (cd web && npm ci)
fi

########################################
# PRODUCTION-SHAPED RUN                #
########################################
if [ "$MODE" = build ]; then
  echo "-> ön yüz derleniyor"
  (cd web && npm run build)
  echo
  echo "   http://localhost:${PROD_PORT}   (üretimdeki gibi: tek süreç, hot reload yok)"
  echo
  exec "$VENV/uvicorn" api.main:app --host 0.0.0.0 --port "$PROD_PORT"
fi

########################################
# DEV: TWO PROCESSES, ONE CTRL-C       #
########################################
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo
  [ "$MODE" = demo ] && echo "   demo veritabanı ayakta bırakıldı. Silmek için:" \
    && echo "   docker -c default rm -f ${DEMO_CONTAINER}"
  exit 0
}
trap cleanup INT TERM EXIT

echo "-> API  :${API_PORT}"
PYTHONPATH=. "$VENV/uvicorn" api.main:app --reload --port "$API_PORT" &
PIDS+=($!)

echo "-> web  :${WEB_PORT}"
(cd web && API_ORIGIN="http://127.0.0.1:${API_PORT}" npm run dev -- --port "$WEB_PORT") &
PIDS+=($!)

sleep 2
echo
echo "   http://localhost:${WEB_PORT}"
[ "$MODE" = demo ] && echo "   (demo veritabanı - ${DEMO_PORT} portunda)"
echo "   Ctrl-C ile durdurun"
echo
wait
