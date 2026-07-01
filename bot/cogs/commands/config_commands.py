#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from typing import Optional

import discord
from discord import app_commands

import sys
sys.path.append('../..')
from config import BotConfig


class ConfigCommands:
    def __init__(self, audio_recorder):
        self.cog = audio_recorder
        self.bot = audio_recorder.bot
        self.register_commands()
        self.register_slash_commands()

    def _check_password(self, password):
        expected = BotConfig.CONFIG_PASSWORD
        if not expected:
            return False, "Komenda /config jest wyłączona (brak CONFIG_PASSWORD w .env)."
        if password != expected:
            return False, "❌ Błędne hasło."
        return True, None

    def _render(self):
        cfg = self.cog.get_config()
        lines = ["⚙️ **Aktualna konfiguracja:**"]
        for k, v in cfg.items():
            lines.append(f"• `{k}` = `{v}`")
        lines.append("\nZmiana: `/config <hasło> set <klucz> <wartość>`")
        return "\n".join(lines)

    # ------------------------------------------------------------------- prefix
    def register_commands(self):
        @self.bot.command(name="config")
        async def config_cmd(ctx, password: str = None, action: str = "show",
                             key: str = None, *, value: str = None):
            """Konfiguracja bota (wymaga hasła): show | set <klucz> <wartość>"""
            # Skasuj wiadomość z hasłem (jeśli bot ma uprawnienia).
            try:
                await ctx.message.delete()
            except Exception:
                pass

            ok, err = self._check_password(password)
            if not ok:
                await ctx.send(err)
                return

            action = (action or "show").lower()
            if action == "show":
                await ctx.send(self._render())
            elif action == "set":
                if not key or value is None:
                    await ctx.send("Użycie: `!config <hasło> set <klucz> <wartość>`")
                    return
                good, msg = self.cog.set_config(key, value)
                await ctx.send(("✅ " if good else "❌ ") + msg)
            else:
                await ctx.send("Akcja: `show` albo `set <klucz> <wartość>`")

    # -------------------------------------------------------------------- slash
    def register_slash_commands(self):
        @self.bot.tree.command(name="config", description="Konfiguracja bota (wymaga hasła)")
        @app_commands.describe(
            password="Hasło konfiguracji (z .env)",
            action="show = pokaż, set = ustaw",
            key="Klucz do ustawienia (dla set)",
            value="Nowa wartość (dla set)",
        )
        @app_commands.choices(action=[
            app_commands.Choice(name="show (pokaż ustawienia)", value="show"),
            app_commands.Choice(name="set (ustaw wartość)", value="set"),
        ])
        async def config_slash(interaction: discord.Interaction,
                               password: str,
                               action: Optional[app_commands.Choice[str]] = None,
                               key: Optional[str] = None,
                               value: Optional[str] = None):
            # Ephemeral - widoczne tylko dla wywołującego (chroni hasło i ustawienia).
            await interaction.response.defer(ephemeral=True)
            ok, err = self._check_password(password)
            if not ok:
                await interaction.followup.send(err, ephemeral=True)
                return

            act = action.value if action else "show"
            if act == "show":
                await interaction.followup.send(self._render(), ephemeral=True)
            elif act == "set":
                if not key or value is None:
                    await interaction.followup.send(
                        "Dla `set` podaj `key` i `value`.", ephemeral=True)
                    return
                good, msg = self.cog.set_config(key, value)
                await interaction.followup.send(("✅ " if good else "❌ ") + msg, ephemeral=True)
