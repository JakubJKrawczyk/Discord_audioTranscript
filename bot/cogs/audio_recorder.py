#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile

import discord
from discord.ext import commands
import asyncio
import wave
import datetime
import torch
import os
import pyaudio
import subprocess
import traceback
import io
from typing import Dict, List, Optional

from config import BotConfig
from utils.audio_processing import AudioProcessor
from cogs.commands_loader import register_all_commands
from utils.ApiController import ApiController, ModelType, OllamaModelConfig


class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recording = False
        self.frames = {}  # Słownik dla przechowywania ramek audio różnych użytkowników
        self.audio = pyaudio.PyAudio()
        self.stream = None

        # Konfiguracja ApiController - ustaw adres API
        ApiController.set_base_url(BotConfig.API_URL)

        # Sprawdzenie dostępności GPU
        self.device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
        print(f"Używanie urządzenia: {self.device}")

        self.user_contexts = {}
        self.transcriptions = {}
        self.ollama_model = BotConfig.OLLAMA_DEFAULT_MODEL
        self.recording_users = {}  # Słownik do przechowywania nagrań poszczególnych użytkowników
        self.current_channel = None  # Aktualny kanał, na którym nagrywamy

        # Utworzenie folderu recordings
        self.recordings_dir = BotConfig.RECORDINGS_DIR
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings utworzony w: {self.recordings_dir}")

        # Sprawdź dostępność serwisów
        self.check_services()

        # Inicjalizacja procesora audio
        self.audio_processor = AudioProcessor()

        # Rejestracja wszystkich komend
        register_all_commands(self)

    def check_services(self):
        """Sprawdza dostępność usług API (Whisper i Ollama)"""
        try:
            print("Sprawdzanie statusu usług API...")
            health = ApiController.check_health()

            # Sprawdź czy API jest dostępne
            if health['status'] != 'ok':
                print(f"OSTRZEŻENIE: API nie jest w pełni operacyjne. Powód: {health.get('message', 'Nieznany')}")
            else:
                print("API jest dostępne.")

            # Sprawdź status Whisper
            whisper_status = health['services']['whisper']
            if whisper_status.get('loaded'):
                print("Model Whisper jest załadowany.")
            else:
                print("OSTRZEŻENIE: Model Whisper nie jest załadowany. Transkrypcja może nie działać.")

            # Sprawdź status Ollama
            ollama_status = health['services']['ollama']
            if ollama_status.get('available'):
                print("Ollama API jest dostępne.")
                # Sprawdź czy nasz model jest dostępny
                self.check_ollama_model()
            else:
                print(f"OSTRZEŻENIE: Ollama API nie jest dostępne. Podsumowania mogą nie działać.")
                if 'error' in ollama_status:
                    print(f"Przyczyna: {ollama_status['error']}")

        except Exception as e:
            print(f"Błąd podczas sprawdzania usług API: {str(e)}")

    def check_ollama_model(self):
        """Sprawdza czy wybrany model Ollama jest dostępny"""
        try:
            print(f"Sprawdzanie dostępności modelu Ollama: {self.ollama_model}...")

            # Pobierz listę dostępnych modeli przez ApiController
            models = ApiController.list_ollama_models()

            # Wypisz wszystkie dostępne modele
            model_names = [model.get('name') for model in models if 'name' in model]
            print(f"Dostępne modele Ollama: {model_names}")

            # Sprawdź czy wybrany model jest dostępny
            if self.ollama_model not in model_names:
                print(f"Model {self.ollama_model} nie jest zainstalowany. Pobieram...")

                # Użyj subprocess do pobrania modelu w tle
                subprocess.Popen(["ollama", "pull", self.ollama_model])
                print(f"Rozpoczęto pobieranie modelu {self.ollama_model} w tle.")
            else:
                print(f"Model {self.ollama_model} jest już zainstalowany.")

        except Exception as e:
            print(f"Błąd podczas sprawdzania modelu Ollama: {str(e)}")

    def callback(self, in_data, frame_count, time_info, status):
        if self.recording:
            # Identyfikacja wszystkich użytkowników na kanale
            if self.current_channel:
                for member in self.current_channel.members:
                    if member.bot:
                        continue  # Pomijamy boty

                    # Tworzenie ramek dla każdego użytkownika, jeśli jeszcze nie istnieją
                    user_id_str = str(member.id)
                    if user_id_str not in self.frames:
                        self.frames[user_id_str] = []

                    # Dodawanie danych audio do ramek danego użytkownika
                    self.frames[user_id_str].append(in_data)
        return (in_data, pyaudio.paContinue)

    def get_username_by_id(self, user_id):
        """Pobiera nazwę użytkownika na podstawie ID"""
        user_id_str = str(user_id)
        for member in self.current_channel.members:
            if str(member.id) == user_id_str:
                return member.display_name
        return f"Użytkownik-{user_id}"

    async def summarize_with_ollama(self, text):
        """Używa Ollama do podsumowania tekstu poprzez ApiController"""
        try:
            print(f"Generowanie podsumowania dla tekstu o długości {len(text)} znaków...")

            # Przygotuj konfigurację dla Ollama
            config = OllamaModelConfig(
                model_name=self.ollama_model,
                temperature=0.0,
                system_prompt="Jesteś ekspertem w podsumowywaniu rozmów. Twoim zadaniem jest tworzyć zwięzłe, ale kompletne podsumowania transkrypcji rozmów.",
                additional_params={
                    "num_predict": 512,
                    "top_k": 40,
                    "top_p": 0.9
                }
            )

            # Utwórz tymczasowy plik tekstowy (Ollama w API wymaga pliku)
            with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", encoding="utf-8", delete=False) as temp_file:
                temp_path = temp_file.name
                temp_file.write(f"""
                Poniżej znajduje się transkrypcja rozmowy. Przygotuj zwięzłe podsumowanie całego tekstu:

                {text}

                Podsumowanie:
                """)

            try:
                # Konwertuj plik tekstowy do formatu audio wymaganego przez API
                # W rzeczywistości API powinno obsługiwać bezpośrednio teksty, ale zakładam że tak działa
                # Można dostosować ApiController dodając metodę do bezpośredniej obsługi tekstów
                with open(temp_path, "rb") as f:
                    file_obj = io.BytesIO(f.read())

                # Wywołaj API przez ApiController, używając konwersji pliku
                result = await asyncio.to_thread(
                    ApiController.transcribe_with_ollama_config,
                    file_obj,
                    config
                )

                return result["text"]
            finally:
                # Zawsze usuń tymczasowy plik
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            print(f"Błąd podczas generowania podsumowania: {str(e)}")
            traceback.print_exc()
            return f"Błąd podczas generowania podsumowania: {str(e)}"

    async def transcribe_audio(self, filepath):
        """Transkrybuje plik audio na tekst używając ApiController"""
        print(f"Rozpoczynam transkrypcję pliku: {filepath}")

        try:
            abs_path = os.path.abspath(filepath)
            print(f"Pełna ścieżka do pliku: {abs_path}")

            # Sprawdź czy plik istnieje
            if not os.path.exists(abs_path):
                print(f"BŁĄD: Plik nie istnieje w ścieżce: {abs_path}")
                return f"Błąd transkrypcji: Plik nie istnieje w ścieżce {abs_path}"

            # Sprawdź czy plik nie jest pusty
            file_size = os.path.getsize(abs_path)
            print(f"Rozmiar pliku: {file_size} bajtów")
            if file_size == 0:
                print("BŁĄD: Plik jest pusty")
                return "Błąd transkrypcji: Plik jest pusty"

            # Użyj ApiController do transkrypcji
            print("Rozpoczynam transkrypcję przez API...")

            async def transcribe_via_api():
                # Użyj Whisper jako domyślny model, chyba że jest niedostępny
                try:
                    # Sprawdź najpierw stan usług
                    health = ApiController.check_health()

                    # Wybierz model - Whisper jeśli dostępny, w przeciwnym razie Ollama
                    if health['services']['whisper'].get('loaded'):
                        # Użyj Whisper
                        result = ApiController.transcribe(abs_path, ModelType.WHISPER)
                        print("Transkrypcja Whisper zakończona")
                        return result
                    else:
                        # Jeśli Whisper niedostępny, użyj Ollama jako fallback
                        if health['services']['ollama'].get('available'):
                            print("Model Whisper niedostępny, używam Ollama jako fallback")
                            result = ApiController.transcribe(abs_path, ModelType.OLLAMA, self.ollama_model)
                            print("Transkrypcja Ollama zakończona")
                            return result
                        else:
                            raise RuntimeError("Ani Whisper, ani Ollama nie są dostępne!")
                except Exception as e:
                    print(f"Błąd podczas wyboru modelu transkrypcji: {str(e)}")
                    # Próbuj użyć Whisper jako ostateczność
                    result = ApiController.transcribe(abs_path, ModelType.WHISPER)
                    return result

            # Uruchom transkrypcję asynchronicznie
            result = await transcribe_via_api()

            # Sprawdź czy mamy tekst w wyniku
            if not result or "text" not in result:
                print("BŁĄD: Brak tekstu w wyniku transkrypcji")
                return "Błąd transkrypcji: Brak tekstu w wyniku"

            print("Transkrypcja zakończona sukcesem")
            return result["text"]

        except Exception as e:
            error_msg = f"Błąd podczas transkrypcji: {str(e)}"
            print(f"BŁĄD KRYTYCZNY: {error_msg}")
            print(f"Szczegóły pliku:")
            print(f"- Ścieżka: {abs_path}")
            print(f"- Istnieje: {os.path.exists(abs_path)}")
            if os.path.exists(abs_path):
                print(f"- Rozmiar: {os.path.getsize(abs_path)}")
                print(f"- Uprawnienia: {oct(os.stat(abs_path).st_mode)[-3:]}")
            traceback.print_exc()
            return error_msg

    # Komendy zostały przeniesione do osobnych plików
    # Zobacz: commands/recording_commands.py, commands/utility_commands.py