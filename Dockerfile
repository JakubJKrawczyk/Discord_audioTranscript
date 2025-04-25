FROM python:3.9-slim
LABEL authors="Jakub"

WORKDIR /app

# Zainstaluj niezbędne zależności systemowe
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    libasound2-dev \
    portaudio19-dev \
    python3-dev \
    ffmpeg \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Zainstaluj Ollama (tylko dla Linuxa amd64)
RUN curl -fsSL https://ollama.com/install.sh | sh

# Skopiuj pliki projektu
COPY script.py .
COPY requirements.txt .

# Zainstaluj dodatkowe zależności których brakuje w wymaganiach
RUN pip install --no-cache-dir numpy==1.24.3 librosa==0.10.1

# Zainstaluj zależności z pliku requirements
RUN pip install --no-cache-dir -r requirements.txt

# Utwórz katalog na nagrania
RUN mkdir -p /app/recordings

# Dodaj skrypt startowy
COPY start.sh .
RUN chmod +x start.sh

# Ustawienie zmiennej środowiskowej (zastąp swoim tokenem lub przekaż podczas uruchomienia)
ENV DISCORD_TOKEN="key"

# Uruchom skrypt startowy
ENTRYPOINT ["./start.sh"]