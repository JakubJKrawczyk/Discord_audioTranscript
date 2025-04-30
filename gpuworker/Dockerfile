FROM python:3.10-slim

# Ustaw zmienne środowiskowe
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    # Ustaw folder cache dla PyTorch i Whisper
    TORCH_HOME=/models/torch \
    WHISPER_MODELS_DIR=/models/whisper

# Zainstaluj niezbędne pakiety systemowe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libsndfile1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Utwórz użytkownika bez uprawnień roota
RUN useradd -m -u 1000 appuser

# Utwórz katalogi aplikacji i ustaw uprawnienia
RUN mkdir -p /app /config /models/torch /models/whisper /uploads \
    && chown -R appuser:appuser /app /config /models /uploads

# Ustaw katalog roboczy
WORKDIR /app

# Skopiuj pliki requirements
COPY requirements.txt .

# Zainstaluj zależności Pythona
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Skopiuj kod aplikacji
COPY *.py .

# Przełącz na użytkownika bez uprawnień roota
USER appuser

# Ustaw zmienną środowiskową do wczytywania plików konfiguracyjnych
ENV PYTHONPATH=/app \
    CONFIG_PATH=/config

# Eksponuj port aplikacji
EXPOSE 8000

# Ustaw punkty montowania wolumenów
VOLUME ["/models", "/config", "/uploads"]

# Uruchom aplikację
CMD ["python", "whisper_transcription_api.py"]