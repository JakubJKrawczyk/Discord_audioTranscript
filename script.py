import discord
from discord import app_commands
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
import threading
import numpy as np
import librosa

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

    @app_commands.command(name="help", description="Wyświetla pomoc dotyczącą wszystkich dostępnych komend")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Pomoc - Dostępne komendy",
            description="Oto lista wszystkich dostępnych komend:",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="/help",
            value="Wyświetla tę pomoc z listą wszystkich dostępnych komend.",
            inline=False
        )

        embed.add_field(
            name="/context",
            value="Ustawia kontekst dla użytkownika, który będzie używany podczas przetwarzania transkrypcji.",
            inline=False
        )

        embed.add_field(
            name="/show_context",
            value="Pokazuje aktualnie ustawiony kontekst dla użytkownika.",
            inline=False
        )

        embed.add_field(
            name="/record",
            value="Rozpoczyna nagrywanie audio. Bot dołączy do Twojego kanału głosowego i zacznie nagrywać.",
            inline=False
        )

        embed.add_field(
            name="/stop",
            value="Zatrzymuje nagrywanie, zapisuje plik audio, transkrybuje go i wysyła wynik.",
            inline=False
        )

        embed.add_field(
            name="/process",
            value="Przetwarza ostatnią transkrypcję przez model Ollama z uwzględnieniem ustalonego kontekstu.",
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="context", description="Ustawia kontekst dla użytkownika")
    @app_commands.describe(new_context="Nowy kontekst do ustawienia")
    async def context(self, interaction: discord.Interaction, new_context: str):
        user_id = interaction.user.id
        self.user_contexts[user_id] = new_context
        await interaction.response.send_message(f"Ustawiono nowy kontekst dla użytkownika {interaction.user.name}")

    @app_commands.command(name="show_context", description="Pokazuje aktualny kontekst użytkownika")
    async def show_context(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        context = self.user_contexts.get(user_id, "Brak ustawionego kontekstu")
        await interaction.response.send_message(f"Twój aktualny kontekst:\n{context}")

    @app_commands.command(name="record", description="Rozpoczyna nagrywanie audio")
    async def record(self, interaction: discord.Interaction):
        if self.recording:
            await interaction.response.send_message("Nagrywanie już trwa!")
            return

        # Check if user is in a voice channel
        if not interaction.user.voice:
            await interaction.response.send_message("Musisz być na kanale głosowym!")
            return

        self.current_recording_user = interaction.user.id

        try:
            # Join voice channel
            channel = interaction.user.voice.channel
            await interaction.response.send_message("Rozpoczynam nagrywanie! Użyj /stop aby zakończyć.")
            voice_client = await channel.connect()

            # Start recording
            self.recording = True
            self.frames = []

            # Audio stream configuration
            # Find default input device
            default_input = self.audio.get_default_input_device_info()

            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,  # Changed to mono
                rate=int(default_input['defaultSampleRate']),  # Use default sample rate
                input=True,
                input_device_index=default_input['index'],  # Use default device
                frames_per_buffer=1024,
                stream_callback=self.callback
            )

            self.stream.start_stream()

        except Exception as e:
            await interaction.followup.send(f"Wystąpił błąd: {str(e)}")
            self.recording = False
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

    @app_commands.command(name="stop", description="Zatrzymuje nagrywanie i transkrybuje audio")
    async def stop(self, interaction: discord.Interaction):
        if not self.recording:
            await interaction.response.send_message("Nie ma aktywnego nagrywania!")
            return

        await interaction.response.defer(thinking=True)

        try:
            self.recording = False

            # Stop stream
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

            # Save audio file
            # Create recordings directory if it doesn't exist
            recordings_dir = os.path.join(os.getcwd(), "recordings")
            os.makedirs(recordings_dir, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(recordings_dir, f"recording_{timestamp}.wav")
            print(f"Saving file: {filename}")  # Debug info

            print("Starting WAV file writing...")  # Debug info
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(int(self.audio.get_default_input_device_info()['defaultSampleRate']))
                audio_data = b''.join(self.frames)
                print(f"Audio data size: {len(audio_data)} bytes")  # Debug info
                wf.writeframes(audio_data)

            # Check if file was created and has appropriate size
            if not os.path.exists(filename):
                raise FileNotFoundError(f"File {filename} was not created")

            file_size = os.path.getsize(filename)
            print(f"File was saved, size: {file_size} bytes")  # Debug info

            if file_size == 0:
                raise ValueError("Audio file is empty")

            # Disconnect from voice channel
            for vc in self.bot.voice_clients:
                await vc.disconnect()

            try:
                # First transcribe
                await interaction.followup.send("Rozpoczynam transkrypcję audio...")
                transcription = await self.transcribe_audio(filename)

                # Save transcription for user
                if self.current_recording_user:
                    self.transcriptions[self.current_recording_user] = transcription

                # Send audio file
                await interaction.followup.send("Nagranie zostało zapisane!", file=discord.File(filename))

                # Send transcription
                await interaction.followup.send("Transkrypcja:")
                for i in range(0, len(transcription), 1900):
                    await interaction.followup.send(transcription[i:i + 1900])

            except Exception as e:
                await interaction.followup.send(f"Błąd podczas przetwarzania: {str(e)}")

            finally:
                # Make sure the file exists before attempting to delete
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except Exception as e:
                        print(f"Cannot delete file: {str(e)}")

        except Exception as e:
            await interaction.followup.send(f"Wystąpił błąd podczas zatrzymywania nagrywania: {str(e)}")

    @app_commands.command(name="process", description="Przetwarza transkrypcję przez model Ollama")
    async def process(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id not in self.transcriptions:
            await interaction.response.send_message("Nie znaleziono transkrypcji do przetworzenia!")
            return

        await interaction.response.defer(thinking=True)

        context = self.user_contexts.get(user_id, "")
        transcription = self.transcriptions[user_id]

        # Prepare prompt for Ollama
        prompt = f"Context: {context}\nText: {transcription}\n"

        try:
            # Call Ollama API
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

                # Save response to file
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"response_{timestamp}.txt"

                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"Original Context:\n{context}\n\n")
                    f.write(f"Transcription:\n{transcription}\n\n")
                    f.write(f"Response:\n{ollama_response}")

                # Send file
                await interaction.followup.send(
                    "Przetworzono tekst przez Ollamę!",
                    file=discord.File(filename)
                )

                # Delete file
                os.remove(filename)

            else:
                await interaction.followup.send(f"Błąd podczas przetwarzania przez Ollamę: {response.status_code}")

        except Exception as e:
            await interaction.followup.send(f"Wystąpił błąd podczas przetwarzania: {str(e)}")

    async def transcribe_audio(self, filepath):
        """Transcribes audio file to text"""
        print(f"Starting transcription of file: {filepath}")

        try:
            abs_path = os.path.abspath(filepath)
            print(f"Full path to file: {abs_path}")

            if not os.path.exists(abs_path):
                print(f"ERROR: File does not exist at path: {abs_path}")
                return f"Błąd transkrypcji: Plik nie istnieje w ścieżce {abs_path}"

            file_size = os.path.getsize(abs_path)
            print(f"File size: {file_size} bytes")

            if file_size == 0:
                print("ERROR: File is empty")
                return "Błąd transkrypcji: Plik jest pusty"

            def transcribe():
                try:
                    print("Loading audio file...")
                    # Load audio with specific data type
                    audio_data, sample_rate = librosa.load(abs_path, sr=16000, dtype=np.float32)
                    print(f"Audio file loaded, sample rate: {sample_rate}Hz")

                    # Normalize audio
                    audio_data = librosa.util.normalize(audio_data)

                    print("Running Whisper model...")
                    result = self.whisper_model.transcribe(
                        audio_data,
                        language="pl",  # Set language to Polish
                        fp16=False  # Disable FP16
                    )
                    print("Transcription completed successfully")
                    return result
                except Exception as e:
                    print(f"ERROR during transcription: {str(e)}")
                    raise

            print("Starting transcription in separate thread...")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, transcribe)

            if not result or "text" not in result:
                print("ERROR: No text in transcription result")
                return "Błąd transkrypcji: Brak tekstu w wyniku"

            print("Transcription completed successfully")
            return result["text"]

        except Exception as e:
            error_msg = f"Błąd podczas transkrypcji: {str(e)}"
            print(f"CRITICAL ERROR: {error_msg}")
            print(f"File details:")
            print(f"- Path: {abs_path}")
            print(f"- Exists: {os.path.exists(abs_path)}")
            if os.path.exists(abs_path):
                print(f"- Size: {os.path.getsize(abs_path)}")
                print(f"- Permissions: {oct(os.stat(abs_path).st_mode)[-3:]}")
            return error_msg


@bot.event
async def on_ready():
    print(f'Bot is ready: {bot.user}')
    await bot.add_cog(AudioRecorder(bot))
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


# Run the bot
bot.run("<your-token>")