# Obraz pod GPU NVIDIA (Whisper liczy na karcie).
# Wymaga na hoście: sterownik NVIDIA + nvidia-container-toolkit.
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Cache modeli na trwałym wolumenie /models:
    #  - Whisper używa XDG_CACHE_HOME (-> /models/cache/whisper)
    #  - PyTorch używa TORCH_HOME
    TORCH_HOME=/models/torch \
    XDG_CACHE_HOME=/models/cache \
    PYTHONPATH=/app \
    CONFIG_PATH=/config

# Python + ffmpeg (Whisper dekoduje audio przez ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Użytkownik bez roota + katalogi (z prawidłowym właścicielem dla wolumenów)
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app /config /models/torch /models/cache \
    && chown -R appuser:appuser /app /config /models

WORKDIR /app

# Torch w wersji CUDA (cu121) - instalowany osobno z indeksu PyTorch.
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121

# Pozostałe zależności (torch jest już zainstalowany powyżej)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Kod aplikacji
COPY *.py .

USER appuser

EXPOSE 8000

# /models i /config dostarcza docker-compose (wolumeny)
VOLUME ["/models", "/config"]

CMD ["python3", "whisper_transcription_api.py"]
