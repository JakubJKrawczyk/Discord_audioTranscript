# Discord Audio Transcript

Bot Discord, który nagrywa głos z kanału głosowego (osobno dla każdego
uczestnika), transkrybuje go modelem **Whisper** i tworzy podsumowania
modelem **Ollama**. Transkrypcje są trwale zapisywane i zarządzalne komendami.

## Architektura

```
Discord  ──►  bot  ──HTTP──►  whisper-api (gpuworker)  ──HTTPS──►  Ollama (host)
                                  │  Whisper: transkrypcja           ollama.jakubkrawczyk.com
                                  │  Ollama:  podsumowania (/summarize/)
```

Serwisy (docker-compose):
- **whisper-api** – transkrypcja audio (GPU) + endpoint `/summarize/`
- **bot** – klient Discord (CPU)

Ollama **nie** jest w dockerze – używamy instancji na hoście (adres w
`OLLAMA_API_URL`, domyślnie `https://ollama.jakubkrawczyk.com`). Modele
zarządzasz po stronie hosta (`ollama pull ...`).

## Wymagania (serwer)
- Docker + docker compose
- GPU NVIDIA + sterownik + **nvidia-container-toolkit** (dla `whisper-api`)
- Działająca Ollama na hoście, osiągalna pod `OLLAMA_API_URL`

## Uruchomienie

```bash
git clone <repo> && cd Discord_audioTranscript

# Cała konfiguracja jest w JEDNYM pliku .env
cp .env.example .env
nano .env          # ustaw DISCORD_TOKEN i OLLAMA_DEFAULT_MODEL (model z Twojej Ollamy)

docker compose up -d --build
docker compose logs -f bot
```

Pierwszy start jest wolny: budowa obrazu z CUDA + pobranie modelu Whisper
(`large` ≈ 3 GB do wolumenu). Bot wstaje dopiero, gdy `whisper-api` jest
„healthy" (do 5 min) – to celowe.

> Brak GPU? Usuń blok `deploy:` z `docker-compose.yml` (Whisper pojedzie na
> CPU – wolno, zwłaszcza dla modelu `large`).

## Konfiguracja (`.env`)

| Zmienna | Opis | Domyślnie |
|---|---|---|
| `DISCORD_TOKEN` | token bota (wymagany) | – |
| `BOT_PREFIX` | prefix komend tekstowych | `!` |
| `WHISPER_MODEL` | rozmiar Whispera (`tiny`…`large`) | `large` |
| `WHISPER_LANGUAGE` | język transkrypcji (`pl`, `auto`, …) | `pl` |
| `OLLAMA_API_URL` | adres Ollamy na hoście | `https://ollama.jakubkrawczyk.com` |
| `OLLAMA_DEFAULT_MODEL` | model do podsumowań (musi istnieć w Ollamie) | `gemma4:e4b` |
| `AUDIO_RETENTION_DAYS` | po ilu dniach kasować audio | `7` |
| `ALLOWED_ORIGINS` | dozwolone originy CORS | `*` |

Adres `bot → whisper-api` (`http://whisper-api:8000`) ustawia samo compose.

## Komendy

Każda działa jako slash (`/`) i z prefixem (np. `!`).

**🎙️ Nagrywanie**
- `/record_user [member] [filename]` – nagrywa jednego użytkownika
- `/record_all [prefix]` – nagrywa wszystkich na kanale
- `/stop` – kończy: zapis → transkrypcja → podsumowanie (nadaje ID)

**📜 Transkrypcje**
- `/transcriptions [strona]` – lista od najnowszej, paginacja ◀▶
- `/summarize <cel>` – `cel`: `ID` | `all` | indeks `2` | przedział `1-3`
- `/delete <cel>` – `cel`: `ID` | indeks `2` | przedział `1-3`

**🤖 Ollama / 🛠️ pozostałe**
- `/change_model <model>`, `/list_models`
- `/context <tekst>`, `/show_context`, `/help`

## Dane i przechowywanie

- `recordings/` – pliki audio WAV (kasowane po `AUDIO_RETENTION_DAYS`)
- `data/` – trwały magazyn:
  - `index.json` – metadane sesji
  - `transcripts/` – każda transkrypcja w osobnym pliku
  - `summaries/` – każde podsumowanie w osobnym pliku
- ID sesji: `T` + data, np. `T20260630213045`
- Transkrypcje i podsumowania trzymane **bezterminowo**; po wygaśnięciu audio
  transkrypcja zostaje (na liście `🎧 audio: nie`).

Oba katalogi są montowane jako wolumeny (`./recordings`, `./data`), więc
przetrwają restart i `docker compose down`.

## Ważne (Discord Developer Portal)
- Włącz **Message Content Intent** i **Server Members Intent**.
- Bot musi mieć prawo *Connect* na kanale głosowym.
