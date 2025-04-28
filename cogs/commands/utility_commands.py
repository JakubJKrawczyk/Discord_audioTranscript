#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import requests
import subprocess
from typing import Optional
import sys
sys.path.append('../..')
from consts import Consts

class UtilityCommands:
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
        async def context(ctx, *, new_context):
            """Ustawia kontekst dla użytkownika"""
            await self._context(ctx, new_context)

        @self.bot.command()
        async def show_context(ctx):
            """Pokazuje aktualny kontekst użytkownika"""
            await ctx.send(Consts.SHOW_CONTEXT)

            await self._show_context(ctx)

        @self.bot.command()
        async def change_model(ctx, model_name):
            """Zmienia model Ollama używany do podsumowań"""
            await ctx.send(Consts.CHANGE_MODEL)
            await self._change_model(ctx, model_name)

        @self.bot.command()
        async def summarize(ctx):
            """Tworzy podsumowanie ostatniej transkrypcji"""
            await self._summarize(ctx)

        @self.bot.command()
        async def list_models(ctx):
            """Wyświetla dostępne modele Ollama"""
            await self._list_models(ctx)

        @self.bot.command(name="help")
        async def help_command(ctx, command_name=None):
            """Wyświetla listę dostępnych komend lub szczegółowe informacje o wybranej komendzie"""
            await self._help(ctx, command_name)

    def register_slash_commands(self):
        """Rejestruje slash komendy"""

        @self.bot.tree.command(name="context", description="Ustawia kontekst dla użytkownika")
        @app_commands.describe(new_context="Nowy kontekst dla użytkownika")
        async def context_slash(interaction: discord.Interaction, new_context: str):
            await self._context_slash(interaction, new_context)

        @self.bot.tree.command(name="show_context", description="Pokazuje aktualny kontekst użytkownika")
        async def show_context_slash(interaction: discord.Interaction):
            await self._show_context_slash(interaction)

        @self.bot.tree.command(name="change_model", description="Zmienia model Ollama używany do podsumowań")
        @app_commands.describe(model_name="Nazwa modelu do użycia")
        async def change_model_slash(interaction: discord.Interaction, model_name: str):
            await self._change_model_slash(interaction, model_name)

        @self.bot.tree.command(name="summarize", description="Tworzy podsumowanie ostatniej transkrypcji")
        async def summarize_slash(interaction: discord.Interaction):
            await self._summarize_slash(interaction)

        @self.bot.tree.command(name="list_models", description="Wyświetla dostępne modele Ollama")
        async def list_models_slash(interaction: discord.Interaction):
            await self._list_models_slash(interaction)

        @self.bot.tree.command(name="help", description="Wyświetla listę komend i informacje o nich")
        @app_commands.describe(command="Nazwa komendy dla której chcesz uzyskać pomoc")
        async def help_slash(interaction: discord.Interaction, command: Optional[str] = None):
            await self._help_slash(interaction, command)

    async def _context(self, ctx, new_context):
        """Implementacja komendy ustawiania kontekstu"""
        user_id = ctx.author.id
        self.cog.user_contexts[user_id] = new_context
        await ctx.send(f"Ustawiono nowy kontekst dla użytkownika {ctx.author.name}")

    async def _context_slash(self, interaction, new_context):
        """Implementacja slash komendy ustawiania kontekstu"""
        user_id = interaction.user.id
        self.cog.user_contexts[user_id] = new_context
        await interaction.response.send_message(
            f"Ustawiono nowy kontekst dla użytkownika {interaction.user.name}",
            ephemeral=True
        )

    async def _show_context(self, ctx):
        """Implementacja komendy pokazywania kontekstu"""
        user_id = ctx.author.id
        context = self.cog.user_contexts.get(user_id, "Brak ustawionego kontekstu")
        await ctx.send(f"Twój aktualny kontekst:\n{context}")

    async def _show_context_slash(self, interaction):
        """Implementacja slash komendy pokazywania kontekstu"""
        user_id = interaction.user.id
        context = self.cog.user_contexts.get(user_id, "Brak ustawionego kontekstu")
        await interaction.response.send_message(f"Twój aktualny kontekst:\n{context}", ephemeral=True)

    async def _change_model(self, ctx, model_name):
        """Implementacja komendy zmiany modelu"""
        old_model = self.cog.ollama_model
        self.cog.ollama_model = model_name

        # Sprawdź czy model istnieje i pobierz go jeśli nie
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                model_names = [model.get("name") for model in available_models]

                if model_name not in model_names:
                    await ctx.send(f"Model {model_name} nie jest zainstalowany. Rozpoczynam pobieranie...")

                    # Użyj subprocess do pobrania modelu w tle
                    subprocess.Popen(["ollama", "pull", model_name])
                    await ctx.send(f"Pobieranie modelu {model_name} rozpoczęte w tle. Może to potrwać kilka minut.")
                else:
                    await ctx.send(f"Zmieniono model z {old_model} na {model_name}.")
            else:
                await ctx.send("Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.")
        except Exception as e:
            await ctx.send(f"Błąd podczas zmiany modelu: {str(e)}")
            self.cog.ollama_model = old_model  # Przywróć poprzedni model

    async def _change_model_slash(self, interaction, model_name):
        """Implementacja slash komendy zmiany modelu"""
        old_model = self.cog.ollama_model
        self.cog.ollama_model = model_name

        # Sprawdź czy model istnieje i pobierz go jeśli nie
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                model_names = [model.get("name") for model in available_models]

                if model_name not in model_names:
                    await interaction.response.send_message(
                        f"Model {model_name} nie jest zainstalowany. Rozpoczynam pobieranie...", ephemeral=False)

                    # Użyj subprocess do pobrania modelu w tle
                    subprocess.Popen(["ollama", "pull", model_name])
                    await interaction.followup.send(
                        f"Pobieranie modelu {model_name} rozpoczęte w tle. Może to potrwać kilka minut.")
                else:
                    await interaction.response.send_message(f"Zmieniono model z {old_model} na {model_name}.",
                                                            ephemeral=False)
            else:
                await interaction.response.send_message(
                    "Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Błąd podczas zmiany modelu: {str(e)}", ephemeral=True)
            self.cog.ollama_model = old_model  # Przywróć poprzedni model

    async def _summarize(self, ctx):
        """Implementacja komendy podsumowania"""
        user_id = ctx.author.id
        if user_id not in self.cog.transcriptions:
            await ctx.send("Nie znaleziono transkrypcji do podsumowania!")
            return

        transcriptions = self.cog.transcriptions[user_id]

        if isinstance(transcriptions, str):
            # Jeśli to pojedyncza transkrypcja (stary format)
            await ctx.send("Generuję podsumowanie...")
            summary = await self.cog.summarize_with_ollama(transcriptions)
            await ctx.send(f"**Podsumowanie:**\n{summary}")
        else:
            # Jeśli to słownik transkrypcji po użytkownikach
            await ctx.send("Generuję podsumowania dla każdego użytkownika...")

            for user_id, transcription in transcriptions.items():
                username = self.cog.get_username_by_id(user_id)
                await ctx.send(f"Generuję podsumowanie dla {username}...")
                summary = await self.cog.summarize_with_ollama(transcription)
                await ctx.send(f"**Podsumowanie dla {username}:**\n{summary}")

    async def _summarize_slash(self, interaction):
        """Implementacja slash komendy podsumowania"""
        user_id = interaction.user.id
        if user_id not in self.cog.transcriptions:
            await interaction.response.send_message("Nie znaleziono transkrypcji do podsumowania!", ephemeral=True)
            return

        transcriptions = self.cog.transcriptions[user_id]

        if isinstance(transcriptions, str):
            # Jeśli to pojedyncza transkrypcja (stary format)
            await interaction.response.send_message("Generuję podsumowanie...", ephemeral=False)
            summary = await self.cog.summarize_with_ollama(transcriptions)
            await interaction.followup.send(f"**Podsumowanie:**\n{summary}")
        else:
            # Jeśli to słownik transkrypcji po użytkownikach
            await interaction.response.send_message("Generuję podsumowania dla każdego użytkownika...", ephemeral=False)

            for user_id, transcription in transcriptions.items():
                username = self.cog.get_username_by_id(user_id)
                await interaction.followup.send(f"Generuję podsumowanie dla {username}...")
                summary = await self.cog.summarize_with_ollama(transcription)
                await interaction.followup.send(f"**Podsumowanie dla {username}:**\n{summary}")

    async def _list_models(self, ctx):
        """Implementacja komendy listowania modeli"""
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                if not available_models:
                    await ctx.send("Brak dostępnych modeli Ollama.")
                    return

                model_info = []
                for model in available_models:
                    name = model.get("name", "Nieznany")
                    size = model.get("size", 0) / (1024 * 1024 * 1024)  # Konwersja na GB
                    model_info.append(f"• {name} ({size:.2f} GB)")

                await ctx.send("**Dostępne modele Ollama:**\n" + "\n".join(model_info))
                await ctx.send(f"Aktualnie używany model: **{self.cog.ollama_model}**")
            else:
                await ctx.send("Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.")
        except Exception as e:
            await ctx.send(f"Błąd podczas pobierania listy modeli: {str(e)}")

    async def _list_models_slash(self, interaction):
        """Implementacja slash komendy listowania modeli"""
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                if not available_models:
                    await interaction.response.send_message("Brak dostępnych modeli Ollama.", ephemeral=True)
                    return

                model_info = []
                for model in available_models:
                    name = model.get("name", "Nieznany")
                    size = model.get("size", 0) / (1024 * 1024 * 1024)  # Konwersja na GB
                    model_info.append(f"• {name} ({size:.2f} GB)")

                await interaction.response.send_message("**Dostępne modele Ollama:**\n" + "\n".join(model_info),
                                                        ephemeral=False)
                await interaction.followup.send(f"Aktualnie używany model: **{self.cog.ollama_model}**")
            else:
                await interaction.response.send_message(
                    "Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Błąd podczas pobierania listy modeli: {str(e)}", ephemeral=True)

    async def _help(self, ctx, command_name=None):
        """Implementacja komendy pomocy"""
        if command_name:
            # Szukaj podanej komendy
            command = self.bot.get_command(command_name)
            if command:
                embed = discord.Embed(
                    title=f"Pomoc dla komendy: {command.name}",
                    description=command.help or "Brak opisu dla tej komendy.",
                    color=discord.Color.blue()
                )

                # Dodaj składnię komendy
                syntax = f"{self.bot.command_prefix}{command.name}"
                if command.signature:
                    syntax += f" {command.signature}"
                embed.add_field(name="Składnia", value=f"`{syntax}`", inline=False)

                # Dodaj informację o slash komendzie
                embed.add_field(name="Slash komenda", value=f"Ta komenda jest również dostępna jako `/{command.name}`",
                                inline=False)

                await ctx.send(embed=embed)
            else:
                await ctx.send(
                    f"❌ Nie znaleziono komendy `{command_name}`. Użyj `!help` lub `/help` aby zobaczyć dostępne komendy.")
        else:
            # Pokaż wszystkie komendy
            embed = discord.Embed(
                title="Lista dostępnych komend",
                description=f"Możesz użyć zarówno prefixu `{self.bot.command_prefix}` jak i slash komend `/`\nZalecane jest używanie slash komend `/`.",
                color=discord.Color.blue()
            )

            # Podziel komendy na kategorie
            recording_commands = []
            ollama_commands = []
            utility_commands = []

            for command in sorted(self.bot.commands, key=lambda x: x.name):
                if command.name in ['record_user', 'record_all', 'stop']:
                    recording_commands.append(f"`{command.name}`")
                elif command.name in ['change_model', 'summarize', 'list_models']:
                    ollama_commands.append(f"`{command.name}`")
                else:
                    utility_commands.append(f"`{command.name}`")

            if recording_commands:
                embed.add_field(
                    name="🎙️ Nagrywanie",
                    value=", ".join(recording_commands),
                    inline=False
                )

            if ollama_commands:
                embed.add_field(
                    name="🤖 Ollama i przetwarzanie",
                    value=", ".join(ollama_commands),
                    inline=False
                )

            if utility_commands:
                embed.add_field(
                    name="🛠️ Pozostałe",
                    value=", ".join(utility_commands),
                    inline=False
                )

            await ctx.send(embed=embed)

    async def _help_slash(self, interaction, command=None):
        """Implementacja slash komendy pomocy"""
        if command:
            # Szukaj podanej komendy
            cmd = self.bot.get_command(command)
            if cmd:
                embed = discord.Embed(
                    title=f"Pomoc dla komendy: {cmd.name}",
                    description=cmd.help or "Brak opisu dla tej komendy.",
                    color=discord.Color.blue()
                )

                # Dodaj składnię komendy
                syntax = f"/{cmd.name}"
                if cmd.signature:
                    params = cmd.signature.strip()
                    if params:
                        syntax += f" {params}"
                embed.add_field(name="Składnia", value=f"`{syntax}`", inline=False)

                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"❌ Nie znaleziono komendy `{command}`. Użyj `/help` bez argumentu aby zobaczyć dostępne komendy.",
                    ephemeral=True
                )
        else:
            # Pokaż wszystkie komendy
            embed = discord.Embed(
                title="Lista dostępnych komend",
                description="Wszystkie komendy są dostępne jako slash komendy zaczynające się od `/`",
                color=discord.Color.blue()
            )

            # Podziel komendy na kategorie
            recording_commands = []
            ollama_commands = []
            utility_commands = []

            # Sprawdź dostępne slash komendy
            for cmd_name in ['record_user', 'record_all', 'stop']:
                recording_commands.append(f"`/{cmd_name}`")

            for cmd_name in ['change_model', 'summarize', 'list_models']:
                ollama_commands.append(f"`/{cmd_name}`")

            for cmd_name in ['help', 'context', 'show_context']:
                utility_commands.append(f"`/{cmd_name}`")

            if recording_commands:
                embed.add_field(
                    name="🎙️ Nagrywanie",
                    value=", ".join(recording_commands),
                    inline=False
                )

            if ollama_commands:
                embed.add_field(
                    name="🤖 Ollama i przetwarzanie",
                    value=", ".join(ollama_commands),
                    inline=False
                )

            if utility_commands:
                embed.add_field(
                    name="🛠️ Pozostałe",
                    value=", ".join(utility_commands),
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)