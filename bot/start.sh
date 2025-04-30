#!/bin/bash

# Uruchom serwer Ollama w tle
ollama serve &

# Poczekaj chwilę, aby Ollama się uruchomiła
sleep 5

# Pobierz mały model do podsumowań (około 4GB)
ollama pull gemma:2b

# Uruchom bota Discord
python3 script.py