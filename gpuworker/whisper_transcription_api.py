import os
import tempfile
import json
import httpx
import base64
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import torch
import whisper
from pydantic import BaseModel
import uvicorn
import logging
from typing import Optional, Dict, Any, Literal, List
import io
from pydub import AudioSegment
from enum import Enum
from dotenv import load_dotenv
from whisper import Whisper

# Załaduj zmienne środowiskowe z pliku .env
config_path = os.environ.get("CONFIG_PATH", ".")
env_file = os.path.join(config_path, ".env")
load_dotenv(env_file)

# Konfiguracja loggera
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("whisper-api")

app = FastAPI(
    title="Whisper & Ollama Transcription API",
    description="API do transkrypcji plików audio za pomocą modelu Whisper lub modeli Ollama",
    version="1.0.0"
)

# Dodaj middleware CORS, aby umożliwić żądania z innych domen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # W środowisku produkcyjnym należy ograniczyć do konkretnych domen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Globalne zmienne przechowujące modele
whisper_model : Optional[Whisper] = None
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434")
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))


class ModelType(str, Enum):
    WHISPER = "whisper"
    OLLAMA = "ollama"


class TranscriptionResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None
    model_used: str


class OllamaModelConfig(BaseModel):
    model_name: str
    temperature: Optional[float] = 0.0
    system_prompt: Optional[str] = None
    additional_params: Optional[Dict[str, Any]] = None


def convert_to_wav(file_content: bytes, source_format: str) -> io.BytesIO:
    """Konwertuje plik audio do formatu WAV."""
    audio = AudioSegment.from_file(io.BytesIO(file_content), format=source_format)
    wav_io = io.BytesIO()
    audio.export(wav_io, format="wav")
    wav_io.seek(0)
    return wav_io


@app.on_event("startup")
async def startup_event():
    """Ładuje model Whisper do pamięci przy starcie aplikacji."""
    global whisper_model
    try:
        logger.info("Ładowanie modelu Whisper...")
        # Załaduj model Whisper o rozmiarze zdefiniowanym w zmiennych środowiskowych
        logger.info(f"Ładowanie modelu Whisper o rozmiarze: {WHISPER_MODEL_SIZE}")
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("Model Whisper załadowany pomyślnie!")

        # Sprawdź czy Ollama API jest dostępne
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{OLLAMA_API_URL}/api/health")
                if response.status_code == 200:
                    logger.info("Ollama API jest dostępne")
                else:
                    logger.warning(f"Ollama API nie jest dostępne: {response.status_code}")
        except Exception as e:
            logger.warning(f"Nie można połączyć się z Ollama API: {e}")

    except Exception as e:
        logger.error(f"Błąd podczas ładowania modelu Whisper: {e}")
        raise


@app.post("/transcribe/", response_model=TranscriptionResponse)
async def transcribe_audio(
        file: UploadFile = File(...),
        model_type: ModelType = Query(ModelType.WHISPER, description="Typ modelu do użycia: whisper lub ollama"),
        ollama_model: str = Query(None, description="Nazwa modelu Ollama do użycia (tylko dla model_type=ollama)")
):
    """
    Endpoint do transkrypcji plików audio.
    Obsługuje formaty WAV i MP3.
    Może korzystać z modelu Whisper lub modeli dostępnych przez Ollama.
    """
    if model_type == ModelType.WHISPER and whisper_model is None:
        raise HTTPException(status_code=500, detail="Model Whisper nie został załadowany")

    if model_type == ModelType.OLLAMA and not ollama_model:
        raise HTTPException(status_code=400, detail="Dla model_type=ollama należy podać parametr ollama_model")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku audio")

    # Sprawdzenie formatu pliku
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.wav', '.mp3']:
        raise HTTPException(status_code=400, detail="Obsługiwane są tylko pliki WAV i MP3")

    try:
        # Odczytanie zawartości pliku
        content = await file.read()
        temp_path = None

        # Tworzymy tymczasowy plik
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_path = temp_file.name
            # Jeśli to MP3, konwertujemy do WAV
            if file_ext == '.mp3':
                wav_io = convert_to_wav(content, "mp3")
                temp_file.write(wav_io.read())
            else:
                temp_file.write(content)

        logger.info(f"Przetwarzanie pliku: {file.filename} za pomocą modelu: {model_type}")

        # Wykonanie transkrypcji w zależności od wybranego modelu
        if model_type == ModelType.WHISPER:
            # Użyj modelu Whisper
            result = whisper_model.transcribe(temp_path)

            # FIX: Obsługa różnych wersji Whisper - dostosowanie model.name
            model_name = ""
            try:
                if hasattr(whisper_model, 'model') and hasattr(whisper_model.model, 'name'):
                    model_name = f"whisper-{whisper_model.model.name}"
                else:
                    # Alternatywne podejścia dla różnych wersji Whisper
                    if hasattr(whisper_model, 'name'):
                        model_name = f"whisper-{whisper_model.name}"
                    elif hasattr(whisper_model, 'model_size'):
                        model_name = f"whisper-{whisper_model.model_size}"
                    else:
                        # Fallback jeśli nie można określić nazwy modelu
                        model_name = f"whisper-{WHISPER_MODEL_SIZE}"
            except Exception as e:
                logger.warning(f"Nie można określić nazwy modelu Whisper: {str(e)}")
                model_name = f"whisper-unknown"

            transcription_result = TranscriptionResponse(
                text=result["text"],
                language=result.get("language"),
                duration=result.get("duration"),
                model_used=model_name
            )
        else:  # ModelType.OLLAMA
            # Użyj modelu Ollama
            # Odczytaj audio jako base64
            with open(temp_path, "rb") as audio_file:
                audio_base64 = base64.b64encode(audio_file.read()).decode("utf-8")

            # Przygotuj prompt dla Ollama
            transcription_result = await transcribe_with_ollama(
                audio_base64=audio_base64,
                model_name=ollama_model,
                file_name=file.filename
            )

        # Usunięcie tymczasowego pliku
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

        return transcription_result

    except Exception as e:
        logger.error(f"Błąd podczas transkrypcji: {e}")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail=f"Błąd transkrypcji: {str(e)}")


async def transcribe_with_ollama(audio_base64: str, model_name: str, file_name: str) -> TranscriptionResponse:
    """
    Transkrybuje audio używając modelu Ollama.
    """
    prompt = (
        "Proszę o dokładną transkrypcję nagrania audio. "
        "Zwróć tylko sam tekst transkrypcji bez dodatkowych komentarzy czy oznaczeń. "
        "Mów jak najbliżej temu, co słyszysz w nagraniu."
    )

    try:
        # Przygotowanie danych dla Ollama
        payload = {
            "model": model_name,
            "prompt": prompt,
            "images": [f"data:audio/wav;base64,{audio_base64}"],
            "temperature": 0.0,
            "stream": False
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{OLLAMA_API_URL}/api/generate", json=payload)

            if response.status_code != 200:
                logger.error(f"Błąd odpowiedzi Ollama: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"Ollama API error: {response.text}")

            result = response.json()
            transcription_text = result.get("response", "")

            # Usuń potencjalne niepotrzebne znaczniki czy prefiksy często dodawane przez LLM
            transcription_text = transcription_text.strip()

            return TranscriptionResponse(
                text=transcription_text,
                model_used=f"ollama-{model_name}"
            )

    except httpx.TimeoutException:
        logger.error("Timeout podczas oczekiwania na odpowiedź z Ollama API")
        raise HTTPException(status_code=504, detail="Timeout podczas transkrypcji z Ollama")
    except Exception as e:
        logger.error(f"Błąd podczas komunikacji z Ollama: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Błąd Ollama API: {str(e)}")


@app.post("/transcribe/ollama/", response_model=TranscriptionResponse)
async def transcribe_with_ollama_config(
        file: UploadFile = File(...),
        config: OllamaModelConfig = Body(...)
):
    """
    Endpoint do transkrypcji plików audio używając modelu Ollama z zaawansowaną konfiguracją.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku audio")

    # Sprawdzenie formatu pliku
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.wav', '.mp3']:
        raise HTTPException(status_code=400, detail="Obsługiwane są tylko pliki WAV i MP3")

    try:
        # Odczytanie zawartości pliku
        content = await file.read()
        temp_path = None

        # Tworzymy tymczasowy plik
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_path = temp_file.name
            # Jeśli to MP3, konwertujemy do WAV
            if file_ext == '.mp3':
                wav_io = convert_to_wav(content, "mp3")
                temp_file.write(wav_io.read())
            else:
                temp_file.write(content)

        logger.info(f"Przetwarzanie pliku: {file.filename} za pomocą modelu Ollama: {config.model_name}")

        # Odczytaj audio jako base64
        with open(temp_path, "rb") as audio_file:
            audio_base64 = base64.b64encode(audio_file.read()).decode("utf-8")

        # Przygotowanie danych dla Ollama
        system_prompt = config.system_prompt or (
            "Jesteś ekspertem w transkrypcji audio. "
            "Twoim zadaniem jest dokładne przepisanie mowy z nagrania. "
            "Pisz dokładnie to, co słyszysz, bez dodatkowych interpretacji czy komentarzy."
        )

        payload = {
            "model": config.model_name,
            "system": system_prompt,
            "prompt": "Transkrybuj poniższe nagranie audio:",
            "images": [f"data:audio/wav;base64,{audio_base64}"],
            "temperature": config.temperature or 0.0,
            "stream": False
        }

        # Dodaj dodatkowe parametry, jeśli zostały podane
        if config.additional_params:
            payload.update(config.additional_params)

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{OLLAMA_API_URL}/api/generate", json=payload)

            if response.status_code != 200:
                logger.error(f"Błąd odpowiedzi Ollama: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"Ollama API error: {response.text}")

            result = response.json()
            transcription_text = result.get("response", "")

            # Usuń potencjalne niepotrzebne znaczniki czy prefiksy często dodawane przez LLM
            transcription_text = transcription_text.strip()

            # Usunięcie tymczasowego pliku
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

            return TranscriptionResponse(
                text=transcription_text,
                model_used=f"ollama-{config.model_name}"
            )

    except Exception as e:
        logger.error(f"Błąd podczas transkrypcji z Ollama: {e}")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail=f"Błąd transkrypcji: {str(e)}")


@app.get("/ollama/models/")
async def list_ollama_models():
    """Endpoint do pobierania listy dostępnych modeli Ollama."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/tags")

            if response.status_code != 200:
                logger.error(f"Błąd odpowiedzi Ollama: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"Ollama API error: {response.text}")

            models = response.json().get("models", [])
            return {"models": models}

    except Exception as e:
        logger.error(f"Błąd podczas pobierania listy modeli Ollama: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd komunikacji z Ollama API: {str(e)}")


@app.get("/health/")
async def health_check():
    """Endpoint do sprawdzenia stanu API."""
    status = {"whisper": {"loaded": whisper_model is not None}}

    # Sprawdź status Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/health")
            status["ollama"] = {
                "available": response.status_code == 200,
                "status_code": response.status_code
            }
    except Exception as e:
        status["ollama"] = {"available": False, "error": str(e)}

    if not whisper_model and status.get("ollama", {}).get("available") is not True:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Ani model Whisper, ani API Ollama nie są dostępne",
                "details": status
            }
        )

    return {"status": "ok", "services": status}


if __name__ == "__main__":
    # Uruchomienie serwera
    logger.info(f"Uruchamianie serwera na {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)