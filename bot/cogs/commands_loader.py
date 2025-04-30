#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from cogs.commands.recording_commands import RecordingCommands
from cogs.commands.utility_commands import UtilityCommands

def register_all_commands(audio_recorder):
    """Rejestruje wszystkie komendy dla AudioRecorder"""
    # Inicjalizacja komend nagrywania
    RecordingCommands(audio_recorder)

    # Inicjalizacja komend użytkowych
    UtilityCommands(audio_recorder)

    print("Wszystkie komendy zostały zarejestrowane")