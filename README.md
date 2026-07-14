# FilmPad

FilmPad is a screenplay editor and local AI adaptation tool built with Python and Tkinter. It combines a formatted screenplay writer with a Local AI workspace for adapting prose source text into screenplay scenes, and a Writer AI assistant for in-editor rewrites — all powered by locally running Ollama models, with no cloud dependency.

## Download

> **Latest release: v0.9** — [All releases](https://github.com/idealiner/filmpad/releases)

| Platform | Download |
|----------|----------|
| **Linux x86_64** | [FilmPad-v0.9-x86_64.AppImage](https://github.com/idealiner/filmpad/releases/download/v0.9/FilmPad-v0.9-x86_64.AppImage) |
| **Diagnostics** | [doctor.sh](https://github.com/idealiner/filmpad/releases/download/v0.9/doctor.sh) |
| **Prompt templates** | [FilmPad-v0.9-templates.zip](https://github.com/idealiner/filmpad/releases/download/v0.9/FilmPad-v0.9-templates.zip) |

Windows and macOS builds are not yet available. The app can be run from source on any platform — see [Running from source](#running-from-source) below.

Quick start (Linux):

```bash
chmod +x FilmPad-v0.6-x86_64.AppImage
./FilmPad-v0.6-x86_64.AppImage
```

The AppImage bundles Python and Tkinter. Only [Ollama](https://ollama.com) needs to be installed separately.

If the app does not launch on first try, download and run `doctor.sh` from the table above.

---

## Releases

### v0.9 — Dictation + Stability
*2026-07-13*

- **Speech-to-text dictation at cursor** — 🎤 Dictate / ⏹ Stop / ✕ Cancel toolbar buttons; records via `arecord` and transcribes with [whisper.cpp](https://github.com/ggerganov/whisper.cpp) fully offline; text inserted at the cursor as one undoable step; entire block hidden when tools are absent
- **Dictation Settings accordion** — configurable `whisper-cli` executable path, GGML model file (`ggml-tiny.en.bin` default), language, and microphone device
- **Auto-save after every SS / TP scene** — Script Supervisor and Typewriter Postscript now save silently after each applied scene; log appends `✓ saved HH:MM:SS` or `⚠ unsaved`; sidebar status shows *Script Supervisor — scene X/Y | saved: HH:MM:SS* in real time
- **Save-before-start prompt** — Auto Transcript, Script Supervisor, and Typewriter Postscript prompt to save the file before starting if no file path is set
- **5-minute timeout on all model calls** — Writer AI, Auto Transcript, Script Supervisor (was 90 s), and Typewriter Postscript (was 180 s) all cap each Ollama call at 300 s; a stalled model is killed cleanly and logged as `timeout — skipped`
- **Undo history cleared after each pipeline scene** — `edit_reset()` after every Auto Transcript block and every SS / TP scene keeps RAM bounded during long unattended runs
- **doctor.sh Section 8** — checks `arecord`, `whisper-cli`, and GGML model files with sizes and direct download / build instructions

### v0.7.1 — Polish & Reliability
*2026-06-28*

- **Centred transitions** — `CUT TO:`, `FADE TO:` and all other Transition blocks are now centred in the script editor
- **Script Supervisor reliability** — comparison button bar is always visible; LLM output no longer writes annotations, correction notes, or parenthetical remarks into the script
- **Progress detail line** — overlay shows *Scene N of T — LX–Y of Z* and *Block N — LX–Y of Z* while processing
- **Overlay redesign** — contextual title derived from current task; thicker progress bars; Cancel button always visible outside the scrollable body
- **Sidebar stays open** — Writer AI panel opens expanded at launch and no longer collapses on window maximise
- **Toggle icons** — ► when expanded (click to collapse), ◄ when collapsed (click to expand)

### v0.7 — Knowledge Extraction
*2026-06-28*

- **Knowledge extraction** — Auto Transcript can write character and location notes to `.md` files in your project folder; a project memory file is also generated via LLM for long-term context

### v0.6 — Script Supervisor, Progress Bar & Launcher Tkinter Check
*2026-06-28*

- **Script Supervisor** — second-pass review agent that processes scenes one by one, compares each against adjacent context and the project knowledge base, and presents a side-by-side comparison for any proposed clean-up fix (Apply & Next / Skip Scene / Stop)
- **Auto Transcript progress bar** — determinate progress bar in the Writer AI panel, shared between Auto Transcript and Script Supervisor, shows percentage of document processed
- **Launcher Tkinter check** — `start-filmpad.sh` now detects a missing Tkinter module before the source-run fallback and shows a distro-specific install command

### v0.5 — Line Numbers, Auto Transcript Log & Auto-Save
*2025-06-27*

- **Line numbers** — canvas gutter on the left of the writer pad, synced with scroll in real time via `dlineinfo`
- **Auto Transcript log** — label below the Auto Transcript button shows Started / Block / Position / Last Saved line numbers
- **Auto-save after each block** — file is silently saved after every completed block; log updates with the saved line
- **doctor.sh** — comprehensive `bash doctor.sh` check: Python version, Tkinter, Ollama install, server status, downloaded models, FUSE

### v0.4 — Launch Reliability and First-Time Setup
*2026-06-26*

- **Launch fallback chain** — launcher now tries AppImage first, then `dist/filmpad`, then `python3 filmpad.py`
- **Desktop-visible launch errors** — failed starts now show GUI error dialogs (Zenity/KDialog/XMessage fallback)
- **Dependency-first startup checks** — Python is checked first, with distro-specific install hint commands
- **Guided first-time setup** — startup questionnaire can install Ollama, missing models, read-aloud tool (`spd-say`), and spellcheck tool (`aspell`)
- **Safe dependency testing mode** — set `FILMPAD_TEST_NO_PYTHON=1` to simulate a missing Python dependency without uninstalling system Python

### v0.2 — Dark Theme, Writer AI & Screenplay Formatter
*2026-06-25*

- **Dark theme** — full dark mode on by default; system accent colour (Cinnamon/GNOME) used for selection highlights; toggle between Light and Dark in the toolbar
- **Writer AI comparison pane** — AI output opens in a side-by-side Original vs Proposed review window before anything is changed in the document; right pane is editable before accepting
- **Screenplay auto-formatter** — accepting AI output automatically applies screenplay tags (Scene Heading, Character, Dialogue, Transition, Action) with correct WGA-standard indentation
- **Transcribe into Script Format** — one-click action with a strict verbatim prompt; preserves all content, transitions, and dialogue without summarising
- **Project knowledge folder** — used as background reference to keep names and locations consistent; the AI is explicitly prevented from importing new content from it
- **Icon improvements** — crisp SVG + PNG icons at all sizes; Plank dock grouping fixed

### v0.1 — Initial release

- Screenplay editor with format presets (Scene Heading, Action, Character, Dialogue, Parenthetical, Transition, Shot)
- Local AI tab for scene-by-scene adaptation from prose source
- Writer AI panel with free-form prompt and project knowledge folder
- Spell check, read-aloud, font picker
- Linux AppImage

---

## Dependencies

### Runtime (required)

| Dependency | Purpose | Install |
|---|---|---|
| **Python 3.10+** | Runtime (source only) | `sudo apt install python3` |
| **python3-tk** | Tkinter GUI (source only) | `sudo apt install python3-tk` |
| **[Ollama](https://ollama.com)** | Local LLM inference engine | See https://ollama.com/download |
| **spd-say** | Text-to-speech read-aloud | `sudo apt install speech-dispatcher` |

> The AppImage bundles Python and Tkinter — only Ollama and spd-say need to be installed separately.

### Optional

| Dependency | Purpose | Notes |
|---|---|---|
| **[Piper TTS](https://github.com/rhasspy/piper)** | Natural-voice offline read-aloud | `python3 -m venv ~/.local/share/piper/venv && pip install piper-tts` |
| **[whisper.cpp](https://github.com/ggerganov/whisper.cpp)** | Offline speech-to-text dictation | Build and copy `whisper-cli` to `~/.local/bin/`; download a GGML model |
| **alsa-utils** | Microphone recording for dictation | `sudo apt install alsa-utils` |
| **aspell** | Spell check | `sudo apt install aspell aspell-en` |

### Ollama models

FilmPad works with any model available in Ollama. The following are tested and recommended:

| Model | Command | Best for |
|---|---|---|
| **llama3** | `ollama pull llama3` | General adaptation, Writer AI |
| **mistral** | `ollama pull mistral` | Dialogue quality, creative writing |
| **mistral:7b** | `ollama pull mistral:7b` | Faster generation on lower-end hardware |
| **llama3.1** | `ollama pull llama3.1` | Longer context, complex scenes |
| **phi3** | `ollama pull phi3` | Lightweight, quick edits |

Pull a model before first use:

```bash
ollama pull llama3
```

Ollama must be running before generating in FilmPad:

```bash
ollama serve   # or: systemctl start ollama
```

### Build dependencies (optional, for building from source)

| Dependency | Purpose |
|---|---|
| `pyinstaller` | Binary packaging |
| `imagemagick` | Icon size generation during build |

## Features

- **Writer tab** — screenplay editor with format presets (Scene Heading, Action, Character, Dialogue, Parenthetical, Transition, Shot), font picker (Courier 10 Pitch preferred), spell check, and read-aloud
- **Dark / Light theme** — full dark mode by default; system accent colour used for selections; toggle in toolbar
- **Writer AI panel** — collapsible right-side panel; free-form prompt; project knowledge folder for context; **Transcribe into Script Format** action; side-by-side comparison pane before any edit is applied; **Review Last Output** to re-open the last comparison
- **Screenplay auto-formatter** — accepted AI output is automatically tagged with screenplay styles (Scene Heading, Character, Dialogue, Transition, Action) matching WGA standard indentation
- **Local AI tab** — split-pane workspace: load a prose source file on the right, open a destination screenplay on the left, select a line range, pick a model, and generate scene-by-scene adaptations with insertion-point control
- **Progress overlay** — elapsed timer and Cancel button on all generation operations
- **Tab auto-save / live reload** — switching to Local AI auto-saves the Writer file; switching back reloads it
- **Collapsible sidebars** — both the Local AI wizard panel and Writer AI panel fold away with a toggle button

## Running from source

## Running from source

```bash
git clone https://github.com/idealiner/filmpad.git
cd filmpad
pip install pyinstaller  # only needed if building AppImage
python3 filmpad.py
```

## GitHub Release Delivery (v0.4)

Build and prepare artifacts:

```bash
./build-appimage.sh
sha256sum FilmPad-v0.4-x86_64.AppImage > FilmPad-v0.4-x86_64.AppImage.sha256
```

Tag and push:

```bash
git add .
git commit -m "release: v0.4"
git tag -a v0.4 -m "FilmPad v0.4"
git push origin main
git push origin v0.4
```

Create GitHub release:

- Tag: `v0.4`
- Title: `FilmPad v0.4`
- Attach: `FilmPad-v0.4-x86_64.AppImage`
- Attach: `FilmPad-v0.4-x86_64.AppImage.sha256`
- Release notes: copy the `v0.4` section from this README

## Repository Layout

- `filmpad.py` — application entry point (all UI and logic)
- `assets/` — icon assets (multiple sizes) and the screenplay adaptation template
- `assets/templates/SCREENPLAY_SCENE_ADAPTATION_TEMPLATE.md` — scene card template used in AI prompts
- `packaging/filmpad.desktop` — Linux desktop entry
- `filmpad.spec` — PyInstaller build configuration
- `build-appimage.sh` — builds a Linux AppImage from the PyInstaller binary
- `local-ai.sh` — original terminal-based adaptation workflow (reference)
- `docs/index.html` — public download page
- `LICENSE` — MIT licence

## Architecture Vision: High-Quality Read Aloud

### Goals

- Natural, expressive speech output
- Low-latency start for short selections
- Stable long-form playback for large documents
- Cross-platform desktop behavior
- Provider-agnostic TTS engine interface
- Privacy-aware operation with optional local-only mode

### Proposed Components

1. Editor Layer (existing Tkinter UI)
2. Selection/Document Extractor
3. Text Normalization Pipeline
4. TTS Provider Adapter Layer
5. Audio Post-Processing and Caching
6. Playback Engine with transport controls
7. Settings and Voice Profile Manager
8. Telemetry/Logging (optional, local-only by default)

### Data Flow

1. User selects text or chooses read-aloud scope (selection, paragraph, full document).
2. Text is normalized (whitespace, punctuation handling, abbreviation rules, optional number/date expansion).
3. Text is chunked into sentence-aware segments under provider token/character limits.
4. Chunks are synthesized through selected provider.
5. Audio chunks are optionally post-processed (loudness normalization, trim silence, crossfade).
6. Chunks are streamed or stitched for playback.
7. Cache stores generated audio keyed by text hash + voice/profile + provider settings.

## Technical Design Details

### 1) TTS Provider Abstraction

Define a common interface so multiple engines can be swapped:

- `synthesize(text, voice, rate, pitch, style) -> AudioChunk`
- `synthesize_stream(chunks, options) -> Iterable[AudioChunk]`
- `list_voices(locale=None) -> list[VoiceInfo]`
- `supports(feature_name) -> bool`

Potential providers:

- Cloud APIs (for premium quality and multilingual coverage)
- Local neural engines (for privacy/offline usage)
- Hybrid fallback chain (local first, cloud fallback)

### 2) Text Normalization and Chunking

Recommended preprocessing steps:

- Unicode normalization (NFC)
- Preserve paragraph boundaries for natural pauses
- Optional SSML conversion where supported
- Sentence boundary detection before chunking
- Hard limit enforcement per provider (characters/tokens)

Chunking strategy:

- Target chunk length: 200 to 800 characters (provider-dependent)
- Prefer sentence-complete chunks
- Add overlap markers only when needed for seamless transitions

### 3) Audio Pipeline

Output format recommendations:

- Internal cache format: PCM WAV or FLAC for edit-safe processing
- Playback format: PCM stream through local player
- Optional export: MP3/WAV

Post-processing options:

- LUFS-based normalization for consistent loudness
- Leading/trailing silence trim
- Optional soft crossfade (20 to 80 ms) between chunks

### 4) Playback Engine

Core controls:

- Play/Pause/Stop
- Skip forward/back sentence or chunk
- Seek within synthesized stream
- Adjustable speaking rate (without severe artifacting)
- Live progress and active-text highlighting

Implementation options:

- Lightweight: `pygame` mixer or `simpleaudio`
- Higher control: `pyaudio`/`sounddevice` + custom buffering

Threading model:

- UI thread: Tkinter only
- Worker thread/process: synthesis and preprocessing
- Playback thread: audio output queue and transport clock

Use thread-safe queues to avoid blocking the Tkinter main loop.

### 5) Caching

Use deterministic cache keys:

- `sha256(text + provider + voice + rate + pitch + style + locale + model_version)`

Cache policy:

- LRU by total bytes
- Configurable max size (for example 1 to 5 GB)
- Optional TTL invalidation when provider model versions change

### 6) Configuration Model

Suggested settings schema:

- Default provider and fallback order
- Voice, locale, speaking rate, pitch, style
- Audio device output
- Cache location and quota
- Privacy mode (disable cloud providers)

Potential storage locations:

- Linux: `~/.config/filmpad/config.json`
- Cache: `~/.cache/filmpad/tts/`

### 7) Error Handling and Resilience

- Provider timeout and retry with backoff
- Graceful fallback to secondary provider
- Partial playback support if some chunks fail
- User-visible diagnostics for actionable failures

### 8) Security and Privacy

- Do not send text to cloud providers when privacy mode is enabled
- Redact logs by default (or disable text logging entirely)
- Validate provider endpoints and TLS certificates
- Keep API keys outside source control (environment variables or OS keyring)

## Suggested Dependency Stack for Read Aloud

Core choices for implementation phase:

- `httpx` for provider API calls
- `pydantic` for validated settings and provider responses
- `sounddevice` or `pyaudio` for playback pipeline
- `numpy` for buffer manipulation
- `rapidfuzz` or simple hash maps for chunk/text mapping (highlight sync support)
- Optional local inference runtime depending on chosen local TTS model

## Running the Current App

From source:

```bash
./run-filmpad.sh
```

From packaged binary:

```bash
./start-filmpad.sh
```

Direct Python launch:

```bash
python3 filmpad.py
```

## Screenplay Formatting Workflow

FilmPad now includes a screenplay formatting toolbar:

- Pick a screenplay-style monospaced font (prefers Courier-family fonts when available)
- Select one or more lines in the editor
- Choose a block type from the `Screenplay Format` dropdown
- Click `Apply To Selection`

Supported block formats:

- Action
- Scene Heading
- Character
- Parenthetical
- Dialogue
- Transition
- Shot

Behavior notes:

- Scene Heading, Character, Transition, and Shot are uppercased automatically
- Parenthetical wraps selected lines with parentheses when needed
- Formatting is line-based and applies margins/spacing for each screenplay block type

## Custom Prompts

FilmPad loads `auto_transcript_prompt.txt` (Auto Transcript) and `ss_prompt.txt` (Script Supervisor) from your **project folder** at runtime, falling back to the built-in defaults if no file is found.

To override either prompt, drop the file into your project folder:

```
my-project/
  auto_transcript_prompt.txt   ← overrides Auto Transcript instructions
  ss_prompt.txt                ← overrides Script Supervisor instructions
```

Or place them in a `templates/` subfolder inside the project folder — FilmPad checks there first:

```
my-project/
  templates/
    auto_transcript_prompt.txt
    ss_prompt.txt
```

Starter files are attached to each release on the [GitHub releases page](https://github.com/idealiner/filmpad/releases).

## Building a Binary

PyInstaller spec is provided as `filmpad.spec`.

Example build command:

```bash
pyinstaller filmpad.spec
```

This produces build artifacts in `build/` and packaged output in `dist/`.

The PyInstaller bundle includes the `assets/` directory so the packaged app can load its window icon at runtime.

For the public v0.1 Linux release, build the AppImage as `FilmPad-v0.1-x86_64.AppImage` and publish it alongside the static download page in `docs/index.html`.

## Packaging With an App Icon

### Current Icon Setup

- `assets/filmpad-icon.ppm` is used by the Tkinter window at runtime
- `assets/filmpad-icon.svg` is used for Linux desktop/AppImage packaging
- `packaging/filmpad.desktop` defines the launcher metadata and icon name

### Why AppImage Is a Good Fit

AppImage is a strong default for this project on Linux because:

- It ships as a single portable file
- It does not require system-wide installation
- It preserves desktop launcher metadata and icon integration cleanly
- It works well with PyInstaller as the binary-producing step

### Build Flow

1. Build the standalone Linux binary with PyInstaller.
2. Assemble an `AppDir/` layout containing:
	- the executable
	- the desktop file
	- the SVG icon
	- an `AppRun` launcher
3. Run `appimagetool` to turn the `AppDir/` into an `.AppImage` file.

### Prerequisites

- `pyinstaller`
- `appimagetool`

`pyinstaller` is already the packaging base for this repository.

### Build Command

```bash
chmod +x build-appimage.sh
./build-appimage.sh
```

Expected output:

- `dist/filmpad` from PyInstaller
- `FilmPad-x86_64.AppImage` from `appimagetool`

### Notes

- PyInstaller itself does not provide Linux desktop icon integration in the same way it does on Windows and macOS.
- On Linux, the visible application icon is typically provided by the desktop entry and icon assets inside the AppImage.
- If you later want native distro packages, the same `filmpad.desktop` and icon assets can be reused for `.deb` or `.rpm` packaging.

## Development Roadmap

1. Introduce modular package layout (`filmpad/` package, not only single-file script).
2. Add read-aloud domain models and provider interface.
3. Implement one local and one cloud provider.
4. Add playback queue, controls, and text highlighting.
5. Add cache layer and settings UI.
6. Add end-to-end tests for chunking, caching, and playback controls.
7. Improve packaging and cross-platform release automation.

## Testing Strategy (Planned)

- Unit tests: normalization, chunking, cache keys, provider adapters
- Integration tests: synthesis pipeline with mocked provider responses
- UI smoke tests: open/save/read-aloud controls
- Performance tests: time-to-first-audio and memory use for long documents

## Contribution Guidelines

- Open an issue describing feature proposal or bug.
- Keep pull requests focused and small.
- Add tests for non-trivial behavior changes.
- Avoid committing secrets or provider credentials.
- Document new provider adapters and capability limits.

## Open Source Notes

- License: add a `LICENSE` file before first public release.
- Security policy: consider adding `SECURITY.md` for vulnerability reporting.
- Code of conduct: consider adding `CODE_OF_CONDUCT.md` for community standards.

## Immediate Next Engineering Tasks

- Refactor `filmpad.py` into modules (`ui`, `core`, `tts`, `audio`, `config`).
- Implement a provider-agnostic TTS interface and stub adapter.
- Add read-aloud menu actions and transport toolbar.
- Add persistent settings and cache manager.
- Add first local quality baseline with objective audio checks.

---

If you want, the next step can be implementation of the first end-to-end read-aloud slice (selection to speech output) behind a feature flag, while preserving the current editor behavior.
