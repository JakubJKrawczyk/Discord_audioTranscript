#!/bin/bash
set -e

# Tworzenie katalogów dla konfiguracji i wgrywanych plików
mkdir -p config uploads

# Kopiowanie przykładowego pliku .env, jeśli nie istnieje
if [ ! -f config/.env ]; then
  cp .env.example config/.env
  echo "Skopiowano przykładowy plik konfiguracyjny do ./config/.env"
fi

# Uruchomienie kontenerów
echo "Uruchamianie kontenerów z API transkrypcji Whisper i Ollama..."
docker-compose up -d

# Wczytanie modelu multimodalnego dla Ollama
echo "Wczytywanie modelu multimodalnego dla Ollama (może potrwać chwilę)..."
docker exec ollama ollama pull llava

echo "Inicjalizacja zakończona pomyślnie!"
echo "API dostępne pod adresem: http://localhost:8000"
echo "Dokumentacja API: http://localhost:8000/docs"