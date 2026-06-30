import os
import tempfile
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

import httpx
import torch  # noqa: F401  (ensures CUDA libs load before whisper)
import whisper
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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

# Globalne zmienne / konfiguracja
whisper_model: Optional[Whisper] = None
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "https://ollama.jakubkrawczyk.com").rstrip("/")
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
# Lista dozwolonych originów dla CORS (oddzielona przecinkami). Domyślnie "*".
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]


async def ollama_is_available() -> Dict[str, Any]:
    """Sprawdza dostępność Ollamy. Ollama nie ma /api/health - używamy /api/tags."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/tags")
            return {
                "available": response.status_code == 200,
                "status_code": response.status_code,
            }
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Ładuje model Whisper przy starcie aplikacji (zamiast on_event)."""
    global whisper_model
    try:
        logger.info(f"Ładowanie modelu Whisper o rozmiarze: {WHISPER_MODEL_SIZE}")
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("Model Whisper załadowany pomyślnie!")
    except Exception as e:
        logger.error(f"Błąd podczas ładowania modelu Whisper: {e}")
        raise

    ollama_status = await ollama_is_available()
    if ollama_status.get("available"):
        logger.info("Ollama API jest dostępne")
    else:
        logger.warning(f"Ollama API nie jest dostępne: {ollama_status}")

    yield
    # (brak specjalnego sprzątania przy zamknięciu)


app = FastAPI(
    title="Whisper & Ollama Transcription API",
    description="API do transkrypcji audio (Whisper) i podsumowań tekstu (Ollama)",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscriptionResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None
    model_used: str


class SummarizeRequest(BaseModel):
    text: str
    model_name: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = 0.0
    context: Optional[str] = None
    additional_params: Optional[Dict[str, Any]] = None


class SummarizeResponse(BaseModel):
    text: str
    model_used: str


@app.post("/transcribe/", response_model=TranscriptionResponse)
async def transcribe_audio(
        file: UploadFile = File(...),
        model_type: str = Query("whisper", description="Tylko 'whisper' jest obsługiwane dla transkrypcji"),
):
    """
    Transkrypcja pliku audio (WAV lub MP3) modelem Whisper.

    Uwaga: Ollama nie potrafi transkrybować audio, więc niezależnie od
    parametru transkrypcję zawsze wykonuje Whisper.
    """
    if model_type.lower() == "ollama":
        raise HTTPException(
            status_code=400,
            detail="Ollama nie obsługuje transkrypcji audio. Użyj model_type=whisper.",
        )

    if whisper_model is None:
        raise HTTPException(status_code=503, detail="Model Whisper nie został załadowany")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku audio")

    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.wav', '.mp3']:
        raise HTTPException(status_code=400, detail="Obsługiwane są tylko pliki WAV i MP3")

    temp_path = None
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_path = temp_file.name
            temp_file.write(content)

        logger.info(f"Transkrypcja pliku: {file.filename} (Whisper {WHISPER_MODEL_SIZE})")
        result = whisper_model.transcribe(temp_path)

        return TranscriptionResponse(
            text=result.get("text", "").strip(),
            language=result.get("language"),
            duration=result.get("duration"),
            model_used=f"whisper-{WHISPER_MODEL_SIZE}",
        )
    except Exception as e:
        logger.error(f"Błąd podczas transkrypcji: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd transkrypcji: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@app.post("/summarize/", response_model=SummarizeResponse)
async def summarize_text(request: SummarizeRequest = Body(...)):
    """
    Podsumowanie / przetworzenie tekstu modelem Ollama (czysto tekstowo).
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Pole 'text' nie może być puste")

    system_prompt = request.system_prompt or (
        "Jesteś ekspertem w podsumowywaniu rozmów. Tworzysz zwięzłe, "
        "ale kompletne podsumowania transkrypcji w języku polskim."
    )

    user_prompt = ""
    if request.context:
        user_prompt += f"Kontekst rozmowy: {request.context}\n\n"
    user_prompt += (
        "Poniżej znajduje się transkrypcja rozmowy. Przygotuj zwięzłe "
        f"podsumowanie:\n\n{request.text}\n\nPodsumowanie:"
    )

    payload: Dict[str, Any] = {
        "model": request.model_name,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "options": {"temperature": request.temperature or 0.0},
    }
    if request.additional_params:
        payload["options"].update(request.additional_params)

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(f"{OLLAMA_API_URL}/api/generate", json=payload)
            if response.status_code != 200:
                logger.error(f"Błąd odpowiedzi Ollama: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}",
                )
            result_text = response.json().get("response", "").strip()
            return SummarizeResponse(text=result_text, model_used=f"ollama-{request.model_name}")
    except httpx.TimeoutException:
        logger.error("Timeout podczas oczekiwania na odpowiedź z Ollama API")
        raise HTTPException(status_code=504, detail="Timeout podczas podsumowania z Ollama")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Błąd podczas komunikacji z Ollama: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd Ollama API: {str(e)}")


@app.get("/ollama/models/")
async def list_ollama_models():
    """Lista dostępnych modeli Ollama."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{OLLAMA_API_URL}/api/tags")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}",
                )
            return {"models": response.json().get("models", [])}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Błąd podczas pobierania listy modeli Ollama: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd komunikacji z Ollama API: {str(e)}")


@app.get("/health/")
async def health_check():
    """Stan API (Whisper + Ollama)."""
    status = {
        "whisper": {"loaded": whisper_model is not None},
        "ollama": await ollama_is_available(),
    }

    if not status["whisper"]["loaded"] and not status["ollama"].get("available"):
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Ani model Whisper, ani API Ollama nie są dostępne",
                "services": status,
            },
        )

    return {"status": "ok", "services": status}


if __name__ == "__main__":
    logger.info(f"Uruchamianie serwera na {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
