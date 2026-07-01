#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import datetime
from typing import Optional

import discord
from discord import app_commands

PAGE_SIZE = 5


async def send_chunks(send, text, header=None):
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


def build_pages(store, sessions):
    """Buduje listę embedów (po PAGE_SIZE nagrań), od najnowszego."""
    pages = []
    total = len(sessions)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    for start in range(0, total, PAGE_SIZE):
        chunk = sessions[start:start + PAGE_SIZE]
        embed = discord.Embed(title="🎧 Nagrania (od najnowszego)", color=discord.Color.blue())
        for i, s in enumerate(chunk, start=start + 1):
            names = ", ".join(p["display_name"] for p in s.get("participants", [])) or "-"
            audio = "tak" if store.has_audio(s) else "nie"
            transcript = "jest" if store.has_transcript(s) else "brak"
            summaries = len(s.get("summaries", []))
            title = s.get("name") or "(bez nazwy)"
            embed.add_field(
                name=f"#{i} · {title}",
                value=(
                    f"🆔 `{s['id']}`\n"
                    f"🕑 {_fmt_date(s.get('created_at'))} · 👥 {names}\n"
                    f"🎧 audio: {audio} · 📝 transkrypcja: {transcript} · 🧠 podsumowania: {summaries}"
                ),
                inline=False,
            )
        embed.set_footer(text=f"Strona {start // PAGE_SIZE + 1}/{total_pages} · łącznie {total}")
        pages.append(embed)
    return pages


class Paginator(discord.ui.View):
    def __init__(self, pages, author_id, start_index=0, timeout=180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.index = max(0, min(start_index, len(pages) - 1))
        self._sync()

    def _sync(self):
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
        @self.bot.command(name="recordings")
        async def recordings(ctx, page: int = 1):
            """Lista nagrań (audio + transkrypcja + podsumowania)"""
            await self._list(ctx.send, ctx.author.id, page)

        @self.bot.command(name="summarize")
        async def summarize(ctx, target: str = "all"):
            """Generuje podsumowanie: <ID> | all | indeks | przedział"""
            await self._summarize(ctx.send, ctx.author.id, target)

        @self.bot.command(name="rename")
        async def rename(ctx, target: str, *, name: str):
            """Zmienia nazwę nagrania: <ID|indeks> <nowa nazwa>"""
            await self._rename(ctx.send, target, name)

        @self.bot.command(name="delete")
        async def delete(ctx, target: str, scope: str = "all"):
            """Usuwa nagranie/element: <cel> [all|audio|summary]"""
            await self._delete(ctx.send, target, scope)

    def register_slash_commands(self):
        @self.bot.tree.command(name="recordings", description="Lista nagrań (audio + transkrypcja + podsumowania)")
        @app_commands.describe(page="Numer strony (opcjonalnie)")
        async def recordings_slash(interaction: discord.Interaction, page: Optional[int] = 1):
            await interaction.response.defer(ephemeral=False)
            await self._list(interaction.followup.send, interaction.user.id, page or 1)

        @self.bot.tree.command(name="summarize", description="Generuje podsumowanie: ID, all, indeks lub przedział")
        @app_commands.describe(target="ID nagrania, 'all', indeks (np. 2) lub przedział (np. 1-3)")
        async def summarize_slash(interaction: discord.Interaction, target: str = "all"):
            await interaction.response.defer(ephemeral=False)
            await self._summarize(interaction.followup.send, interaction.user.id, target)

        @self.bot.tree.command(name="rename", description="Zmienia nazwę nagrania")
        @app_commands.describe(target="ID nagrania lub indeks", name="Nowa nazwa")
        async def rename_slash(interaction: discord.Interaction, target: str, name: str):
            await interaction.response.defer(ephemeral=False)
            await self._rename(interaction.followup.send, target, name)

        @self.bot.tree.command(name="delete", description="Usuwa nagranie lub jego element")
        @app_commands.describe(
            target="ID nagrania, indeks (np. 2) lub przedział (np. 1-3)",
            scope="Co usunąć: all (całość), audio, summary",
        )
        @app_commands.choices(scope=[
            app_commands.Choice(name="all (całe nagranie)", value="all"),
            app_commands.Choice(name="audio", value="audio"),
            app_commands.Choice(name="summary (podsumowania)", value="summary"),
        ])
        async def delete_slash(interaction: discord.Interaction, target: str,
                               scope: Optional[app_commands.Choice[str]] = None):
            await interaction.response.defer(ephemeral=False)
            await self._delete(interaction.followup.send, target, scope.value if scope else "all")

    # -------------------------------------------------------------------- logika
    async def _list(self, send, author_id, page):
        sessions = await asyncio.to_thread(self.store.list_sessions)
        if not sessions:
            await send("Brak zapisanych nagrań.")
            return
        pages = build_pages(self.store, sessions)
        start = max(0, min(page - 1, len(pages) - 1))
        await send(embed=pages[start], view=Paginator(pages, author_id, start_index=start))

    async def _summarize(self, send, requester_id, target):
        targets = await asyncio.to_thread(self.store.resolve_targets, target)
        if not targets:
            await send(f"Nie znaleziono nagrania dla: `{target}` (podaj ID, `all`, indeks lub przedział).")
            return
        await send(f"Generuję podsumowanie dla {len(targets)} nagrań...")
        for s in targets:
            summary = await self.cog.summarize_session(s, requester_id=requester_id, label="manual")
            if summary:
                names = ", ".join(p["display_name"] for p in s.get("participants", [])) or "-"
                await send_chunks(send, summary, header=f"**Podsumowanie {s['id']}** ({names}):")
            else:
                await send(f"Nagranie `{s['id']}` nie ma transkrypcji - pomijam.")

    async def _rename(self, send, target, name):
        targets = await asyncio.to_thread(self.store.resolve_targets, target)
        if not targets:
            await send(f"Nie znaleziono nagrania dla: `{target}`.")
            return
        s = targets[0]
        await asyncio.to_thread(self.store.set_name, s["id"], name)
        extra = f" (dopasowano {len(targets)}, zmieniono pierwsze)" if len(targets) > 1 else ""
        await send(f"✏️ Zmieniono nazwę `{s['id']}` na: **{name}**{extra}")

    async def _delete(self, send, target, scope):
        scope = (scope or "all").lower()
        valid = {"all", "audio", "summary", "podsumowanie", "podsumowania", "całość", "nagranie"}
        if scope not in valid:
            await send(f"Nieznany zakres: `{scope}`. Użyj: `all` | `audio` | `summary`.")
            return
        targets = await asyncio.to_thread(self.store.resolve_targets, target)
        if not targets:
            await send(f"Nie znaleziono nagrania dla: `{target}`.")
            return

        done = []
        for s in targets:
            sid = s["id"]
            if scope == "audio":
                ok = await asyncio.to_thread(self.store.delete_audio, sid)
                label = "audio"
            elif scope in ("summary", "podsumowanie", "podsumowania"):
                ok = await asyncio.to_thread(self.store.delete_summaries, sid)
                label = "podsumowania"
            else:
                ok = await asyncio.to_thread(self.store.delete_session, sid)
                label = "całe nagranie"
            if ok:
                done.append(sid)
        await send(f"🗑️ Usunięto ({label}) dla {len(done)}: {', '.join(done) if done else '-'}")
