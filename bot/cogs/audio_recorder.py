#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import wave
import asyncio
import datetime
import traceback

import discord
from discord.ext import commands, tasks, voice_recv

from config import BotConfig
from cogs.commands_loader import register_all_commands
from utils.ApiController import ApiController, ModelType
from utils.audio_sink import PerUserPCMSink
from utils.storage import TranscriptionStore


class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Stan silnika: idle | auto | manual
        self.mode = "idle"
        self.home_channel_id = BotConfig.VOICE_CHANNEL_ID  # kanał "domowy" trybu auto
        self.current_channel = None
        self.voice_client = None
        self.sink = None
        self.guild = None
        self.manual_only_users = None       # ograniczenie dla /record_user
        self._proc_lock = asyncio.Lock()   # serializuje flush i finalize
        self._auto_started = False
        self._auto_announced = False  # czy ogłoszono start bieżącej sesji auto

        # Przyrostowe przetwarzanie sesji (aby nie trzymać całości w pamięci):
        self._flush_lines = []       # [(start_dt, display, text)]
        self._flush_audio_raw = {}   # uid -> ścieżka pliku .pcm (surowe audio)
        self._flush_display = {}      # uid -> display_name
        self._session_ts = None       # znacznik do nazw plików
        self._session_started_dt = None

        # „Żywa" transkrypcja - jedna wiadomość na czacie kanału, edytowana
        # w miejscu w miarę transkrybowania kolejnych wypowiedzi.
        self._live_msg = None        # aktualnie edytowana wiadomość
        self._live_buf = ""          # jej bieżąca treść
        self._live_first = True      # czy to pierwsza wiadomość sesji (nagłówek)
        self._live_last_placeholder = False  # ostatnia linia to znacznik "----"?

        ApiController.set_base_url(BotConfig.API_URL)

        self.user_contexts = {}

        # --- Ustawienia edytowalne w locie przez /config -------------------
        self.ollama_model = BotConfig.OLLAMA_DEFAULT_MODEL
        self.silence_timeout_min = BotConfig.SILENCE_TIMEOUT_MIN
        self.silence_rms_threshold = BotConfig.SILENCE_RMS_THRESHOLD
        self.result_channel_id = BotConfig.RESULT_CHANNEL_ID
        self.audio_retention_days = BotConfig.AUDIO_RETENTION_DAYS

        self.recordings_dir = BotConfig.RECORDINGS_DIR
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings: {self.recordings_dir}")

        self.store = TranscriptionStore(
            base_dir=BotConfig.DATA_DIR,
            recordings_dir=self.recordings_dir,
            audio_retention_days=self.audio_retention_days,
        )
        # Wczytaj zapisane nadpisania ustawień (jeśli są).
        self._load_runtime_config()
        print(f"Magazyn danych: {BotConfig.DATA_DIR} (audio: {self.audio_retention_days} dni)")

        self.check_services()
        register_all_commands(self)

    # =======================================================================
    #  Cykl życia cog-a
    # =======================================================================
    async def cog_load(self):
        try:
            removed = await asyncio.to_thread(self.store.prune_audio)
            if removed:
                print(f"Usunięto {len(removed)} starych plików audio.")
        except Exception as e:  # noqa: BLE001
            print(f"Błąd czyszczenia audio: {e}")
        if not self.audio_cleanup_loop.is_running():
            self.audio_cleanup_loop.start()

    def cog_unload(self):
        self.audio_cleanup_loop.cancel()
        self.monitor_loop.cancel()
        self.flush_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Automatyczne dołączenie do kanału domowego, jeśli włączony tryb auto.
        if self._auto_started:
            return
        if BotConfig.AUTO_RECORD and self.home_channel_id:
            ch = self.bot.get_channel(self.home_channel_id)
            if isinstance(ch, discord.VoiceChannel):
                self._auto_started = True
                try:
                    await self.start_auto(ch)
                    print(f"AUTO: dołączono do kanału {ch.name}")
                except Exception as e:  # noqa: BLE001
                    print(f"AUTO: nie udało się dołączyć: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # W trybie auto: gdy kanał opustoszeje, finalizuj szybciej niż pętla.
        if self.mode != "auto" or self.current_channel is None:
            return
        members = [m for m in self.current_channel.members if not m.bot]
        if not members and self.sink and self.sink.has_audio():
            await self.finalize(reason="kanał opustoszał", announce=True)

    @tasks.loop(hours=24)
    async def audio_cleanup_loop(self):
        try:
            removed = await asyncio.to_thread(self.store.prune_audio)
            if removed:
                print(f"[cleanup] Usunięto {len(removed)} starych plików audio.")
        except Exception as e:  # noqa: BLE001
            print(f"[cleanup] Błąd: {e}")

    @tasks.loop(seconds=BotConfig.AUTO_CHECK_INTERVAL_SEC)
    async def monitor_loop(self):
        # Finalizacja w trybie auto: cisza dłuższa niż timeout lub pusty kanał.
        if self.mode != "auto" or self.sink is None or self.current_channel is None:
            return
        try:
            members = [m for m in self.current_channel.members if not m.bot]
            if self._has_session_content():
                # Nowa sesja: ogłoś rozpoczęcie nagrywania na czacie kanału.
                if not self._auto_announced:
                    self._auto_announced = True
                    await self._announce_start()
                timeout = self.silence_timeout_min * 60
                if not members:
                    await self.finalize(reason="kanał opustoszał", announce=True)
                elif self.sink.silent_for() >= timeout:
                    await self.finalize(reason=f"cisza > {self.silence_timeout_min} min", announce=True)
        except Exception as e:  # noqa: BLE001
            print(f"[monitor] Błąd: {e}")

    @tasks.loop(seconds=4)
    async def flush_loop(self):
        # Przyrostowe przetwarzanie zakończonych wypowiedzi (zwalnia pamięć).
        if self.mode == "idle" or self.sink is None:
            return
        try:
            await self._flush_pending()
        except Exception as e:  # noqa: BLE001
            print(f"[flush] Błąd: {e}")

    def _has_session_content(self) -> bool:
        if self._flush_lines or self._flush_audio_raw:
            return True
        return bool(self.sink and self.sink.has_audio())

    # =======================================================================
    #  Połączenie / tryby
    # =======================================================================
    async def _connect(self, channel, gated: bool):
        threshold = self.silence_rms_threshold if gated else 0
        guild = channel.guild
        vc = guild.voice_client
        if vc is None:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
        else:
            if vc.channel != channel:
                await vc.move_to(channel)
            if vc.is_listening():
                vc.stop_listening()
        sink = PerUserPCMSink(rms_threshold=threshold, utterance_gap=BotConfig.UTTERANCE_GAP_SEC)
        vc.listen(sink)
        self.voice_client = vc
        self.sink = sink
        self.guild = guild
        self.current_channel = channel
        return vc, sink

    def _reset_session_state(self):
        self._flush_lines = []
        self._flush_audio_raw = {}
        self._flush_display = {}
        self._session_ts = None
        self._session_started_dt = None
        self._auto_announced = False
        self._live_msg = None
        self._live_buf = ""
        self._live_first = True
        self._live_last_placeholder = False

    async def start_auto(self, channel):
        await self._connect(channel, gated=True)
        self.mode = "auto"
        self.home_channel_id = channel.id
        self.manual_only_users = None
        self._reset_session_state()
        if not self.monitor_loop.is_running():
            self.monitor_loop.start()
        if not self.flush_loop.is_running():
            self.flush_loop.start()

    async def _announce_start(self):
        """Pisze na czacie kanału głosowego, że zaczęło się nagrywanie (tryb auto)."""
        try:
            if self.current_channel is not None:
                await self.current_channel.send("🔴 Wykryłem głos — zaczynam nagrywanie.")
        except Exception as e:  # noqa: BLE001
            print(f"Nie udało się wysłać powiadomienia o starcie: {e}")

    async def start_manual(self, channel, only_users=None):
        await self._connect(channel, gated=False)
        self.mode = "manual"
        self.manual_only_users = set(only_users) if only_users else None
        self._reset_session_state()
        if not self.flush_loop.is_running():
            self.flush_loop.start()

    async def stop_manual(self, send):
        await self.finalize(send=send, reason="/stop", announce=True)
        # Wróć na kanał domowy i wznów auto, jeśli był ustawiony.
        if self.home_channel_id:
            ch = self.bot.get_channel(self.home_channel_id)
            if isinstance(ch, discord.VoiceChannel):
                await self.start_auto(ch)
                return ch
        await self._disconnect()
        return None

    async def leave(self, send=None):
        await self.finalize(send=send, reason="/leave", announce=True)
        await self._disconnect()

    async def _disconnect(self):
        vc = self.voice_client
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
        self.voice_client = None
        self.sink = None
        self.current_channel = None
        self.mode = "idle"
        self.manual_only_users = None

    # =======================================================================
    #  Finalizacja nagrania -> transkrypcja + podsumowanie + nazwa
    # =======================================================================
    def _save_wav(self, frames: bytes, filepath: str):
        with wave.open(filepath, 'wb') as wf:
            wf.setnchannels(BotConfig.AUDIO_CHANNELS)
            wf.setsampwidth(BotConfig.AUDIO_SAMPLE_WIDTH)
            wf.setframerate(BotConfig.AUDIO_SAMPLE_RATE)
            wf.writeframes(frames)

    def _display_name(self, user_id):
        uid = int(user_id)
        member = self.guild.get_member(uid) if self.guild else None
        if member:
            return member.display_name
        user = self.bot.get_user(uid)
        return user.display_name if user else f"Użytkownik-{user_id}"

    def _resolve_send(self, send):
        if send is not None:
            return send
        # Tryb auto: publikuj na czacie tekstowym kanału głosowego.
        if self.current_channel is not None:
            return self.current_channel.send
        # Fallback: wskazany kanał tekstowy wyników.
        if self.result_channel_id:
            ch = self.bot.get_channel(self.result_channel_id)
            if ch is not None:
                return ch.send
        return None

    def _live_channel(self):
        """Kanał, na którego czacie pisze się „żywą" transkrypcję."""
        if self.current_channel is not None:
            return self.current_channel
        if self.result_channel_id:
            return self.bot.get_channel(self.result_channel_id)
        return None

    # Limit treści wiadomości Discord to 2000 znaków - zostawiamy zapas.
    _LIVE_MAX = 1900

    async def _update_live_transcript(self, new_lines):
        """
        Dopisuje świeżo striptowane wypowiedzi do jednej „żywej" wiadomości na
        czacie kanału (edycja w miejscu). Po przekroczeniu limitu Discorda
        otwiera kolejną wiadomość i kontynuuje w niej.
        """
        if not new_lines:
            return
        channel = self._live_channel()
        if channel is None:
            return
        for dt, disp, txt, is_placeholder in sorted(new_lines, key=lambda x: x[0]):
            # Nie powtarzaj znaczników "----" jeden pod drugim (bez zaśmiecania).
            if is_placeholder and self._live_last_placeholder:
                continue
            self._live_last_placeholder = is_placeholder
            line = f"`[{dt:%H:%M:%S}]` **{disp}:** {txt}"
            if len(line) > self._LIVE_MAX:
                line = line[:self._LIVE_MAX]
            need_new = (
                self._live_msg is None
                or len(self._live_buf) + 1 + len(line) > self._LIVE_MAX
            )
            if need_new:
                content = line
                if self._live_first:
                    content = "📝 **Transkrypcja na żywo:**\n" + line
                    self._live_first = False
                try:
                    self._live_msg = await channel.send(content)
                    self._live_buf = content
                except Exception as e:  # noqa: BLE001
                    print(f"[live] Nie udało się wysłać wiadomości: {e}")
                    self._live_msg = None
            else:
                self._live_buf += "\n" + line
                try:
                    await self._live_msg.edit(content=self._live_buf)
                except Exception as e:  # noqa: BLE001
                    print(f"[live] Nie udało się edytować wiadomości: {e}")

    @staticmethod
    async def _send_chunks(send, text, header=None):
        if header:
            await send(header)
        text = text or "(pusto)"
        for i in range(0, len(text), 1900):
            await send(text[i:i + 1900])

    async def _transcribe_pcm(self, pcm) -> str:
        """Transkrybuje pojedynczą wypowiedź (PCM) przez plik tymczasowy."""
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".wav", dir=self.recordings_dir)
        os.close(fd)
        try:
            self._save_wav(bytes(pcm), path)
            return await self.transcribe_audio(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _append_raw(path, pcm):
        with open(path, "ab") as f:
            f.write(pcm)

    async def _process_items(self, items):
        """
        Przetwarza ZAKOŃCZONE wypowiedzi: dopisuje audio na dysk (surowe PCM),
        transkrybuje i zapamiętuje linię z czasem. Zakłada trzymany _proc_lock.
        """
        new_lines = []
        for it in items:
            uid = it["uid"]
            if self.manual_only_users and uid not in self.manual_only_users:
                continue
            pcm = it["pcm"]
            if not pcm:
                continue
            start = it["start"]
            display = it["display"] or self._display_name(uid)

            if self._session_ts is None:
                self._session_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            if self._session_started_dt is None or start < self._session_started_dt:
                self._session_started_dt = start

            raw = self._flush_audio_raw.get(uid)
            if raw is None:
                channel_name = self.current_channel.name if self.current_channel else "kanal"
                safe = channel_name.replace(" ", "_")
                raw = os.path.join(self.recordings_dir, f"{safe}_{uid}_{self._session_ts}.pcm")
                self._flush_audio_raw[uid] = raw
                self._flush_display[uid] = display

            await asyncio.to_thread(self._append_raw, raw, pcm)  # audio -> dysk (zwalnia RAM)
            text = await self._transcribe_pcm(pcm)
            stripped = (text or "").strip()
            if stripped and not stripped.startswith("Błąd"):
                entry = (start, display, stripped)
                self._flush_lines.append(entry)         # trwały transkrypt (realna mowa)
                new_lines.append((start, display, stripped, False))
            else:
                # Whisper nie rozpoznał mowy (cisza/szum/halucynacja) - znacznik
                # tylko w podglądzie, NIE trafia do transkryptu ani do Ollamy.
                new_lines.append((start, display, "----------------", True))

        # Świeżo przetworzone wypowiedzi -> żywa wiadomość na czacie.
        await self._update_live_transcript(new_lines)

    async def _flush_pending(self):
        """Przetwarza zakończone wypowiedzi (wołane cyklicznie przez flush_loop)."""
        if self.sink is None or self.mode == "idle":
            return
        async with self._proc_lock:
            items = self.sink.pop_completed(
                BotConfig.UTTERANCE_GAP_SEC, BotConfig.MAX_UTTERANCE_SEC
            )
            if items:
                await self._process_items(items)

    async def finalize(self, send=None, reason="", announce=False):
        async with self._proc_lock:
            # Domknij wszystkie pozostałe (aktywne) wypowiedzi.
            if self.sink is not None:
                await self._process_items(self.sink.drain_all())

            lines = self._flush_lines
            audio_raw = self._flush_audio_raw
            display_map = self._flush_display
            started = self._session_started_dt
            # Wyzeruj stan sesji pod następne nagranie.
            self._flush_lines = []
            self._flush_audio_raw = {}
            self._flush_display = {}
            self._session_ts = None
            self._session_started_dt = None
            self._auto_announced = False
            self._live_msg = None
            self._live_buf = ""
            self._live_first = True
            self._live_last_placeholder = False

            if not lines and not audio_raw:
                return None

            out = self._resolve_send(send)
            if out and announce:
                await out(f"⏹️ Finalizuję nagranie ({reason})..." if reason else "⏹️ Finalizuję nagranie...")

            channel_name = self.current_channel.name if self.current_channel else "?"

            # Surowe PCM -> WAV (audio per osoba do ZIP-a i retencji).
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_files = {}
            for uid, raw in audio_raw.items():
                try:
                    with open(raw, "rb") as f:
                        pcm = f.read()
                except OSError:
                    pcm = b""
                if not pcm:
                    continue
                wav = os.path.join(self.recordings_dir, f"{channel_name.replace(' ', '_')}_{uid}_{ts}.wav")
                self._save_wav(pcm, wav)
                try:
                    os.remove(raw)
                except OSError:
                    pass
                audio_files[uid] = {
                    "display_name": display_map.get(uid, self._display_name(uid)),
                    "audio_file": wav,
                }

            lines.sort(key=lambda x: x[0])
            transcript_text = "\n".join(
                f"[{dt:%Y-%m-%d %H:%M:%S}] {disp}: {txt}" for dt, disp, txt in lines
            )

            session = await asyncio.to_thread(
                self.store.add_session, channel_name, transcript_text, audio_files,
                started or datetime.datetime.now(),
            )

            summary = None
            name = ""
            if transcript_text.strip():
                summary = await self.summarize_with_ollama(transcript_text)
                await asyncio.to_thread(self.store.add_summary, session["id"], "auto", summary)
                name = await self.generate_title(summary or transcript_text)
                if name:
                    await asyncio.to_thread(self.store.set_name, session["id"], name)

            if out:
                parts = ", ".join(a["display_name"] for a in audio_files.values()) or "-"
                await out(f"🎧 **{name or '(bez nazwy)'}**  ·  `{session['id']}`\n👥 {parts}")
                if summary:
                    await self._send_chunks(out, summary, header="**Podsumowanie:**")
            return session

    # =======================================================================
    #  Usługi API (Whisper / Ollama)
    # =======================================================================
    def check_services(self):
        try:
            print("Sprawdzanie statusu usług API...")
            health = ApiController.check_health()
            if health.get('status') != 'ok':
                print(f"OSTRZEŻENIE: API nie w pełni operacyjne: {health.get('message')}")
            else:
                print("API jest dostępne.")
            services = health.get('services', {})
            if services.get('whisper', {}).get('loaded'):
                print("Model Whisper jest załadowany.")
            else:
                print("OSTRZEŻENIE: Model Whisper nie jest załadowany.")
            if services.get('ollama', {}).get('available'):
                print("Ollama API jest dostępne.")
                self.check_ollama_model()
            else:
                print("OSTRZEŻENIE: Ollama API nie jest dostępne.")
        except Exception as e:
            print(f"Błąd sprawdzania usług API: {str(e)}")

    def check_ollama_model(self):
        try:
            models = ApiController.list_ollama_models()
            model_names = [m.get('name') for m in models if 'name' in m]
            print(f"Dostępne modele Ollama: {model_names}")
            if self.ollama_model not in model_names:
                print(f"OSTRZEŻENIE: Model {self.ollama_model} nie jest dostępny w Ollamie.")
            else:
                print(f"Model {self.ollama_model} jest dostępny.")
        except Exception as e:
            print(f"Błąd sprawdzania modelu Ollama: {str(e)}")

    def get_username_by_id(self, user_id):
        return self._display_name(user_id)

    async def transcribe_audio(self, filepath):
        print(f"Transkrypcja: {filepath}")
        try:
            abs_path = os.path.abspath(filepath)
            if not os.path.exists(abs_path):
                return f"Błąd transkrypcji: brak pliku ({abs_path})"
            if os.path.getsize(abs_path) == 0:
                return "Błąd transkrypcji: pusty plik"
            result = await asyncio.to_thread(ApiController.transcribe, abs_path, ModelType.WHISPER)
            if not result or "text" not in result:
                return "Błąd transkrypcji: brak tekstu w wyniku"
            return result["text"]
        except Exception as e:
            traceback.print_exc()
            return f"Błąd podczas transkrypcji: {str(e)}"

    async def summarize_with_ollama(self, text, user_id=None):
        try:
            context = self.user_contexts.get(user_id) if user_id is not None else None
            result = await asyncio.to_thread(
                ApiController.summarize, text, self.ollama_model, None, 0.0, context, "summary"
            )
            return result["text"]
        except Exception as e:
            msg = str(e)
            traceback.print_exc()
            if "not found" in msg.lower() or "404" in msg:
                return (
                    f"⚠️ Model `{self.ollama_model}` nie jest dostępny w Ollamie. "
                    f"Pobierz go (`ollama pull {self.ollama_model}`) lub zmień `/change_model`."
                )
            return f"Błąd podczas generowania podsumowania: {msg}"

    async def generate_title(self, text):
        try:
            result = await asyncio.to_thread(
                ApiController.summarize, text, self.ollama_model, None, 0.3, None, "title"
            )
            title = (result.get("text") or "").strip().strip('"').strip()
            if title:
                title = title.splitlines()[0][:80]
            return title
        except Exception as e:  # noqa: BLE001
            print(f"Błąd generowania nazwy: {e}")
            return ""

    async def summarize_session(self, session, requester_id=None, label="all"):
        combined = await asyncio.to_thread(self.store.build_combined_text, session)
        if not combined.strip():
            return None
        summary = await self.summarize_with_ollama(combined, user_id=requester_id)
        await asyncio.to_thread(self.store.add_summary, session["id"], label, summary)
        return summary

    # =======================================================================
    #  Konfiguracja w locie (/config)
    # =======================================================================
    CONFIG_KEYS = (
        "ollama_model",
        "silence_timeout_min",
        "silence_rms_threshold",
        "result_channel_id",
        "home_channel_id",
        "audio_retention_days",
    )

    def _config_path(self):
        return os.path.join(BotConfig.DATA_DIR, "runtime_config.json")

    def _load_runtime_config(self):
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for k in self.CONFIG_KEYS:
            if k in data:
                setattr(self, k, data[k])
        self.store.audio_retention_days = self.audio_retention_days
        print("Wczytano nadpisania ustawień z runtime_config.json")

    def _save_runtime_config(self):
        data = {k: getattr(self, k, None) for k in self.CONFIG_KEYS}
        try:
            os.makedirs(BotConfig.DATA_DIR, exist_ok=True)
            tmp = self._config_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._config_path())
        except Exception as e:  # noqa: BLE001
            print(f"Nie udało się zapisać runtime_config: {e}")

    def get_config(self):
        return {k: getattr(self, k, None) for k in self.CONFIG_KEYS}

    def set_config(self, key, value):
        key = (key or "").strip().lower()
        raw = (value if value is not None else "").strip()
        try:
            if key == "ollama_model":
                if not raw:
                    return False, "Podaj nazwę modelu."
                self.ollama_model = raw
            elif key == "silence_timeout_min":
                v = float(raw)
                if v <= 0:
                    return False, "silence_timeout_min musi być > 0."
                self.silence_timeout_min = v
            elif key == "silence_rms_threshold":
                v = int(raw)
                if v < 0:
                    return False, "silence_rms_threshold musi być >= 0."
                self.silence_rms_threshold = v
                if self.sink is not None and self.mode == "auto":
                    self.sink.rms_threshold = v
            elif key in ("result_channel_id", "home_channel_id"):
                v = None if raw.lower() in ("none", "0", "null", "") else int(raw)
                setattr(self, key, v)
            elif key == "audio_retention_days":
                v = int(raw)
                if v < 0:
                    return False, "audio_retention_days musi być >= 0."
                self.audio_retention_days = v
                self.store.audio_retention_days = v
            else:
                return False, f"Nieznany klucz: {key}. Dostępne: {', '.join(self.CONFIG_KEYS)}"
        except ValueError:
            return False, f"Nieprawidłowa wartość dla {key}: {raw}"
        self._save_runtime_config()
        return True, f"{key} = {getattr(self, key)}"

    # Komendy w: cogs/commands/recording_commands.py, utility_commands.py,
    #            transcription_commands.py, config_commands.py
