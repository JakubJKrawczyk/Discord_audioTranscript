FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# libopus jest wymagany do dekodowania głosu odbieranego z Discorda.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopus0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Najpierw zależności (lepsze cache warstw)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Reszta kodu
COPY . .

# Katalog na nagrania
RUN mkdir -p /app/recordings

# Token i konfiguracja pochodzą ze zmiennych środowiskowych (DISCORD_TOKEN, API_URL itd.)
CMD ["python", "main.py"]
