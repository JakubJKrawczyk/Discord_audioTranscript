#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import audioop
from collections import defaultdict

from discord.ext import voice_recv


class PerUserPCMSink(voice_recv.AudioSink):
    """
    Sink zbierający surowe PCM osobno dla każdego użytkownika
    (48 kHz, 16-bit, stereo).

    Tryb bramkowania (gate): jeśli ``rms_threshold > 0``, klatki o amplitudzie
    RMS poniżej progu są traktowane jako cisza i odrzucane, a znacznik
    ``last_sound`` (monotonic) aktualizowany jest tylko dla klatek z dźwiękiem.
    To pozwala trybowi auto wykrywać ciszę i nie zapisywać pustych fragmentów.
    Przy ``rms_threshold == 0`` (tryb ręczny) zapisujemy wszystko.
    """

    def __init__(self, rms_threshold: int = 0):
        super().__init__()
        self.rms_threshold = rms_threshold
        self.buffers = defaultdict(bytearray)
        self.last_sound = time.monotonic()
        self.started_at = None  # monotonic czasu pierwszego dźwięku
        self.stats = {"writes": 0, "none_user": 0, "empty_pcm": 0, "silence": 0}

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data: voice_recv.VoiceData):
        try:
            self.stats["writes"] += 1
            if user is None:
                self.stats["none_user"] += 1
                return
            pcm = getattr(data, "pcm", None)
            if not pcm:
                self.stats["empty_pcm"] += 1
                return

            if self.rms_threshold > 0:
                try:
                    if audioop.rms(pcm, 2) < self.rms_threshold:
                        self.stats["silence"] += 1
                        return  # cisza - odrzuć klatkę
                except Exception:
                    pass  # przy błędzie liczenia RMS lepiej zapisać niż zgubić

            now = time.monotonic()
            self.last_sound = now
            if self.started_at is None:
                self.started_at = now
            self.buffers[str(user.id)].extend(pcm)
        except Exception:
            # Pojedynczy pakiet nie może zabić wątku odbioru.
            pass

    def has_audio(self) -> bool:
        return any(self.buffers.values())

    def silent_for(self) -> float:
        """Ile sekund minęło od ostatniego dźwięku."""
        return time.monotonic() - self.last_sound

    def snapshot_and_reset(self):
        """Zwraca zebrane bufory (bytes) i czyści sink pod nową sesję."""
        data = {uid: bytes(buf) for uid, buf in self.buffers.items() if buf}
        self.buffers = defaultdict(bytearray)
        self.started_at = None
        self.last_sound = time.monotonic()
        return data

    def cleanup(self):
        pass
