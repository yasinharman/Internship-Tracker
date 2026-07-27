# Python 3.12 we are using light linux version of python.
FROM python:3.12-slim

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

# The container does nothing on its own: it just stays up so Coolify can run
# scheduled tasks inside it (`python main.py`). Scheduling lives in Coolify,
# not in this image.
#
# 'exec' form + sleep as PID 1 means SIGTERM stops the container immediately
# instead of Docker waiting out the 10s kill timeout on every redeploy.
CMD ["sleep", "infinity"]