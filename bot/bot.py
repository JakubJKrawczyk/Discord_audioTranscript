#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from config import BotConfig

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=BotConfig.DEFAULT_PREFIX,
            intents=BotConfig.INTENTS,
            help_command=None
        )

    async def setup_hook(self):
        # Synchronizacja slash komend.
        try:
            if BotConfig.GUILD_ID:
                guild = discord.Object(id=BotConfig.GUILD_ID)
                # Skopiuj wszystkie komendy do gildii i zsynchronizuj (natychmiast).
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                # Wyczyść stare komendy globalne (usuwa m.in. nieaktualne jak /transcriptions).
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                print(f"Zsynchronizowano {len(synced)} slash komend do gildii {BotConfig.GUILD_ID}")
            else:
                synced = await self.tree.sync()
                print(f"Zsynchronizowano {len(synced)} globalnych slash komend (propagacja do ~1h)")
        except Exception as e:
            print(f"Błąd synchronizacji slash komend: {e}")

    async def on_ready(self):
        print(f'Bot jest gotowy: {self.user}')
        # Ustaw status bota
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/help"
            )
        )