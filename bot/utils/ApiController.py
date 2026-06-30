import os
import requests
import json
from enum import Enum
from typing import Optional, Dict, Any, List, Union


class ModelType(str, Enum):
    """Enum for model types supported by the API"""
    WHISPER = "whisper"
    OLLAMA = "ollama"


class ApiController:
    """
    Static client for the Whisper & Ollama transcription/summarization API
    (the gpuworker service). All network calls are synchronous (built on
    ``requests``); call them from async code via ``asyncio.to_thread``.
    """

    # Default base URL for the API
    _base_url = "http://localhost:8000"

    # Default timeouts (seconds) - transcription/summarization can be slow.
    _timeout = 600

    @classmethod
    def set_base_url(cls, url: str) -> None:
        """Set the base URL for the API."""
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string")

        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        cls._base_url = url.rstrip("/")

    @classmethod
    def transcribe(
            cls,
            file_path: str,
            model_type: Union[ModelType, str] = ModelType.WHISPER,
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Whisper.

        Args:
            file_path: Path to audio file (WAV or MP3)
            model_type: Kept for backwards compatibility; only WHISPER is
                supported for transcription (Ollama cannot transcribe audio).

        Returns:
            Dict containing the transcription result (``text`` key).
        """
        if not file_path or not isinstance(file_path, str):
            raise ValueError("file_path must be a non-empty string")

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Normalise model_type but force Whisper for transcription.
        if isinstance(model_type, str):
            try:
                model_type = ModelType(model_type.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid model_type: {model_type}. Must be 'whisper' or 'ollama'"
                )

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.wav', '.mp3']:
            raise ValueError(
                f"Unsupported file format: {file_ext}. Only WAV and MP3 are supported"
            )

        mime = 'audio/wav' if file_ext == '.wav' else 'audio/mpeg'
        url = f"{cls._base_url}/transcribe/?model_type={ModelType.WHISPER.value}"

        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, mime)}
            try:
                response = requests.post(url, files=files, timeout=cls._timeout)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                cls._handle_request_error(e)

    @classmethod
    def summarize(
            cls,
            text: str,
            model_name: str,
            system_prompt: Optional[str] = None,
            temperature: float = 0.0,
            context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Summarize (or otherwise process) text with an Ollama model via the
        API's text endpoint. This is a pure text-in/text-out call - no audio.

        Returns:
            Dict containing the result (``text`` key).
        """
        if not text or not isinstance(text, str):
            raise ValueError("text must be a non-empty string")
        if not model_name or not isinstance(model_name, str):
            raise ValueError("model_name must be a non-empty string")

        payload: Dict[str, Any] = {
            "text": text,
            "model_name": model_name,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if context:
            payload["context"] = context

        try:
            response = requests.post(
                f"{cls._base_url}/summarize/", json=payload, timeout=cls._timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            cls._handle_request_error(e)

    @classmethod
    def list_ollama_models(cls) -> List[Dict[str, Any]]:
        """Get the list of available Ollama models."""
        try:
            response = requests.get(f"{cls._base_url}/ollama/models/", timeout=30)
            response.raise_for_status()

            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('models'), list):
                raise RuntimeError("Unexpected API response format")

            return data['models']
        except requests.RequestException as e:
            cls._handle_request_error(e)

    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        """Check the health status of the API (never raises)."""
        error_shape = {
            'whisper': {'loaded': False},
            'ollama': {'available': False},
        }
        try:
            response = requests.get(f"{cls._base_url}/health/", timeout=10)

            if response.status_code >= 400:
                return {
                    'status': 'error',
                    'message': f"API returned error status: {response.status_code}",
                    'services': {**error_shape,
                                 'ollama': {'available': False, 'error': response.text}},
                }

            data = response.json()
            if not isinstance(data, dict) or 'status' not in data:
                return {
                    'status': 'error',
                    'message': "Unexpected API response format",
                    'services': error_shape,
                }
            return data
        except requests.RequestException as e:
            return {
                'status': 'error',
                'message': f"Failed to connect to API: {str(e)}",
                'services': {**error_shape,
                             'ollama': {'available': False, 'error': str(e)}},
            }

    @staticmethod
    def _handle_request_error(error: requests.RequestException) -> None:
        """Translate a requests exception into a RuntimeError with detail."""
        if getattr(error, 'response', None) is not None:
            status_code = error.response.status_code
            try:
                detail = error.response.json().get('detail', error.response.reason)
            except (ValueError, json.JSONDecodeError):
                detail = error.response.text or error.response.reason or 'Unknown error'
            raise RuntimeError(f"API error ({status_code}): {detail}")
        raise RuntimeError(f"API request failed: {str(error)}")
