#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os

import discord
from dotenv import load_dotenv

# Wczytaj zmienne środowiskowe z pliku .env (jeśli istnieje)
load_dotenv()


class BotConfig:
    # Konfiguracja podstawowa
    DEFAULT_PREFIX = os.environ.get("BOT_PREFIX", "!")

    # UWAGA: token NIE jest już trzymany w kodzie. Pochodzi wyłącznie ze
    # zmiennej środowiskowej DISCORD_TOKEN (np. z pliku .env). Stary token
    # wpisany na sztywno został skompromitowany i należy go unieważnić.
    TOKEN = os.environ.get("DISCORD_TOKEN")

    # Konfiguracja intencji
    INTENTS = discord.Intents.default()
    INTENTS.message_content = True
    INTENTS.voice_states = True

    # Konfiguracja modeli AI
    WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "large")
    OLLAMA_DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "deepseek-r1:14b")

    # Adres serwera transkrypcji (gpuworker)
    API_URL = os.environ.get("API_URL", "http://localhost:8000")

    # Konfiguracja ścieżek
    RECORDINGS_DIR = os.environ.get(
        "RECORDINGS_DIR", os.path.join(os.getcwd(), "recordings")
    )
    # Trwały magazyn transkrypcji i podsumowań
    DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))

    # Po ilu dniach usuwać pliki audio (transkrypcje trzymane są bezterminowo)
    AUDIO_RETENTION_DAYS = int(os.environ.get("AUDIO_RETENTION_DAYS", "7"))

    # Konfiguracja audio z Discorda (PCM odbierany z voice gateway)
    # Discord zawsze wysyła 48 kHz, 16-bit, stereo.
    AUDIO_CHANNELS = 2
    AUDIO_SAMPLE_WIDTH = 2  # 16-bit
    AUDIO_SAMPLE_RATE = 48000

    @classmethod
    def require_token(cls) -> str:
        """Zwraca token bota albo zgłasza czytelny błąd, jeśli go brakuje."""
        if not cls.TOKEN:
            raise RuntimeError(
                "Brak tokenu bota. Ustaw zmienną środowiskową DISCORD_TOKEN "
                "(np. w pliku bot/.env - patrz .env.example)."
            )
        return cls.TOKEN
