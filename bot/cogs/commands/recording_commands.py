#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import traceback
from typing import Optional

import discord
from discord import app_commands

import sys
sys.path.append('../..')
from consts import Consts


class RecordingCommands:
    def __init__(self, audio_recorder):
        self.cog = audio_recorder
        self.bot = audio_recorder.bot
        self.register_commands()
        self.register_slash_commands()

    # --------------------------------------------------------------- rejestracja
    def register_commands(self):
        @self.bot.command()
        async def auto(ctx, *, channel: discord.VoiceChannel = None):
            """Wprowadza bota na kanał (tryb auto - stały nasłuch)"""
            await self._auto(ctx, channel)

        @self.bot.command()
        async def leave(ctx):
            """Wyłącza bota z kanału (kończy tryb auto)"""
            await self._leave(ctx)

        @self.bot.command()
        async def record_user(ctx, member: discord.Member = None, filename: str = "recording"):
            """Nagrywa konkretnego użytkownika na Twoim kanale"""
            await self._record(ctx, only_member=member or ctx.author)

        @self.bot.command()
        async def record_all(ctx, filename_prefix: str = "recording"):
            """Nagrywa wszystkich na Twoim kanale"""
            await self._record(ctx, only_member=None)

        @self.bot.command()
        async def stop(ctx):
            """Kończy nagrywanie i wraca na kanał domowy"""
            await self._stop(ctx)

    def register_slash_commands(self):
        @self.bot.tree.command(name="auto", description="Wprowadza bota na kanał (tryb auto - stały nasłuch)")
        @app_commands.describe(channel="Kanał głosowy (opcjonalnie; domyślnie Twój)")
        async def auto_slash(interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
            await interaction.response.defer(ephemeral=False)
            ctx = await self._ctx(interaction)
            await self._auto(ctx, channel)

        @self.bot.tree.command(name="leave", description="Wyłącza bota z kanału (kończy tryb auto)")
        async def leave_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=False)
            ctx = await self._ctx(interaction)
            await self._leave(ctx)

        @self.bot.tree.command(name="record_user", description="Nagrywa konkretnego użytkownika na Twoim kanale")
        @app_commands.describe(member="Użytkownik do nagrania (domyślnie Ty)")
        async def record_user_slash(interaction: discord.Interaction, member: Optional[discord.Member] = None):
            await interaction.response.defer(ephemeral=False)
            ctx = await self._ctx(interaction)
            await self._record(ctx, only_member=member or interaction.user)

        @self.bot.tree.command(name="record_all", description="Nagrywa wszystkich na Twoim kanale")
        async def record_all_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=False)
            ctx = await self._ctx(interaction)
            await self._record(ctx, only_member=None)

        @self.bot.tree.command(name="stop", description="Kończy nagrywanie i wraca na kanał domowy")
        async def stop_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=False)
            ctx = await self._ctx(interaction)
            await self._stop(ctx)

    async def _ctx(self, interaction):
        """Pseudo-kontekst dla slash komend."""
        class PseudoContext:
            def __init__(self, it):
                self.interaction = it
                self.author = it.user
                self.voice = it.user.voice
                self.guild = it.guild

            async def send(self, *args, **kwargs):
                await interaction.followup.send(*args, **kwargs)

        return PseudoContext(interaction)

    # -------------------------------------------------------------------- logika
    async def _auto(self, ctx, channel):
        target = channel or (ctx.author.voice.channel if ctx.author.voice else None)
        if target is None:
            await ctx.send("Podaj kanał albo wejdź na kanał głosowy.")
            return
        try:
            await self.cog.start_auto(target)
            await ctx.send(f"🎙️ Tryb auto: nasłuchuję na **{target.name}**. `/leave` aby wyłączyć.")
        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {e}")
            traceback.print_exc()

    async def _leave(self, ctx):
        if self.cog.mode == "idle" and self.cog.voice_client is None:
            await ctx.send("Nie jestem na żadnym kanale.")
            return
        try:
            await self.cog.leave(send=ctx.send)
            await ctx.send("👋 Wyszedłem z kanału. Tryb auto wyłączony.")
        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {e}")
            traceback.print_exc()

    async def _record(self, ctx, only_member=None):
        if self.cog.mode == "manual":
            await ctx.send("Już nagrywam ręcznie. Użyj `/stop`, aby zakończyć.")
            return
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return
        channel = ctx.author.voice.channel
        try:
            only = {str(only_member.id)} if only_member else None
            await self.cog.start_manual(channel, only_users=only)
            await ctx.send(Consts.WCHODZI_NA_KANAL)
            if only_member:
                await ctx.send(f"🔴 Nagrywam **{only_member.display_name}** na **{channel.name}**. `/stop` aby zakończyć.")
            else:
                await ctx.send(f"🔴 Nagrywam kanał **{channel.name}**. `/stop` aby zakończyć.")
        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {e}")
            traceback.print_exc()

    async def _stop(self, ctx):
        if self.cog.mode == "manual":
            try:
                await ctx.send(Consts.ZAKONCZENIE_NAGRYWANIA)
                home = await self.cog.stop_manual(send=ctx.send)
                if home is not None:
                    await ctx.send(f"↩️ Wracam na kanał domowy **{home.name}** (tryb auto).")
                else:
                    await ctx.send("Rozłączono.")
                await ctx.send(Consts.FINISH)
            except Exception as e:
                await ctx.send(f"Wystąpił błąd podczas kończenia: {e}")
                traceback.print_exc()
        elif self.cog.mode == "auto":
            await ctx.send("Tryb auto jest aktywny. Użyj `/leave`, aby wyłączyć bota z kanału.")
        else:
            await ctx.send("Nie ma aktywnego nagrywania.")
