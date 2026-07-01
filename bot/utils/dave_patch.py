#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sklejka DAVE (E2EE) dla ODBIORU głosu.

Discord wymusza DAVE na voice gateway v8. discord.py 2.7 prowadzi pełny
handshake MLS (bot staje się członkiem grupy), ale jego DaveSession jest
używana tylko do wysyłania (encrypt_opus). discord-ext-voice-recv przy
odbiorze robi tylko deszyfrację transportową i od razu podaje dane do Opusa,
przez co pod DAVE Opus dostaje szyfrogram -> "corrupted stream".

Ten monkey-patch wpina odszyfrowanie DAVE (DaveSession.decrypt) tuż przed
dekodowaniem Opus w PacketDecoder._decode_packet. decrypt() sam przepuszcza
pakiety niezaszyfrowane (passthrough), więc jest bezpieczny również gdy DAVE
akurat nie działa.
"""
import logging

log = logging.getLogger("dave_patch")


def apply_dave_receive_patch() -> bool:
    try:
        import davey
        from discord.ext.voice_recv import opus as vr_opus
    except Exception as e:  # noqa: BLE001
        print(f"DAVE patch: pominięto (brak zależności: {e})")
        return False

    PacketDecoder = vr_opus.PacketDecoder
    if getattr(PacketDecoder, "_dave_patched", False):
        return True

    AUDIO = davey.MediaType.audio

    def _dave_decrypt(decoder, data):
        """Odszyfruj warstwę DAVE dla danego mówiącego; passthrough gdy brak DAVE."""
        if not data:
            return data
        try:
            vc = decoder.sink.voice_client
            conn = getattr(vc, "_connection", None)
            sess = getattr(conn, "dave_session", None)
            if sess is None or not getattr(sess, "ready", False):
                return data  # DAVE nieaktywny -> zwykły Opus
            uid = decoder._cached_id or vc._get_id_from_ssrc(decoder.ssrc)
            if not uid:
                return data
            return bytes(sess.decrypt(int(uid), AUDIO, data))
        except Exception:  # noqa: BLE001
            # Nie wywracaj wątku odbioru - w najgorszym razie zgub klatkę.
            return data

    def _decode_packet(self, packet):
        assert self._decoder is not None

        if packet:
            pcm = self._decoder.decode(_dave_decrypt(self, packet.decrypted_data), fec=False)
            return packet, pcm

        # Pakiet "fake" - użyj FEC z następnego, jeśli jest.
        next_packet = self._buffer.peek_next()
        if next_packet is not None:
            pcm = self._decoder.decode(_dave_decrypt(self, next_packet.decrypted_data), fec=True)
        else:
            pcm = self._decoder.decode(None, fec=False)
        return packet, pcm

    PacketDecoder._decode_packet = _decode_packet
    PacketDecoder._dave_patched = True
    print("DAVE receive patch zastosowany (voice_recv PacketDecoder._decode_packet).")
    return True
