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

    def wants_opus(self) -> bool:
        # Chcemy zdekodowane PCM, nie Opus.
        return False

    def write(self, user, data: voice_recv.VoiceData):
        if user is None:
            # Pakiet zanim SSRC zostało powiązane z użytkownikiem - pomijamy.
            return
        self.buffers[str(user.id)].extend(data.pcm)

    def cleanup(self):
        # Bufory są pobierane przez komendę stop; nic nie zwalniamy tutaj.
        pass
