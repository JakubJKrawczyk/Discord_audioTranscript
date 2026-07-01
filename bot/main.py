#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import ctypes.util
import logging
import traceback

import discord

# Logowanie - potrzebne, by widzieć wewnętrzne komunikaty discord.py
# (m.in. tryb szyfrowania głosu, błędy odbioru RTP).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("discord.voice_client").setLevel(logging.DEBUG)
logging.getLogger("discord.gateway").setLevel(logging.INFO)
try:
    logging.getLogger("discord.ext.voice_recv").setLevel(logging.DEBUG)
except Exception:
    pass

from config import BotConfig
from bot import Bot
from cogs.audio_recorder import AudioRecorder
from cogs.error_handlers import register_error_handlers


def disable_dave():
    """
    Wyłącza DAVE (E2EE głosu Discorda). discord-ext-voice-recv nie potrafi
    zdjąć szyfrowania DAVE przy ODBIORZE - Opus dostaje zaszyfrowane dane i
    rzuca 'corrupted stream', a wątek odbioru pada po pierwszym pakiecie.
    Ustawiając has_dave=False bot zgłasza max_dave_protocol_version=0, więc
    Discord negocjuje połączenie bez E2EE (samo szyfrowanie transportowe).
    """
    try:
        import discord.voice_state as _vs
        _vs.has_dave = False
        print("DAVE wyłączony (has_dave=False) - odbiór głosu bez E2EE.")
    except Exception as e:  # noqa: BLE001
        print(f"OSTRZEŻENIE: nie udało się wyłączyć DAVE: {e}")


def ensure_opus():
    """
    Ładuje bibliotekę Opus. Bez niej discord-ext-voice-recv nie zdekoduje
    dźwięku z Discorda i nagrania będą ciszą. Na obrazach slim automatyczne
    ładowanie zawodzi, więc ładujemy jawnie po sonamie.
    """
    if discord.opus.is_loaded():
        return
    candidates = [
        ctypes.util.find_library("opus"),
        "libopus.so.0",
        "libopus.so",
        "opus",
    ]
    for name in candidates:
        if not name:
            continue
        try:
            discord.opus.load_opus(name)
            if discord.opus.is_loaded():
                print(f"Opus załadowany: {name}")
                return
        except Exception:
            continue
    print("OSTRZEŻENIE: nie udało się załadować Opusa - nagrywanie głosu nie zadziała!")


async def main():
    # Wyłącz DAVE (E2EE) - inaczej odbiór głosu nie działa z voice_recv
    disable_dave()

    # Załaduj Opus (wymagany do odbioru/dekodowania głosu z Discorda)
    ensure_opus()

    # Inicjalizacja bota
    bot = Bot()

    # Rejestracja cogów
    await bot.add_cog(AudioRecorder(bot))

    # Rejestracja uchwytów błędów
    register_error_handlers(bot)

    # Uruchomienie bota
    print('Uruchamianie bota...')
    token = BotConfig.require_token()

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        await bot.close()
    except Exception as e:
        print(f"Błąd podczas uruchamiania bota: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
