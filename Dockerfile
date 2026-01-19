# Python 3.12'un hafif Linux sürümünü kullan
FROM python:3.12-slim

# Çalışma klasörünü ayarla
WORKDIR /app

# Gerekli sistem kütüphanelerini yükle (Postgres bağlantısı ve derleme için şart)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python kütüphanelerini kopyala ve kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

# Projedeki tüm dosyaları konteynerin içine kopyala
COPY . .

# Python çıktılarının anlık görünmesi için buffer'ı kapat
ENV PYTHONUNBUFFERED=1