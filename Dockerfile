# TWO SERVICES, ONE IMAGE
# ========================
# Coolify offers no start-command box for a Dockerfile application, so the
# image's CMD decides what a container does - and this repo has two jobs:
# the crawler, which runs on a schedule inside an idle container, and the
# dashboard, which is a long-running server.
#
# Rather than a second Dockerfile that drifts out of step, the build stops at
# a shared `base` and short stages pick the CMD. Coolify's "Docker Build
# Stage Target" field selects one:
#
#     (empty)     -> the last stage, `worker`   - the scraper container
#     dashboard   -> FastAPI + the React build on 8501
#
# The worker stage is LAST on purpose: an empty target builds the final
# stage, so the existing service keeps behaving exactly as it did.
#
# The dashboard is two languages now - a Node stage builds the front end to
# static files, and the Python stage copies those files in and serves them.
# Node is only ever a build tool: nothing in the shipped image runs it.

# Python 3.12 we are using light linux version of python.
FROM python:3.12-slim AS base

# Adjust working file
WORKDIR /app

# Download necessary libraries for our program.
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Download necessary libraries for our program.
# No browser install: every spider now makes plain HTTP requests, so the
# ~500MB Chromium download and its system dependencies are gone.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the files in the project to the container.
COPY . .

# To see the logs live when the program runs.
ENV PYTHONUNBUFFERED=1


# --- web build ------------------------------------------------------------
# The React app compiles to plain files in web/dist. package.json and the
# lockfile are copied first so that `npm ci` is only re-run when the
# dependencies actually change, not on every edit to a component.
#
# `npm ci` rather than `npm install`: it installs exactly what the lockfile
# says and fails if the two disagree, so a deployed build cannot silently
# pick up a different version of a dependency than the one tested here.
FROM node:22-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


# --- dashboard ------------------------------------------------------------
# FastAPI serves the JSON API and the built front end from one process, so
# the browser talks to a single origin and there is no CORS configuration to
# get wrong between here and Coolify.
#
# --host 0.0.0.0 is what makes it reachable from outside the container rather
# than only from inside it. The port stays 8501, the one Streamlit used, so
# nothing in the hosting panel has to be re-pointed.
FROM base AS dashboard
COPY --from=webbuild /web/dist /app/web/dist
EXPOSE 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8501"]

# --- worker (default) -----------------------------------------------------
# The container does nothing on its own: it just stays up so Coolify can run
# scheduled tasks inside it (`python main.py`). Scheduling lives in Coolify,
# not in this image.
#
# 'exec' form + sleep as PID 1 means SIGTERM stops the container immediately
# instead of Docker waiting out the 10s kill timeout on every redeploy.
#
# Kept last so that a build with no target selected is still this one.
FROM base AS worker
CMD ["sleep", "infinity"]