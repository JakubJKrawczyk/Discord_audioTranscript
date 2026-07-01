#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import audioop
import datetime
from collections import defaultdict

from discord.ext import voice_recv


class PerUserPCMSink(voice_recv.AudioSink):
    """
    Zbiera PCM osobno dla każdego użytkownika, dzieląc na WYPOWIEDZI.

    Wypowiedź = ciągły fragment mowy; nowa wypowiedź zaczyna się, gdy przerwa
    od poprzedniej klatki przekroczy ``utterance_gap`` sekund. Każda wypowiedź
    ma znacznik czasu (wall-clock) startu - pozwala zbudować chronologiczny
    transkrypt wielu rozmówców.

    Bramkowanie ciszy (``rms_threshold > 0``): klatki poniżej progu RMS są
    odrzucane (tryb auto). Przy 0 zapisujemy wszystko (tryb ręczny), ale i tak
    dzielimy na wypowiedzi po przerwach.
    """

    def __init__(self, rms_threshold: int = 0, utterance_gap: float = 1.5):
        super().__init__()
        self.rms_threshold = rms_threshold
        self.utterance_gap = utterance_gap
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
        return any(any(s["pcm"] for s in segs) for segs in self.utterances.values())

    def silent_for(self) -> float:
        return time.monotonic() - self.last_sound

    def snapshot_and_reset(self):
        """
        Zwraca (users, utterances) i czyści sink.
        users: {uid: display_name}
        utterances: {uid: [ {start: datetime, pcm: bytes}, ... ]}
        """
        utts = {}
        for uid, segs in self.utterances.items():
            kept = [{"start": s["start"], "pcm": bytes(s["pcm"])} for s in segs if s["pcm"]]
            if kept:
                utts[uid] = kept
        users = dict(self.users)
        self.utterances = defaultdict(list)
        self.users = {}
        self.started_at = None
        self.last_sound = time.monotonic()
        return users, utts

    def cleanup(self):
        pass
