#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trwały magazyn transkrypcji i podsumowań.

Układ katalogów (DATA_DIR):
    index.json            - metadane wszystkich sesji
    transcripts/          - tekst każdej transkrypcji (1 plik na uczestnika)
    summaries/            - tekst każdego podsumowania (1 plik)
Audio (pliki WAV) trzymane jest w RECORDINGS_DIR i czyszczone po N dniach;
transkrypcje i podsumowania są trzymane bezterminowo.

Wszystkie operacje są synchroniczne (I/O na plikach) i bezpieczne wątkowo;
z kodu async wołaj je przez asyncio.to_thread.
"""
import os
import re
import json
import glob
import time
import datetime
import threading


def _safe(name: str, limit: int = 40) -> str:
    """Bezpieczny fragment nazwy pliku."""
    cleaned = re.sub(r'[^0-9A-Za-z_-]+', '_', str(name)).strip('_')
    return (cleaned or "x")[:limit]


class TranscriptionStore:
    def __init__(self, base_dir: str, recordings_dir: str, audio_retention_days: int = 7):
        self.base_dir = base_dir
        self.recordings_dir = recordings_dir
        self.audio_retention_days = audio_retention_days
        self.transcripts_dir = os.path.join(base_dir, "transcripts")
        self.summaries_dir = os.path.join(base_dir, "summaries")
        self.index_path = os.path.join(base_dir, "index.json")
        self._lock = threading.RLock()

        os.makedirs(self.transcripts_dir, exist_ok=True)
        os.makedirs(self.summaries_dir, exist_ok=True)
        os.makedirs(self.recordings_dir, exist_ok=True)
        if not os.path.exists(self.index_path):
            self._write_index([])

    # ------------------------------------------------------------------ utils
    def _read_index(self):
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write_index(self, data):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.index_path)

    @staticmethod
    def _sorted(sessions):
        """Sortuje sesje od najnowszej do najstarszej."""
        return sorted(sessions, key=lambda s: s.get("created_at", ""), reverse=True)

    def _abs(self, rel):
        return os.path.join(self.base_dir, rel) if rel else None

    @staticmethod
    def _rm(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # -------------------------------------------------------------- public API
    def list_sessions(self):
        """Zwraca sesje posortowane od najnowszej do najstarszej."""
        with self._lock:
            return self._sorted(self._read_index())

    def get_by_id(self, session_id: str):
        with self._lock:
            for s in self._read_index():
                if s["id"].lower() == session_id.lower():
                    return s
        return None

    def add_session(self, channel_name, transcripts, created_at=None, name=""):
        """
        transcripts: dict[user_id_str -> {display_name, text, audio_file}]
        name: opcjonalna nazwa nagrania (np. wygenerowana przez summarizer).
        Zwraca utworzoną sesję (z nadanym ID).
        """
        with self._lock:
            sessions = self._read_index()
            created = created_at or datetime.datetime.now()
            base_id = "T" + created.strftime("%Y%m%d%H%M%S")
            existing = {s["id"] for s in sessions}
            session_id = base_id
            suffix = ord('a')
            while session_id in existing:
                session_id = base_id + chr(suffix)
                suffix += 1

            participants = []
            entries = {}
            for uid, data in transcripts.items():
                display = data.get("display_name") or f"Użytkownik-{uid}"
                text = data.get("text") or ""
                tfile = os.path.join(
                    self.transcripts_dir, f"{session_id}__{uid}__{_safe(display)}.txt"
                )
                with open(tfile, "w", encoding="utf-8") as f:
                    f.write(text)

                participants.append({"user_id": uid, "display_name": display})
                entries[uid] = {
                    "display_name": display,
                    "text_file": os.path.relpath(tfile, self.base_dir),
                    "audio_file": data.get("audio_file"),
                    "length": len(text),
                }

            session = {
                "id": session_id,
                "name": name or "",
                "created_at": created.isoformat(timespec="seconds"),
                "channel": channel_name,
                "participants": participants,
                "transcripts": entries,
                "summaries": [],
            }
            sessions.append(session)
            self._write_index(sessions)
            return session

    def set_name(self, session_id, name):
        """Ustawia nazwę nagrania dla sesji."""
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"] == session_id), None)
            if target is None:
                return False
            target["name"] = name or ""
            self._write_index(sessions)
            return True

    def read_transcript_text(self, session, user_id):
        t = session.get("transcripts", {}).get(user_id)
        if not t:
            return ""
        try:
            with open(self._abs(t["text_file"]), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def build_combined_text(self, session):
        """Łączy transkrypcje wszystkich uczestników w jeden tekst rozmowy."""
        parts = []
        for uid, t in session.get("transcripts", {}).items():
            text = self.read_transcript_text(session, uid)
            if text.strip():
                parts.append(f"[{t['display_name']}]: {text}")
        return "\n\n".join(parts)

    def add_summary(self, session_id, label, text):
        """Zapisuje podsumowanie do pliku i dopisuje je do sesji."""
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"] == session_id), None)
            if target is None:
                return None
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            sfile = os.path.join(
                self.summaries_dir, f"{session_id}__{_safe(label)}__{ts}.txt"
            )
            with open(sfile, "w", encoding="utf-8") as f:
                f.write(text)
            target.setdefault("summaries", []).append({
                "file": os.path.relpath(sfile, self.base_dir),
                "label": label,
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            })
            self._write_index(sessions)
            return sfile

    def delete_session(self, session_id: str) -> bool:
        """Usuwa sesję wraz z plikami transkrypcji, podsumowań i audio."""
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"].lower() == session_id.lower()), None)
            if target is None:
                return False
            for t in target.get("transcripts", {}).values():
                self._rm(self._abs(t.get("text_file")))
                self._rm(t.get("audio_file"))
            for sm in target.get("summaries", []):
                self._rm(self._abs(sm.get("file")))
            sessions = [s for s in sessions if s["id"] != target["id"]]
            self._write_index(sessions)
            return True

    def prune_audio(self):
        """Usuwa pliki audio starsze niż retention; transkrypcje zostają."""
        cutoff = time.time() - self.audio_retention_days * 86400
        removed = []
        with self._lock:
            sessions = self._read_index()
            changed = False
            for s in sessions:
                for t in s.get("transcripts", {}).values():
                    af = t.get("audio_file")
                    if not af:
                        continue
                    if not os.path.exists(af):
                        t["audio_file"] = None
                        t["audio_expired"] = True
                        changed = True
                    elif os.path.getmtime(af) < cutoff:
                        self._rm(af)
                        t["audio_file"] = None
                        t["audio_expired"] = True
                        changed = True
                        removed.append(af)
            if changed:
                self._write_index(sessions)

        # Posprzątaj też osierocone pliki WAV w katalogu nagrań.
        for wav in glob.glob(os.path.join(self.recordings_dir, "*.wav")):
            try:
                if os.path.getmtime(wav) < cutoff:
                    self._rm(wav)
                    removed.append(wav)
            except OSError:
                pass
        return removed

    # ------------------------------------------------------ rozwiązywanie celów
    def resolve_targets(self, arg: str):
        """
        Zamienia argument komendy na listę sesji (posortowanych od najnowszej):
          - 'all'           -> wszystkie
          - '<id>'          -> jedna sesja po ID (np. T20260630213045)
          - '<n>'           -> n-ta pozycja listy (1 = najnowsza)
          - '<start>-<end>' -> przedział indeksów listy (włącznie)
        """
        sessions = self.list_sessions()
        a = (arg or "").strip()
        if not a:
            return []
        if a.lower() == "all":
            return sessions

        m = re.match(r'^(\d+)\s*-\s*(\d+)$', a)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start > end:
                start, end = end, start
            start = max(start, 1)
            return sessions[start - 1:end]

        if a.isdigit():
            idx = int(a)
            if 1 <= idx <= len(sessions):
                return [sessions[idx - 1]]
            return []

        s = next((x for x in sessions if x["id"].lower() == a.lower()), None)
        return [s] if s else []
