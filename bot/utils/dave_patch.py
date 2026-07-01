#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sklejka DAVE (E2EE) dla ODBIORU głosu + odporność na uszkodzone pakiety.

Discord wymusza DAVE na voice gateway v8. discord.py 2.7 prowadzi handshake
MLS (bot jest członkiem grupy), ale jego DaveSession używana jest tylko do
wysyłania. voice-recv przy odbiorze robi tylko deszyfrację transportową i od
razu podaje dane do Opusa -> pod DAVE Opus dostaje szyfrogram -> OpusError
"corrupted stream", a wyjątek zabija wątek PacketRouter (koniec nagrywania).

Ten patch:
  1. Przed Opusem odszyfrowuje warstwę DAVE (DaveSession.decrypt).
  2. Gdy DAVE aktywny, ale sesja NIE jest jeszcze gotowa (trwa handshake MLS)
     albo deszyfracja się nie powiedzie -> pomija pakiet (PLC/cisza), zamiast
     karmić Opus szyfrogramem.
  3. Dekodowanie Opus jest w pełni zabezpieczone - pojedynczy błędny pakiet
     nigdy nie wywróci wątku odbioru.
"""
import logging

log = logging.getLogger("dave_patch")

# 20 ms ramka Discorda: 48000 Hz * 0.02 s * 2 kanały * 2 bajty = 3840 B ciszy.
_SILENCE_FRAME = b"\x00" * 3840


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

    def _dave_payload(decoder, data):
        """
        Zwraca dane gotowe do Opusa:
          - bez DAVE -> oryginalne dane,
          - DAVE gotowy -> odszyfrowane,
          - DAVE niegotowy / błąd -> None (pakiet do pominięcia).
        """
        if not data:
            return data
        try:
            vc = decoder.sink.voice_client
            conn = getattr(vc, "_connection", None)
            sess = getattr(conn, "dave_session", None)
            dave_ver = getattr(conn, "dave_protocol_version", 0) or 0
            if not dave_ver or sess is None:
                return data  # kanał bez E2EE -> zwykły Opus
            if not getattr(sess, "ready", False):
                return None  # trwa handshake MLS -> pomiń pakiet
            uid = decoder._cached_id or vc._get_id_from_ssrc(decoder.ssrc)
            if not uid:
                return None
            return bytes(sess.decrypt(int(uid), AUDIO, data))
        except Exception:  # noqa: BLE001
            return None  # nie udało się odszyfrować -> pomiń

    def _safe_decode(decoder, data, fec=False):
        """Dekoduje Opus tak, by żaden błąd nie wywrócił wątku odbioru."""
        try:
            return decoder.decode(data, fec=fec)
        except Exception:  # noqa: BLE001
            try:
                return decoder.decode(None, fec=False)  # PLC / cisza
            except Exception:  # noqa: BLE001
                return _SILENCE_FRAME

    def _decode_packet(self, packet):
        assert self._decoder is not None

        if packet:
            payload = _dave_payload(self, packet.decrypted_data)
            pcm = _safe_decode(self._decoder, payload, fec=False)
            return packet, pcm

        # Pakiet "fake" - spróbuj FEC z następnego, jeśli jest.
        next_packet = self._buffer.peek_next()
        if next_packet is not None:
            payload = _dave_payload(self, next_packet.decrypted_data)
            pcm = _safe_decode(self._decoder, payload, fec=(payload is not None))
        else:
            pcm = _safe_decode(self._decoder, None, fec=False)
        return packet, pcm

    PacketDecoder._decode_packet = _decode_packet
    PacketDecoder._dave_patched = True
    print("DAVE receive patch zastosowany (odporny na niegotową sesję i błędne pakiety).")
    return True
