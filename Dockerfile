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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy all the files in the project to the container.
COPY . .

# To see the logs live when the program runs.
ENV PYTHONUNBUFFERED=1

# Default command (docker-compose overrides this per service).
# Without a CMD the container starts an interactive python shell and exits immediately.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]