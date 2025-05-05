import os
import requests
import json
from enum import Enum
from typing import Optional, Dict, Any, List, Union, BinaryIO


class ModelType(str, Enum):
    """Enum for model types supported by the API"""
    WHISPER = "whisper"
    OLLAMA = "ollama"


class OllamaModelConfig:
    """Class for Ollama model configuration with validation"""

    def __init__(
            self,
            model_name: str,
            temperature: Optional[float] = 0.0,
            system_prompt: Optional[str] = None,
            additional_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Ollama model configuration

        Args:
            model_name: Name of the Ollama model to use
            temperature: Temperature for model generation (0.0 to 1.0)
            system_prompt: System prompt to use for the Ollama model
            additional_params: Additional parameters for the Ollama API

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate model_name
        if not model_name or not isinstance(model_name, str) or model_name.strip() == "":
            raise ValueError("model_name must be a non-empty string")
        self.model_name = model_name

        # Validate temperature
        if temperature is not None:
            if not isinstance(temperature, (int, float)):
                raise ValueError("temperature must be a number")
            if temperature < 0.0 or temperature > 1.0:
                raise ValueError("temperature must be between 0.0 and 1.0")
        self.temperature = temperature

        # Validate system_prompt if provided
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise ValueError("system_prompt must be a string")
        self.system_prompt = system_prompt

        # Validate additional_params if provided
        if additional_params is not None and not isinstance(additional_params, dict):
            raise ValueError("additional_params must be a dictionary")
        self.additional_params = additional_params

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API request"""
        config = {
            "model_name": self.model_name
        }

        if self.temperature is not None:
            config["temperature"] = self.temperature

        if self.system_prompt is not None:
            config["system_prompt"] = self.system_prompt

        if self.additional_params is not None:
            config["additional_params"] = self.additional_params

        return config


class ApiController:
    """
    Static class for interacting with the Whisper & Ollama Transcription API
    with enhanced input validation
    """

    # Default base URL for the API
    _base_url = "http://localhost:8000"

    @classmethod
    def set_base_url(cls, url: str) -> None:
        """
        Set the base URL for the API

        Args:
            url: Base URL for the API

        Raises:
            ValueError: If URL is empty or invalid
        """
        if not url:
            raise ValueError("URL cannot be empty")

        if not isinstance(url, str):
            raise ValueError("URL must be a string")

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        cls._base_url = url.rstrip("/")  # Remove trailing slash if present

    @classmethod
    def transcribe(
            cls,
            file_path: str,
            model_type: Union[ModelType, str] = ModelType.WHISPER,
            ollama_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Whisper or Ollama

        Args:
            file_path: Path to audio file (WAV or MP3)
            model_type: Type of model to use (WHISPER or OLLAMA)
            ollama_model: Name of Ollama model (required if model_type is OLLAMA)

        Returns:
            Dict containing transcription result

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If API request fails
            FileNotFoundError: If file doesn't exist
            TypeError: If parameters have wrong type
        """
        # Validate file_path
        if not file_path:
            raise ValueError("file_path cannot be empty")

        if not isinstance(file_path, str):
            raise TypeError("file_path must be a string")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not os.path.isfile(file_path):
            raise ValueError(f"Not a file: {file_path}")

        # Validate model_type
        if isinstance(model_type, str):
            try:
                model_type = ModelType(model_type.lower())
            except ValueError:
                raise ValueError(f"Invalid model_type: {model_type}. Must be 'whisper' or 'ollama'")
        elif not isinstance(model_type, ModelType):
            raise TypeError("model_type must be a ModelType enum or string")

        # Validate ollama_model if model_type is OLLAMA
        if model_type == ModelType.OLLAMA:
            if not ollama_model:
                raise ValueError("ollama_model is required when model_type is OLLAMA")

            if not isinstance(ollama_model, str) or ollama_model.strip() == "":
                raise ValueError("ollama_model must be a non-empty string")

        # Check file extension
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.wav', '.mp3']:
            raise ValueError(f"Unsupported file format: {file_ext}. Only WAV and MP3 files are supported")

        # Build URL with query parameters
        url = f"{cls._base_url}/transcribe/?model_type={model_type.value}"
        if model_type == ModelType.OLLAMA and ollama_model:
            url += f"&ollama_model={ollama_model}"

        # Prepare files for upload
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'audio/wav' if file_ext == '.wav' else 'audio/mp3')}

            try:
                response = requests.post(url, files=files)
                response.raise_for_status()  # Raise exception for error status codes

                return response.json()
            except requests.RequestException as e:
                cls._handle_request_error(e)

    @classmethod
    def transcribe_file_object(
            cls,
            file_obj: BinaryIO,
            filename: str,
            model_type: Union[ModelType, str] = ModelType.WHISPER,
            ollama_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Whisper or Ollama from a file-like object

        Args:
            file_obj: File-like object containing audio data
            filename: Name of the file (for determining file type)
            model_type: Type of model to use (WHISPER or OLLAMA)
            ollama_model: Name of Ollama model (required if model_type is OLLAMA)

        Returns:
            Dict containing transcription result

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If API request fails
            TypeError: If parameters have wrong type
        """
        # Validate file_obj
        if file_obj is None:
            raise ValueError("file_obj cannot be None")

        if not hasattr(file_obj, 'read') or not callable(getattr(file_obj, 'read')):
            raise TypeError("file_obj must be a file-like object with a 'read' method")

        # Validate filename
        if not filename:
            raise ValueError("filename cannot be empty")

        if not isinstance(filename, str):
            raise TypeError("filename must be a string")

        # Validate model_type
        if isinstance(model_type, str):
            try:
                model_type = ModelType(model_type.lower())
            except ValueError:
                raise ValueError(f"Invalid model_type: {model_type}. Must be 'whisper' or 'ollama'")
        elif not isinstance(model_type, ModelType):
            raise TypeError("model_type must be a ModelType enum or string")

        # Validate ollama_model if model_type is OLLAMA
        if model_type == ModelType.OLLAMA:
            if not ollama_model:
                raise ValueError("ollama_model is required when model_type is OLLAMA")

            if not isinstance(ollama_model, str) or ollama_model.strip() == "":
                raise ValueError("ollama_model must be a non-empty string")

        # Check file extension
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in ['.wav', '.mp3']:
            raise ValueError(f"Unsupported file format: {file_ext}. Only WAV and MP3 files are supported")

        # Build URL with query parameters
        url = f"{cls._base_url}/transcribe/?model_type={model_type.value}"
        if model_type == ModelType.OLLAMA and ollama_model:
            url += f"&ollama_model={ollama_model}"

        # Prepare files for upload
        files = {'file': (filename, file_obj, 'audio/wav' if file_ext == '.wav' else 'audio/mp3')}

        try:
            response = requests.post(url, files=files)
            response.raise_for_status()  # Raise exception for error status codes

            return response.json()
        except requests.RequestException as e:
            cls._handle_request_error(e)

    @classmethod
    def transcribe_with_ollama_config(
            cls,
            file_path: str,
            config: Union[Dict[str, Any], OllamaModelConfig]
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Ollama with advanced configuration

        Args:
            file_path: Path to audio file (WAV or MP3)
            config: Ollama model configuration (dict or OllamaModelConfig)

        Returns:
            Dict containing transcription result

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If API request fails
            FileNotFoundError: If file doesn't exist
            TypeError: If parameters have wrong type
        """
        # Validate file_path
        if not file_path:
            raise ValueError("file_path cannot be empty")

        if not isinstance(file_path, str):
            raise TypeError("file_path must be a string")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not os.path.isfile(file_path):
            raise ValueError(f"Not a file: {file_path}")

        # Validate config
        if config is None:
            raise ValueError("config cannot be None")

        if isinstance(config, OllamaModelConfig):
            config_dict = config.to_dict()
        elif isinstance(config, dict):
            # Validate required keys in config dict
            if 'model_name' not in config or not config['model_name']:
                raise ValueError("model_name is required in config dictionary")

            # Convert to OllamaModelConfig for validation
            try:
                config_obj = OllamaModelConfig(
                    model_name=config['model_name'],
                    temperature=config.get('temperature'),
                    system_prompt=config.get('system_prompt'),
                    additional_params=config.get('additional_params')
                )
                config_dict = config_obj.to_dict()
            except ValueError as e:
                raise ValueError(f"Invalid config dictionary: {str(e)}")
        else:
            raise TypeError("config must be a dictionary or OllamaModelConfig object")

        # Check file extension
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.wav', '.mp3']:
            raise ValueError(f"Unsupported file format: {file_ext}. Only WAV and MP3 files are supported")

        # Prepare files and data for upload
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'audio/wav' if file_ext == '.wav' else 'audio/mp3')}

            try:
                # For this endpoint, we need to send the config in the request body
                response = requests.post(
                    f"{cls._base_url}/transcribe/ollama/",
                    files=files,
                    data={'config': json.dumps(config_dict)}
                )
                response.raise_for_status()

                return response.json()
            except requests.RequestException as e:
                cls._handle_request_error(e)

    @classmethod
    def list_ollama_models(cls) -> List[Dict[str, Any]]:
        """
        Get list of available Ollama models

        Returns:
            List of Ollama model information

        Raises:
            RuntimeError: If API request fails
        """
        try:
            response = requests.get(f"{cls._base_url}/ollama/models/")
            response.raise_for_status()

            data = response.json()

            # Validate response format
            if not isinstance(data, dict) or 'models' not in data:
                raise RuntimeError("Unexpected API response format")

            if not isinstance(data['models'], list):
                raise RuntimeError("API returned models in unexpected format")

            return data['models']
        except requests.RequestException as e:
            cls._handle_request_error(e)

    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        """
        Check health status of the API

        Returns:
            Dict containing health status information

        Raises:
            RuntimeError: If API request fails
        """
        try:
            response = requests.get(f"{cls._base_url}/health/")

            if response.status_code >= 400:
                # For health check, we'll return a custom error response instead of raising
                return {
                    'status': 'error',
                    'message': f"API returned error status: {response.status_code}",
                    'services': {
                        'whisper': {'loaded': False},
                        'ollama': {'available': False, 'error': response.text}
                    }
                }

            data = response.json()

            # Validate response format
            if not isinstance(data, dict) or 'status' not in data:
                return {
                    'status': 'error',
                    'message': "Unexpected API response format",
                    'services': {
                        'whisper': {'loaded': False},
                        'ollama': {'available': False, 'error': "Invalid response format"}
                    }
                }

            return data
        except requests.RequestException as e:
            # For health check, we'll return a custom error response instead of raising
            return {
                'status': 'error',
                'message': f"Failed to connect to API: {str(e)}",
                'services': {
                    'whisper': {'loaded': False},
                    'ollama': {'available': False, 'error': str(e)}
                }
            }

    @staticmethod
    def _handle_request_error(error: requests.RequestException) -> None:
        """
        Handle requests exceptions

        Args:
            error: RequestException from requests library

        Raises:
            RuntimeError with enhanced error message
        """
        if hasattr(error, 'response') and error.response is not None:
            # The request was made and the server responded with a status code
            # that falls out of the range of 2xx
            status_code = error.response.status_code

            try:
                # Try to parse error detail from JSON response
                error_data = error.response.json()
                detail = error_data.get('detail', error.response.reason)
            except (ValueError, json.JSONDecodeError):
                # If response is not JSON, use text or reason
                detail = error.response.text or error.response.reason or 'Unknown error'

            raise RuntimeError(f"API error ({status_code}): {detail}")
        else:
            # The request was made but no response was received or another error occurred
            raise RuntimeError(f"API request failed: {str(error)}")