#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio

import discord
from discord import app_commands
from typing import Optional
import sys
sys.path.append('../..')
from consts import Consts
from utils.ApiController import ApiController

# Struktura pomocy: (kategoria, [(składnia, opis), ...])
HELP_SECTIONS = [
    ("🎙️ Nagrywanie", [
        ("/auto [kanał]", "Wprowadza bota na kanał (stały nasłuch, auto-nagrywanie)."),
        ("/leave", "Wyłącza bota z kanału (kończy tryb auto)."),
        ("/record_user [użytkownik]", "Przechodzi na Twój kanał i nagrywa tę osobę."),
        ("/record_all", "Przechodzi na Twój kanał i nagrywa wszystkich."),
        ("/stop", "Kończy nagrywanie, przetwarza i wraca na kanał domowy."),
    ]),
    ("🎧 Nagrania", [
        ("/recordings [strona]", "Lista nagrań: nazwa, audio, transkrypcja, podsumowania (◀ ▶)."),
        ("/summarize <cel>", "Generuje podsumowanie. cel: ID • all • indeks `2` • przedział `1-3`."),
        ("/rename <cel> <nazwa>", "Zmienia nazwę nagrania."),
        ("/delete <cel> [zakres]", "Usuwa. zakres: `all` (całość) • `audio` • `summary`."),
    ]),
    ("🤖 Ollama", [
        ("/change_model <model>", "Zmienia model używany do podsumowań."),
        ("/list_models", "Pokazuje modele dostępne w Ollamie."),
    ]),
    ("⚙️ Konfiguracja", [
        ("/config <hasło> show", "Pokazuje ustawienia (odpowiedź prywatna)."),
        ("/config <hasło> set <klucz> <wartość>", "Zmienia ustawienie w locie (np. silence_timeout_min, silence_rms_threshold, ollama_model)."),
    ]),
    ("🛠️ Pozostałe", [
        ("/context <tekst>", "Ustawia Twój kontekst (poprawia jakość podsumowań)."),
        ("/show_context", "Pokazuje Twój aktualny kontekst."),
        ("/help [komenda]", "Ta pomoc, albo szczegóły wybranej komendy."),
    ]),
]


def build_help_embed(prefix="/"):
    """Buduje embed z pełną listą komend (składnia + opis)."""
    embed = discord.Embed(
        title="📖 Dostępne komendy",
        description=(
            f"Każda komenda działa jako slash (`/`) oraz z prefixem (`{prefix}`).\n"
            "Zalecane są slash komendy `/`."
        ),
        color=discord.Color.blue(),
    )
    for category, items in HELP_SECTIONS:
        value = "\n".join(f"**`{syntax}`**\n{desc}" for syntax, desc in items)
        embed.add_field(name=category, value=value, inline=False)
    return embed


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
            await self._show_context(ctx)

        @self.bot.command()
        async def change_model(ctx, model_name):
            """Zmienia model Ollama używany do podsumowań"""
            await ctx.send(Consts.CHANGE_MODEL)
            await self._change_model(ctx, model_name)

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

    async def _model_names(self):
        """Zwraca listę nazw modeli dostępnych na serwerze Ollama."""
        models = await asyncio.to_thread(ApiController.list_ollama_models)
        return [m.get("name") for m in models if m.get("name")]

    async def _change_model(self, ctx, model_name):
        """Implementacja komendy zmiany modelu"""
        old_model = self.cog.ollama_model
        try:
            model_names = await self._model_names()
            if model_name not in model_names:
                await ctx.send(
                    f"Model {model_name} nie jest dostępny na serwerze Ollama. "
                    f"Pobierz go na serwerze: `ollama pull {model_name}`."
                )
                return
            self.cog.ollama_model = model_name
            await ctx.send(f"Zmieniono model z {old_model} na {model_name}.")
        except Exception as e:
            await ctx.send(f"Błąd podczas zmiany modelu: {str(e)}")

    async def _change_model_slash(self, interaction, model_name):
        """Implementacja slash komendy zmiany modelu"""
        await interaction.response.defer(ephemeral=False)
        old_model = self.cog.ollama_model
        try:
            model_names = await self._model_names()
            if model_name not in model_names:
                await interaction.followup.send(
                    f"Model {model_name} nie jest dostępny na serwerze Ollama. "
                    f"Pobierz go na serwerze: `ollama pull {model_name}`."
                )
                return
            self.cog.ollama_model = model_name
            await interaction.followup.send(f"Zmieniono model z {old_model} na {model_name}.")
        except Exception as e:
            await interaction.followup.send(f"Błąd podczas zmiany modelu: {str(e)}")

    @staticmethod
    def _format_models(models):
        lines = []
        for model in models:
            name = model.get("name", "Nieznany")
            size = model.get("size", 0) / (1024 * 1024 * 1024)  # GB
            lines.append(f"• {name} ({size:.2f} GB)")
        return lines

    async def _list_models(self, ctx):
        """Implementacja komendy listowania modeli"""
        try:
            models = await asyncio.to_thread(ApiController.list_ollama_models)
            if not models:
                await ctx.send("Brak dostępnych modeli Ollama.")
                return
            await ctx.send("**Dostępne modele Ollama:**\n" + "\n".join(self._format_models(models)))
            await ctx.send(f"Aktualnie używany model: **{self.cog.ollama_model}**")
        except Exception as e:
            await ctx.send(f"Błąd podczas pobierania listy modeli: {str(e)}")

    async def _list_models_slash(self, interaction):
        """Implementacja slash komendy listowania modeli"""
        await interaction.response.defer(ephemeral=False)
        try:
            models = await asyncio.to_thread(ApiController.list_ollama_models)
            if not models:
                await interaction.followup.send("Brak dostępnych modeli Ollama.")
                return
            await interaction.followup.send(
                "**Dostępne modele Ollama:**\n" + "\n".join(self._format_models(models))
            )
            await interaction.followup.send(f"Aktualnie używany model: **{self.cog.ollama_model}**")
        except Exception as e:
            await interaction.followup.send(f"Błąd podczas pobierania listy modeli: {str(e)}")

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
            await ctx.send(embed=build_help_embed(self.bot.command_prefix))

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
            await interaction.response.send_message(
                embed=build_help_embed(self.bot.command_prefix), ephemeral=True
            )