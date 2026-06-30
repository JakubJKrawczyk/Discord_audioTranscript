#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
