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
        # Synchronizowanie slash komend z Discordem
        await self.tree.sync()
        print("Slash commands synchronized")

    async def on_ready(self):
        print(f'Bot jest gotowy: {self.user}')
        # Ustaw status bota
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/help"
            )
        )