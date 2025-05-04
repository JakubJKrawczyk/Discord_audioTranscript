# API Transkrypcji Audio (Whisper + Ollama)

Aplikacja API do transkrypcji plików audio z wykorzystaniem modelu OpenAI Whisper oraz modeli multimodalnych dostępnych przez Ollama.

## Funkcjonalności

- Transkrypcja plików audio w formatach WAV i MP3
- Obsługa dwóch silników transkrypcji:
  - OpenAI Whisper (lokalnie)
  - Modele multimodalne z Ollama (np. LLaVA)
- Automatyczna konwersja formatów audio
- RESTful API z dokumentacją Swagger
- Obsługa CORS dla integracji z aplikacjami frontendowymi
- Konteneryzacja z Docker i docker-compose

## Wymagania

- Docker
- docker-compose
- ~10GB wolnego miejsca na dysku (zależnie od używanych modeli)

## Instalacja i uruchomienie

### Automatyczna instalacja

```bash
# Pobierz repozytorium
git clone https://github.com/twojarepo/whisper-ollama-api
cd whisper-ollama-api

# Nadaj uprawnienia do wykonania skryptu inicjalizacyjnego
chmod +x init.sh

# Uruchom skrypt inicjalizacyjny
./init.sh
```

### Ręczna instalacja

1. Utwórz katalogi konfiguracyjne:
   ```bash
   mkdir -p config uploads
   ```

2. Skopiuj przykładowy plik konfiguracyjny:
   ```bash
   cp .env.example config/.env
   ```

3. Uruchom kontenery:
   ```bash
   docker-compose up -d
   ```

4. Pobierz model multimodalny dla Ollama:
   ```bash
   docker exec ollama ollama pull llava
   ```

## Konfiguracja

Edytuj plik `config/.env` aby dostosować ustawienia aplikacji:

- `WHISPER_MODEL` - rozmiar modelu Whisper (tiny, base, small, medium, large)
- `OLLAMA_API_URL` - adres URL do serwera Ollama
- `HOST` i `PORT` - ustawienia serwera API

## Użycie API

Interfejs Swagger API dostępny jest pod adresem: http://localhost:8000/docs

### Podstawowe endpointy

1. **Transkrypcja z modelem Whisper:**
   ```
   POST /transcribe/?model_type=whisper
   ```

2. **Transkrypcja z modelem Ollama:**
   ```
   POST /transcribe/?model_type=ollama&ollama_model=llava
   ```

3. **Zaawansowana transkrypcja z modelem Ollama:**
   ```
   POST /transcribe/ollama/
   ```
   Z body w formacie JSON:
   ```json
   {
     "model_name": "llava",
     "temperature": 0.1,
     "system_prompt": "Transkrybuj dokładnie poniższe nagranie audio."
   }
   ```

4. **Lista dostępnych modeli Ollama:**
   ```
   GET /ollama/models/
   ```

5. **Stan API:**
   ```
   GET /health/
   ```

## Struktura projektu

```
whisper-ollama-api/
├── config/              # Pliki konfiguracyjne
│   └── .env             # Zmienne środowiskowe
├── models/              # Pliki modeli (zarządzane przez Docker)
│   ├── torch/           # Cache PyTorch
│   └── whisper/         # Modele Whisper
├── uploads/             # Katalog na przesyłane pliki
├── Dockerfile           # Definicja obrazu Docker
├── docker-compose.yml   # Konfiguracja docker-compose
├── requirements.txt     # Zależności Pythona
├── whisper_transcription_api.py  # Główny plik aplikacji
└── init.sh              # Skrypt inicjalizacyjny
```

## Wolumeny Docker

Aplikacja korzysta z następujących wolumenów:

- `whisper-models` - przechowuje pobrane modele Whisper i PyTorch
- `ollama-models` - przechowuje modele Ollama
- `./config` - katalog konfiguracyjny
- `./uploads` - katalog na przesyłane pliki audio

## Debugowanie

Aby zobaczyć logi aplikacji:

```bash
docker logs whisper-ollama-api
```

Aby zobaczyć logi Ollama:

```bash
docker logs ollama
```

## Modele Whisper

Dostępne rozmiary modeli Whisper:

| Model  | Pamięć | Czas transkrypcji | Jakość |
|--------|--------|-------------------|--------|
| tiny   | ~1GB   | ~2x szybciej      | Niska  |
| base   | ~1GB   | ~1x (bazowy)      | Średnia|
| small  | ~2GB   | ~2x wolniej       | Dobra  |
| medium | ~5GB   | ~4x wolniej       | Lepsza |
| large  | ~10GB  | ~6x wolniej       | Najlepsza |

## Licencja

MIT