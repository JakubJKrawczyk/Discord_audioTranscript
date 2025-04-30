#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import wave
import numpy as np
import librosa
import torch

class AudioProcessor:
    """Klasa do przetwarzania dźwięku i przygotowywania danych dla modelu Whisper"""

    def __init__(self):
        self.sample_rate = 16000  # Whisper używa 16kHz

    def load_audio(self, file_path):
        """Wczytuje plik audio do numpy array z odpowiednim próbkowaniem"""
        try:
            audio_data, sr = librosa.load(file_path, sr=self.sample_rate, dtype=np.float32)
            return audio_data, sr
        except Exception as e:
            print(f"Błąd podczas wczytywania pliku audio {file_path}: {str(e)}")
            raise

    def normalize_audio(self, audio_data):
        """Normalizuje amplitudę audio do zakresu [-1, 1]"""
        return librosa.util.normalize(audio_data)

    def convert_to_tensor(self, audio_data, device):
        """Konwertuje audio numpy array do tensora PyTorch i przenosi na odpowiednie urządzenie"""
        tensor = torch.from_numpy(audio_data).float()
        return tensor.to(device)

    def prepare_audio_for_whisper(self, file_path, device):
        """Przygotowuje plik audio do przetwarzania przez model Whisper"""
        audio_data, sr = self.load_audio(file_path)
        audio_data = self.normalize_audio(audio_data)

        if device.type == 'cuda':
            # Przenosimy dane na GPU tylko jeśli używamy CUDA
            return self.convert_to_tensor(audio_data, device)
        else:
            # Dla CPU nie musimy konwertować do tensora, whisper poradzi sobie z numpy array
            return audio_data

    def save_audio(self, frames, filepath, channels=1, sample_width=2, sample_rate=16000):
        """Zapisuje dane audio do pliku WAV"""
        try:
            # Upewnij się, że katalog istnieje
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            # Zapisz plik WAV
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(sample_rate)

                if isinstance(frames, list):
                    # Jeśli frames to lista fragmentów dźwięku
                    audio_data = b''.join(frames)
                else:
                    # Jeśli frames to już połączone dane
                    audio_data = frames

                wf.writeframes(audio_data)

            return True, filepath
        except Exception as e:
            print(f"Błąd podczas zapisywania audio do {filepath}: {str(e)}")
            return False, str(e)