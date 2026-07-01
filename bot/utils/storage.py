#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trwały magazyn nagrań.

Model sesji (nagrania):
    id, name, created_at, channel, participants,
    transcript_file  -> transcripts/<id>.txt  (CHRONOLOGICZNY, wielu mówców)
    transcript_len
    audio: [{user_id, display_name, file}]     (audio per osoba, w RECORDINGS_DIR)
    summaries: [{file, label, created_at}]

Audio kasowane po N dniach; transkrypcje i podsumowania - bezterminowo.
Czyta też stary format (per-user "transcripts") dla zgodności wstecznej.
"""
import os
import re
import json
import glob
import time
import datetime
import threading


def _safe(name: str, limit: int = 40) -> str:
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

    # -------------------------------------------------------- format-agnostic
    def _audio_entries(self, session):
        """Lista {user_id, display_name, file} niezależnie od formatu sesji."""
        if "audio" in session:
            return session.get("audio", [])
        # stary format: transcripts[uid].audio_file
        out = []
        for uid, t in session.get("transcripts", {}).items():
            out.append({
                "user_id": uid,
                "display_name": t.get("display_name", uid),
                "file": t.get("audio_file"),
            })
        return out

    def read_transcript(self, session):
        """Zwraca treść transkryptu (nowy chronologiczny lub sklejony stary)."""
        tf = session.get("transcript_file")
        if tf:
            try:
                with open(self._abs(tf), "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return ""
        # stary format
        parts = []
        for uid, t in session.get("transcripts", {}).items():
            p = self._abs(t.get("text_file"))
            try:
                with open(p, "r", encoding="utf-8") as f:
                    txt = f.read()
            except OSError:
                txt = ""
            if txt.strip():
                parts.append(f"[{t.get('display_name', uid)}]: {txt}")
        return "\n\n".join(parts)

    def build_combined_text(self, session):
        return self.read_transcript(session)

    def has_transcript(self, session) -> bool:
        if "transcript_len" in session:
            return (session.get("transcript_len") or 0) > 0
        return any((t.get("length") or 0) > 0 for t in session.get("transcripts", {}).values())

    def has_audio(self, session) -> bool:
        return any(e.get("file") and os.path.exists(e["file"]) for e in self._audio_entries(session))

    # -------------------------------------------------------------- public API
    def list_sessions(self):
        with self._lock:
            return self._sorted(self._read_index())

    def get_by_id(self, session_id: str):
        with self._lock:
            for s in self._read_index():
                if s["id"].lower() == session_id.lower():
                    return s
        return None

    def add_session(self, channel_name, transcript_text, audio_files, created_at=None, name=""):
        """
        transcript_text: gotowy CHRONOLOGICZNY transkrypt (wielu mówców).
        audio_files: dict[uid -> {"display_name", "audio_file" (ścieżka abs)}]
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

            tfile = os.path.join(self.transcripts_dir, f"{session_id}.txt")
            with open(tfile, "w", encoding="utf-8") as f:
                f.write(transcript_text or "")

            participants, audio = [], []
            for uid, data in (audio_files or {}).items():
                display = data.get("display_name") or f"Użytkownik-{uid}"
                participants.append({"user_id": uid, "display_name": display})
                audio.append({
                    "user_id": uid,
                    "display_name": display,
                    "file": data.get("audio_file"),
                })

            session = {
                "id": session_id,
                "name": name or "",
                "created_at": created.isoformat(timespec="seconds"),
                "channel": channel_name,
                "participants": participants,
                "transcript_file": os.path.relpath(tfile, self.base_dir),
                "transcript_len": len(transcript_text or ""),
                "audio": audio,
                "summaries": [],
            }
            sessions.append(session)
            self._write_index(sessions)
            return session

    def set_name(self, session_id, name):
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"] == session_id), None)
            if target is None:
                return False
            target["name"] = name or ""
            self._write_index(sessions)
            return True

    def add_summary(self, session_id, label, text):
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"] == session_id), None)
            if target is None:
                return None
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            sfile = os.path.join(self.summaries_dir, f"{session_id}__{_safe(label)}__{ts}.txt")
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
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"].lower() == session_id.lower()), None)
            if target is None:
                return False
            # transkrypt (nowy i stary)
            self._rm(self._abs(target.get("transcript_file")))
            for t in target.get("transcripts", {}).values():
                self._rm(self._abs(t.get("text_file")))
            # audio
            for e in self._audio_entries(target):
                self._rm(e.get("file"))
            # podsumowania
            for sm in target.get("summaries", []):
                self._rm(self._abs(sm.get("file")))
            sessions = [s for s in sessions if s["id"] != target["id"]]
            self._write_index(sessions)
            return True

    def delete_audio(self, session_id: str) -> bool:
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"].lower() == session_id.lower()), None)
            if target is None:
                return False
            for e in target.get("audio", []):
                self._rm(e.get("file"))
                e["file"] = None
            for t in target.get("transcripts", {}).values():  # stary format
                self._rm(t.get("audio_file"))
                t["audio_file"] = None
            self._write_index(sessions)
            return True

    def delete_summaries(self, session_id: str) -> bool:
        with self._lock:
            sessions = self._read_index()
            target = next((s for s in sessions if s["id"].lower() == session_id.lower()), None)
            if target is None:
                return False
            for sm in target.get("summaries", []):
                self._rm(self._abs(sm.get("file")))
            target["summaries"] = []
            self._write_index(sessions)
            return True

    def export_bundle(self, session):
        """Zwraca elementy nagrania do spakowania: transkrypt, podsumowania, audio."""
        summaries = []
        for sm in session.get("summaries", []):
            p = self._abs(sm.get("file"))
            if p and os.path.exists(p):
                summaries.append(p)
        audio = []
        for e in self._audio_entries(session):
            f = e.get("file")
            if f and os.path.exists(f):
                audio.append((e.get("display_name", e.get("user_id")), f))
        return {
            "transcript_text": self.read_transcript(session),
            "summaries": summaries,
            "audio": audio,
        }

    def prune_audio(self):
        cutoff = time.time() - self.audio_retention_days * 86400
        removed = []
        with self._lock:
            sessions = self._read_index()
            changed = False
            for s in sessions:
                for e in self._audio_entries(s):
                    f = e.get("file")
                    if not f:
                        continue
                    if not os.path.exists(f):
                        e["file"] = None
                        changed = True
                    elif os.path.getmtime(f) < cutoff:
                        self._rm(f)
                        e["file"] = None
                        changed = True
                        removed.append(f)
            if changed:
                self._write_index(sessions)

        for pat in ("*.wav", "*.pcm"):
            for f in glob.glob(os.path.join(self.recordings_dir, pat)):
                try:
                    if os.path.getmtime(f) < cutoff:
                        self._rm(f)
                        removed.append(f)
                except OSError:
                    pass
        return removed

    # ------------------------------------------------------ rozwiązywanie celów
    def resolve_targets(self, arg: str):
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
