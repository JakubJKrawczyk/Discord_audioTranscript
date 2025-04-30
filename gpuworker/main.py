import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import torch
import whisper
from pydantic import BaseModel
import uvicorn
import logging
from typing import Optional
import io
from pydub import AudioSegment

# Konfiguracja loggera
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("whisper-api")

app = FastAPI(title="Whisper Transcription API")

# Globalna zmienna przechowująca model
whisper_model = None


class TranscriptionResponse(BaseModel):
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None


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
        # Możesz zmienić rozmiar modelu: tiny, base, small, medium, large
        whisper_model = whisper.load_model("base")
        logger.info("Model Whisper załadowany pomyślnie!")
    except Exception as e:
        logger.error(f"Błąd podczas ładowania modelu Whisper: {e}")
        raise


@app.post("/transcribe/", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Endpointdo transkrypcji plików audio.
    Obsługuje formaty WAV i MP3.
    """
    global whisper_model

    if whisper_model is None:
        raise HTTPException(status_code=500, detail="Model nie został załadowany")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak pliku audio")

    # Sprawdzenie formatu pliku
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ['.wav', '.mp3']:
        raise HTTPException(status_code=400, detail="Obsługiwane są tylko pliki WAV i MP3")

    try:
        # Odczytanie zawartości pliku
        content = await file.read()

        # Tworzymy tymczasowy plik
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_path = temp_file.name
            # Jeśli to MP3, konwertujemy do WAV
            if file_ext == '.mp3':
                wav_io = convert_to_wav(content, "mp3")
                temp_file.write(wav_io.read())
            else:
                temp_file.write(content)

        logger.info(f"Przetwarzanie pliku: {file.filename}")

        # Wykonanie transkrypcji
        result = whisper_model.transcribe(temp_path)

        # Usunięcie tymczasowego pliku
        os.unlink(temp_path)

        return TranscriptionResponse(
            text=result["text"],
            language=result.get("language"),
            duration=result.get("duration")
        )

    except Exception as e:
        logger.error(f"Błąd podczas transkrypcji: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail=f"Błąd transkrypcji: {str(e)}")


@app.get("/health/")
async def health_check():
    """Endpoint do sprawdzenia stanu API."""
    if whisper_model is None:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Model nie jest załadowany"}
        )
    return {"status": "ok", "model_loaded": True}


if __name__ == "__main__":
    # Uruchomienie serwera
    uvicorn.run(app, host="0.0.0.0", port=8000)