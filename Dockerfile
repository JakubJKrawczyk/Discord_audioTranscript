FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Ustawienie zmiennych środowiskowych
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalacja podstawowych pakietów i zależności dla PyAudio
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    python3-numpy \
    portaudio19-dev \
    libportaudio2 \
    libasound2-dev \
    libsndfile1 \
    ffmpeg \
    wget \
    git \
    curl \
    gcc \
    build-essential \
    pkg-config \
    pulseaudio \
    alsa-utils \
    libasound2-plugins \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/alsa
COPY alsa.conf /etc/alsa/alsa.conf

# Instalacja Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Tworzenie katalogu aplikacji
WORKDIR /app

# Kopiowanie plików projektu
COPY . .

# Upewnij się, że numpy jest zainstalowany przed PyTorch
RUN pip3 install --no-cache-dir numpy==1.24.3

# Instalacja PyTorch z obsługą CUDA
RUN pip3 install --no-cache-dir torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu118

# Instalacja pozostałych zależności Pythona
RUN pip3 install --no-cache-dir discord.py
RUN pip3 install --no-cache-dir PyAudio
RUN pip3 install --no-cache-dir librosa soundfile
RUN pip3 install --no-cache-dir openai-whisper
RUN pip3 install --no-cache-dir requests python-dotenv keyboard tqdm

# Potwierdź instalację numpy
RUN python3 -c "import numpy; print(f'NumPy version: {numpy.__version__}')"

# Tworzenie katalogu na nagrania
RUN mkdir -p /app/recordings && chmod 777 /app/recordings

# Uruchomienie serwera Ollama w tle i bota
CMD ["sh", "-c", "ollama serve & sleep 5 && python3 main.py"]