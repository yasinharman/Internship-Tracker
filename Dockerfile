# TWO SERVICES, ONE IMAGE
# ========================
# Coolify offers no start-command box for a Dockerfile application, so the
# image's CMD decides what a container does - and this repo has two jobs:
# the crawler, which runs on a schedule inside an idle container, and the
# Streamlit dashboard, which is a long-running server.
#
# Rather than a second Dockerfile that drifts out of step, the build stops at
# a shared `base` and two one-line stages pick the CMD. Coolify's "Docker
# Build Stage Target" field selects one:
#
#     (empty)     -> the last stage, `worker`   - the scraper container
#     dashboard   -> Streamlit on 8501
#
# The worker stage is LAST on purpose: an empty target builds the final
# stage, so the existing service keeps behaving exactly as it did.

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


# --- dashboard ------------------------------------------------------------
# Streamlit reads the database and serves the board. --server.headless keeps
# it from printing the first-run e-mail prompt and waiting on stdin, and
# --server.address 0.0.0.0 is what makes it reachable from outside the
# container rather than only from inside it.
FROM base AS dashboard
EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.port", "8501", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true"]

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