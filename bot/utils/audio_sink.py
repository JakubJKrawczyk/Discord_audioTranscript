#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import audioop
import datetime
import threading
from collections import defaultdict

from discord.ext import voice_recv


class PerUserPCMSink(voice_recv.AudioSink):
    """
    Zbiera PCM osobno dla każdego użytkownika, dzieląc na WYPOWIEDZI
    (nowa wypowiedź po przerwie > ``utterance_gap`` s; każda ma znacznik czasu).

    Bezpieczny wątkowo: ``write`` woła wątek odbioru, a ``pop_completed`` /
    ``drain_all`` woła pętla asynchroniczna (przetwarzanie przyrostowe, aby nie
    trzymać całej sesji w pamięci).
    """

    def __init__(self, rms_threshold: int = 0, utterance_gap: float = 1.5):
        super().__init__()
        self.rms_threshold = rms_threshold
        self.utterance_gap = utterance_gap
        self._lock = threading.Lock()
        # uid -> lista wypowiedzi: {"start": datetime, "last_mono": float, "pcm": bytearray}
        self.utterances = defaultdict(list)
        self.users = {}          # uid -> display_name
        self.last_sound = time.monotonic()
        self.started_at = None
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
                        return
                except Exception:
                    pass

            now = time.monotonic()
            uid = str(user.id)
            with self._lock:
                self.users[uid] = getattr(user, "display_name", None) or uid
                segs = self.utterances[uid]
                if not segs or (now - segs[-1]["last_mono"]) > self.utterance_gap:
                    segs.append({
                        "start": datetime.datetime.now(),
                        "last_mono": now,
                        "pcm": bytearray(),
                    })
                seg = segs[-1]
                seg["pcm"].extend(pcm)
                seg["last_mono"] = now
                self.last_sound = now
                if self.started_at is None:
                    self.started_at = now
        except Exception:
            pass

    def has_audio(self) -> bool:
        with self._lock:
            return any(any(s["pcm"] for s in segs) for segs in self.utterances.values())

    def silent_for(self) -> float:
        return time.monotonic() - self.last_sound

    def pop_completed(self, min_idle: float):
        """
        Zwraca ZAKOŃCZONE wypowiedzi (bezczynne dłużej niż min_idle) i usuwa je
        z pamięci. Aktywna (ostatnia, wciąż odbierana) wypowiedź zostaje.
        Element: {"uid", "display", "start", "pcm"(bytes)}.
        """
        now = time.monotonic()
        out = []
        with self._lock:
            for uid in list(self.utterances.keys()):
                segs = self.utterances[uid]
                keep = []
                for i, s in enumerate(segs):
                    is_last = (i == len(segs) - 1)
                    idle = now - s["last_mono"]
                    if (not is_last) or idle > min_idle:
                        if s["pcm"]:
                            out.append({
                                "uid": uid,
                                "display": self.users.get(uid, uid),
                                "start": s["start"],
                                "pcm": bytes(s["pcm"]),
                            })
                    else:
                        keep.append(s)
                if keep:
                    self.utterances[uid] = keep
                else:
                    del self.utterances[uid]
        return out

    def drain_all(self):
        """Zwraca WSZYSTKIE pozostałe wypowiedzi i czyści sink (do finalizacji)."""
        out = []
        with self._lock:
            for uid, segs in self.utterances.items():
                for s in segs:
                    if s["pcm"]:
                        out.append({
                            "uid": uid,
                            "display": self.users.get(uid, uid),
                            "start": s["start"],
                            "pcm": bytes(s["pcm"]),
                        })
            self.utterances = defaultdict(list)
            self.started_at = None
            self.last_sound = time.monotonic()
        return out

    def cleanup(self):
        pass
