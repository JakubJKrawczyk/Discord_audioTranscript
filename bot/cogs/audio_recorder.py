#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import asyncio
import traceback

from discord.ext import commands, tasks

from config import BotConfig
from cogs.commands_loader import register_all_commands
from utils.ApiController import ApiController, ModelType
from utils.audio_sink import PerUserPCMSink  # noqa: F401  (re-export dla zgodności)
from utils.storage import TranscriptionStore


class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recording = False
        self.current_channel = None  # Kanał, na którym nagrywamy
        self.voice_client = None     # Aktywny VoiceRecvClient
        self.sink = None             # Aktywny PerUserPCMSink
        self.recording_users = {}    # {user_id: nazwa_pliku}

        # Skonfiguruj adres serwera transkrypcji
        ApiController.set_base_url(BotConfig.API_URL)

        self.user_contexts = {}
        self.ollama_model = BotConfig.OLLAMA_DEFAULT_MODEL

        # Foldery na nagrania i dane
        self.recordings_dir = BotConfig.RECORDINGS_DIR
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings: {self.recordings_dir}")

        # Trwały magazyn transkrypcji/podsumowań
        self.store = TranscriptionStore(
            base_dir=BotConfig.DATA_DIR,
            recordings_dir=self.recordings_dir,
            audio_retention_days=BotConfig.AUDIO_RETENTION_DAYS,
        )
        print(f"Magazyn danych: {BotConfig.DATA_DIR} (audio: {BotConfig.AUDIO_RETENTION_DAYS} dni)")

        # Sprawdź dostępność usług API
        self.check_services()

        # Rejestracja wszystkich komend
        register_all_commands(self)

    async def cog_load(self):
        """Wywoływane przy ładowaniu cog-a - jednorazowe czyszczenie + pętla."""
        try:
            removed = await asyncio.to_thread(self.store.prune_audio)
            if removed:
                print(f"Usunięto {len(removed)} starych plików audio.")
        except Exception as e:  # noqa: BLE001
            print(f"Błąd podczas czyszczenia audio: {e}")
        if not self.audio_cleanup_loop.is_running():
            self.audio_cleanup_loop.start()

    def cog_unload(self):
        self.audio_cleanup_loop.cancel()

    @tasks.loop(hours=24)
    async def audio_cleanup_loop(self):
        """Codzienne czyszczenie plików audio starszych niż retencja."""
        try:
            removed = await asyncio.to_thread(self.store.prune_audio)
            if removed:
                print(f"[cleanup] Usunięto {len(removed)} starych plików audio.")
        except Exception as e:  # noqa: BLE001
            print(f"[cleanup] Błąd: {e}")

    def check_services(self):
        """Sprawdza dostępność usług API (Whisper i Ollama)."""
        try:
            print("Sprawdzanie statusu usług API...")
            health = ApiController.check_health()

            if health.get('status') != 'ok':
                print(f"OSTRZEŻENIE: API nie jest w pełni operacyjne: {health.get('message')}")
            else:
                print("API jest dostępne.")

            services = health.get('services', {})
            if services.get('whisper', {}).get('loaded'):
                print("Model Whisper jest załadowany.")
            else:
                print("OSTRZEŻENIE: Model Whisper nie jest załadowany. Transkrypcja może nie działać.")

            if services.get('ollama', {}).get('available'):
                print("Ollama API jest dostępne.")
                self.check_ollama_model()
            else:
                print("OSTRZEŻENIE: Ollama API nie jest dostępne. Podsumowania mogą nie działać.")
        except Exception as e:
            print(f"Błąd podczas sprawdzania usług API: {str(e)}")

    def check_ollama_model(self):
        """Sprawdza, czy wybrany model Ollama jest dostępny na serwerze."""
        try:
            models = ApiController.list_ollama_models()
            model_names = [m.get('name') for m in models if 'name' in m]
            print(f"Dostępne modele Ollama: {model_names}")

            if self.ollama_model not in model_names:
                print(
                    f"OSTRZEŻENIE: Model {self.ollama_model} nie jest dostępny na serwerze Ollama. "
                    f"Pobierz go na serwerze: `ollama pull {self.ollama_model}`."
                )
            else:
                print(f"Model {self.ollama_model} jest dostępny.")
        except Exception as e:
            print(f"Błąd podczas sprawdzania modelu Ollama: {str(e)}")

    def get_username_by_id(self, user_id):
        """Pobiera nazwę użytkownika na podstawie ID (jeśli jest na kanale)."""
        user_id_str = str(user_id)
        if self.current_channel:
            for member in self.current_channel.members:
                if str(member.id) == user_id_str:
                    return member.display_name
        return f"Użytkownik-{user_id}"

    async def transcribe_audio(self, filepath):
        """Transkrybuje plik audio na tekst używając ApiController (Whisper)."""
        print(f"Rozpoczynam transkrypcję pliku: {filepath}")
        try:
            abs_path = os.path.abspath(filepath)

            if not os.path.exists(abs_path):
                return f"Błąd transkrypcji: Plik nie istnieje ({abs_path})"
            if os.path.getsize(abs_path) == 0:
                return "Błąd transkrypcji: Plik jest pusty"

            result = await asyncio.to_thread(
                ApiController.transcribe, abs_path, ModelType.WHISPER
            )

            if not result or "text" not in result:
                return "Błąd transkrypcji: Brak tekstu w wyniku"

            print("Transkrypcja zakończona sukcesem")
            return result["text"]
        except Exception as e:
            error_msg = f"Błąd podczas transkrypcji: {str(e)}"
            print(f"BŁĄD KRYTYCZNY: {error_msg}")
            traceback.print_exc()
            return error_msg

    async def summarize_with_ollama(self, text, user_id=None):
        """Tworzy podsumowanie tekstu przez tekstowy endpoint API (Ollama)."""
        try:
            print(f"Generowanie podsumowania dla tekstu o długości {len(text)} znaków...")
            context = self.user_contexts.get(user_id) if user_id is not None else None
            result = await asyncio.to_thread(
                ApiController.summarize,
                text,
                self.ollama_model,
                None,        # system_prompt - domyślny z API
                0.0,         # temperature
                context,     # kontekst użytkownika (opcjonalny)
            )
            return result["text"]
        except Exception as e:
            print(f"Błąd podczas generowania podsumowania: {str(e)}")
            traceback.print_exc()
            return f"Błąd podczas generowania podsumowania: {str(e)}"

    async def summarize_session(self, session, requester_id=None, label="all"):
        """
        Tworzy podsumowanie całej sesji (połączone transkrypcje uczestników),
        zapisuje je do pliku w magazynie i zwraca tekst podsumowania.
        """
        combined = await asyncio.to_thread(self.store.build_combined_text, session)
        if not combined.strip():
            return None
        summary = await self.summarize_with_ollama(combined, user_id=requester_id)
        await asyncio.to_thread(self.store.add_summary, session["id"], label, summary)
        return summary

    # Komendy znajdują się w:
    #   cogs/commands/recording_commands.py
    #   cogs/commands/utility_commands.py
    #   cogs/commands/transcription_commands.py
