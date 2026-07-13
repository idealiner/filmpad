#!/usr/bin/env bash
# FilmPad — System Readiness Check
# Run this script to diagnose missing dependencies before launching FilmPad.
# On Linux: bash doctor.sh
# On macOS: bash doctor.sh
# On Windows: open Git Bash or WSL and run: bash doctor.sh

set -euo pipefail

PASS="✅"
WARN="⚠️ "
FAIL="❌"
INFO="ℹ️ "

echo ""
echo "══════════════════════════════════════════"
echo "  FilmPad — System Readiness Check"
echo "══════════════════════════════════════════"
echo ""

# ── 1. OS ──────────────────────────────────────────────────────────────
OS="$(uname -s 2>/dev/null || echo Unknown)"
ARCH="$(uname -m 2>/dev/null || echo Unknown)"
echo "${INFO} OS:   $OS ($ARCH)"
echo ""

# ── 2. Python ──────────────────────────────────────────────────────────
echo "── Python ──────────────────────────────"
if command -v python3 &>/dev/null; then
    PY_VER="$(python3 --version 2>&1)"
    PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
    PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        echo "${PASS} $PY_VER"
    else
        echo "${WARN} $PY_VER  (FilmPad needs Python 3.10+)"
    fi
else
    echo "${FAIL} python3 not found"
    echo "     Install: https://www.python.org/downloads/"
fi

# ── 3. Tkinter ─────────────────────────────────────────────────────────
echo ""
echo "── Tkinter ─────────────────────────────"
if python3 -c "import tkinter" 2>/dev/null; then
    TK_VER="$(python3 -c "import tkinter; r=tkinter.Tk(); r.withdraw(); print(r.tk.call('info','patchlevel')); r.destroy()" 2>/dev/null || echo "unknown")"
    echo "${PASS} tkinter available (Tcl/Tk $TK_VER)"
else
    echo "${FAIL} tkinter not available"
    if [ "$OS" = "Linux" ]; then
        echo "     Fix: sudo apt install python3-tk   (Debian/Ubuntu)"
        echo "          sudo dnf install python3-tkinter  (Fedora)"
    elif [ "$OS" = "Darwin" ]; then
        echo "     Fix: brew install python-tk"
        echo "          or use the python.org installer (includes tkinter)"
    fi
fi

# ── 4. Ollama ──────────────────────────────────────────────────────────
echo ""
echo "── Ollama ──────────────────────────────"
OLLAMA_CMD=""
for p in ollama /usr/local/bin/ollama /opt/homebrew/bin/ollama "$HOME/.local/bin/ollama"; do
    if command -v "$p" &>/dev/null || [ -x "$p" ]; then
        OLLAMA_CMD="$p"
        break
    fi
done

if [ -z "$OLLAMA_CMD" ]; then
    echo "${FAIL} ollama not found"
    echo "     Install: https://ollama.com/download"
else
    OLLAMA_VER="$("$OLLAMA_CMD" --version 2>/dev/null || echo "unknown version")"
    echo "${PASS} $OLLAMA_CMD  ($OLLAMA_VER)"

    # Check if the server is running
    echo ""
    echo "── Ollama server ───────────────────────"
    if "$OLLAMA_CMD" list &>/dev/null 2>&1; then
        echo "${PASS} Ollama server is running"
        echo ""
        echo "── Downloaded models ───────────────────"
        MODELS="$("$OLLAMA_CMD" list 2>/dev/null | tail -n +2 | awk '{print $1}' | head -20)"
        if [ -z "$MODELS" ]; then
            echo "${WARN} No models downloaded yet"
            echo "     Suggested: ollama pull mistral:7b"
            echo "                ollama pull phi3"
            echo "                ollama pull llama3.1:8b"
        else
            while IFS= read -r model; do
                echo "${PASS} $model"
            done <<< "$MODELS"
        fi
    else
        echo "${WARN} Ollama server is not running"
        echo "     Start it:  ollama serve"
        echo "     (FilmPad's pre-flight check will catch this too)"
    fi
fi

# ── 5. speech-dispatcher (spd-say) — required for read-aloud ──────────────
echo ""
echo "── Read-aloud: spd-say (required) ─────"
if command -v spd-say &>/dev/null; then
    echo "${PASS} spd-say available"
else
    echo "${FAIL} spd-say not found  (▶ Read Aloud will not work)"
    if [ "$OS" = "Linux" ]; then
        echo "     Fix: sudo apt install speech-dispatcher"
    fi
fi

# ── 6. Piper TTS — optional, natural-voice read-aloud ─────────────────
echo ""
echo "── Natural voice TTS: Piper (optional) ─"
PIPER_PY="$HOME/.local/share/piper/venv/bin/python"
PIPER_VOICES_DIR="$HOME/.local/share/piper/voices"
RYAN_VOICE="$PIPER_VOICES_DIR/en_US-ryan-high.onnx"
RYAN_JSON="$PIPER_VOICES_DIR/en_US-ryan-high.onnx.json"

PIPER_OK=false
RYAN_OK=false

if [ -x "$PIPER_PY" ]; then
    PIPER_OK=true
fi
if [ -f "$RYAN_VOICE" ] && [ -f "$RYAN_JSON" ]; then
    RYAN_OK=true
fi

if $PIPER_OK && $RYAN_OK; then
    VOICE_COUNT="$(ls "$PIPER_VOICES_DIR"/*.onnx 2>/dev/null | wc -l)"
    echo "${PASS} Piper installed  ($VOICE_COUNT voice(s) found)"
    echo "${PASS} en_US-ryan-high voice present"
else
    if ! $PIPER_OK; then
        echo "${WARN} Piper TTS not installed  (enables natural-sounding offline read-aloud)"
        echo ""
        echo "     To install Piper:"
        echo "       mkdir -p ~/.local/share/piper/voices"
        echo "       python3 -m venv ~/.local/share/piper/venv"
        echo "       ~/.local/share/piper/venv/bin/pip install piper-tts"
    else
        echo "${PASS} Piper venv installed"
    fi

    if ! $RYAN_OK; then
        echo ""
        if $PIPER_OK; then
            echo "${WARN} en_US-ryan-high voice not found"
        fi
        echo "     To download the Ryan EN voice (recommended):"
        echo "       mkdir -p ~/.local/share/piper/voices"
        echo "       cd ~/.local/share/piper/voices"
        echo "       wget -q --show-progress \\"
        echo "         https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"
        echo "       wget -q --show-progress \\"
        echo "         https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json"
        echo ""
        echo "     Then restart FilmPad — the voice will appear in the toolbar dropdown."
    fi
fi

# ── 7. AppImage dependencies (Linux only) ───────────────────────
if [ "$OS" = "Linux" ]; then
    echo ""
    echo "── AppImage runtime (Linux) ────────────"
    if command -v fusermount &>/dev/null || command -v fusermount3 &>/dev/null; then
        echo "${PASS} FUSE available (AppImage can mount)"
    else
        echo "${WARN} FUSE not found — AppImage may fall back to extraction mode (still works)"
        echo "     Fix: sudo apt install fuse libfuse2"
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Check complete."
echo "══════════════════════════════════════════"
echo ""
echo "If everything above shows ✅, FilmPad should run without issues."
echo "If you see ❌ or ⚠️, follow the fix instructions above."
echo ""

# Keep the terminal open so output is readable (fixes the "flashes and closes" issue)
if [ -t 0 ]; then
    read -rp "Press Enter to close..." _
fi
