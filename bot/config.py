#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands

class BotConfig:
    # Konfiguracja podstawowa
    DEFAULT_PREFIX = '/'
    DEFAULT_TOKEN = "dupa"

    # Konfiguracja intencji
    INTENTS = discord.Intents.default()
    INTENTS.message_content = True
    INTENTS.voice_states = True

    # Konfiguracja modeli AI
    WHISPER_MODEL_SIZE = "large"
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_DEFAULT_MODEL = "deepseek-r1:14b"

    # Konfiguracja ścieżek
    import os
    RECORDINGS_DIR = os.path.join(os.getcwd(), "recordings")

    # Konfiguracja audio
    AUDIO_FORMAT = 1  # pyaudio.paInt16
    AUDIO_CHANNELS = 1  # Mono
    AUDIO_SAMPLE_WIDTH = 2  # 16-bit
    AUDIO_CHUNK_SIZE = 1024  # Rozmiar bufora audio