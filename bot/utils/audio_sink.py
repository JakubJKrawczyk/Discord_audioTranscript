#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from collections import defaultdict

from discord.ext import voice_recv


class PerUserPCMSink(voice_recv.AudioSink):
    """
    Sink dla discord-ext-voice-recv, który zbiera surowe PCM oddzielnie dla
    każdego użytkownika. Discord wysyła 48 kHz, 16-bit, stereo.
    """

    def __init__(self):
        super().__init__()
        self.buffers = defaultdict(bytearray)
        # Liczniki diagnostyczne
        self.stats = {"writes": 0, "none_user": 0, "empty_pcm": 0}

    def wants_opus(self) -> bool:
        # Chcemy zdekodowane PCM, nie Opus.
        return False

    def write(self, user, data: voice_recv.VoiceData):
        # Pojedynczy wadliwy pakiet NIE może zabić wątku odbioru - inaczej
        # nagrywanie urywa się po chwili. Dlatego pełne zabezpieczenie.
        try:
            self.stats["writes"] += 1
            if user is None:
                # Pakiet zanim SSRC zostało powiązane z użytkownikiem.
                self.stats["none_user"] += 1
                return
            pcm = getattr(data, "pcm", None)
            if not pcm:
                # Klatka ciszy/keepalive bez PCM - pomijamy.
                self.stats["empty_pcm"] += 1
                return
            self.buffers[str(user.id)].extend(pcm)
        except Exception:
            # Świadomie połykamy - lepiej zgubić klatkę niż cały strumień.
            pass

    def cleanup(self):
        # Bufory są pobierane przez komendę stop; nic nie zwalniamy tutaj.
        pass
