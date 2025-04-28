#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import traceback

def register_error_handlers(bot):
    """Rejestruje wszystkie uchwyty błędów dla bota"""

    # Obsługa błędów slash komend
    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandNotFound):
            await interaction.response.send_message(
                "❌ Nie znaleziono tej komendy slash. Użyj `/help` aby zobaczyć dostępne komendy.",
                ephemeral=True
            )
        else:
            # Zapisz szczegóły błędu do logów
            error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            print(f"Błąd w slash komendzie: {error_traceback}")

            try:
                await interaction.response.send_message(
                    f"❌ Wystąpił błąd: {str(error)}",
                    ephemeral=True
                )
            except:
                await interaction.followup.send(
                    f"❌ Wystąpił błąd: {str(error)}",
                    ephemeral=True
                )


    # Obsługa błędów dla zwykłych komend
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(f"❌ Nieznana komenda: `{ctx.message.content}`. Użyj `/help` aby zobaczyć dostępne komendy.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"❌ Brakujący argument: {error.param.name}. Użyj `/help {ctx.command.name}` aby sprawdzić poprawną składnię.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Nieprawidłowy argument. Użyj `/help {ctx.command.name}` aby sprawdzić poprawną składnię.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"❌ Nie znaleziono użytkownika. Sprawdź czy nazwa użytkownika jest poprawna.")
        else:
            await ctx.send(f"❌ Wystąpił błąd: {str(error)}")
            # Zapisz szczegóły błędu do logów
            error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            print(f"Błąd w komendzie: {error_traceback}")