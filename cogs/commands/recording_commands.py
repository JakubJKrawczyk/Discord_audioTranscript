#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import wave
import datetime
import os
import pyaudio
from typing import Optional

class RecordingCommands:
    def __init__(self, audio_recorder):
        self.cog = audio_recorder
        self.bot = audio_recorder.bot

        # Rejestracja tradycyjnych komend
        self.register_commands()

        # Rejestracja slash komend
        self.register_slash_commands()

    def register_commands(self):
        """Rejestruje tradycyjne komendy"""

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
        """Rejestruje slash komendy"""

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
        """Tworzy pseudo-kontekst dla obsługi interakcji slash komend"""
        class PseudoContext:
            def __init__(self, interaction):
                self.interaction = interaction
                self.author = interaction.user
                self.voice = interaction.user.voice
                self.followup = interaction.followup

            async def send(self, *args, **kwargs):
                await self.followup.send(*args, **kwargs)

        return PseudoContext(interaction)

    async def _record_user(self, ctx, member = None, filename = "recording"):
        """Implementacja komendy nagrywania pojedynczego użytkownika"""
        if self.cog.recording:
            await ctx.send("Nagrywanie już trwa! Użyj !stop aby zakończyć.")
            return

        # Sprawdź czy użytkownik jest na kanale głosowym
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        # Jeśli nie podano członka, nagraj autora
        target_user = member if member else ctx.author

        try:
            # Dołącz do kanału głosowego
            channel = ctx.author.voice.channel
            self.cog.current_channel = channel
            voice_client = await channel.connect()

            # Ustaw tryb nagrywania
            self.cog.recording_users = {str(target_user.id): filename}
            self.cog.frames = {}  # Wyczyść ramki

            # Rozpocznij nagrywanie
            self.cog.recording = True

            print(f"wykryto {self.cog.audio.get_device_count()} urządzeń wejściowych")
            # Konfiguracja streamu audio
            default_input = self.cog.audio.get_default_input_device_info()

            self.cog.stream = self.cog.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=int(default_input['defaultSampleRate']),
                input=True,
                input_device_index=default_input['index'],
                frames_per_buffer=1024,
                stream_callback=self.cog.callback
            )

            self.cog.stream.start_stream()
            await ctx.send(f"Rozpoczęto nagrywanie użytkownika {target_user.display_name} (plik: {filename})! Użyj !stop aby zakończyć.")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            self.cog.recording = False
            self.cog.recording_users = {}
            if self.cog.stream:
                self.cog.stream.stop_stream()
                self.cog.stream.close()

    async def _record_all(self, ctx, filename_prefix = "recording"):
        """Implementacja komendy nagrywania wszystkich użytkowników"""
        if self.cog.recording:
            await ctx.send("Nagrywanie już trwa! Użyj !stop aby zakończyć.")
            return

        # Sprawdź czy użytkownik jest na kanale głosowym
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        try:
            # Dołącz do kanału głosowym
            channel = ctx.author.voice.channel
            self.cog.current_channel = channel
            voice_client = await channel.connect()

            # Pobierz wszystkich użytkowników na kanale (oprócz botów)
            users_to_record = {}
            for member in channel.members:
                if not member.bot:
                    users_to_record[str(member.id)] = f"{filename_prefix}_{member.display_name}"

            # Ustaw tryb nagrywania
            self.cog.recording_users = users_to_record
            self.cog.frames = {}  # Wyczyść ramki

            # Rozpocznij nagrywanie
            self.cog.recording = True

            # Konfiguracja streamu audio
            default_input = self.cog.audio.get_default_input_device_info()

            self.cog.stream = self.cog.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=int(default_input['defaultSampleRate']),
                input=True,
                input_device_index=default_input['index'],
                frames_per_buffer=1024,
                stream_callback=self.cog.callback
            )

            self.cog.stream.start_stream()
            users_str = ", ".join([member.display_name for member in channel.members if not member.bot])
            await ctx.send(f"Rozpoczęto nagrywanie wszystkich użytkowników na kanale {channel.name} (użytkownicy: {users_str})! Użyj !stop aby zakończyć.")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            self.cog.recording = False
            self.cog.recording_users = {}
            if self.cog.stream:
                self.cog.stream.stop_stream()
                self.cog.stream.close()

    async def _stop(self, ctx):
        """Implementacja komendy zatrzymania nagrywania"""
        if not self.cog.recording:
            await ctx.send("Nie ma aktywnego nagrywania!")
            return

        try:
            self.cog.recording = False

            # Zatrzymaj stream
            if self.cog.stream:
                self.cog.stream.stop_stream()
                self.cog.stream.close()

            # Zapisz pliki audio dla każdego nagrywanego użytkownika
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

            # Sprawdź, którzy użytkownicy mają dane do zapisania
            saved_files = []
            transcriptions = {}

            for user_id, filename_base in self.cog.recording_users.items():
                frames_to_save = self.cog.frames.get(user_id, [])

                if not frames_to_save:
                    print(f"Brak danych audio dla użytkownika {user_id}")
                    continue

                # Tworzenie nazwy pliku
                filename = os.path.join(self.cog.recordings_dir, f"{filename_base}_{timestamp}.wav")

                print(f"Zapisuję plik: {filename}")  # Debug info

                # Zapisz plik WAV
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(1)  # Mono
                    wf.setsampwidth(self.cog.audio.get_sample_size(pyaudio.paInt16))
                    wf.setframerate(int(self.cog.audio.get_default_input_device_info()['defaultSampleRate']))
                    audio_data = b''.join(frames_to_save)
                    print(f"Rozmiar danych audio dla użytkownika {user_id}: {len(audio_data)} bajtów")
                    wf.writeframes(audio_data)

                saved_files.append(filename)

                # Wykonaj transkrypcję dla tego pliku
                await ctx.send(f"Rozpoczynam transkrypcję dla użytkownika {self.cog.get_username_by_id(user_id)}...")
                transcription = await self.cog.transcribe_audio(filename)
                transcriptions[user_id] = transcription

            # Rozłącz się z kanału głosowego
            for vc in self.bot.voice_clients:
                await vc.disconnect()

            if not saved_files:
                await ctx.send("Brak danych audio do zapisania.")
                return

            # Zapisz transkrypcje dla użytkownika, który wywołał !stop
            user_id = ctx.author.id
            self.cog.transcriptions[user_id] = transcriptions

            # Wyślij informacje o zapisanych plikach
            await ctx.send(f"Zapisano {len(saved_files)} plików audio w folderze {self.cog.recordings_dir}")

            # Wyślij transkrypcje
            await ctx.send("Transkrypcje:")
            for user_id, transcription in transcriptions.items():
                username = self.cog.get_username_by_id(user_id)
                await ctx.send(f"**Transkrypcja dla {username}:**")
                for i in range(0, len(transcription), 1900):
                    await ctx.send(transcription[i:i+1900])

            # Automatycznie generuj podsumowania dla każdego użytkownika
            await ctx.send("Generuję podsumowania...")
            summaries = {}

            for user_id, transcription in transcriptions.items():
                if len(transcription) > 30:  # Jeśli jest co podsumowywać
                    username = self.cog.get_username_by_id(user_id)
                    await ctx.send(f"Generuję podsumowanie dla {username}...")
                    summary = await self.cog.summarize_with_ollama(transcription)
                    summaries[user_id] = summary

            # Wyślij podsumowania
            if summaries:
                await ctx.send("**Podsumowania:**")
                for user_id, summary in summaries.items():
                    username = self.cog.get_username_by_id(user_id)
                    await ctx.send(f"**Podsumowanie dla {username}:**\n{summary}")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd podczas zatrzymywania nagrywania: {str(e)}")
            import traceback
            traceback.print_exc()