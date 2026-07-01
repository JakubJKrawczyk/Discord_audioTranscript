#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import ctypes.util
import traceback

import discord

from config import BotConfig
from bot import Bot
from cogs.audio_recorder import AudioRecorder
from cogs.error_handlers import register_error_handlers


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
