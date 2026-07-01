#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from cogs.commands.recording_commands import RecordingCommands
from cogs.commands.utility_commands import UtilityCommands
from cogs.commands.transcription_commands import TranscriptionCommands
from cogs.commands.config_commands import ConfigCommands

def register_all_commands(audio_recorder):
    """Rejestruje wszystkie komendy dla AudioRecorder"""
    # Inicjalizacja komend nagrywania
    RecordingCommands(audio_recorder)

    # Inicjalizacja komend użytkowych
    UtilityCommands(audio_recorder)

    # Inicjalizacja komend nagrań (lista / summarize / rename / delete)
    TranscriptionCommands(audio_recorder)

    # Inicjalizacja komendy konfiguracji (/config)
    ConfigCommands(audio_recorder)

    print("Wszystkie komendy zostały zarejestrowane")