# FilmPad

FilmPad is a screenplay editor and local AI adaptation tool built with Python and Tkinter. It combines a formatted screenplay writer with a Local AI workspace for adapting prose source text into screenplay scenes, and a Writer AI assistant for in-editor rewrites — all powered by locally running Ollama models, with no cloud dependency.

## Download (Linux AppImage)

- Direct download (v0.1): https://github.com/idealiner/filmpad/releases/download/v0.1/FilmPad-v0.1-x86_64.AppImage
- Release page: https://github.com/idealiner/filmpad/releases/tag/v0.1
- Public download page: https://idealiner.github.io/filmpad/

Quick run:

```bash
chmod +x FilmPad-v0.1-x86_64.AppImage
./FilmPad-v0.1-x86_64.AppImage
```

## Dependencies

### Runtime (required)

| Dependency | Purpose | Install |
|---|---|---|
| **Python 3.10+** | Runtime (source only) | `sudo apt install python3` |
| **python3-tk** | Tkinter GUI (source only) | `sudo apt install python3-tk` |
| **[Ollama](https://ollama.com)** | Local LLM inference engine | See https://ollama.com/download |
| **spd-say** | Text-to-speech read-aloud | `sudo apt install speech-dispatcher` |

> The AppImage bundles Python and Tkinter — only Ollama and spd-say need to be installed separately.

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

- **Writer tab** — screenplay editor with format presets (Scene Heading, Action, Character, Dialogue, Parenthetical, Transition, Shot), font picker, spell check, and read-aloud
- **Writer AI panel** — collapsible right-side panel with free-form prompt, project knowledge folder context, and a one-click "Transcribe into Script Format" action; replaces selected text with AI output
- **Local AI tab** — split-pane workspace: load a prose source file on the right, open a destination screenplay on the left, select a line range, pick a model, and generate scene-by-scene adaptations with insertion-point control
- **Progress overlay** — elapsed timer and Cancel button on all generation operations
- **Tab auto-save / live reload** — switching to Local AI auto-saves the Writer file; switching back reloads it, keeping both panes in sync
- **Collapsible sidebars** — both the Local AI wizard panel and Writer AI panel fold away with a toggle button

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
