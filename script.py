import discord
from discord.ext import commands
import asyncio
import wave
import datetime
import whisper
import torch
import os
import requests
import json
import pyaudio
import wave
import threading
from pynput import keyboard

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)


class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recording = False
        self.frames = []
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.whisper_model = whisper.load_model("base")
        self.user_contexts = {}
        self.transcriptions = {}
        self.ollama_url = "http://localhost:11434/api/generate"
        self.current_recording_user = None
        self.current_file = None  # Dodajemy śledzenie aktualnego pliku

        # Utworzenie folderu recordings
        self.recordings_dir = os.path.join(os.getcwd(), "recordings")
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings utworzony w: {self.recordings_dir}")

    def callback(self, in_data, frame_count, time_info, status):
        if self.recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    @commands.command()
    async def context(self, ctx, *, new_context):
        """Ustawia kontekst dla użytkownika"""
        user_id = ctx.author.id
        self.user_contexts[user_id] = new_context
        await ctx.send(f"Ustawiono nowy kontekst dla użytkownika {ctx.author.name}")

    @commands.command()
    async def show_context(self, ctx):
        """Pokazuje aktualny kontekst użytkownika"""
        user_id = ctx.author.id
        context = self.user_contexts.get(user_id, "Brak ustawionego kontekstu")
        await ctx.send(f"Twój aktualny kontekst:\n{context}")

    @commands.command()
    async def record(self, ctx):
        """Rozpoczyna nagrywanie"""
        if self.recording:
            await ctx.send("Nagrywanie już trwa!")
            return

        # Sprawdź czy użytkownik jest na kanale głosowym
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        self.current_recording_user = ctx.author.id

        try:
            # Dołącz do kanału głosowego
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()

            # Rozpocznij nagrywanie
            self.recording = True
            self.frames = []

            # Konfiguracja streamu audio
            # Znajdź domyślne urządzenie wejściowe
            default_input = self.audio.get_default_input_device_info()

            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,  # Zmienione na mono
                rate=int(default_input['defaultSampleRate']),  # Używamy domyślnej częstotliwości próbkowania
                input=True,
                input_device_index=default_input['index'],  # Używamy domyślnego urządzenia
                frames_per_buffer=1024,
                stream_callback=self.callback
            )

            self.stream.start_stream()
            await ctx.send("Rozpoczęto nagrywanie! Użyj !stop aby zakończyć.")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            self.recording = False
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

    @commands.command()
    async def stop(self, ctx):
        """Zatrzymuje nagrywanie"""
        if not self.recording:
            await ctx.send("Nie ma aktywnego nagrywania!")
            return

        try:
            self.recording = False

            # Zatrzymaj stream
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

            # Zapisz plik audio
            # Utwórz folder recordings jeśli nie istnieje
            recordings_dir = os.path.join(os.getcwd(), "recordings")
            os.makedirs(recordings_dir, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(recordings_dir, f"recording_{timestamp}.wav")
            print(f"Zapisuję plik: {filename}")  # Debug info

            print("Rozpoczynam zapis pliku WAV...")  # Debug info
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(int(self.audio.get_default_input_device_info()['defaultSampleRate']))
                audio_data = b''.join(self.frames)
                print(f"Rozmiar danych audio: {len(audio_data)} bajtów")  # Debug info
                wf.writeframes(audio_data)

            # Sprawdź czy plik został utworzony i ma odpowiedni rozmiar
            if not os.path.exists(filename):
                raise FileNotFoundError(f"Plik {filename} nie został utworzony")

            file_size = os.path.getsize(filename)
            print(f"Plik został zapisany, rozmiar: {file_size} bajtów")  # Debug info

            if file_size == 0:
                raise ValueError("Plik audio jest pusty")

            # Rozłącz się z kanału głosowego
            for vc in self.bot.voice_clients:
                await vc.disconnect()

            try:
                # Najpierw wykonaj transkrypcję
                await ctx.send("Rozpoczynam transkrypcję audio...")
                transcription = await self.transcribe_audio(filename)

                # Zapisz transkrypcję dla użytkownika
                if self.current_recording_user:
                    self.transcriptions[self.current_recording_user] = transcription

                # Wyślij plik audio
                await ctx.send("Nagranie zostało zapisane!", file=discord.File(filename))

                # Wyślij transkrypcję
                await ctx.send("Transkrypcja:")
                for i in range(0, len(transcription), 1900):
                    await ctx.send(transcription[i:i + 1900])

            except Exception as e:
                await ctx.send(f"Błąd podczas przetwarzania: {str(e)}")

            finally:
                # Upewnij się że plik istnieje przed próbą usunięcia
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except Exception as e:
                        print(f"Nie można usunąć pliku: {str(e)}")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd podczas zatrzymywania nagrywania: {str(e)}")

    @commands.command()
    async def process(self, ctx):
        """Przetwarza transkrypcję przez Ollamę"""
        user_id = ctx.author.id
        if user_id not in self.transcriptions:
            await ctx.send("Nie znaleziono transkrypcji do przetworzenia!")
            return

        context = self.user_contexts.get(user_id, "")
        transcription = self.transcriptions[user_id]

        # Przygotuj prompt dla Ollamy
        prompt = f"Context: {context}\nText: {transcription}\n"

        try:
            # Wywołaj API Ollamy
            response = requests.post(
                self.ollama_url,
                json={
                    "model": "llama2",
                    "prompt": prompt,
                    "stream": False
                }
            )

            if response.status_code == 200:
                ollama_response = response.json()['response']

                # Zapisz odpowiedź do pliku
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"response_{timestamp}.txt"

                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"Original Context:\n{context}\n\n")
                    f.write(f"Transcription:\n{transcription}\n\n")
                    f.write(f"Response:\n{ollama_response}")

                # Wyślij plik
                await ctx.send(
                    "Przetworzono tekst przez Ollamę!",
                    file=discord.File(filename)
                )

                # Usuń plik
                os.remove(filename)

            else:
                await ctx.send(f"Błąd podczas przetwarzania przez Ollamę: {response.status_code}")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd podczas przetwarzania: {str(e)}")

    async def transcribe_audio(self, filepath):
        """Transkrybuje plik audio na tekst"""
        print(f"Rozpoczynam transkrypcję pliku: {filepath}")

        try:
            abs_path = os.path.abspath(filepath)
            print(f"Pełna ścieżka do pliku: {abs_path}")

            if not os.path.exists(abs_path):
                print(f"BŁĄD: Plik nie istnieje w ścieżce: {abs_path}")
                return f"Błąd transkrypcji: Plik nie istnieje w ścieżce {abs_path}"

            file_size = os.path.getsize(abs_path)
            print(f"Rozmiar pliku: {file_size} bajtów")

            if file_size == 0:
                print("BŁĄD: Plik jest pusty")
                return "Błąd transkrypcji: Plik jest pusty"

            import numpy as np
            import librosa

            def transcribe():
                try:
                    print("Wczytuję plik audio...")
                    # Wczytaj audio z określonym typem danych
                    audio_data, sample_rate = librosa.load(abs_path, sr=16000, dtype=np.float32)
                    print(f"Plik audio wczytany, próbkowanie: {sample_rate}Hz")

                    # Normalizacja audio
                    audio_data = librosa.util.normalize(audio_data)

                    print("Uruchamiam model Whisper...")
                    result = self.whisper_model.transcribe(
                        audio_data,
                        language="pl",  # Ustawienie języka na polski
                        fp16=False  # Wyłączenie FP16
                    )
                    print("Transkrypcja zakończona pomyślnie")
                    return result
                except Exception as e:
                    print(f"BŁĄD w trakcie transkrypcji: {str(e)}")
                    raise

            print("Uruchamiam transkrypcję w osobnym wątku...")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, transcribe)

            if not result or "text" not in result:
                print("BŁĄD: Brak tekstu w wyniku transkrypcji")
                return "Błąd transkrypcji: Brak tekstu w wyniku"

            print("Transkrypcja zakończona sukcesem")
            return result["text"]

        except Exception as e:
            error_msg = f"Błąd podczas transkrypcji: {str(e)}"
            print(f"BŁĄD KRYTYCZNY: {error_msg}")
            print(f"Szczegóły pliku:")
            print(f"- Ścieżka: {abs_path}")
            print(f"- Istnieje: {os.path.exists(abs_path)}")
            if os.path.exists(abs_path):
                print(f"- Rozmiar: {os.path.getsize(abs_path)}")
                print(f"- Uprawnienia: {oct(os.stat(abs_path).st_mode)[-3:]}")
            return error_msg


@bot.event
async def on_ready():
    print(f'Bot jest gotowy: {bot.user}')
    await bot.add_cog(AudioRecorder(bot))


# Uruchom bota
bot.run('<token>')