#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from cogs.commands.recording_commands import RecordingCommands
from cogs.commands.utility_commands import UtilityCommands
from cogs.commands.transcription_commands import TranscriptionCommands

def register_all_commands(audio_recorder):
    """Rejestruje wszystkie komendy dla AudioRecorder"""
    # Inicjalizacja komend nagrywania
    RecordingCommands(audio_recorder)

    # Inicjalizacja komend użytkowych
    UtilityCommands(audio_recorder)

    # Inicjalizacja komend transkrypcji (lista / summarize / delete)
    TranscriptionCommands(audio_recorder)

    print("Wszystkie komendy zostały zarejestrowane")