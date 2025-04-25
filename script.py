import discord
from discord.ext import commands
from discord import app_commands
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
import keyboard
import subprocess
import time
import traceback
from typing import Optional

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='/',
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Synchronizowanie slash komend z Discordem
        await self.tree.sync()
        print("Slash commands synchronized")


bot = Bot()


class AudioRecorder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recording = False
        self.frames = {}  # Słownik dla przechowywania ramek audio różnych użytkowników
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.whisper_model = whisper.load_model("base")
        self.user_contexts = {}
        self.transcriptions = {}
        self.ollama_url = "http://localhost:11434/api/generate"
        self.ollama_model = "gemma:2b"  # Domyślny model - mały model do podsumowań
        self.record_all_users = False  # Czy nagrywać wszystkich użytkowników
        self.targeted_user_id = None  # ID konkretnego użytkownika do nagrywania
        self.current_channel = None  # Aktualny kanał, na którym nagrywamy

        # Utworzenie folderu recordings
        self.recordings_dir = os.path.join(os.getcwd(), "recordings")
        os.makedirs(self.recordings_dir, exist_ok=True)
        print(f"Folder recordings utworzony w: {self.recordings_dir}")

        # Sprawdź czy Ollama jest zainstalowana i załaduj model
        self.check_ollama()

    def check_ollama(self):
        """Sprawdza czy Ollama jest zainstalowana i pobiera model jeśli potrzeba"""
        try:
            # Sprawdź czy Ollama jest dostępna
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code != 200:
                print("Ollama API nie jest dostępne. Upewnij się, że Ollama jest uruchomiona.")
                return False

            # Pobierz listę dostępnych modeli
            available_models = response.json().get("models", [])
            model_names = [model.get("name") for model in available_models]

            print(f"Dostępne modele Ollama: {model_names}")

            # Sprawdź czy nasz model jest dostępny, jeśli nie - pobierz go
            if self.ollama_model not in model_names:
                print(f"Model {self.ollama_model} nie jest zainstalowany. Pobieram...")

                # Użyj subprocess do pobrania modelu w tle
                subprocess.Popen(["ollama", "pull", self.ollama_model])
                print(f"Rozpoczęto pobieranie modelu {self.ollama_model} w tle.")

                # Możemy kontynuować działanie bota podczas pobierania
                return True
            else:
                print(f"Model {self.ollama_model} jest już zainstalowany.")
                return True

        except Exception as e:
            print(f"Błąd podczas sprawdzania Ollama: {str(e)}")
            return False

    def callback(self, in_data, frame_count, time_info, status):
        if self.recording:
            if self.record_all_users:
                # Nagrywaj wszystkich (nie rozróżniamy użytkowników w ten sposób)
                if "all" not in self.frames:
                    self.frames["all"] = []
                self.frames["all"].append(in_data)
            elif self.targeted_user_id:
                # Nagrywaj konkretnego użytkownika (nie rozróżniamy tutaj - będziemy filtrować na poziomie Discord)
                if str(self.targeted_user_id) not in self.frames:
                    self.frames[str(self.targeted_user_id)] = []
                self.frames[str(self.targeted_user_id)].append(in_data)
        return (in_data, pyaudio.paContinue)

    # Obsługa tradycyjnych komend (dla kompatybilności wstecznej)
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
    async def record_user(self, ctx, member: discord.Member = None):
        """Rozpoczyna nagrywanie konkretnego użytkownika"""
        if self.recording:
            await ctx.send("Nagrywanie już trwa! Użyj !stop aby zakończyć.")
            return

        # Sprawdź czy użytkownik jest na kanale głosowym
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        # Jeśli nie podano członka, nagraj autora
        target_user = member if member else ctx.author

        try:
            # Dołącz do kanału głosowego
            channel = ctx.author.voice.channel
            self.current_channel = channel
            voice_client = await channel.connect()

            # Ustaw tryb nagrywania
            self.record_all_users = False
            self.targeted_user_id = target_user.id
            self.frames = {}  # Wyczyść ramki

            # Rozpocznij nagrywanie
            self.recording = True

            # Konfiguracja streamu audio
            default_input = self.audio.get_default_input_device_info()

            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=int(default_input['defaultSampleRate']),
                input=True,
                input_device_index=default_input['index'],
                frames_per_buffer=1024,
                stream_callback=self.callback
            )

            self.stream.start_stream()
            await ctx.send(f"Rozpoczęto nagrywanie użytkownika {target_user.display_name}! Użyj !stop aby zakończyć.")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            self.recording = False
            self.targeted_user_id = None
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

    @commands.command()
    async def record_all(self, ctx):
        """Rozpoczyna nagrywanie wszystkich na kanale"""
        if self.recording:
            await ctx.send("Nagrywanie już trwa! Użyj !stop aby zakończyć.")
            return

        # Sprawdź czy użytkownik jest na kanale głosowym
        if not ctx.author.voice:
            await ctx.send("Musisz być na kanale głosowym!")
            return

        try:
            # Dołącz do kanału głosowego
            channel = ctx.author.voice.channel
            self.current_channel = channel
            voice_client = await channel.connect()

            # Ustaw tryb nagrywania
            self.record_all_users = True
            self.targeted_user_id = None
            self.frames = {}  # Wyczyść ramki

            # Rozpocznij nagrywanie
            self.recording = True

            # Konfiguracja streamu audio
            default_input = self.audio.get_default_input_device_info()

            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=int(default_input['defaultSampleRate']),
                input=True,
                input_device_index=default_input['index'],
                frames_per_buffer=1024,
                stream_callback=self.callback
            )

            self.stream.start_stream()
            await ctx.send(f"Rozpoczęto nagrywanie wszystkich na kanale {channel.name}! Użyj !stop aby zakończyć.")

        except Exception as e:
            await ctx.send(f"Wystąpił błąd: {str(e)}")
            self.recording = False
            self.record_all_users = False
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
            recordings_dir = os.path.join(os.getcwd(), "recordings")
            os.makedirs(recordings_dir, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

            # Określ jaki tryb nagrywania był używany
            if self.record_all_users:
                mode = "all"
                frames_to_save = self.frames.get("all", [])
                filename = os.path.join(recordings_dir, f"recording_all_{timestamp}.wav")
            elif self.targeted_user_id:
                mode = f"user_{self.targeted_user_id}"
                frames_to_save = self.frames.get(str(self.targeted_user_id), [])
                filename = os.path.join(recordings_dir, f"recording_user_{self.targeted_user_id}_{timestamp}.wav")
            else:
                await ctx.send("Błąd: Nie można określić trybu nagrywania.")
                return

            print(f"Zapisuję plik: {filename}")  # Debug info

            if not frames_to_save:
                await ctx.send("Brak danych audio do zapisania.")

                # Rozłącz się z kanału głosowego
                for vc in self.bot.voice_clients:
                    await vc.disconnect()

                return

            print("Rozpoczynam zapis pliku WAV...")  # Debug info
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(int(self.audio.get_default_input_device_info()['defaultSampleRate']))
                audio_data = b''.join(frames_to_save)
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

                # Zapisz transkrypcję dla użytkownika, który wywołał !stop
                user_id = ctx.author.id
                self.transcriptions[user_id] = transcription

                # Wyślij plik audio
                await ctx.send("Nagranie zostało zapisane!", file=discord.File(filename))

                # Wyślij transkrypcję
                await ctx.send("Transkrypcja:")
                for i in range(0, len(transcription), 1900):
                    await ctx.send(transcription[i:i + 1900])

                # Automatycznie generuj podsumowanie
                if len(transcription) > 30:  # Jeśli jest co podsumowywać
                    await ctx.send("Generuję podsumowanie...")
                    summary = await self.summarize_with_ollama(transcription)
                    await ctx.send(f"**Podsumowanie:**\n{summary}")

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
    async def change_model(self, ctx, model_name):
        """Zmienia model Ollama używany do podsumowań"""
        old_model = self.ollama_model
        self.ollama_model = model_name

        # Sprawdź czy model istnieje i pobierz go jeśli nie
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                model_names = [model.get("name") for model in available_models]

                if model_name not in model_names:
                    await ctx.send(f"Model {model_name} nie jest zainstalowany. Rozpoczynam pobieranie...")

                    # Użyj subprocess do pobrania modelu w tle
                    subprocess.Popen(["ollama", "pull", model_name])
                    await ctx.send(f"Pobieranie modelu {model_name} rozpoczęte w tle. Może to potrwać kilka minut.")
                else:
                    await ctx.send(f"Zmieniono model z {old_model} na {model_name}.")
            else:
                await ctx.send("Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.")
        except Exception as e:
            await ctx.send(f"Błąd podczas zmiany modelu: {str(e)}")
            self.ollama_model = old_model  # Przywróć poprzedni model

    @commands.command()
    async def summarize(self, ctx):
        """Tworzy podsumowanie ostatniej transkrypcji"""
        user_id = ctx.author.id
        if user_id not in self.transcriptions:
            await ctx.send("Nie znaleziono transkrypcji do podsumowania!")
            return

        transcription = self.transcriptions[user_id]

        await ctx.send("Generuję podsumowanie...")
        summary = await self.summarize_with_ollama(transcription)

        await ctx.send(f"**Podsumowanie:**\n{summary}")

    @commands.command()
    async def list_models(self, ctx):
        """Wyświetla dostępne modele Ollama"""
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                available_models = response.json().get("models", [])
                if not available_models:
                    await ctx.send("Brak dostępnych modeli Ollama.")
                    return

                model_info = []
                for model in available_models:
                    name = model.get("name", "Nieznany")
                    size = model.get("size", 0) / (1024 * 1024 * 1024)  # Konwersja na GB
                    model_info.append(f"• {name} ({size:.2f} GB)")

                await ctx.send("**Dostępne modele Ollama:**\n" + "\n".join(model_info))
                await ctx.send(f"Aktualnie używany model: **{self.ollama_model}**")
            else:
                await ctx.send("Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.")
        except Exception as e:
            await ctx.send(f"Błąd podczas pobierania listy modeli: {str(e)}")

    @commands.command(name="help")
    async def help_command(self, ctx, command_name=None):
        """Wyświetla listę dostępnych komend lub szczegółowe informacje o wybranej komendzie"""

        if command_name:
            # Szukaj podanej komendy
            command = self.bot.get_command(command_name)
            if command:
                embed = discord.Embed(
                    title=f"Pomoc dla komendy: {command.name}",
                    description=command.help or "Brak opisu dla tej komendy.",
                    color=discord.Color.blue()
                )

                # Dodaj składnię komendy
                syntax = f"{self.bot.command_prefix}{command.name}"
                if command.signature:
                    syntax += f" {command.signature}"
                embed.add_field(name="Składnia", value=f"`{syntax}`", inline=False)

                # Dodaj informację o slash komendzie
                embed.add_field(name="Slash komenda", value=f"Ta komenda jest również dostępna jako `/{command.name}`",
                                inline=False)

                await ctx.send(embed=embed)
            else:
                await ctx.send(
                    f"❌ Nie znaleziono komendy `{command_name}`. Użyj `!help` lub `/help` aby zobaczyć dostępne komendy.")
        else:
            # Pokaż wszystkie komendy
            embed = discord.Embed(
                title="Lista dostępnych komend",
                description=f"Możesz użyć zarówno prefixu `{self.bot.command_prefix}` jak i slash komend `/`\nZalecane jest używanie slash komend `/`.",
                color=discord.Color.blue()
            )

            # Podziel komendy na kategorie
            recording_commands = []
            ollama_commands = []
            utility_commands = []

            for command in sorted(self.bot.commands, key=lambda x: x.name):
                if command.name in ['record_user', 'record_all', 'stop']:
                    recording_commands.append(f"`{command.name}`")
                elif command.name in ['change_model', 'summarize', 'list_models']:
                    ollama_commands.append(f"`{command.name}`")
                else:
                    utility_commands.append(f"`{command.name}`")

            if recording_commands:
                embed.add_field(
                    name="🎙️ Nagrywanie",
                    value=", ".join(recording_commands),
                    inline=False
                )

            if ollama_commands:
                embed.add_field(
                    name="🤖 Ollama i przetwarzanie",
                    value=", ".join(ollama_commands),
                    inline=False
                )

            if utility_commands:
                embed.add_field(
                    name="🛠️ Pozostałe",
                    value=", ".join(utility_commands),
                    inline=False
                )

            await ctx.send(embed=embed)

    async def summarize_with_ollama(self, text):
        """Używa Ollama do podsumowania tekstu"""
        try:
            # Przygotuj prompt dla modelu
            prompt = f"""
            Poniżej znajduje się transkrypcja rozmowy. Przygotuj zwięzłe podsumowanie najważniejszych punktów:

            {text}

            Podsumowanie:
            """

            # Wywołaj API Ollamy
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False
                }
            )

            if response.status_code == 200:
                return response.json()['response']
            else:
                print(f"Błąd API Ollama: {response.status_code}")
                return "Nie udało się wygenerować podsumowania."

        except Exception as e:
            print(f"Błąd podczas generowania podsumowania: {str(e)}")
            return f"Błąd podczas generowania podsumowania: {str(e)}"

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


# Rejestracja slash komend

# Slash komenda help
@bot.tree.command(name="help", description="Wyświetla listę komend i informacje o nich")
@app_commands.describe(command="Nazwa komendy dla której chcesz uzyskać pomoc")
async def help_slash(interaction: discord.Interaction, command: Optional[str] = None):
    if command:
        # Szukaj podanej komendy
        cmd = bot.get_command(command)
        if cmd:
            embed = discord.Embed(
                title=f"Pomoc dla komendy: {cmd.name}",
                description=cmd.help or "Brak opisu dla tej komendy.",
                color=discord.Color.blue()
            )

            # Dodaj składnię komendy
            syntax = f"/{cmd.name}"
            if cmd.signature:
                params = cmd.signature.strip()
                if params:
                    syntax += f" {params}"
            embed.add_field(name="Składnia", value=f"`{syntax}`", inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ Nie znaleziono komendy `{command}`. Użyj `/help` bez argumentu aby zobaczyć dostępne komendy.",
                ephemeral=True
            )
    else:
        # Pokaż wszystkie komendy
        embed = discord.Embed(
            title="Lista dostępnych komend",
            description="Wszystkie komendy są dostępne jako slash komendy zaczynające się od `/`",
            color=discord.Color.blue()
        )

        # Podziel komendy na kategorie
        recording_commands = []
        ollama_commands = []
        utility_commands = []

        # Sprawdź dostępne slash komendy
        for cmd_name in ['record_user', 'record_all', 'stop']:
            recording_commands.append(f"`/{cmd_name}`")

        for cmd_name in ['change_model', 'summarize', 'list_models']:
            ollama_commands.append(f"`/{cmd_name}`")

        for cmd_name in ['help', 'context', 'show_context']:
            utility_commands.append(f"`/{cmd_name}`")

        if recording_commands:
            embed.add_field(
                name="🎙️ Nagrywanie",
                value=", ".join(recording_commands),
                inline=False
            )

        if ollama_commands:
            embed.add_field(
                name="🤖 Ollama i przetwarzanie",
                value=", ".join(ollama_commands),
                inline=False
            )

        if utility_commands:
            embed.add_field(
                name="🛠️ Pozostałe",
                value=", ".join(utility_commands),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


# Slash komenda context
@bot.tree.command(name="context", description="Ustawia kontekst dla użytkownika")
@app_commands.describe(new_context="Nowy kontekst dla użytkownika")
async def context_slash(interaction: discord.Interaction, new_context: str):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    user_id = interaction.user.id
    cog.user_contexts[user_id] = new_context
    await interaction.response.send_message(f"Ustawiono nowy kontekst dla użytkownika {interaction.user.name}",
                                            ephemeral=True)


# Slash komenda show_context
@bot.tree.command(name="show_context", description="Pokazuje aktualny kontekst użytkownika")
async def show_context_slash(interaction: discord.Interaction):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    user_id = interaction.user.id
    context = cog.user_contexts.get(user_id, "Brak ustawionego kontekstu")
    await interaction.response.send_message(f"Twój aktualny kontekst:\n{context}", ephemeral=True)


# Slash komenda record_user
@bot.tree.command(name="record_user", description="Rozpoczyna nagrywanie konkretnego użytkownika")
@app_commands.describe(member="Użytkownik do nagrania (opcjonalnie, domyślnie ty)")
async def record_user_slash(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    if cog.recording:
        await interaction.followup.send("Nagrywanie już trwa! Użyj /stop aby zakończyć.")
        return

    # Sprawdź czy użytkownik jest na kanale głosowym
    if not interaction.user.voice:
        await interaction.followup.send("Musisz być na kanale głosowym!")
        return

    # Jeśli nie podano członka, nagraj autora
    target_user = member if member else interaction.user

    try:
        # Dołącz do kanału głosowego
        channel = interaction.user.voice.channel
        cog.current_channel = channel
        voice_client = await channel.connect()

        # Ustaw tryb nagrywania
        cog.record_all_users = False
        cog.targeted_user_id = target_user.id
        cog.frames = {}  # Wyczyść ramki

        # Rozpocznij nagrywanie
        cog.recording = True

        # Konfiguracja streamu audio
        default_input = cog.audio.get_default_input_device_info()

        cog.stream = cog.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=int(default_input['defaultSampleRate']),
            input=True,
            input_device_index=default_input['index'],
            frames_per_buffer=1024,
            stream_callback=cog.callback
        )

        cog.stream.start_stream()
        await interaction.followup.send(
            f"Rozpoczęto nagrywanie użytkownika {target_user.display_name}! Użyj /stop aby zakończyć.")

    except Exception as e:
        await interaction.followup.send(f"Wystąpił błąd: {str(e)}")
        cog.recording = False
        cog.targeted_user_id = None
        if cog.stream:
            cog.stream.stop_stream()
            cog.stream.close()


# Slash komenda record_all
@bot.tree.command(name="record_all", description="Rozpoczyna nagrywanie wszystkich na kanale")
async def record_all_slash(interaction: discord.Interaction):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    if cog.recording:
        await interaction.followup.send("Nagrywanie już trwa! Użyj /stop aby zakończyć.")
        return

    # Sprawdź czy użytkownik jest na kanale głosowym
    if not interaction.user.voice:
        await interaction.followup.send("Musisz być na kanale głosowym!")
        return

    try:
        # Dołącz do kanału głosowego
        channel = interaction.user.voice.channel
        cog.current_channel = channel
        voice_client = await channel.connect()

        # Ustaw tryb nagrywania
        cog.record_all_users = True
        cog.targeted_user_id = None
        cog.frames = {}  # Wyczyść ramki

        # Rozpocznij nagrywanie
        cog.recording = True

        # Konfiguracja streamu audio
        default_input = cog.audio.get_default_input_device_info()

        cog.stream = cog.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=int(default_input['defaultSampleRate']),
            input=True,
            input_device_index=default_input['index'],
            frames_per_buffer=1024,
            stream_callback=cog.callback
        )

        cog.stream.start_stream()
        await interaction.followup.send(
            f"Rozpoczęto nagrywanie wszystkich na kanale {channel.name}! Użyj /stop aby zakończyć.")

    except Exception as e:
        await interaction.followup.send(f"Wystąpił błąd: {str(e)}")
        cog.recording = False
        cog.record_all_users = False
        if cog.stream:
            cog.stream.stop_stream()
            cog.stream.close()


# Slash komenda stop
@bot.tree.command(name="stop", description="Zatrzymuje nagrywanie")
async def stop_slash(interaction: discord.Interaction):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    if not cog.recording:
        await interaction.followup.send("Nie ma aktywnego nagrywania!")
        return

    try:
        cog.recording = False

        # Zatrzymaj stream
        if cog.stream:
            cog.stream.stop_stream()
            cog.stream.close()

        # Zapisz plik audio
        recordings_dir = os.path.join(os.getcwd(), "recordings")
        os.makedirs(recordings_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Określ jaki tryb nagrywania był używany
        if cog.record_all_users:
            mode = "all"
            frames_to_save = cog.frames.get("all", [])
            filename = os.path.join(recordings_dir, f"recording_all_{timestamp}.wav")
        elif cog.targeted_user_id:
            mode = f"user_{cog.targeted_user_id}"
            frames_to_save = cog.frames.get(str(cog.targeted_user_id), [])
            filename = os.path.join(recordings_dir, f"recording_user_{cog.targeted_user_id}_{timestamp}.wav")
        else:
            await interaction.followup.send("Błąd: Nie można określić trybu nagrywania.")
            return

        print(f"Zapisuję plik: {filename}")  # Debug info

        if not frames_to_save:
            await interaction.followup.send("Brak danych audio do zapisania.")

            # Rozłącz się z kanału głosowego
            for vc in bot.voice_clients:
                await vc.disconnect()

            return

        print("Rozpoczynam zapis pliku WAV...")  # Debug info
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(cog.audio.get_sample_size(pyaudio.paInt16))
            wf.setframerate(int(cog.audio.get_default_input_device_info()['defaultSampleRate']))
            audio_data = b''.join(frames_to_save)
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
        for vc in bot.voice_clients:
            await vc.disconnect()

        try:
            # Najpierw wykonaj transkrypcję
            await interaction.followup.send("Rozpoczynam transkrypcję audio...")
            transcription = await cog.transcribe_audio(filename)

            # Zapisz transkrypcję dla użytkownika, który wywołał /stop
            user_id = interaction.user.id
            cog.transcriptions[user_id] = transcription

            # Wyślij plik audio
            await interaction.followup.send("Nagranie zostało zapisane!", file=discord.File(filename))

            # Wyślij transkrypcję
            await interaction.followup.send("Transkrypcja:")
            for i in range(0, len(transcription), 1900):
                await interaction.followup.send(transcription[i:i + 1900])

            # Automatycznie generuj podsumowanie
            if len(transcription) > 30:  # Jeśli jest co podsumowywać
                await interaction.followup.send("Generuję podsumowanie...")
                summary = await cog.summarize_with_ollama(transcription)
                await interaction.followup.send(f"**Podsumowanie:**\n{summary}")

        except Exception as e:
            await interaction.followup.send(f"Błąd podczas przetwarzania: {str(e)}")

        finally:
            # Upewnij się że plik istnieje przed próbą usunięcia
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception as e:
                    print(f"Nie można usunąć pliku: {str(e)}")

    except Exception as e:
        await interaction.followup.send(f"Wystąpił błąd podczas zatrzymywania nagrywania: {str(e)}")


# Slash komenda change_model
@bot.tree.command(name="change_model", description="Zmienia model Ollama używany do podsumowań")
@app_commands.describe(model_name="Nazwa modelu do użycia")
async def change_model_slash(interaction: discord.Interaction, model_name: str):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    old_model = cog.ollama_model
    cog.ollama_model = model_name

    # Sprawdź czy model istnieje i pobierz go jeśli nie
    try:
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            available_models = response.json().get("models", [])
            model_names = [model.get("name") for model in available_models]

            if model_name not in model_names:
                await interaction.response.send_message(
                    f"Model {model_name} nie jest zainstalowany. Rozpoczynam pobieranie...", ephemeral=False)

                # Użyj subprocess do pobrania modelu w tle
                subprocess.Popen(["ollama", "pull", model_name])
                await interaction.followup.send(
                    f"Pobieranie modelu {model_name} rozpoczęte w tle. Może to potrwać kilka minut.")
            else:
                await interaction.response.send_message(f"Zmieniono model z {old_model} na {model_name}.",
                                                        ephemeral=False)
        else:
            await interaction.response.send_message(
                "Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Błąd podczas zmiany modelu: {str(e)}", ephemeral=True)
        cog.ollama_model = old_model  # Przywróć poprzedni model


# Slash komenda summarize
@bot.tree.command(name="summarize", description="Tworzy podsumowanie ostatniej transkrypcji")
async def summarize_slash(interaction: discord.Interaction):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in cog.transcriptions:
        await interaction.response.send_message("Nie znaleziono transkrypcji do podsumowania!", ephemeral=True)
        return

    transcription = cog.transcriptions[user_id]

    await interaction.response.send_message("Generuję podsumowanie...", ephemeral=False)
    summary = await cog.summarize_with_ollama(transcription)

    await interaction.followup.send(f"**Podsumowanie:**\n{summary}")


# Slash komenda list_models
@bot.tree.command(name="list_models", description="Wyświetla dostępne modele Ollama")
async def list_models_slash(interaction: discord.Interaction):
    # Pobierz instancję AudioRecorder
    cog = bot.get_cog('AudioRecorder')
    if not cog:
        await interaction.response.send_message("Błąd: moduł AudioRecorder nie jest dostępny", ephemeral=True)
        return

    try:
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            available_models = response.json().get("models", [])
            if not available_models:
                await interaction.response.send_message("Brak dostępnych modeli Ollama.", ephemeral=True)
                return

            model_info = []
            for model in available_models:
                name = model.get("name", "Nieznany")
                size = model.get("size", 0) / (1024 * 1024 * 1024)  # Konwersja na GB
                model_info.append(f"• {name} ({size:.2f} GB)")

            await interaction.response.send_message("**Dostępne modele Ollama:**\n" + "\n".join(model_info),
                                                    ephemeral=False)
            await interaction.followup.send(f"Aktualnie używany model: **{cog.ollama_model}**")
        else:
            await interaction.response.send_message(
                "Nie można połączyć z Ollama API. Upewnij się, że serwer jest uruchomiony.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Błąd podczas pobierania listy modeli: {str(e)}", ephemeral=True)


# Obsługa błędów slash komend
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandNotFound):
        await interaction.response.send_message(
            "❌ Nie znaleziono tej komendy slash. Użyj `/help` aby zobaczyć dostępne komendy.",
            ephemeral=True
        )
    else:
        # Zapisz szczegóły błędu do logów
        error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(f"Błąd w slash komendzie: {error_traceback}")

        try:
            await interaction.response.send_message(
                f"❌ Wystąpił błąd: {str(error)}",
                ephemeral=True
            )
        except:
            await interaction.followup.send(
                f"❌ Wystąpił błąd: {str(error)}",
                ephemeral=True
            )


# Obsługa błędów dla zwykłych komend
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❌ Nieznana komenda: `{ctx.message.content}`. Użyj `/help` aby zobaczyć dostępne komendy.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"❌ Brakujący argument: {error.param.name}. Użyj `/help {ctx.command.name}` aby sprawdzić poprawną składnię.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Nieprawidłowy argument. Użyj `/help {ctx.command.name}` aby sprawdzić poprawną składnię.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ Nie znaleziono użytkownika. Sprawdź czy nazwa użytkownika jest poprawna.")
    else:
        await ctx.send(f"❌ Wystąpił błąd: {str(error)}")
        # Zapisz szczegóły błędu do logów
        error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(f"Błąd w komendzie: {error_traceback}")


@bot.event
async def on_ready():
    print(f'Bot jest gotowy: {bot.user}')
    await bot.add_cog(AudioRecorder(bot))
    # Ustaw status bota
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))


if __name__ == "__main__":
    # Używaj zmiennej środowiskowej lub zastąp ten token bezpiecznym sposobem
    TOKEN = os.environ.get("DISCORD_TOKEN", "twój-token-tutaj")
    bot.run(TOKEN)