# FilmPad v0.4 Quickstart (Linux)

This guide is for first-time users.

## 1) Download and run

```bash
chmod +x FilmPad-v0.4-x86_64.AppImage
./FilmPad-v0.4-x86_64.AppImage
```

## 2) If AppImage does not open

Run FilmPad from source fallback:

```bash
python3 filmpad.py
```

If Python/Tkinter are missing:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-tk
```

## 3) Optional AI setup

To use Local AI features, install Ollama and at least one model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral:7b
```

## 4) Verify your environment (recommended)

```bash
chmod +x doctor.sh
./doctor.sh
```

`doctor.sh` prints PASS/FAIL and shows install commands for missing dependencies.
