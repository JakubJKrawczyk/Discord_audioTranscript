#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import discord
from discord.ext import commands
import asyncio
import traceback

from config import BotConfig
from bot import Bot
from cogs.audio_recorder import AudioRecorder
from cogs.error_handlers import register_error_handlers

async def main():
    # Inicjalizacja bota
    bot = Bot()

    # Rejestracja cogów
    await bot.add_cog(AudioRecorder(bot))

    # Rejestracja uchwytów błędów
    register_error_handlers(bot)

    # Uruchomienie bota
    print('Uruchamianie bota...')
    TOKEN = os.environ.get("DISCORD_TOKEN", BotConfig.DEFAULT_TOKEN)

    try:
        await bot.start(TOKEN)
    except KeyboardInterrupt:
        await bot.close()
    except Exception as e:
        print(f"Błąd podczas uruchamiania bota: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    # Sprawdź dostępność CUDA
    import torch
    print(f"CUDA dostępne: {torch.cuda.is_available()}")
    print(f"Liczba urządzeń CUDA: {torch.cuda.device_count()}")
    if torch.cuda.is_available():
        print(f"Nazwa GPU: {torch.cuda.get_device_name(0)}")

    # Uruchom główną pętlę asyncio
    asyncio.run(main())