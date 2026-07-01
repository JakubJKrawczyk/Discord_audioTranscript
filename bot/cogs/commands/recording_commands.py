#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import wave
import asyncio
import datetime
import traceback
from typing import Optional

import discord
from discord import app_commands
from discord.ext import voice_recv

import sys
sys.path.append('../..')
from consts import Consts
from config import BotConfig
from utils.audio_sink import PerUserPCMSink


class RecordingCommands:
    def __init__(self, audio_recorder):
        self.cog = audio_recorder
        self.bot = audio_recorder.bot

        self.register_commands()
        self.register_slash_commands()

    def register_commands(self):
        """Rejestruje tradycyjne komendy (prefixowe)."""

        @self.bot.command()
        async def record_user(ctx, member: discord.Member = None, filename: str = "recording"):
            """Rozpoczyna nagrywanie konkretnego użytkownika"""
            await self._record_user(ctx, member, filename)

        @self.bot.command()
        async def record_all(ctx, filename_prefix: str = "recording"):
            """Rozpoczyna nagrywanie wszystkich na kanale"""
            await self._record_all(ctx, filename_prefix)

        @self.bot.command()
        async def stop(ctx):
            """Zatrzymuje nagrywanie"""
            await self._stop(ctx)

    def register_slash_commands(self):
        """Rejestruje slash komendy."""

        @self.bot.tree.command(name="record_user", description="Rozpoczyna nagrywanie konkretnego użytkownika")
        @app_commands.describe(
            member="Użytkownik do nagrania (opcjonalnie, domyślnie ty)",
            filename="Nazwa pliku nagrania (opcjonalnie)"
        )
        async def record_user_slash(
                interaction: discord.Interaction,
                member: Optional[discord.Member] = None,
                filename: Optional[str] = "recording"
        ):
            await interaction.response.defer(ephemeral=False)
            ctx = await self.create_context_from_interaction(interaction)
            await self._record_user(ctx, member, filename)

        @self.bot.tree.command(name="record_all", description="Rozpoczyna nagrywanie wszystkich na kanale")
        @app_commands.describe(filename_prefix="Prefix nazwy pliku nagrania (opcjonalnie)")
        async def record_all_slash(interaction: discord.Interaction, filename_prefix: Optional[str] = "recording"):
            await interaction.response.defer(ephemeral=False)
            ctx = await self.create_context_from_interaction(interaction)
            await self._record_all(ctx, filename_prefix)

        @self.bot.tree.command(name="stop", description="Zatrzymuje nagrywanie")
        async def stop_slash(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=False)
            ctx = await self.create_context_from_interaction(interaction)
            await self._stop(ctx)

    async def create_context_from_interaction(self, interaction):
        """Tworzy pseudo-kontekst dla obsługi slash komend."""
        class PseudoContext:
            def __init__(self, interaction):
                self.interaction = interaction
                self.author = interaction.user
                self.voice = interaction.user.voice
                self.guild = interaction.guild
                self.followup = interaction.followup

            async def send(self, *args, **kwargs):
                await self.followup.send(*args, **kwargs)

        return PseudoContext(interaction)

    async def _connect_and_listen(self, ctx, channel):
        """Łączy się z kanałem głosowym i zaczyna nasłuchiwać audio per-user."""
        guild = channel.guild

        # Zamknij ewentualne poprzednie połączenie głosowe w tej gildii.
        if guild.voice_client is not None:
            await guild.voice_client.disconnect(force=True)

        voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        sink = PerUserPCMSink()
        voice_client.listen(sink)

        self.cog.current_channel = channel
        self.cog.voice_client = voice_client
        self.cog.sink = sink
        return voice_client, sink

    async def _record_user(self, ctx, member=None, filename="recording"):
        """Nagrywanie pojedynczego użytkownika."""
        if self.cog.recording:
            await ctx.send("Nagrywanie już trwa! Użyj /stop aby zakończyć.")
            return

        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        target_user = member if member else ctx.author

        try:
            channel = ctx.author.voice.channel
            await self._connect_and_listen(ctx, channel)
            await ctx.send(Consts.WCHODZI_NA_KANAL)

            self.cog.recording_users = {str(target_user.id): filename}
            self.cog.recording = True

            await ctx.send(
                f"🔴 Nagrywam użytkownika **{target_user.display_name}**. "
                f"Użyj `/stop`, aby zakończyć."
            )
        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            traceback.print_exc()
            await self._cleanup_voice()

    async def _record_all(self, ctx, filename_prefix="recording"):
        """Nagrywanie wszystkich użytkowników na kanale."""
        if self.cog.recording:
            await ctx.send("Nagrywanie już trwa! Użyj /stop aby zakończyć.")
            return

        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        try:
            channel = ctx.author.voice.channel
            await self._connect_and_listen(ctx, channel)
            await ctx.send(Consts.WCHODZI_NA_KANAL)

            users_to_record = {
                str(member.id): f"{filename_prefix}_{member.display_name}"
                for member in channel.members if not member.bot
            }
            self.cog.recording_users = users_to_record
            self.cog.recording = True

            users_str = ", ".join(m.display_name for m in channel.members if not m.bot)
            await ctx.send(
                f"🔴 Nagrywam kanał **{channel.name}** (uczestnicy: {users_str}). "
                f"Użyj `/stop`, aby zakończyć."
            )
        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            traceback.print_exc()
            await self._cleanup_voice()

    async def _cleanup_voice(self):
        """Zatrzymuje nasłuch i rozłącza klienta głosowego."""
        self.cog.recording = False
        vc = self.cog.voice_client
        if vc is not None:
            try:
                if vc.is_listening():
                    vc.stop_listening()
            except Exception:
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        self.cog.voice_client = None
        self.cog.sink = None

    def _save_wav(self, frames: bytes, filepath: str):
        """Zapisuje surowe PCM (48 kHz, stereo, 16-bit) do pliku WAV."""
        with wave.open(filepath, 'wb') as wf:
            wf.setnchannels(BotConfig.AUDIO_CHANNELS)
            wf.setsampwidth(BotConfig.AUDIO_SAMPLE_WIDTH)
            wf.setframerate(BotConfig.AUDIO_SAMPLE_RATE)
            wf.writeframes(frames)

    @staticmethod
    async def _send_chunks(ctx, text, header=None):
        """Wysyła długi tekst w kawałkach po 1900 znaków (limit Discorda)."""
        if header:
            await ctx.send(header)
        text = text or "(pusto)"
        for i in range(0, len(text), 1900):
            await ctx.send(text[i:i + 1900])

    async def _stop(self, ctx):
        """Zatrzymuje nagrywanie, zapisuje pliki, transkrybuje i podsumowuje."""
        if not self.cog.recording:
            await ctx.send("Nie ma aktywnego nagrywania!")
            return

        try:
            self.cog.recording = False

            # Przechwyć bufory zanim rozłączymy klienta.
            sink = self.cog.sink
            buffers = dict(sink.buffers) if sink else {}
            if sink:
                sizes = {k: len(v) for k, v in sink.buffers.items()}
                print(f"[sink] stats={sink.stats} bufory(bajty)={sizes}")

            vc = self.cog.voice_client
            if vc is not None:
                if vc.is_listening():
                    vc.stop_listening()
                await vc.disconnect(force=True)
            self.cog.voice_client = None
            self.cog.sink = None

            await ctx.send(Consts.ZAKONCZENIE_NAGRYWANIA)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            channel_name = self.cog.current_channel.name if self.cog.current_channel else "?"
            session_transcripts = {}  # uid -> {display_name, text, audio_file}

            for user_id, filename_base in self.cog.recording_users.items():
                pcm = buffers.get(user_id)
                if not pcm:
                    print(f"Brak danych audio dla użytkownika {user_id}")
                    continue

                filename = os.path.join(
                    self.cog.recordings_dir, f"{filename_base}_{timestamp}.wav"
                )
                self._save_wav(bytes(pcm), filename)
                print(f"Zapisano {filename} ({len(pcm)} bajtów PCM)")

                display = self.cog.get_username_by_id(user_id)
                await ctx.send(f"⏳ Transkrybuję nagranie użytkownika **{display}**...")

                text = await self.cog.transcribe_audio(filename)
                session_transcripts[user_id] = {
                    "display_name": display,
                    "text": text,
                    "audio_file": filename,
                }

            if not session_transcripts:
                await ctx.send("Brak danych audio do zapisania.")
                return

            # Zapisz sesję w trwałym magazynie (nadaje ID transkrypcji).
            session = await asyncio.to_thread(
                self.cog.store.add_session, channel_name, session_transcripts
            )

            participants = ", ".join(d["display_name"] for d in session_transcripts.values())
            await ctx.send(
                f"Zapisano transkrypcję **{session['id']}** "
                f"({len(session_transcripts)} uczestn.: {participants})."
            )

            for data in session_transcripts.values():
                await self._send_chunks(
                    ctx, data["text"], header=f"**Transkrypcja dla {data['display_name']}:**"
                )

            # Surowa transkrypcja jest zapisana. Podsumowanie tworzy się osobno
            # na żądanie: /summarize <ID>.
            await ctx.send(f"Aby podsumować: `/summarize {session['id']}`")
            await ctx.send(Consts.FINISH)

        except Exception as e:
            await ctx.send(f"Wystąpił błąd podczas zatrzymywania nagrywania: {str(e)}")
            traceback.print_exc()
            await self._cleanup_voice()
