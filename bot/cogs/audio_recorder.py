#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import asyncio
import wave
import datetime
import whisper
import torch
import os
import requests
import pyaudio
import subprocess
import traceback

from config import BotConfig
from utils.audio_processing import AudioProcessor
from cogs.commands_loader import register_all_commands

class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recording = False
        self.frames = {}  # Słownik dla przechowywania ramek audio różnych użytkowników
        self.audio = pyaudio.PyAudio()
        self.stream = None

        # Inicjalizacja Whisper na GPU jeśli dostępne
        if torch.cuda.is_available():
            print("Inicjalizacja Whisper na GPU...")
            self.device = torch.device("cuda")
            self.whisper_model = whisper.load_model(BotConfig.WHISPER_MODEL_SIZE).to(self.device)
        else:
            print("CUDA niedostępne, używam CPU...")
            self.device = torch.device("cpu")
            self.whisper_model = whisper.load_model(BotConfig.WHISPER_MODEL_SIZE)

        self.user_contexts = {}
        self.transcriptions = {}
        self.ollama_url = BotConfig.OLLAMA_URL
        self.ollama_model = BotConfig.OLLAMA_DEFAULT_MODEL
        self.recording_users = {}  # Słownik do przechowywania nagrań poszczególnych użytkowników
        self.current_channel = None  # Aktualny kanał, na którym nagrywamy

        # Utworzenie folderu recordings
        self.recordings_dir = BotConfig.RECORDINGS_DIR
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings utworzony w: {self.recordings_dir}")

        # Sprawdź czy Ollama jest zainstalowana i załaduj model
        self.check_ollama()

        # Inicjalizacja procesora audio
        self.audio_processor = AudioProcessor()

        # Rejestracja wszystkich komend
        register_all_commands(self)

    def check_ollama(self):
        """Sprawdza czy Ollama jest zainstalowana i pobiera model jeśli potrzeba"""
        try:
            # Sprawdź czy Ollama jest dostępna
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code != 200:
                print("Ollama API nie jest dostępne. Upewnij się, że Ollama jest uruchomiona.")
                return False

            # Pobierz listę dostępnych modeli
            available_models = response.json().get("models", [])
            model_names = [model.get("name") for model in available_models]

            print(f"Dostępne modele Ollama: {model_names}")

            # Sprawdź czy nasz model jest dostępny, jeśli nie - pobierz go
            if self.ollama_model not in model_names:
                print(f"Model {self.ollama_model} nie jest zainstalowany. Pobieram...")

                # Użyj subprocess do pobrania modelu w tle
                subprocess.Popen(["ollama", "pull", self.ollama_model])
                print(f"Rozpoczęto pobieranie modelu {self.ollama_model} w tle.")

                # Możemy kontynuować działanie bota podczas pobierania
                return True
            else:
                print(f"Model {self.ollama_model} jest już zainstalowany.")
                return True

        except Exception as e:
            print(f"Błąd podczas sprawdzania Ollama: {str(e)}")
            return False

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
        """Używa Ollama do podsumowania tekstu"""
        try:
            # Przygotuj prompt dla modelu
            prompt = f"""
            Poniżej znajduje się transkrypcja rozmowy. Przygotuj zwięzłe podsumowanie całego tekstu:

            {text}

            Podsumowanie:
            """

            # Wywołaj API Ollamy
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False
                }
            )

            if response.status_code == 200:
                return response.json()['response']
            else:
                print(f"Błąd API Ollama: {response.status_code}")
                return "Nie udało się wygenerować podsumowania."

        except Exception as e:
            print(f"Błąd podczas generowania podsumowania: {str(e)}")
            return f"Błąd podczas generowania podsumowania: {str(e)}"

    async def transcribe_audio(self, filepath):
        """Transkrybuje plik audio na tekst"""
        print(f"Rozpoczynam transkrypcję pliku: {filepath}")

        try:
            abs_path = os.path.abspath(filepath)
            print(f"Pełna ścieżka do pliku: {abs_path}")

            if not os.path.exists(abs_path):
                print(f"BŁĄD: Plik nie istnieje w ścieżce: {abs_path}")
                return f"Błąd transkrypcji: Plik nie istnieje w ścieżce {abs_path}"

            file_size = os.path.getsize(abs_path)
            print(f"Rozmiar pliku: {file_size} bajtów")

            if file_size == 0:
                print("BŁĄD: Plik jest pusty")
                return "Błąd transkrypcji: Plik jest pusty"

            import numpy as np
            import librosa

            def transcribe():
                try:
                    print("Wczytuję plik audio...")
                    audio_data, sample_rate = librosa.load(abs_path, sr=16000, dtype=np.float32)
                    print(f"Plik audio wczytany, próbkowanie: {sample_rate}Hz")

                    # Dla GPU, przenieś tensor na urządzenie
                    if torch.cuda.is_available():
                        audio_tensor = torch.tensor(audio_data).to(self.device)
                        audio_data = audio_tensor.cpu().numpy() if isinstance(audio_tensor, torch.Tensor) else audio_data

                    print("Uruchamiam model Whisper...")
                    # Użyj określonego urządzenia (GPU jeśli dostępne)
                    result = self.whisper_model.transcribe(
                        audio_data,
                        language="pl",  # Ustawienie języka na polski
                        fp16=torch.cuda.is_available()  # Używaj FP16 tylko jeśli mamy CUDA
                    )
                    print("Transkrypcja zakończona pomyślnie")
                    return result
                except Exception as e:
                    print(f"BŁĄD w trakcie transkrypcji: {str(e)}")
                    traceback.print_exc()
                    raise

            print("Uruchamiam transkrypcję w osobnym wątku...")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, transcribe)

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