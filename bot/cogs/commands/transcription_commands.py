#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import datetime
from typing import Optional

import discord
from discord import app_commands

PAGE_SIZE = 5


async def send_chunks(send, text, header=None):
    """Wysyła długi tekst w kawałkach po 1900 znaków (limit Discorda)."""
    if header:
        await send(header)
    text = text or "(pusto)"
    for i in range(0, len(text), 1900):
        await send(text[i:i + 1900])


def _fmt_date(iso):
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso or "?"


def build_pages(sessions):
    """Buduje listę embedów (po PAGE_SIZE sesji), od najnowszej do najstarszej."""
    pages = []
    total = len(sessions)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    for start in range(0, total, PAGE_SIZE):
        chunk = sessions[start:start + PAGE_SIZE]
        embed = discord.Embed(
            title="📜 Transkrypcje (od najnowszej)",
            color=discord.Color.blue(),
        )
        for i, s in enumerate(chunk, start=start + 1):
            names = ", ".join(p["display_name"] for p in s.get("participants", [])) or "-"
            has_audio = any(t.get("audio_file") for t in s.get("transcripts", {}).values())
            summaries = len(s.get("summaries", []))
            embed.add_field(
                name=f"#{i} · {s['id']}",
                value=(
                    f"🕑 {_fmt_date(s.get('created_at'))}\n"
                    f"👥 {names}\n"
                    f"🎧 audio: {'tak' if has_audio else 'nie'} · 📝 podsumowania: {summaries}"
                ),
                inline=False,
            )
        embed.set_footer(text=f"Strona {start // PAGE_SIZE + 1}/{total_pages} · łącznie {total}")
        pages.append(embed)
    return pages


class Paginator(discord.ui.View):
    """Prosty paginator z przyciskami ◀ ▶ (tylko dla autora komendy)."""

    def __init__(self, pages, author_id, start_index=0, timeout=180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.index = max(0, min(start_index, len(pages) - 1))
        self._sync()

    def _sync(self):
        # children[0] = prev, children[1] = next (kolejność deklaracji)
        self.children[0].disabled = self.index <= 0
        self.children[1].disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("To nie jest Twoja lista.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)


class TranscriptionCommands:
    def __init__(self, audio_recorder):
        self.cog = audio_recorder
        self.bot = audio_recorder.bot
        self.store = audio_recorder.store

        self.register_commands()
        self.register_slash_commands()

    # --------------------------------------------------------------- rejestracja
    def register_commands(self):
        @self.bot.command(name="transcriptions")
        async def transcriptions(ctx, page: int = 1):
            """Lista transkrypcji z paginacją"""
            await self._list(ctx, ctx.author.id, page)

        @self.bot.command(name="summarize")
        async def summarize(ctx, target: str = "all"):
            """Podsumuj transkrypcję: <ID> | all | <start>-<end>"""
            await self._summarize(ctx, ctx.send, ctx.author.id, target)

        @self.bot.command(name="delete")
        async def delete(ctx, target: str):
            """Usuń transkrypcję: <ID> | <start>-<end> | <indeks>"""
            await self._delete(ctx, ctx.send, target)

    def register_slash_commands(self):
        @self.bot.tree.command(name="transcriptions", description="Lista transkrypcji (od najnowszej) z paginacją")
        @app_commands.describe(page="Numer strony (opcjonalnie)")
        async def transcriptions_slash(interaction: discord.Interaction, page: Optional[int] = 1):
            await interaction.response.defer(ephemeral=False)
            await self._list_slash(interaction, page or 1)

        @self.bot.tree.command(name="summarize", description="Podsumuj transkrypcję: ID, all lub przedział indeksów")
        @app_commands.describe(target="ID transkrypcji, 'all', albo przedział np. 1-3")
        async def summarize_slash(interaction: discord.Interaction, target: str = "all"):
            await interaction.response.defer(ephemeral=False)
            await self._summarize(interaction, interaction.followup.send, interaction.user.id, target)

        @self.bot.tree.command(name="delete", description="Usuń transkrypcję: ID, indeks lub przedział indeksów")
        @app_commands.describe(target="ID transkrypcji, indeks np. 2, albo przedział np. 1-3")
        async def delete_slash(interaction: discord.Interaction, target: str):
            await interaction.response.defer(ephemeral=False)
            await self._delete(interaction, interaction.followup.send, target)

    # -------------------------------------------------------------------- logika
    async def _list(self, ctx, author_id, page):
        sessions = await asyncio.to_thread(self.store.list_sessions)
        if not sessions:
            await ctx.send("Brak zapisanych transkrypcji.")
            return
        pages = build_pages(sessions)
        start = max(0, min(page - 1, len(pages) - 1))
        view = Paginator(pages, author_id, start_index=start)
        await ctx.send(embed=pages[start], view=view)

    async def _list_slash(self, interaction, page):
        sessions = await asyncio.to_thread(self.store.list_sessions)
        if not sessions:
            await interaction.followup.send("Brak zapisanych transkrypcji.")
            return
        pages = build_pages(sessions)
        start = max(0, min(page - 1, len(pages) - 1))
        view = Paginator(pages, interaction.user.id, start_index=start)
        await interaction.followup.send(embed=pages[start], view=view)

    async def _summarize(self, ctx_or_inter, send, requester_id, target):
        targets = await asyncio.to_thread(self.store.resolve_targets, target)
        if not targets:
            await send(
                f"Nie znaleziono transkrypcji dla: `{target}`. "
                f"Podaj ID, `all`, indeks lub przedział (np. `1-3`)."
            )
            return

        await send(f"Generuję podsumowanie dla {len(targets)} transkrypcji...")
        for s in targets:
            summary = await self.cog.summarize_session(s, requester_id=requester_id, label="manual")
            if summary:
                names = ", ".join(p["display_name"] for p in s.get("participants", [])) or "-"
                await send_chunks(send, summary, header=f"**Podsumowanie {s['id']}** ({names}):")
            else:
                await send(f"Transkrypcja `{s['id']}` jest pusta - pomijam.")

    async def _delete(self, ctx_or_inter, send, target):
        targets = await asyncio.to_thread(self.store.resolve_targets, target)
        if not targets:
            await send(
                f"Nie znaleziono transkrypcji dla: `{target}`. "
                f"Podaj ID, indeks lub przedział (np. `1-3`)."
            )
            return

        deleted = []
        for s in targets:
            ok = await asyncio.to_thread(self.store.delete_session, s["id"])
            if ok:
                deleted.append(s["id"])
        await send(
            f"Usunięto {len(deleted)} transkrypcji"
            + (f": {', '.join(deleted)}" if deleted else ".")
        )
