#!/usr/bin/env python3
from pathlib import Path
import json
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


PREFERRED_SCREENPLAY_FONTS = [
    "Courier Prime",
    "Courier Screenplay",
    "Courier 10 Pitch",
    "Courier New",
    "Courier",
    "Liberation Mono",
    "Nimbus Mono PS",
    "DejaVu Sans Mono",
]


SCREENPLAY_FORMATS = {
    "Action": {"uppercase": False},
    "Scene Heading": {"uppercase": True},
    "Character": {"uppercase": True},
    "Parenthetical": {"uppercase": False},
    "Dialogue": {"uppercase": False},
    "Transition": {"uppercase": True},
    "Shot": {"uppercase": True},
}

SPELL_TAG = "misspelled"
AUTO_TRANSCRIPT_TAG = "auto_transcript_block"
LOCAL_AI_SOURCE_RANGE_TAG = "local_ai_source_range"
LOCAL_AI_RESULT_HIGHLIGHT_TAG = "local_ai_result_highlight"
LOCAL_AI_MODELS = [
    "mistral:7b",
    "llama3.1:8b",
    "qwen2.5-coder:7b",
]

LIGHT_COLORS = {
    "text_bg": "white",       "text_fg": "black",        "insert": "black",
    "sel_bg": "#4a90d9",     "sel_fg": "white",
    "gutter_bg": "#f0f0f0",  "gutter_fg": "#666666",
    "result_hl": "#fff2b3",  "source_hl": "#d9ebff",
    "at_hl": "#ffe8c0",
    "spell_fg": "#cc0000",   "status_fg": "#555555",
    "ttk_bg": "#f0f0f0",     "ttk_fg": "#000000",
    "entry_bg": "white",
}
DARK_COLORS = {
    "text_bg": "#1e1e1e",    "text_fg": "#d4d4d4",      "insert": "#d4d4d4",
    "sel_bg": "#264f78",     "sel_fg": "#ffffff",
    "gutter_bg": "#252526",  "gutter_fg": "#858585",
    "result_hl": "#3a3a00",  "source_hl": "#1a3550",
    "at_hl": "#332200",
    "spell_fg": "#f48771",   "status_fg": "#aaaaaa",
    "ttk_bg": "#2b2b2b",     "ttk_fg": "#d4d4d4",
    "entry_bg": "#3c3c3c",
}

# Maps accent colour names → a selection-background hex that is clearly tinted
# and still gives enough contrast for white (#fff) text on top.
_ACCENT_PALETTE: dict[str, str] = {
    "pink":   "#7d1c4e",
    "purple": "#5c1a7c",
    "red":    "#8b1a1a",
    "orange": "#7d3000",
    "yellow": "#6b5900",
    "green":  "#1a5c20",
    "teal":   "#005c52",
    "blue":   "#264f78",
    "slate":  "#2c3e50",
    "grey":   "#3a4a5a",
    "gray":   "#3a4a5a",
}

# ── Piper TTS ──────────────────────────────────────────────────────────────
_PIPER_PYTHON = Path.home() / ".local/share/piper/venv/bin/python"
_PIPER_VOICES_DIR = Path.home() / ".local/share/piper/voices"

# ── Recent files ──────────────────────────────────────────────────────────
_RECENT_FILE = Path.home() / ".config/filmpad/recent_files.json"


def _get_system_accent_sel_bg() -> str:
    """Return a selection-background hex colour that matches the system accent.

    Probe order:
      1. GNOME 46+ / Cinnamon  accent-color gsettings key (returns a name)
      2. Cinnamon theme name   (colour encoded as suffix e.g. 'WhiteSur-Dark-pink')
      3. GTK 4 / GTK 3 CSS    @define-color accent_color …
      4. Hard-coded blue fallback
    """
    # 1 — gsettings accent-color key
    for schema in ("org.gnome.desktop.interface", "org.cinnamon.desktop.interface"):
        try:
            r = subprocess.run(
                ["gsettings", "get", schema, "accent-color"],
                capture_output=True, text=True, timeout=1,
            )
            if r.returncode == 0:
                name = r.stdout.strip().strip("'\"").lower()
                if name in _ACCENT_PALETTE:
                    return _ACCENT_PALETTE[name]
        except Exception:
            pass

    # 2 — Cinnamon theme name suffix  e.g. "WhiteSur-Dark-pink"
    try:
        r = subprocess.run(
            ["gsettings", "get", "org.cinnamon.theme", "name"],
            capture_output=True, text=True, timeout=1,
        )
        if r.returncode == 0:
            theme = r.stdout.strip().strip("'\"").lower()
            for name, color in _ACCENT_PALETTE.items():
                if theme.endswith(f"-{name}") or f"-{name}-" in theme:
                    return color
    except Exception:
        pass

    # 3 — GTK CSS @define-color accent_color
    for css_path in (
        Path.home() / ".config/gtk-4.0/gtk.css",
        Path.home() / ".config/gtk-3.0/gtk.css",
    ):
        try:
            text = css_path.read_text(encoding="utf-8")
            m = re.search(r"@define-color\s+accent_color\s+(#[0-9a-fA-F]{3,8})", text)
            if m:
                return m.group(1)
        except Exception:
            pass

    return _ACCENT_PALETTE["blue"]


def _detect_piper_voices() -> list[str]:
    """Return sorted list of Piper voice names found in _PIPER_VOICES_DIR."""
    d = _PIPER_VOICES_DIR
    if not d.is_dir():
        return []
    return sorted(
        p.stem for p in d.glob("*.onnx")
        if (d / (p.stem + ".onnx.json")).exists()
    )


def _split_tts_chunks(text: str, max_chars: int = 220) -> list[str]:
    """Split text on sentence boundaries into chunks of roughly max_chars."""
    parts = re.split(r"(?<=[.!?\u2026])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = (current + " " + part).strip() if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) > max_chars:
                words = part.split()
                current = ""
                for w in words:
                    test = (current + " " + w).strip()
                    if len(test) <= max_chars:
                        current = test
                    else:
                        if current:
                            chunks.append(current)
                        current = w
            else:
                current = part
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def _find_whisper_cpp(exe_path: str = "") -> str | None:
    """Return the absolute path to a whisper.cpp whisper-cli binary, or None."""
    candidates: list[str] = []
    if exe_path:
        candidates.append(str(Path(exe_path).expanduser()))
    candidates += [
        str(Path.home() / ".local/bin/whisper-cli"),
        str(Path.home() / ".local/share/whisper.cpp/build/bin/whisper-cli"),
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    # Fall back to PATH
    return shutil.which("whisper-cli")


def _load_recent_files() -> list[str]:
    """Return the persisted recent-files list (newest first)."""
    try:
        return json.loads(_RECENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_recent_files(paths: list[str]) -> None:
    """Write the recent-files list to disk."""
    try:
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps(paths, indent=2), encoding="utf-8")
    except OSError:
        pass


class FilmPad:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FilmPad")
        self.root.geometry("900x600")
        self.icon_image = None
        self._dark_mode = False
        self._last_comparison: dict | None = None  # {original, proposed, sel_start, sel_end}
        self.available_fonts = self._available_screenplay_fonts()
        self.font_var = tk.StringVar(value=self.available_fonts[0])
        self.format_var = tk.StringVar(value="Action")
        self._piper_voice_var = tk.StringVar(value="")
        self._tts_speed_var = tk.DoubleVar(value=0.8)
        self._read_btn: ttk.Button | None = None
        # ── Dictation toolbar refs/vars (must precede _build_toolbar) ───────────────
        self._dictation_status_var = tk.StringVar(value="")
        self._dictation_exe_var = tk.StringVar(
            value=str(Path.home() / ".local/bin/whisper-cli")
        )
        self._dictation_model_var = tk.StringVar(
            value=str(Path.home() / ".local/share/whisper.cpp/models/ggml-tiny.en.bin")
        )
        self._dictation_lang_var = tk.StringVar(value="en")
        self._dictation_device_var = tk.StringVar(value="")
        self._dictation_start_btn: ttk.Button | None = None
        self._dictation_stop_btn: ttk.Button | None = None
        self._dictation_cancel_btn: ttk.Button | None = None
        self.screenplay_font = tkfont.Font(family=self.font_var.get(), size=11)
        self.screenplay_font_bold = tkfont.Font(family=self.font_var.get(), size=11, weight="bold")
        self.screenplay_font_scene = tkfont.Font(family=self.font_var.get(), size=11, weight="bold", underline=True)

        self.current_file = None
        self._recent_files: list[str] = _load_recent_files()
        self._recent_menu: tk.Menu | None = None

        self.toolbar = ttk.Frame(root, padding=(10, 8))
        self.toolbar.pack(side="top", fill="x")
        self._build_toolbar()

        self.main_notebook = ttk.Notebook(root)
        self.main_notebook.pack(fill="both", expand=True)

        self.editor_tab = ttk.Frame(self.main_notebook)
        self.local_ai_tab = ttk.Frame(self.main_notebook)
        self.main_notebook.add(self.editor_tab, text="Writer")
        self.main_notebook.add(self.local_ai_tab, text="Local AI")
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        self.editor_frame = tk.PanedWindow(
            self.editor_tab, orient="horizontal",
            sashwidth=5, sashrelief="flat", bd=0,
        )
        self.editor_frame.pack(fill="both", expand=True)
        self._editor_text_frame = ttk.Frame(self.editor_frame)
        self.editor_frame.add(self._editor_text_frame, stretch="always", minsize=300)

        self.text = tk.Text(
            self._editor_text_frame,
            wrap="word",
            undo=True,
            font=self.screenplay_font,
            padx=36,
            pady=24,
        )
        self.scroll = tk.Scrollbar(self._editor_text_frame, command=self.text.yview)
        _c0 = DARK_COLORS  # dark is default at startup
        self.line_gutter = tk.Canvas(
            self._editor_text_frame, width=52,
            highlightthickness=0, background=_c0["gutter_bg"],
            cursor="arrow", takefocus=False,
        )
        self._gutter_update_job: str | None = None
        self.text.configure(yscrollcommand=self._on_text_yscroll)
        self._configure_screenplay_tags()

        self.writer_ai_project_folder_var = tk.StringVar(value="")
        self.writer_ai_model_var = tk.StringVar(value=LOCAL_AI_MODELS[0])
        self.writer_ai_status_var = tk.StringVar(value="Select text then write a prompt.")
        self.writer_ai_generating = False
        self._writer_ai_cancelled = False
        self._writer_ai_process: subprocess.Popen | None = None
        self._writer_ai_sel_start: str | None = None
        self._writer_ai_sel_end: str | None = None
        self._auto_transcript_running = False
        self._auto_transcript_cancelled = False
        self._auto_transcript_process: subprocess.Popen | None = None
        self._auto_transcript_safe_mode_var = tk.BooleanVar(value=True)
        self._at_extract_knowledge_var = tk.BooleanVar(value=False)
        self._at_known_chars: dict = {}   # {name: {dialogue, refs, scenes}}
        self._at_known_locs: dict = {}    # {heading: [action_lines]}
        self._at_current_loc: str = ""
        self._auto_transcript_btn: ttk.Button | None = None
        self._auto_transcript_block_num: int = 0
        self._at_start_line: int = 0
        self._at_total_lines_snapshot: int = 0
        self._at_log_var = tk.StringVar(value="")
        self._at_progress_var = tk.DoubleVar(value=0.0)
        self._progress_detail_var = tk.StringVar(value="")
        self._script_supervisor_running = False
        self._script_supervisor_btn: ttk.Button | None = None
        self._ss_scene_list: list[tuple[str, str]] = []
        self._ss_scene_idx: int = 0
        self._ss_log_var = tk.StringVar(value="")
        self._ss_full_log: list = []
        self._ss_pending: dict | None = None
        self._ss_style_rewrite_var = tk.BooleanVar(value=False)
        self._sidebar_checkbuttons: list = []  # tk.Checkbutton refs updated in _apply_theme
        self._accordion_headers: list = []      # (hdr_frame, arrow_lbl, title_lbl) tuples
        # ── Typewriter Postscript state ──────────────────────────────────
        self._tp_running = False
        self._tp_btn: ttk.Button | None = None
        self._tp_log_var = tk.StringVar(value="")
        self._tp_full_log: list = []
        self._tp_scene_list: list[tuple[str, str]] = []
        self._tp_scene_idx: int = 0
        self._tp_applied_count: int = 0
        self._tp_clean_count: int = 0
        self._tp_strip_metadata_var = tk.BooleanVar(value=False)
        self._auto_transcript_block_start: str | None = None
        self._auto_transcript_block_end: str | None = None

        self._build_writer_ai_panel()
        self.scroll.pack(side="right", fill="y")
        self.line_gutter.pack(side="left", fill="y")
        self.text.pack(fill="both", expand=True)
        self.text.bind("<KeyRelease>", self._schedule_line_number_update)
        self.text.bind("<ButtonRelease>", self._schedule_line_number_update)
        self.text.bind("<Configure>", self._schedule_line_number_update)

        self.local_ai_source_path_var = tk.StringVar(value="")
        self.local_ai_start_line_var = tk.StringVar(value="1")
        self.local_ai_end_line_var = tk.StringVar(value="30")
        self.local_ai_dest_file = ""
        self.local_ai_insert_index: str = tk.END
        self.local_ai_result_label_var = tk.StringVar(value="Result (Editable)")
        self.local_ai_model_var = tk.StringVar(value=LOCAL_AI_MODELS[0])
        self.local_ai_status_var = tk.StringVar(value="Pick a source file and line range to begin.")
        self.local_ai_link_scroll_var = tk.BooleanVar(value=False)
        self.local_ai_temp_dir_var = tk.StringVar(value="/tmp/filmpad")
        self.local_ai_generating = False
        self.local_ai_last_slice = ""
        self._local_ai_syncing_scroll = False
        self.local_ai_selecting_range = False
        self.local_ai_range_start_click = None
        self._ollama_process: subprocess.Popen | None = None
        self._generation_cancelled = False
        self._progress_win: tk.Toplevel | None = None
        self.local_ai_replace_range: tuple[str, str] | None = None
        self._speech_process: subprocess.Popen | None = None
        self._tts_stop_event = threading.Event()
        self._tts_thread: threading.Thread | None = None
        self._tts_audio_proc: subprocess.Popen | None = None
        self._tts_widget: tk.Text | None = None
        # ── Dictation state ───────────────────────────────────────────────
        self._dictation_recording = False
        self._dictation_cancelled = False
        self._dictation_process: subprocess.Popen | None = None
        self._dictation_tmp_wav: str | None = None
        self._dictation_cursor_pos: str | None = None
        self._dictation_target: tk.Text | None = None

        self._build_local_ai_workspace()

        self._set_window_icon()
        self._build_menu()
        # Show setup helper shortly after launch so startup stays responsive.
        self.root.after(800, self._prompt_local_ai_dependency_setup)

    def _available_screenplay_fonts(self) -> list[str]:
        font_families = set(tkfont.families(self.root))
        fonts = [font_name for font_name in PREFERRED_SCREENPLAY_FONTS if font_name in font_families]
        return fonts or ["Courier"]

    def _build_toolbar(self) -> None:
        ttk.Label(self.toolbar, text="Font").pack(side="left")

        font_picker = ttk.Combobox(
            self.toolbar,
            textvariable=self.font_var,
            values=self.available_fonts,
            state="readonly",
            width=20,
        )
        font_picker.pack(side="left", padx=(8, 18))
        font_picker.bind("<<ComboboxSelected>>", self._on_font_selected)

        ttk.Label(self.toolbar, text="Screenplay Format").pack(side="left")

        format_picker = ttk.Combobox(
            self.toolbar,
            textvariable=self.format_var,
            values=list(SCREENPLAY_FORMATS),
            state="readonly",
            width=18,
        )
        format_picker.pack(side="left", padx=(8, 8))

        ttk.Button(
            self.toolbar,
            text="Apply To Selection",
            command=self.apply_screenplay_format,
        ).pack(side="left")

        _piper_voices = _detect_piper_voices()
        _has_spd = bool(shutil.which("spd-say"))
        _has_tts = _has_spd or bool(_piper_voices)

        if _has_tts:
            ttk.Separator(self.toolbar, orient="vertical").pack(side="left", fill="y", padx=(14, 10))
            self._read_btn = ttk.Button(
                self.toolbar,
                text="\u25b6 Read Aloud",
                command=self._toggle_read_aloud,
                width=14,
            )
            self._read_btn.pack(side="left")

        if _piper_voices:
            if not self._piper_voice_var.get():
                self._piper_voice_var.set(_piper_voices[0])
            ttk.Label(self.toolbar, text="Voice").pack(side="left", padx=(10, 4))
            ttk.Combobox(
                self.toolbar,
                textvariable=self._piper_voice_var,
                values=["spd-say"] + _piper_voices,
                state="readonly",
                width=20,
            ).pack(side="left", padx=(0, 6))
            ttk.Label(self.toolbar, text="Speed").pack(side="left", padx=(10, 4))
            _speed_lbl = ttk.Label(self.toolbar, text="0.8\u00d7", width=4)
            ttk.Scale(
                self.toolbar,
                from_=0.5, to=2.0,
                orient="horizontal",
                variable=self._tts_speed_var,
                length=80,
                command=lambda v: _speed_lbl.configure(text=f"{float(v):.1f}\u00d7"),
            ).pack(side="left", padx=(0, 2))
            _speed_lbl.pack(side="left", padx=(0, 8))

        if bool(shutil.which("arecord")) and _find_whisper_cpp() is not None:
            ttk.Separator(self.toolbar, orient="vertical").pack(side="left", fill="y", padx=(14, 10))
            self._dictation_start_btn = ttk.Button(
                self.toolbar,
                text="\U0001f3a4 Dictate",
                command=self._start_dictation,
                width=11,
            )
            self._dictation_start_btn.pack(side="left")
            self._dictation_stop_btn = ttk.Button(
                self.toolbar,
                text="\u23f9 Stop",
                command=self._stop_dictation_and_transcribe,
                width=6,
                state="disabled",
            )
            self._dictation_stop_btn.pack(side="left", padx=(4, 0))
            self._dictation_cancel_btn = ttk.Button(
                self.toolbar,
                text="\u2715 Cancel",
                command=self._cancel_dictation,
                width=7,
                state="disabled",
            )
            self._dictation_cancel_btn.pack(side="left", padx=(2, 0))
            ttk.Label(
                self.toolbar,
                textvariable=self._dictation_status_var,
                foreground="#cc0000",
                width=5,
            ).pack(side="left", padx=(6, 0))

        ttk.Separator(self.toolbar, orient="vertical").pack(side="right", fill="y", padx=(10, 14))
        self._theme_btn = ttk.Button(
            self.toolbar, text="\U0001f319 Dark", width=8, command=self._toggle_dark_mode
        )
        self._theme_btn.pack(side="right")

    def _show_about_dialog(self) -> None:
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        win.title("About FilmPad")
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg=c["ttk_bg"])
        win.update_idletasks()
        w, h = 520, 580
        rx = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        ry = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{max(0, rx)}+{max(0, ry)}")

        outer = ttk.Frame(win, padding=(28, 24, 28, 20))
        outer.pack(fill="both", expand=True)

        # Header
        tk.Label(
            outer, text="FilmPad", font=("TkDefaultFont", 22, "bold"),
            bg=c["ttk_bg"], fg=c["ttk_fg"],
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="Screenplay editor \u2014 local AI assistant \u2014 no cloud",
            font=("TkDefaultFont", 10),
            bg=c["ttk_bg"], fg=c["status_fg"],
        ).pack(anchor="w", pady=(2, 0))

        # Version / date row
        acc = _get_system_accent_sel_bg() if self._dark_mode else LIGHT_COLORS["sel_bg"]
        ver_row = tk.Frame(outer, bg=c["ttk_bg"])
        ver_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            ver_row, text="v0.9", font=("TkDefaultFont", 12, "bold"),
            bg=acc, fg=LIGHT_COLORS["sel_fg"], padx=8, pady=2,
        ).pack(side="left")
        tk.Label(
            ver_row, text="  \u2022  Build 2026-07-12  \u2022  Linux x86_64 AppImage",
            font=("TkDefaultFont", 9),
            bg=c["ttk_bg"], fg=c["status_fg"],
        ).pack(side="left")

        ttk.Separator(outer).pack(fill="x", pady=(14, 10))

        # Scrollable feature list
        txt_frame = tk.Frame(outer, bg=c["ttk_bg"])
        txt_frame.pack(fill="both", expand=True)
        scr = ttk.Scrollbar(txt_frame)
        scr.pack(side="right", fill="y")
        txt = tk.Text(
            txt_frame, wrap="word", font=("TkDefaultFont", 9),
            background=c["entry_bg"], foreground=c["ttk_fg"],
            relief="flat", borderwidth=0, padx=10, pady=8,
            yscrollcommand=scr.set, cursor="arrow",
        )
        txt.pack(fill="both", expand=True)
        scr.configure(command=txt.yview)

        txt.tag_configure("h", font=("TkDefaultFont", 9, "bold"), foreground=acc)
        txt.tag_configure("bullet", lmargin1=10, lmargin2=20)
        txt.tag_configure("dim", foreground=c["status_fg"])

        _ABOUT = [
            ("v0.9 \u2014 Dictation + Stability  (2026-07-13)", "h", [
                "Speech-to-text dictation at cursor \u2014 whisper.cpp (fully offline, no cloud, no Python packages); \U0001f3a4 Dictate / \u23f9 Stop / \u2715 Cancel toolbar buttons; \u25cf REC indicator",
                "Dictation Settings accordion \u2014 configurable whisper-cli path, model file (.bin), language, mic device; default ggml-tiny.en.bin; upgrade-compatible with any GGML model",
                "Dictation hidden when whisper-cli or arecord absent \u2014 matches Read Aloud pattern",
                "doctor.sh updated \u2014 Section 8 checks arecord, whisper-cli, and model files with install instructions",
                "Stability: added 5-minute timeout to Writer AI and Auto Transcript ollama calls \u2014 prevents UI freeze if model stalls",
                "Stability: undo history cleared after each Auto Transcript block \u2014 prevents RAM accumulation over long sessions",
                "Stability: Auto Transcript now warns and prompts Save before starting if file is unsaved",
            ]),
            ("v0.8 \u2014 AI Pipeline Overhaul  (2026-07-12)", "h", [
                "Accordion sidebar \u2014 Writer AI / Auto Transcript / Script Supervisor / Typewriter Postscript; all collapsed by default; system accent colour header + border when open",
                "Typewriter Postscript \u2014 new formatting-only final pass; converts headings, cues and transitions to ALL CAPS industry standard; off-rails guard prevents content deletion",
                "Script Supervisor hardened \u2014 basic SS prompt locked/hardcoded (no local override); adds missing character cues and mood parentheticals by inference; never invents content",
                "Content-protection layer \u2014 _ss_protect_content diff filter enforces that surviving lines are never rewritten; only artifact deletions and capitalisation fixes pass through",
                "Fast pre-screening \u2014 scenes skipped in <50 ms if no detectable issues; timeouts log \u2018timeout \u2014 skipped\u2019 and move on (no more exit-code \u22122 errors)",
                "SS preamble capture \u2014 text before the first scene heading is now processed and cleaned",
                "Knowledge base in SS log \u2014 first 8 names from the knowledge base shown on run start",
                "Panel width widened to 310 px; \u2018Select a function to start.\u2019 hint in always-visible area",
            ]),
            ("v0.7.3 \u2014 Script Supervisor: style ref mode  (2026-07-09)", "h", [
                "Rewrite-to-style-ref (auto-apply) checkbox \u2014 uses style_reference.txt from project folder",
                "ss_prompt_style.txt local override for style-rewrite pass",
                "Artifact removal prompt: outline headers, Hero\u2019s Journey labels, block markers deleted; clean ACT I headers reformatted not deleted",
                "Commentary stripper \u2014 _strip_ss_commentary removes model preamble/notes from output",
                "Character cue insertion allowed by diff filter (ALL CAPS attribution above dialogue)",
                "Knowledge base used in style-rewrite mode (first 2000 chars); logged on run start",
            ]),
            ("v0.7.1 \u2013 v0.7.2 \u2014 Polish & reliability  (2026-06-28)", "h", [
                "Centred transitions (CUT TO:, FADE TO: \u2026)",
                "Script Supervisor comparison button bar always visible; LLM annotations stripped",
                "Progress detail line: Scene N of T \u2014 LX\u2013Y of Z",
                "Overlay redesign with Cancel always visible; thicker progress bars",
                "Sidebar stays open at launch; toggle icons \u25ba / \u25c4",
            ]),
            ("v0.7 \u2014 Knowledge Extraction  (2026-06-28)", "h", [
                "Auto Transcript writes character + location notes to .md files in project folder",
                "LLM-generated project memory file for long-term context",
            ]),
            ("v0.6 \u2014 Script Supervisor  (2026-06-28)", "h", [
                "Scene-by-scene review with side-by-side comparison (Apply & Next / Skip / Stop)",
                "Auto Transcript progress bar (shared with Script Supervisor)",
                "Launcher Tkinter check with distro-specific install hint",
            ]),
            ("v0.5 \u2014 Line Numbers & Auto-Save  (2025-06-27)", "h", [
                "Canvas gutter line numbers synced with scroll",
                "Auto Transcript block log; auto-save after every block",
                "doctor.sh diagnostics script",
            ]),
            ("v0.2 \u2013 v0.4 \u2014 Foundations", "h", [
                "Dark theme with system accent colour (Cinnamon/GNOME)",
                "Writer AI side-by-side comparison pane (editable before accepting)",
                "Screenplay auto-tagger: Scene Heading, Character, Dialogue, Transition, Action",
                "Transcribe into Script Format (verbatim strict prompt)",
                "Project knowledge folder for name/location consistency",
                "Launch fallback chain; guided first-time setup; desktop error dialogs",
            ]),
            ("v0.1 \u2014 Initial release", "h", [
                "Screenplay editor with format presets",
                "Local AI tab for prose \u2192 screenplay adaptation",
                "Spell check, read-aloud (spd-say), font picker",
                "Linux AppImage",
            ]),
        ]

        first = True
        for title, tag, bullets in _ABOUT:
            if not first:
                txt.insert("end", "\n")
            first = False
            txt.insert("end", title + "\n", tag)
            for b in bullets:
                txt.insert("end", f"  \u2022 {b}\n", "bullet")

        txt.configure(state="disabled")

        ttk.Separator(outer).pack(fill="x", pady=(12, 10))

        # Footer
        foot = tk.Frame(outer, bg=c["ttk_bg"])
        foot.pack(fill="x")
        gh_lbl = tk.Label(
            foot, text="\U0001f517  github.com/idealiner/filmpad",
            font=("TkDefaultFont", 9), bg=c["ttk_bg"],
            fg=acc, cursor="hand2",
        )
        gh_lbl.pack(side="left")
        gh_lbl.bind("<Button-1>", lambda e: __import__("webbrowser").open(
            "https://github.com/idealiner/filmpad"
        ))
        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right")

        win.wait_visibility()
        win.grab_set()
        win.focus_set()

    def _toggle_dark_mode(self) -> None:
        self._dark_mode = not self._dark_mode
        self._apply_theme()
        self._theme_btn.configure(text="\u2600 Light" if self._dark_mode else "\U0001f319 Dark")

    def _apply_theme(self) -> None:
        c = dict(DARK_COLORS if self._dark_mode else LIGHT_COLORS)
        if self._dark_mode:
            c["sel_bg"] = _get_system_accent_sel_bg()
        bd = c["entry_bg"]   # border colour used everywhere

        # --- ttk styles ---
        style = ttk.Style()
        style.theme_use("clam")
        # Global defaults: affects every widget that doesn't override
        style.configure(".",
            background=c["ttk_bg"], foreground=c["ttk_fg"],
            fieldbackground=c["entry_bg"], troughcolor=c["gutter_bg"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
            bordercolor=bd, darkcolor=bd, lightcolor=bd,
            relief="flat", borderwidth=1,
        )
        style.configure("TFrame", background=c["ttk_bg"], borderwidth=0, relief="flat")
        style.configure("TLabel", background=c["ttk_bg"], foreground=c["ttk_fg"])
        style.configure("TButton",
            background=c["ttk_bg"], foreground=c["ttk_fg"],
            bordercolor=bd, darkcolor=bd, lightcolor=bd,
            relief="flat", borderwidth=1, padding=(4, 2),
        )
        style.map("TButton",
            background=[("active", c["sel_bg"]), ("pressed", c["sel_bg"])],
            foreground=[("active", c["sel_fg"]), ("pressed", c["sel_fg"])],
            bordercolor=[("active", c["sel_bg"]), ("pressed", c["sel_bg"])],
            darkcolor=[("active", c["sel_bg"])], lightcolor=[("active", c["sel_bg"])],
        )
        style.configure("TEntry",
            fieldbackground=c["entry_bg"], foreground=c["ttk_fg"],
            bordercolor=bd, darkcolor=bd, lightcolor=bd,
            insertcolor=c["insert"],
        )
        style.configure("TCombobox",
            fieldbackground=c["entry_bg"], foreground=c["ttk_fg"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
            bordercolor=bd, darkcolor=bd, lightcolor=bd,
            arrowcolor=c["ttk_fg"],
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", c["entry_bg"])],
            bordercolor=[("focus", bd), ("!focus", bd)],
        )
        style.configure("TNotebook",
            background=c["ttk_bg"], bordercolor=bd,
            darkcolor=c["ttk_bg"], lightcolor=c["ttk_bg"],
            tabmargins=(0, 0, 0, 0),
        )
        style.configure("TNotebook.Tab",
            background=c["ttk_bg"], foreground=c["ttk_fg"], padding=(10, 4),
            bordercolor=bd, darkcolor=c["ttk_bg"], lightcolor=c["ttk_bg"],
        )
        style.map("TNotebook.Tab",
            background=[("selected", c["text_bg"])],
            foreground=[("selected", c["text_fg"])],
            bordercolor=[("selected", bd)],
            darkcolor=[("selected", c["text_bg"])],
            lightcolor=[("selected", c["text_bg"])],
        )
        style.configure("TSeparator", background=bd)
        style.configure("Vertical.TScrollbar",
            background=c["entry_bg"], troughcolor=c["gutter_bg"],
            bordercolor=c["gutter_bg"], darkcolor=c["gutter_bg"], lightcolor=c["gutter_bg"],
            arrowcolor=c["ttk_fg"], relief="flat", borderwidth=0,
        )
        style.map("Vertical.TScrollbar",
            background=[("active", c["sel_bg"])],
        )
        style.configure("TProgressbar",
            background=c["sel_bg"], troughcolor=c["entry_bg"],
            bordercolor=c["entry_bg"],
        )
        # Classic tk.Checkbutton — neutral indicator, accent highlight on hover
        _cb_normal_bg = c["ttk_bg"]
        _cb_hover_bg = c["sel_bg"]
        for _cb in getattr(self, "_sidebar_checkbuttons", []):
            try:
                _cb.configure(
                    bg=_cb_normal_bg, fg=c["ttk_fg"],
                    activebackground=_cb_hover_bg, activeforeground=c["sel_fg"],
                    selectcolor=c["entry_bg"],
                    highlightbackground=_cb_normal_bg, highlightcolor=_cb_normal_bg,
                    highlightthickness=0,
                )
                _cb.unbind("<Enter>")
                _cb.unbind("<Leave>")
                _cb.bind("<Enter>", lambda e, w=_cb, h=_cb_hover_bg: w.configure(bg=h))
                _cb.bind("<Leave>", lambda e, w=_cb, n=_cb_normal_bg: w.configure(bg=n))
            except Exception:
                pass
        # Accordion headers — call each section's refresh function
        for _refresh in getattr(self, "_accordion_headers", []):
            try:
                _refresh()
            except Exception:
                pass
        if hasattr(self, "_writer_ai_panel_canvas"):
            self._writer_ai_panel_canvas.configure(background=c["ttk_bg"])
        # File-dialog and other classic Listbox selection colours
        self.root.option_add("*Listbox.selectBackground", c["sel_bg"])
        self.root.option_add("*Listbox.selectForeground", c["sel_fg"])
        self.root.option_add("*Listbox.background", c["entry_bg"])
        self.root.option_add("*Listbox.foreground", c["ttk_fg"])
        # Remove the highlight ring on the root and toolbar
        self.root.configure(bg=c["ttk_bg"],
            highlightbackground=c["ttk_bg"], highlightcolor=c["ttk_bg"],
            highlightthickness=0)
        if hasattr(self, "editor_frame"):
            self.editor_frame.configure(background=c["ttk_bg"])
        self.toolbar.configure(style="TFrame")

        # --- tk.Text widgets ---
        text_opts = dict(
            background=c["text_bg"], foreground=c["text_fg"],
            insertbackground=c["insert"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
            inactiveselectbackground=c["sel_bg"],
            highlightbackground=c["ttk_bg"], highlightcolor=c["sel_bg"],
            highlightthickness=1 if self._dark_mode else 0,
            borderwidth=0, relief="flat",
        )
        for widget in [self.text, self.writer_ai_prompt_text]:
            widget.configure(**text_opts)
        if hasattr(self, "local_ai_result_text"):
            self.local_ai_result_text.configure(**text_opts)
            self.local_ai_result_text.tag_configure(
                LOCAL_AI_RESULT_HIGHLIGHT_TAG, background=c["result_hl"])
        if hasattr(self, "local_ai_source_text"):
            self.local_ai_source_text.configure(**text_opts)
            self.local_ai_source_text.tag_configure(
                LOCAL_AI_SOURCE_RANGE_TAG, background=c["source_hl"])
        if hasattr(self, "local_ai_result_line_canvas"):
            self.local_ai_result_line_canvas.configure(bg=c["gutter_bg"])
        if hasattr(self, "local_ai_line_canvas"):
            self.local_ai_line_canvas.configure(bg=c["gutter_bg"])
        if hasattr(self, "line_gutter") and self.line_gutter:
            self.line_gutter.configure(background=c["gutter_bg"])
            self._schedule_line_number_update()
        if hasattr(self, "_writer_ai_panel_canvas"):
            self._writer_ai_panel_canvas.configure(background=c["ttk_bg"])

        # --- classic tk.Scrollbar widgets (don't respond to ttk style) ---
        sb_opts = dict(
            bg=c["entry_bg"], troughcolor=c["gutter_bg"],
            activebackground=c["sel_bg"],
            highlightbackground=c["ttk_bg"], highlightcolor=c["ttk_bg"],
            highlightthickness=0, borderwidth=0, relief="flat",
            elementborderwidth=0,
        )
        classic_scrollbars = [self.scroll]
        for attr in ("writer_ai_prompt_scroll", "local_ai_result_scroll", "local_ai_source_scroll"):
            if hasattr(self, attr):
                classic_scrollbars.append(getattr(self, attr))
        for sb in classic_scrollbars:
            try:
                sb.configure(**sb_opts)
            except Exception:
                pass

        # --- menus (classic tk, don't respond to ttk style) ---
        menu_opts = dict(
            bg=c["ttk_bg"], fg=c["ttk_fg"],
            activebackground=c["sel_bg"], activeforeground=c["sel_fg"],
            disabledforeground=c["gutter_fg"],
            borderwidth=0, relief="flat",
        )
        for menu_attr in ("_menu_bar", "_file_menu", "_recent_menu", "_format_menu", "_font_menu", "_screenplay_menu"):
            obj = getattr(self, menu_attr, None)
            if isinstance(obj, tk.Menu):
                try:
                    obj.configure(**menu_opts)
                except Exception:
                    pass

        # --- toolbar highlight borders ---
        self.toolbar.configure(style="Dark.TFrame" if self._dark_mode else "TFrame")
        style.configure("Dark.TFrame", background=c["ttk_bg"])

        self._configure_screenplay_tags()

    def _on_font_selected(self, _event: tk.Event) -> None:
        self.screenplay_font.configure(family=self.font_var.get(), size=11)
        self._configure_screenplay_tags()
        self._schedule_line_number_update()

    def _on_text_yscroll(self, *args) -> None:
        self.scroll.set(*args)
        self._schedule_line_number_update()

    def _schedule_line_number_update(self, event=None) -> None:
        if self._gutter_update_job:
            self.root.after_cancel(self._gutter_update_job)
        self._gutter_update_job = self.root.after(40, self._update_line_numbers)

    def _update_line_numbers(self) -> None:
        self._gutter_update_job = None
        canvas = self.line_gutter
        canvas.delete("all")
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        w = canvas.winfo_width()
        if w < 4:
            return
        canvas.create_line(w - 1, 0, w - 1, canvas.winfo_height(),
                           fill=c["gutter_fg"], width=1)
        try:
            first = int(self.text.index("@0,0").split(".")[0])
        except tk.TclError:
            return
        total = int(self.text.index("end-1c").split(".")[0])
        lineno = first
        while lineno <= total:
            dline = self.text.dlineinfo(f"{lineno}.0")
            if dline is None:
                lineno += 1
                if lineno > first + 500:
                    break
                continue
            _lx, ly, _lw, lh, _lb = dline
            if ly > canvas.winfo_height():
                break
            canvas.create_text(
                w - 6, ly + lh // 2,
                text=str(lineno), anchor="e",
                font=self.screenplay_font,
                fill=c["gutter_fg"],
            )
            lineno += 1

    def _configure_screenplay_tags_for_widget(self, widget: tk.Text) -> None:
        family = self.font_var.get()
        self.screenplay_font_bold.configure(family=family, size=11, weight="bold")
        self.screenplay_font_scene.configure(family=family, size=11, weight="bold", underline=True)

        cw = max(self.screenplay_font.measure("0"), 8)
        ls = max(self.screenplay_font.metrics("linespace"), 12)

        widget.configure(font=self.screenplay_font, tabs=(cw * 4,))

        # Action -- full-width, no indent; the baseline for all measurements
        widget.tag_configure(
            "Action",
            font=self.screenplay_font,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=4, spacing3=4,
            justify="left",
        )
        # Scene Heading -- full-width, bold+underline, double blank line above (WGA standard)
        widget.tag_configure(
            "Scene Heading",
            font=self.screenplay_font_scene,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls * 2, spacing3=6,
            justify="left",
        )
        # Character -- centred in the column (~22 chars from left, WGA ~3.7" from page edge)
        widget.tag_configure(
            "Character",
            font=self.screenplay_font,
            lmargin1=cw * 22, lmargin2=cw * 22, rmargin=cw * 20,
            spacing1=ls, spacing3=0,
            justify="left",
        )
        # Parenthetical -- narrower than dialogue, sits between character and dialogue
        widget.tag_configure(
            "Parenthetical",
            font=self.screenplay_font,
            lmargin1=cw * 16, lmargin2=cw * 16, rmargin=cw * 16,
            spacing1=2, spacing3=2,
            justify="left",
        )
        # Dialogue -- indented block, wider than parenthetical, standard ~2.5" from page edge
        widget.tag_configure(
            "Dialogue",
            font=self.screenplay_font,
            lmargin1=cw * 10, lmargin2=cw * 10, rmargin=cw * 10,
            spacing1=2, spacing3=4,
            justify="left",
        )
        # Transition -- centred, double blank line above
        widget.tag_configure(
            "Transition",
            font=self.screenplay_font,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls * 2, spacing3=ls,
            justify="center",
        )
        # Shot -- full-width bold (sub-heading style), single blank line above
        widget.tag_configure(
            "Shot",
            font=self.screenplay_font_bold,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls, spacing3=4,
            justify="left",
        )
        # Spell-check highlight -- red underline, lowest priority
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        widget.tag_configure(SPELL_TAG, underline=True, foreground=c["spell_fg"])
        widget.tag_lower(SPELL_TAG)
        # Auto-transcript active block -- amber background, raised above screenplay tags
        widget.tag_configure(AUTO_TRANSCRIPT_TAG, background=c["at_hl"])
        widget.tag_raise(AUTO_TRANSCRIPT_TAG)

    def _configure_screenplay_tags(self) -> None:
        self._configure_screenplay_tags_for_widget(self.text)
        if hasattr(self, "local_ai_result_text"):
            self._configure_screenplay_tags_for_widget(self.local_ai_result_text)

    _SLUG_RE = re.compile(r"^(INT\.?|EXT\.?|INT\./EXT\.?|I/E\.?)\s", re.IGNORECASE)
    _TRANS_RE = re.compile(
        r"^(FADE\s+(IN|OUT|TO)|CUT\s+TO|SMASH\s+CUT|MATCH\s+CUT|"
        r"DISSOLVE\s+TO|WIPE\s+TO|INTERCUT|TIME\s+CUT|JUMP\s+CUT)",
        re.IGNORECASE,
    )

    def _auto_tag_screenplay_block(self, widget: tk.Text, start_idx: str, end_idx: str) -> None:
        """Heuristically apply screenplay format tags to a newly-inserted block of text."""
        for tag in SCREENPLAY_FORMATS:
            widget.tag_remove(tag, start_idx, end_idx)

        start_row = int(widget.index(start_idx).split(".")[0])
        end_row   = int(widget.index(end_idx).split(".")[0])

        in_dialogue = False
        for row in range(start_row, end_row + 1):
            line = widget.get(f"{row}.0", f"{row}.end")
            stripped = line.strip()
            if not stripped:
                in_dialogue = False
                continue

            if self._SLUG_RE.match(stripped):
                tag = "Scene Heading"
                in_dialogue = False
            elif self._TRANS_RE.match(stripped):
                tag = "Transition"
                in_dialogue = False
            elif stripped.startswith("(") and stripped.endswith(")"):
                tag = "Parenthetical"
            elif (
                stripped == stripped.upper()
                and len(stripped) <= 45
                and not re.search(r"[.,!?;:]", stripped)
                and " - " not in stripped
                and " – " not in stripped
            ):
                tag = "Character"
                in_dialogue = True
            elif in_dialogue:
                tag = "Dialogue"
            else:
                tag = "Action"
                in_dialogue = False

            widget.tag_add(tag, f"{row}.0", f"{row}.end")

    def _active_editor_widget(self) -> tk.Text:
        focus_widget = self.root.focus_get()
        if hasattr(self, "local_ai_result_text") and focus_widget is self.local_ai_result_text:
            return self.local_ai_result_text
        if self.main_notebook.select() == str(self.local_ai_tab):
            return self.local_ai_result_text
        return self.text

    def apply_screenplay_format(self) -> None:
        target = self._active_editor_widget()
        try:
            selection_start = target.index("sel.first")
            selection_end = target.index("sel.last")
        except tk.TclError:
            messagebox.showinfo(
                "Select text",
                "Select the text you want to reformat first.",
            )
            return

        start = target.index(f"{selection_start} linestart")
        end = target.index(f"{selection_end} lineend")
        format_name = self.format_var.get()

        for existing_format in SCREENPLAY_FORMATS:
            target.tag_remove(existing_format, start, end)

        selected_text = target.get(start, end)
        replacement = self._format_screenplay_text(selected_text, format_name)

        target.delete(start, end)
        target.insert(start, replacement)
        new_end = target.index(f"{start} + {len(replacement)}c")
        target.tag_add(format_name, start, new_end)
        target.edit_modified(True)

    def _format_screenplay_text(self, text: str, format_name: str) -> str:
        lines = text.splitlines()
        if not lines:
            return text

        if SCREENPLAY_FORMATS[format_name]["uppercase"]:
            formatted_lines = [line.upper() for line in lines]
        else:
            formatted_lines = lines

        if format_name == "Parenthetical":
            parenthetical_lines = []
            for line in formatted_lines:
                stripped = line.strip()
                if stripped and not (stripped.startswith("(") and stripped.endswith(")")):
                    stripped = f"({stripped})"
                parenthetical_lines.append(stripped)
            formatted_lines = parenthetical_lines

        return "\n".join(formatted_lines)

    def _set_window_icon(self) -> None:
        # Icons and .desktop file are already installed by _install_icons_early()
        # in main() before tk.Tk() was called.  Just set the window property here.
        # Only pass the 256px image so _NET_WM_ICON always has the high-res version
        # — avoids Plank picking a 48px thumbnail and upscaling it.
        self.icon_images: list[tk.PhotoImage] = []
        for name in ("filmpad-icon-256.png", "filmpad-icon.png"):
            icon_path = resource_path(f"assets/{name}")
            if icon_path.exists():
                try:
                    self.icon_images.append(tk.PhotoImage(file=icon_path))
                    break  # only need one large image
                except tk.TclError:
                    continue
        if self.icon_images:
            self.root.iconphoto(True, *self.icon_images)

    def _install_icon_for_desktop(self) -> None:
        """Delegate to the module-level installer (kept for compatibility)."""
        import os
        appimage_path = os.environ.get("APPIMAGE")
        exec_cmd = appimage_path if appimage_path else f"python3 {Path(sys.argv[0]).resolve()}"
        _install_icons_early(exec_cmd)

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        self._menu_bar = menu_bar

        file_menu = tk.Menu(menu_bar, tearoff=0)
        self._file_menu = file_menu
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.open_file, accelerator="Ctrl+O")
        recent_menu = tk.Menu(file_menu, tearoff=0)
        self._recent_menu = recent_menu
        file_menu.add_cascade(label="Open Recent", menu=recent_menu)
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_file)
        file_menu.add_separator()
        file_menu.add_command(label="Strip Scene Card Metadata", command=self._strip_scene_card_metadata)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

        format_menu = tk.Menu(menu_bar, tearoff=0)
        self._format_menu = format_menu

        font_menu = tk.Menu(format_menu, tearoff=0)
        self._font_menu = font_menu
        for font_name in self.available_fonts:
            font_menu.add_radiobutton(
                label=font_name,
                value=font_name,
                variable=self.font_var,
                command=self._on_font_menu_selected,
            )

        screenplay_menu = tk.Menu(format_menu, tearoff=0)
        self._screenplay_menu = screenplay_menu
        for format_name in SCREENPLAY_FORMATS:
            screenplay_menu.add_command(
                label=format_name,
                command=lambda selected=format_name: self._apply_named_format(selected),
            )

        menu_bar.add_cascade(label="File", menu=file_menu)
        format_menu.add_cascade(label="Font", menu=font_menu)
        format_menu.add_cascade(label="Screenplay", menu=screenplay_menu)
        format_menu.add_separator()
        format_menu.add_command(
            label="Check Spelling",
            command=self._check_spelling,
            accelerator="F7",
        )
        format_menu.add_command(label="Clear Spell Check", command=self._clear_spelling)
        menu_bar.add_cascade(label="Format", menu=format_menu)
        menu_bar.add_command(label="About", command=self._show_about_dialog)
        self.root.config(menu=menu_bar)

        self.root.bind("<Control-n>", lambda _e: self.new_file())
        self.root.bind("<Control-o>", lambda _e: self.open_file())
        self.root.bind("<Control-s>", lambda _e: self.save_file())
        self.root.bind("<F7>", lambda _e: self._check_spelling())
        self._rebuild_recent_menu()

    def _get_installed_ollama_models(self) -> set[str]:
        if not shutil.which("ollama"):
            return set()
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=4,
            )
        except (OSError, subprocess.TimeoutExpired):
            return set()
        if result.returncode != 0:
            return set()
        models: set[str] = set()
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                models.add(parts[0].strip())
        return models

    def _prompt_local_ai_dependency_setup(self) -> None:
        has_ollama = shutil.which("ollama") is not None
        installed_models = self._get_installed_ollama_models() if has_ollama else set()
        missing_models = [m for m in LOCAL_AI_MODELS if m not in installed_models]
        has_spd_say = shutil.which("spd-say") is not None
        has_spell_tool = any(shutil.which(tool) for tool in ("aspell", "hunspell"))

        if has_ollama and not missing_models and has_spd_say and has_spell_tool:
            return

        if not has_ollama:
            self.local_ai_status_var.set("Local AI setup needed: Ollama is not installed.")
        elif missing_models:
            self.local_ai_status_var.set(
                "Local AI setup needed: missing models " + ", ".join(missing_models)
            )
        elif not has_spd_say:
            self.local_ai_status_var.set("Setup suggestion: install spd-say for read aloud.")
        elif not has_spell_tool:
            self.local_ai_status_var.set("Setup suggestion: install aspell or hunspell for spellcheck.")

        summary_lines = []
        if not has_ollama:
            summary_lines.append("- Ollama is missing")
        if missing_models:
            summary_lines.append("- Missing models: " + ", ".join(missing_models))
        if not has_spd_say:
            summary_lines.append("- Read-aloud tool missing: spd-say")
        if not has_spell_tool:
            summary_lines.append("- Spellcheck tool missing: aspell/hunspell")
        summary = "\n".join(summary_lines)

        if not messagebox.askyesno(
            "FilmPad first-time setup",
            "FilmPad detected missing optional/required dependencies:\n\n"
            f"{summary}\n\n"
            "Open guided setup now?",
        ):
            return

        self._show_local_ai_setup_dialog(
            ollama_missing=not has_ollama,
            missing_models=missing_models,
            spd_say_missing=not has_spd_say,
            spell_tool_missing=not has_spell_tool,
        )

    def _show_local_ai_setup_dialog(
        self,
        ollama_missing: bool,
        missing_models: list[str],
        spd_say_missing: bool,
        spell_tool_missing: bool,
    ) -> None:
        win = tk.Toplevel(self.root)
        win.title("FilmPad setup")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Install missing FilmPad dependencies",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Select what to install. A terminal will open and run the selected commands.",
            wraplength=430,
        ).pack(anchor="w", pady=(4, 10))

        install_ollama_var = tk.BooleanVar(value=ollama_missing)
        install_spd_say_var = tk.BooleanVar(value=spd_say_missing)
        install_spell_var = tk.BooleanVar(value=spell_tool_missing)
        model_vars: dict[str, tk.BooleanVar] = {
            model: tk.BooleanVar(value=True) for model in missing_models
        }

        if ollama_missing:
            ttk.Checkbutton(
                frame,
                text="Install Ollama",
                variable=install_ollama_var,
            ).pack(anchor="w", pady=(0, 8))

        if missing_models:
            ttk.Label(frame, text="Install models:").pack(anchor="w")
            for model in missing_models:
                ttk.Checkbutton(
                    frame,
                    text=model,
                    variable=model_vars[model],
                ).pack(anchor="w")

        if spd_say_missing or spell_tool_missing:
            ttk.Label(frame, text="Install system tools:").pack(anchor="w", pady=(8, 0))
            if spd_say_missing:
                ttk.Checkbutton(
                    frame,
                    text="speech-dispatcher (provides spd-say for Read Aloud)",
                    variable=install_spd_say_var,
                ).pack(anchor="w")
            if spell_tool_missing:
                ttk.Checkbutton(
                    frame,
                    text="aspell (spellcheck)",
                    variable=install_spell_var,
                ).pack(anchor="w")

        status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status_var, wraplength=430).pack(anchor="w", pady=(10, 0))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(12, 0))

        def _run_setup() -> None:
            selected_models = [
                model for model, var in model_vars.items() if var.get()
            ]
            install_ollama = bool(ollama_missing and install_ollama_var.get())
            install_spd_say = bool(spd_say_missing and install_spd_say_var.get())
            install_spell = bool(spell_tool_missing and install_spell_var.get())
            if not install_ollama and not selected_models and not install_spd_say and not install_spell:
                status_var.set("Nothing selected.")
                return

            cmd_lines = ["set -e"]
            package_names: list[str] = []
            if install_spd_say:
                package_names.append("speech-dispatcher")
            if install_spell:
                package_names.append("aspell")
            if package_names:
                cmd_lines.extend(self._build_package_install_script(package_names))
            if install_ollama:
                cmd_lines.extend(
                    [
                        "echo 'Installing Ollama...'",
                        "curl -fsSL https://ollama.com/install.sh | sh",
                    ]
                )
            if selected_models:
                cmd_lines.extend(
                    [
                        "if ! command -v ollama >/dev/null 2>&1; then",
                        "  echo 'Ollama was not found on PATH after setup.'",
                        "  exit 1",
                        "fi",
                        "if ! ollama list >/dev/null 2>&1; then",
                        "  if command -v systemctl >/dev/null 2>&1; then",
                        "    sudo systemctl start ollama || true",
                        "  fi",
                        "fi",
                        "if ! ollama list >/dev/null 2>&1; then",
                        "  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &",
                        "  sleep 2",
                        "fi",
                    ]
                )
                for model in selected_models:
                    cmd_lines.append(f"ollama pull {shlex.quote(model)}")
            cmd_lines.append("echo")
            cmd_lines.append("echo 'Setup complete. You can close this terminal.'")
            command_script = "\n".join(cmd_lines)

            launched = self._open_setup_terminal(command_script)
            if launched:
                status_var.set("Setup launched in terminal.")
                win.destroy()
            else:
                status_var.set("No terminal emulator found. Run setup commands manually.")
                messagebox.showinfo(
                    "Manual setup",
                    "No terminal emulator was detected. Run these commands manually:\n\n"
                    + command_script,
                )

        ttk.Button(btn_row, text="Run Setup", command=_run_setup).pack(side="left")
        ttk.Button(btn_row, text="Skip", command=win.destroy).pack(side="left", padx=(8, 0))

    def _build_package_install_script(self, packages: list[str]) -> list[str]:
        quoted = " ".join(shlex.quote(pkg) for pkg in packages)
        return [
            "echo 'Installing system packages...'",
            "if command -v apt-get >/dev/null 2>&1; then",
            "  sudo apt-get update",
            f"  sudo apt-get install -y {quoted}",
            "elif command -v dnf >/dev/null 2>&1; then",
            f"  sudo dnf install -y {quoted}",
            "elif command -v pacman >/dev/null 2>&1; then",
            f"  sudo pacman -Sy --noconfirm {quoted}",
            "elif command -v zypper >/dev/null 2>&1; then",
            f"  sudo zypper install -y {quoted}",
            "else",
            "  echo 'Unsupported package manager. Install manually:'",
            f"  echo '  {quoted}'",
            "  exit 1",
            "fi",
        ]

    def _open_setup_terminal(self, script: str) -> bool:
        shell_cmd = f"{script}\nexec bash"
        candidates = [
            ["x-terminal-emulator", "-e", "bash", "-lc", shell_cmd],
            ["gnome-terminal", "--", "bash", "-lc", shell_cmd],
            ["konsole", "-e", "bash", "-lc", shell_cmd],
            ["xfce4-terminal", "--hold", "-e", f"bash -lc {shlex.quote(shell_cmd)}"],
            ["xterm", "-hold", "-e", "bash", "-lc", shell_cmd],
        ]
        for cmd in candidates:
            if shutil.which(cmd[0]) is None:
                continue
            try:
                subprocess.Popen(cmd)
                return True
            except OSError:
                continue
        return False

    # ------------------------------------------------------------------
    # Writer AI panel
    # ------------------------------------------------------------------

    def _build_writer_ai_panel(self) -> None:
        outer = ttk.Frame(self.editor_frame)
        self.editor_frame.add(outer, stretch="never", minsize=32)

        _sash_after = [None]

        def _enforce_max_wa_width(event=None) -> None:
            if _sash_after[0] is not None:
                self.root.after_cancel(_sash_after[0])
            _sash_after[0] = self.root.after(80, _do_sash_enforce)

        def _do_sash_enforce(event=None) -> None:
            _sash_after[0] = None
            total = self.editor_frame.winfo_width()
            if total < 100:
                return
            max_wa = max(32, total // 3)
            try:
                sx = self.editor_frame.sash_coord(0)[0]
                right_w = total - sx
                if right_w < 32 or sx >= total:
                    self.editor_frame.sash_place(0, max(0, total - 300), 0)
                elif right_w > max_wa:
                    self.editor_frame.sash_place(0, total - max_wa, 0)
            except tk.TclError:
                pass

        self.editor_frame.bind("<Configure>", _enforce_max_wa_width)
        self.root.bind("<Configure>", _enforce_max_wa_width, add="+")
        self.editor_frame.bind("<ButtonRelease-1>", _do_sash_enforce)

        self._writer_ai_toggle_btn = ttk.Button(
            outer, text="\u25b6", width=3, command=self._toggle_writer_ai_sidebar
        )
        self._writer_ai_toggle_btn.pack(side="top", padx=(4, 4), pady=4)

        self._writer_ai_panel_container = ttk.Frame(outer)
        _wa_sb = ttk.Scrollbar(self._writer_ai_panel_container, orient="vertical")
        _wa_sb.pack(side="right", fill="y")
        self._writer_ai_panel_canvas = tk.Canvas(
            self._writer_ai_panel_container,
            highlightthickness=0, width=310,
            background=DARK_COLORS["ttk_bg"],
            yscrollcommand=_wa_sb.set,
        )
        self._writer_ai_panel_canvas.pack(side="left", fill="both", expand=True)
        _wa_sb.configure(command=self._writer_ai_panel_canvas.yview)
        self._writer_ai_content = ttk.Frame(
            self._writer_ai_panel_canvas, padding=(6, 2, 10, 10)
        )
        _wa_cw = self._writer_ai_panel_canvas.create_window(
            (0, 0), window=self._writer_ai_content, anchor="nw"
        )
        self._writer_ai_panel_canvas.bind(
            "<Configure>",
            lambda e, cw=_wa_cw: self._writer_ai_panel_canvas.itemconfigure(
                cw, width=e.width
            ),
        )
        self._writer_ai_content.bind(
            "<Configure>",
            lambda e: self._writer_ai_panel_canvas.configure(
                scrollregion=self._writer_ai_panel_canvas.bbox("all")
            ),
        )
        self._writer_ai_panel_container.pack(side="top", fill="both", expand=True)
        self._writer_ai_toggle_btn.configure(text="\u25b6")

        # \u2500\u2500 Accordion helper \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        def _make_acc(title: str, expanded: bool = False) -> ttk.Frame:
            c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
            outer = tk.Frame(
                self._writer_ai_content,
                bg=c["ttk_bg"],
                highlightbackground=c["ttk_bg"], highlightthickness=0,
            )
            outer.pack(fill="x", pady=(5, 0))
            hdr = tk.Frame(outer, bg=c["ttk_bg"], cursor="hand2")
            hdr.pack(fill="x")
            body = ttk.Frame(outer, padding=(4, 2, 0, 6))
            _open = [expanded]
            _arrow = tk.StringVar(value="\u25bc" if expanded else "\u25b6")

            def _accent():
                cc = DARK_COLORS if self._dark_mode else LIGHT_COLORS
                acc = _get_system_accent_sel_bg() if self._dark_mode else cc["sel_bg"]
                return acc, cc["sel_fg"], cc["ttk_bg"], cc["ttk_fg"]

            def _apply_style():
                acc, acc_fg, bg, fg = _accent()
                if _open[0]:
                    outer.configure(highlightbackground=acc, highlightthickness=1, bg=bg)
                    hdr.configure(bg=acc)
                    arrow_lbl.configure(bg=acc, fg=acc_fg)
                    title_lbl.configure(bg=acc, fg=acc_fg)
                else:
                    outer.configure(highlightbackground=bg, highlightthickness=0, bg=bg)
                    hdr.configure(bg=bg)
                    arrow_lbl.configure(bg=bg, fg=fg)
                    title_lbl.configure(bg=bg, fg=fg)

            def _toggle(e=None):
                _open[0] = not _open[0]
                if _open[0]:
                    body.pack(fill="x")
                    _arrow.set("\u25bc")
                else:
                    body.pack_forget()
                    _arrow.set("\u25b6")
                _apply_style()
                self._writer_ai_content.update_idletasks()
                self._writer_ai_panel_canvas.configure(
                    scrollregion=self._writer_ai_panel_canvas.bbox("all")
                )

            arrow_lbl = tk.Label(
                hdr, textvariable=_arrow, bg=c["ttk_bg"], fg=c["ttk_fg"],
                font=("TkDefaultFont", 7), cursor="hand2",
            )
            arrow_lbl.pack(side="left", padx=(0, 2))
            arrow_lbl.bind("<Button-1>", _toggle)
            title_lbl = tk.Label(
                hdr, text=title, bg=c["ttk_bg"], fg=c["ttk_fg"],
                font=("TkDefaultFont", 9, "bold"), cursor="hand2", pady=4,
            )
            title_lbl.pack(side="left")
            title_lbl.bind("<Button-1>", _toggle)
            hdr.bind("<Button-1>", _toggle)
            self._accordion_headers.append(_apply_style)
            if expanded:
                body.pack(fill="x")
                _apply_style()
            return body

        # ── Shared config (always visible) ─────────────────────────────────────────────
        ttk.Label(self._writer_ai_content, text="Project knowledge folder").pack(
            anchor="w", pady=(4, 0)
        )
        folder_row = ttk.Frame(self._writer_ai_content)
        folder_row.pack(fill="x", pady=(2, 4))
        ttk.Entry(
            folder_row, textvariable=self.writer_ai_project_folder_var, width=26
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            folder_row, text="...", width=3, command=self._pick_writer_ai_project_folder
        ).pack(side="left", padx=(4, 0))

        ttk.Label(self._writer_ai_content, text="Model").pack(anchor="w")
        ttk.Combobox(
            self._writer_ai_content,
            textvariable=self.writer_ai_model_var,
            values=LOCAL_AI_MODELS,
            state="readonly",
            width=28,
        ).pack(fill="x", pady=(2, 0))
        ttk.Label(
            self._writer_ai_content,
            text="Select a function to start.",
            font=("TkDefaultFont", 8),
            foreground="#888888",
        ).pack(anchor="w", pady=(6, 0))

        # \u2500\u2500 Accordion 1: Writer AI tools \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _wa = _make_acc("Writer AI", expanded=False)
        ttk.Label(
            _wa,
            text="Select text in editor, write a prompt, then generate.",
            wraplength=280, font=("TkDefaultFont", 8),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(_wa, text="Prompt").pack(anchor="w")
        prompt_frame = ttk.Frame(_wa)
        prompt_frame.pack(fill="x", pady=(2, 6))
        self.writer_ai_prompt_text = tk.Text(
            prompt_frame, width=30, height=7, wrap="word", padx=6, pady=6
        )
        prompt_scroll = tk.Scrollbar(prompt_frame, command=self.writer_ai_prompt_text.yview)
        self.writer_ai_prompt_scroll = prompt_scroll
        self.writer_ai_prompt_text.configure(yscrollcommand=prompt_scroll.set)
        prompt_scroll.pack(side="right", fill="y")
        self.writer_ai_prompt_text.pack(side="left", fill="both", expand=True)
        ttk.Button(
            _wa, text="\u2728 Transcribe into Script Format",
            command=self._transcribe_to_script_format,
        ).pack(fill="x", pady=(2, 0))
        ttk.Button(
            _wa, text="Edit Selection", command=self._run_writer_ai_edit
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(
            _wa, text="\u25a7 Review Last Output",
            command=self._show_writer_ai_comparison,
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(
            _wa, text="Save", command=self.save_file
        ).pack(fill="x", pady=(4, 0))

        # \u2500\u2500 Accordion 2: Auto Transcript \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _at = _make_acc("Auto Transcript", expanded=False)
        ttk.Label(
            _at,
            text="Place cursor at start point, then run. Processes the whole document block by block without review.",
            wraplength=240, font=("TkDefaultFont", 8),
        ).pack(anchor="w", pady=(0, 4))
        self._auto_transcript_btn = ttk.Button(
            _at, text="\u25b6 Auto Transcript", command=self._toggle_auto_transcript,
        )
        self._auto_transcript_btn.pack(fill="x")
        ttk.Label(
            _at, textvariable=self._at_log_var, wraplength=240,
            font=("TkDefaultFont", 8), foreground="#888888",
        ).pack(anchor="w", pady=(4, 0))
        self._at_progress_bar = ttk.Progressbar(
            _at, variable=self._at_progress_var, mode="determinate", maximum=100,
        )
        self._at_progress_bar.pack(fill="x", pady=(4, 2))
        _cb1 = tk.Checkbutton(
            _at,
            text="Safe mode (smaller steps, slower, more stable)",
            variable=self._auto_transcript_safe_mode_var,
            relief="flat", borderwidth=0, padx=0,
        )
        _cb1.pack(anchor="w", padx=0, pady=(4, 0))
        self._sidebar_checkbuttons.append(_cb1)
        _cb2 = tk.Checkbutton(
            _at,
            text="Extract knowledge to project folder",
            variable=self._at_extract_knowledge_var,
            relief="flat", borderwidth=0, padx=0,
        )
        _cb2.pack(anchor="w", padx=0, pady=(2, 0))
        self._sidebar_checkbuttons.append(_cb2)

        # \u2500\u2500 Accordion 3: Script Supervisor \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _ss = _make_acc("Script Supervisor", expanded=False)
        ttk.Label(
            _ss,
            text="Second-pass review: finds continuity gaps, block artifacts and "
                 "scene inconsistencies. Shows a comparison for each proposed fix.",
            wraplength=240, font=("TkDefaultFont", 8),
        ).pack(anchor="w", pady=(0, 4))
        self._script_supervisor_btn = ttk.Button(
            _ss, text="\u25b6 Script Supervisor", command=self._toggle_script_supervisor,
        )
        self._script_supervisor_btn.pack(fill="x")
        _cb3 = tk.Checkbutton(
            _ss,
            text="Rewrite to style ref (auto-apply)",
            variable=self._ss_style_rewrite_var,
            relief="flat", borderwidth=0, padx=0,
        )
        _cb3.pack(anchor="w", padx=0, pady=(4, 0))
        self._sidebar_checkbuttons.append(_cb3)
        ttk.Label(
            _ss, textvariable=self._ss_log_var, wraplength=240,
            font=("TkDefaultFont", 8), foreground="#888888",
        ).pack(anchor="w", pady=(4, 0))
        ttk.Button(
            _ss, text="View SS Log", command=self._show_ss_log_window,
        ).pack(fill="x", pady=(4, 0))

        # \u2500\u2500 Accordion 4: Typewriter Postscript \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _tp = _make_acc("Typewriter Postscript", expanded=False)
        ttk.Label(
            _tp,
            text="Final pass: cleans typos, duplicates, artifacts, misformatting "
                 "and missing character cues across the whole document.",
            wraplength=240, font=("TkDefaultFont", 8),
        ).pack(anchor="w", pady=(0, 4))
        self._tp_btn = ttk.Button(
            _tp, text="\u25b6 Typewriter Postscript",
            command=self._toggle_typewriter_postscript,
        )
        self._tp_btn.pack(fill="x")
        _cb_tp = tk.Checkbutton(
            _tp,
            text="Strip card metadata first",
            variable=self._tp_strip_metadata_var,
            relief="flat", borderwidth=0, padx=0,
        )
        _cb_tp.pack(anchor="w", padx=0, pady=(4, 0))
        self._sidebar_checkbuttons.append(_cb_tp)
        ttk.Label(
            _tp, textvariable=self._tp_log_var, wraplength=240,
            font=("TkDefaultFont", 8), foreground="#888888",
        ).pack(anchor="w", pady=(4, 0))
        ttk.Button(
            _tp, text="View TP Log", command=self._show_tp_log_window,
        ).pack(fill="x", pady=(4, 0))

        # \u2500\u2500 Accordion 5: Dictation Settings \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        _ds = _make_acc("Dictation Settings", expanded=False)
        ttk.Label(
            _ds, text="whisper-cli executable",
            font=("TkDefaultFont", 8, "bold"),
        ).pack(anchor="w", pady=(0, 2))
        _exe_row = ttk.Frame(_ds)
        _exe_row.pack(fill="x")
        ttk.Entry(_exe_row, textvariable=self._dictation_exe_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            _exe_row, text="...", width=3, command=self._pick_dictation_exe
        ).pack(side="left", padx=(4, 0))

        ttk.Label(
            _ds, text="Model file (.bin)",
            font=("TkDefaultFont", 8, "bold"),
        ).pack(anchor="w", pady=(6, 2))
        _model_row = ttk.Frame(_ds)
        _model_row.pack(fill="x")
        ttk.Entry(_model_row, textvariable=self._dictation_model_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            _model_row, text="...", width=3, command=self._pick_dictation_model
        ).pack(side="left", padx=(4, 0))

        _lang_dev_row = ttk.Frame(_ds)
        _lang_dev_row.pack(fill="x", pady=(6, 0))
        ttk.Label(_lang_dev_row, text="Language").pack(side="left")
        ttk.Entry(
            _lang_dev_row, textvariable=self._dictation_lang_var, width=5
        ).pack(side="left", padx=(4, 12))
        ttk.Label(_lang_dev_row, text="Mic device").pack(side="left")
        ttk.Entry(
            _lang_dev_row, textvariable=self._dictation_device_var, width=10
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            _ds,
            text="Leave Mic device blank for system default (e.g. plughw:1,0 or pulse).",
            font=("TkDefaultFont", 8), foreground="#888888", wraplength=240,
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            _ds,
            text="Smallest model: ggml-tiny.en.bin\nUpgrade anytime: ggml-base.en.bin",
            font=("TkDefaultFont", 8), foreground="#888888", wraplength=240,
        ).pack(anchor="w", pady=(4, 0))

        # \u2500\u2500 Status (always visible) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        ttk.Separator(self._writer_ai_content).pack(fill="x", pady=(10, 4))
        ttk.Label(
            self._writer_ai_content,
            textvariable=self.writer_ai_status_var,
            wraplength=240,
        ).pack(anchor="w")

        # Mouse-wheel scrolling (bind recursively to all children)
        def _wa_mw(e: tk.Event) -> None:
            self._writer_ai_panel_canvas.yview_scroll(
                -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1, "units"
            )

        def _bind_mw(w: tk.BaseWidget) -> None:
            w.bind("<Button-4>", _wa_mw, "+")
            w.bind("<Button-5>", _wa_mw, "+")
            w.bind("<MouseWheel>", _wa_mw, "+")
            for child in w.winfo_children():
                _bind_mw(child)

        _bind_mw(self._writer_ai_content)
        self._writer_ai_panel_canvas.bind("<Button-4>", _wa_mw)
        self._writer_ai_panel_canvas.bind("<Button-5>", _wa_mw)
        self._writer_ai_panel_canvas.bind("<MouseWheel>", _wa_mw)

        # Dynamic wraplength \u2014 recurse into accordion bodies
        _refresh_lock = [False]

        def _refresh_label_wraps(event=None) -> None:
            if _refresh_lock[0]:
                return
            w = self._writer_ai_content.winfo_width()
            if w < 50:
                return
            new_wrap = max(80, w - 16)
            _refresh_lock[0] = True

            def _recurse(widget: tk.BaseWidget) -> None:
                if isinstance(widget, (ttk.Label, tk.Label)):
                    try:
                        widget.configure(wraplength=new_wrap)
                    except tk.TclError:
                        pass
                for child in widget.winfo_children():
                    _recurse(child)

            _recurse(self._writer_ai_content)
            _refresh_lock[0] = False

        self._writer_ai_content.bind("<Configure>", _refresh_label_wraps, add="+")


    def _toggle_writer_ai_sidebar(self) -> None:
        total = self.editor_frame.winfo_width()
        if self._writer_ai_panel_container.winfo_ismapped():
            self._writer_ai_panel_container.pack_forget()
            self._writer_ai_toggle_btn.configure(text="\u25c4")
            try:
                self.editor_frame.sash_place(0, total - 36, 0)
            except tk.TclError:
                pass
        else:
            self._writer_ai_panel_container.pack(
                side="top", fill="both", expand=True
            )
            self._writer_ai_toggle_btn.configure(text="\u25b6")
            default_wa = min(300, max(200, total // 4))
            try:
                self.editor_frame.sash_place(0, total - default_wa, 0)
            except tk.TclError:
                pass

    def _pick_writer_ai_project_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Project Knowledge Folder")
        if folder:
            self.writer_ai_project_folder_var.set(folder)

    def _load_custom_prompt(self, filename: str, fallback: str) -> str:
        """Return text from <project_folder>/templates/<filename>, then
        <project_folder>/<filename>, then fallback."""
        folder = self.writer_ai_project_folder_var.get().strip()
        if folder:
            base = Path(folder)
            for candidate in (base / "templates" / filename, base / filename):
                if candidate.is_file():
                    try:
                        text = candidate.read_text(encoding="utf-8").strip()
                        if text:
                            return text
                    except OSError:
                        pass
        return fallback

    def _read_project_knowledge(self) -> str:
        folder = self.writer_ai_project_folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            return ""
        MAX_CHARS = 8000
        _KNOWLEDGE_EXCLUDE = {
            "style_reference.txt",
            "ss_prompt.txt", "ss_prompt_style.txt", "auto_transcript_prompt.txt",
        }
        chunks: list[str] = []
        total = 0
        for ext in ("*.md", "*.txt", "*.fdx"):
            for fpath in sorted(Path(folder).glob(ext)):
                if fpath.name in _KNOWLEDGE_EXCLUDE:
                    continue
                if total >= MAX_CHARS:
                    break
                try:
                    file_text = fpath.read_text(encoding="utf-8", errors="replace")
                    header = f"--- {fpath.name} ---\n"
                    available = MAX_CHARS - total - len(header)
                    if available <= 0:
                        break
                    chunk = header + file_text[:available]
                    chunks.append(chunk)
                    total += len(chunk)
                except Exception:
                    continue
        return "\n\n".join(chunks)

    def _build_writer_ai_prompt(
        self, selected_text: str, user_prompt: str, project_context: str
    ) -> str:
        template_text = self._load_adaptation_template()
        parts: list[str] = [
            "You are an expert screenplay writer and story editor.\n",
            "Work ONLY with what is explicitly present in the SELECTED TEXT. "
            "Do not add characters, events, or details that are not already there.\n",
            "The PROJECT KNOWLEDGE is background reference only — use it to stay "
            "consistent with names, locations, and tone, but do NOT import new content "
            "from it or invent anything absent from the selected text.\n\n",
        ]
        if project_context:
            parts.append(
                f"PROJECT KNOWLEDGE:\n{'=' * 40}\n{project_context}\n\n"
            )
        parts.append(
            f"SCREENPLAY TEMPLATE (format reference):\n{'=' * 40}\n{template_text}\n\n"
        )
        parts.append(
            f"SELECTED TEXT TO EDIT:\n{'=' * 40}\n{selected_text}\n\n"
        )
        parts.append(f"INSTRUCTION:\n{user_prompt}\n\n")
        parts.append(
            "Respond with ONLY the rewritten text. "
            "No explanations, no preamble, no meta-commentary.\n"
        )
        style_ref = self._load_custom_prompt("style_reference.txt", "")
        if style_ref:
            parts.append(
                f"\nREQUIRED OUTPUT STYLE — your output MUST conform to every rule below:\n"
                f"{'=' * 40}\n{style_ref}\n"
            )
        return "".join(parts)

    def _run_writer_ai_edit(self) -> None:
        if self.writer_ai_generating:
            return
        user_prompt = self.writer_ai_prompt_text.get("1.0", "end-1c").strip()
        if not user_prompt:
            messagebox.showinfo("Writer AI", "Enter a prompt first.")
            return
        try:
            sel_start = self.text.index(tk.SEL_FIRST)
            sel_end = self.text.index(tk.SEL_LAST)
            selected_text = self.text.get(sel_start, sel_end)
        except tk.TclError:
            sel_start = sel_end = None
            selected_text = self.text.get("1.0", "end-1c")
        if not selected_text.strip():
            messagebox.showinfo(
                "Writer AI", "Select some text or add content to the editor first."
            )
            return
        model = self.writer_ai_model_var.get()
        project_context = self._read_project_knowledge()
        full_prompt = self._build_writer_ai_prompt(selected_text, user_prompt, project_context)
        self.writer_ai_generating = True
        self._writer_ai_cancelled = False
        self._writer_ai_sel_start = sel_start
        self._writer_ai_sel_end = sel_end
        self.writer_ai_status_var.set("Generating...")
        detail = user_prompt[:60] + ("..." if len(user_prompt) > 60 else "")
        self._show_writer_ai_progress_overlay(detail, model)
        threading.Thread(
            target=self._run_writer_ai_thread, args=(model, full_prompt), daemon=True
        ).start()

    def _run_writer_ai_thread(self, model: str, prompt: str) -> None:
        import os
        try:
            env = {**os.environ, "COLUMNS": "10000", "TERM": "dumb"}
            proc = subprocess.Popen(
                ["ollama", "run", model],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            self._writer_ai_process = proc
            try:
                out, _err = proc.communicate(input=prompt.encode("utf-8"), timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.root.after(0, self._finish_writer_ai_edit, "", 1)
                return
            output = out.decode("utf-8", errors="replace")
            self.root.after(0, self._finish_writer_ai_edit, output, proc.returncode)
        except Exception:
            self.root.after(0, self._finish_writer_ai_edit, "", 1)

    def _finish_writer_ai_edit(self, output: str, returncode: int) -> None:
        self._close_progress_overlay()
        self.writer_ai_generating = False
        self._writer_ai_process = None
        if self._writer_ai_cancelled:
            self.writer_ai_status_var.set("Cancelled.")
            return
        if returncode != 0 or not output.strip():
            self.writer_ai_status_var.set("Error or no output from model.")
            return
        cleaned = self._sanitize_local_ai_output(output).strip()
        # Capture the original text for side-by-side review before any replacement
        if self._writer_ai_sel_start and self._writer_ai_sel_end:
            original = self.text.get(self._writer_ai_sel_start, self._writer_ai_sel_end)
        else:
            original = self.text.get("1.0", "end-1c")
        self._last_comparison = {
            "original": original,
            "proposed": cleaned,
            "sel_start": self._writer_ai_sel_start,
            "sel_end": self._writer_ai_sel_end,
        }
        self.writer_ai_status_var.set("Done. Review in comparison pane.")
        self._show_writer_ai_comparison()

    def _show_writer_ai_comparison(self) -> None:
        """Open (or re-open) the side-by-side original vs proposed comparison window."""
        data = self._last_comparison
        if not data:
            self.writer_ai_status_var.set("No output to review yet.")
            return
        # Bring existing window to front if already open
        if hasattr(self, "_cmp_win") and self._cmp_win and self._cmp_win.winfo_exists():
            self._cmp_win.lift()
            self._cmp_win.focus_force()
            return
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        self._cmp_win = win
        win.title("Review \u2014 Original vs Proposed")
        win.transient(self.root)
        self.root.update_idletasks()
        w, h = 1100, 720
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2
        # Keep window on-screen
        rx = max(0, rx)
        ry = max(0, ry)
        win.geometry(f"{w}x{h}+{rx}+{ry}")
        win.minsize(700, 500)
        win.configure(bg=c["ttk_bg"])

        # Header row
        header = tk.Frame(win, bg=c["ttk_bg"])
        header.pack(side="top", fill="x", padx=10, pady=(8, 0))
        tk.Label(header, text="Original  (read-only)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="left", padx=(0, 0))
        tk.Label(header, text="Proposed  (editable before accepting)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="right", padx=(0, 10))

        # Button bar — packed BEFORE the pane so it is always visible
        btn_bar = tk.Frame(win, bg=c["ttk_bg"])
        btn_bar.pack(side="bottom", fill="x", padx=10, pady=8)
        tk.Label(btn_bar,
                 text="Edit the right pane freely, then Accept to replace the selection in the editor.",
                 bg=c["ttk_bg"], fg=c["status_fg"]).pack(side="left")

        def _accept() -> None:
            new_text = prop_text.get("1.0", "end-1c")
            sel_start = data["sel_start"]
            sel_end = data["sel_end"]
            ins_pos = None
            if sel_start and sel_end:
                try:
                    self.text.delete(sel_start, sel_end)
                    self.text.insert(sel_start, new_text)
                    ins_pos = sel_start
                except tk.TclError:
                    self.text.insert(tk.END, "\n" + new_text)
            else:
                self.text.insert(tk.END, "\n" + new_text)
            if ins_pos is not None:
                end_pos = self.text.index(f"{ins_pos} + {len(new_text)}c")
                self._auto_tag_screenplay_block(self.text, ins_pos, end_pos)
            self.writer_ai_status_var.set("Changes accepted.")
            win.destroy()

        def _discard() -> None:
            self.writer_ai_status_var.set("Changes discarded.")
            win.destroy()

        tk.Button(btn_bar, text="Discard", width=12, command=_discard,
                  bg=c["entry_bg"], fg=c["ttk_fg"], relief="flat",
                  activebackground=c["sel_bg"]).pack(side="right", padx=(6, 0))
        tk.Button(btn_bar, text="Accept Changes", width=16, command=_accept,
                  bg="#0e639c", fg="white", relief="flat",
                  activebackground="#1177bb").pack(side="right")

        # Pane fills whatever space remains between header and button bar
        pane = tk.PanedWindow(win, orient="horizontal",
                              bg=c["ttk_bg"], sashrelief="flat", sashwidth=6)
        pane.pack(side="top", fill="both", expand=True, padx=10, pady=(4, 0))

        text_opts = dict(
            wrap="word", font=self.screenplay_font, padx=10, pady=10,
            background=c["text_bg"], foreground=c["text_fg"],
            insertbackground=c["insert"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
            inactiveselectbackground=c["sel_bg"],
        )
        orig_frame = tk.Frame(pane, bg=c["ttk_bg"])
        orig_text = tk.Text(orig_frame, state="normal", **text_opts)
        orig_scroll = tk.Scrollbar(orig_frame, command=orig_text.yview)
        orig_text.configure(yscrollcommand=orig_scroll.set)
        orig_scroll.pack(side="right", fill="y")
        orig_text.pack(fill="both", expand=True)
        orig_text.insert("1.0", data["original"])
        orig_text.configure(state="disabled")
        pane.add(orig_frame, stretch="always")

        prop_frame = tk.Frame(pane, bg=c["ttk_bg"])
        prop_text = tk.Text(prop_frame, **text_opts)
        prop_scroll = tk.Scrollbar(prop_frame, command=prop_text.yview)
        prop_text.configure(yscrollcommand=prop_scroll.set)
        prop_scroll.pack(side="right", fill="y")
        prop_text.pack(fill="both", expand=True)
        prop_text.insert("1.0", data["proposed"])
        pane.add(prop_frame, stretch="always")
        self._cmp_prop_text = prop_text

    def _transcribe_to_script_format(self) -> None:
        default_prompt = (
            "Reformat the following text as a properly laid-out screenplay.\n\n"
            "STRICT RULES — follow every one:\n"
            "1. Preserve every word verbatim: action lines, descriptions, situational "
            "notes, transitions, and all dialogue — do NOT cut, summarise, or paraphrase "
            "anything, not even a single sentence.\n"
            "2. Do NOT add anything that is not in the source: no notes, no "
            "[bracketed placeholders], no 'Dialogue not provided', no confidence scores, "
            "no commentary, no preamble — nothing.\n"
            "3. Scene headings (INT./EXT. or bare location lines): ALL CAPS, own line.\n"
            "4. Transitions (CUT TO, INTERCUT, FADE TO, SMASH CUT, etc.): "
            "ALL CAPS, own line, copied exactly as written.\n"
            "5. When a character speaks: place the character name in ALL CAPS on its own "
            "line, then their words on the next line, copied letter-for-letter.\n"
            "6. Everything else (description, action, stage directions) becomes an "
            "action line — copy it word for word.\n"
            "7. Do NOT merge, split, or reorder scenes.\n\n"
            "Output the reformatted screenplay and nothing else."
        )
        self.writer_ai_prompt_text.delete("1.0", tk.END)
        self.writer_ai_prompt_text.insert("1.0", default_prompt)
        self._run_writer_ai_edit()

    # ------------------------------------------------------------------
    # Auto Transcript (pseudo-agent loop)
    # ------------------------------------------------------------------

    _AT_SLUG_RE = re.compile(r"^(INT\.?|EXT\.?|INT\./EXT\.?|I/E\.?)\s", re.IGNORECASE)
    _AT_TRANS_RE = re.compile(
        r"^(FADE\s+(IN|OUT|TO)|CUT\s+TO|SMASH\s+CUT|MATCH\s+CUT|"
        r"DISSOLVE\s+TO|WIPE\s+TO|INTERCUT|TIME\s+CUT|JUMP\s+CUT)",
        re.IGNORECASE,
    )
    # Character name: ALL CAPS line, optional parenthetical suffix
    _AT_CHAR_NAME_RE = re.compile(r"^([A-Z][A-Z0-9 '.\-]{1,})(?:\s*\([^)]*\))?\s*$")
    _AT_MAX_CHARS = 2200  # max chars per block (leaves headroom for prompt)
    _AT_SAFE_MAX_CHARS = 1200
    _AT_NEXT_STEP_DELAY_MS = 300
    _AT_SAFE_NEXT_STEP_DELAY_MS = 1200

    _AT_PROMPT_DEFAULT = (
        "Reformat the following raw text as a properly formatted screenplay.\n\n"
        "FORMAT RULES:\n"
        "1. Scene headings (INT./EXT./INT.-EXT. LOCATION \u2014 TIME): ALL CAPS, own line.\n"
        "2. Action lines: present tense, short visual paragraphs. One blank line between blocks.\n"
        "3. Character names: ALL CAPS on their own line directly above dialogue.\n"
        "4. Dialogue: immediately below the character name line.\n"
        "5. Parentheticals: on their own line between character name and dialogue, "
        "only when delivery is not clear from context.\n"
        "6. Transitions (CUT TO:, FADE TO:, MATCH CUT TO:, SMASH CUT TO:, "
        "INTERCUT WITH:, etc.): ALL CAPS, own line, ending with a colon.\n"
        "7. Inserts and labels (INSERT \u2014 DESCRIPTION:, ON THE SCREEN:, "
        "BACK TO SCENE): ALL CAPS, own line.\n\n"
        "STRICT CONTENT RULES:\n"
        "8. Copy every word VERBATIM \u2014 do NOT cut, summarise, paraphrase, "
        "or rearrange anything. Not a single word.\n"
        "9. Do NOT add anything not present in the source: no placeholders, "
        "no [brackets], no explanatory notes, no preamble, no extra dialogue, nothing.\n"
        "10. Do NOT merge, split, or reorder scenes.\n"
        "11. Do NOT invent character names. Use only names that appear in the source text. "
        "If a speaker is unidentified, use UNKNOWN SPEAKER as the character cue.\n"
        "12. Do NOT add story events, locations, or dialogue that are not in the source. "
        "Reformatting and restructuring existing content is your job \u2014 inventing new content is not.\n\n"
        "Output the reformatted screenplay and nothing else."
    )

    _SS_STYLE_INSTRUCTIONS_DEFAULT = (
        "### INSTRUCTIONS — READ CAREFULLY ###\n\n"
        "OUTPUT: Return ONLY the corrected scene text. No notes. No explanations. No summary.\n"
        "Do not write anything before or after the scene. Do not describe what you changed.\n\n"
        "### TASK 1 — DELETE THESE ARTIFACTS ###\n\n"
        "Find and remove:\n"
        "- Orphan words/fragments at scene boundaries (block-boundary transcription leftovers)\n"
        "- Duplicated lines (same line or near-identical sentence appearing twice)\n"
        "- Technical markers: [END OF BLOCK], [CONTINUED], [inaudible], [transcription note], etc.\n"
        "- Story development outline text: act sub-labels with structure descriptions\n"
        "  (e.g. ACT I \u2014 ORDINARY WORLD / INCITING DISTURBANCE, Ordinary World,\n"
        "  Call to Adventure, 5-ACT STRUCTURE, Purpose:, HERO'S JOURNEY ALIGNMENT,\n"
        "  numbered outline items like '1. ORDINARY WORLD' and surrounding bullet-point text)\n"
        "- Editor or production notes embedded in action lines\n"
        "- Any line that has no story function and is inconsistent with the scene around it\n\n"
        "RULE: If you are not sure whether something is an artifact \u2014 LEAVE IT.\n"
        "Only remove what is unambiguously junk with zero story value.\n\n"
        "EXCEPTION: A clean standalone act header (e.g. ACT ONE or ACT I alone on its own\n"
        "line) is legitimate \u2014 reformat to ALL CAPS on its own line, do NOT remove it.\n\n"
        "### TASK 2 \u2014 APPLY FORMATTING FROM REQUIRED OUTPUT STYLE ###\n\n"
        "1. Scene headings: ALL CAPS, INT./EXT. LOCATION \u2014 TIME\n"
        "2. Transitions: ALL CAPS, own line, ending with colon (e.g. CUT TO:)\n"
        "3. Character cue lines above dialogue: ALL CAPS\n"
        "4. Parentheticals: own line, in parentheses\n"
        "5. Capitalisation/punctuation per REQUIRED OUTPUT STYLE\n\n"
        "### NEVER TOUCH ###\n\n"
        "- Dialogue: do not change a single word any character speaks\n"
        "- Action lines: do not rephrase, compress, or expand any description\n"
        "- Story events, props, characters, locations: do not add or remove anything\n"
        "- Sequence: do not reorder anything\n"
        "- Character names: use only names already present in this scene\n"
        "- Do NOT invent new characters, locations, events, or dialogue under any circumstances\n\n"
        "### REMINDER ###\n\n"
        "OUTPUT ONLY THE SCENE TEXT. Nothing else. No notes. No explanations."
    )

    _TP_INSTRUCTIONS_DEFAULT = (
        "### TYPEWRITER POSTSCRIPT — FORMATTING PASS ONLY ###\n\n"
        "OUTPUT ONLY THE REFORMATTED SCENE TEXT. No notes. No explanations.\n\n"
        "Your ONLY job is to apply industry-standard screenplay formatting.\n"
        "Do NOT change, add, or remove any story words, sentences, or content.\n\n"
        "FORMATTING CORRECTIONS TO APPLY:\n\n"
        "1. SCENE HEADINGS\n"
        "   Convert to ALL CAPS. Format: INT./EXT. LOCATION \u2014 TIME\n"
        "   Remove any SCENE number prefix: 'SCENE 3: INT. ...' \u2192 'INT. ...'\n"
        "   Use em dash (\u2014) between location and time.\n\n"
        "2. CHARACTER CUES\n"
        "   Convert to ALL CAPS on their own line above the dialogue.\n"
        "   If a line reads 'Name: dialogue' or 'First Last: dialogue', reformat as:\n"
        "       NAME\n"
        "       dialogue text\n"
        "   Include extensions in parentheses: (V.O.), (O.S.), (CONT'D).\n\n"
        "3. TRANSITIONS\n"
        "   Convert to ALL CAPS on their own line, ending with colon or period.\n\n"
        "4. PARENTHETICALS\n"
        "   Format on their own line, in parentheses, between the character cue and dialogue.\n\n"
        "5. DELETE THESE ARTIFACT LINES (no story value):\n"
        "   - Lines exactly matching: Not provided, Not Available, Unclear, Unknown, (None), N/A\n"
        "   - Inline LLM notes: lines starting with (Note: or Note: This scene...\n"
        "   - File references: any line containing .md (e.g. '03_File.md (context)')\n"
        "   - Template headers: lines starting with # followed by ALL CAPS words\n"
        "   - SCENE number prefixes on their own line: SCENE 3, SCENE #4\n\n"
        "NEVER DO:\n"
        "- Delete any line, sentence, dialogue, or action beat that has story content\n"
        "- Add new words, descriptions, or content not already present\n"
        "- Change character names, locations, or any story detail\n"
        "- Add notes, commentary, or explanations\n\n"
        "If the scene is already correctly formatted, return it completely unchanged.\n"
        "OUTPUT ONLY THE SCENE TEXT. Nothing else."
    )

    _SS_INSTRUCTIONS_DEFAULT = (
        "### SCRIPT SUPERVISOR — CONSERVATIVE REVIEW PASS ###\n\n"
        "OUTPUT ONLY THE CORRECTED SCENE TEXT. No notes. No explanations.\n\n"
        "WHAT TO FIX — do only these five things:\n\n"
        "1. TYPOS / SPELLING\n"
        "   Correct obvious misspellings of common words only.\n"
        "   Do NOT change character names, location names, or any proper noun.\n\n"
        "2. ARTIFACTS\n"
        "   Delete lines that are transcription/production leftovers with no story value:\n"
        "   [CONTINUED], [END OF BLOCK], [inaudible], block-boundary orphan fragments,\n"
        "   structural outline text (ACT I \u2014 ..., Ordinary World, Purpose:, etc.),\n"
        "   standalone placeholder words (Not provided, Unclear, Unknown, (None), N/A),\n"
        "   inline LLM notes ((Note: ...) or Note: This scene is correct...),\n"
        "   file references (anything.md ...), template headers (# PROJECT \u2014 TEMPLATE),\n"
        "   scene number prefixes (SCENE 3: or SCENE #: at the start of a heading).\n\n"
        "3. EXACT DUPLICATIONS\n"
        "   If the same sentence or line appears twice, delete the second occurrence.\n\n"
        "4. MISSING CHARACTER CUES\n"
        "   If a line of dialogue has no ALL CAPS character name above it, add the correct\n"
        "   name inferred from context. Use ONLY names already present in this scene\n"
        "   or the KNOWLEDGE BASE. Do NOT invent new names.\n\n"
        "5. MOOD / ACTION PARENTHETICALS\n"
        "   If a dialogue delivery is ambiguous, add a brief parenthetical on its own line\n"
        "   inferred from scene context: e.g. (quietly), (to SARAH), (picks up the file).\n"
        "   Keep them minimal (1-5 words). Do NOT add them if context is already clear.\n\n"
        "6. UNKNOWN TIME IN SCENE HEADING\n"
        "   If a scene heading contains UNKNOWN or has no time specifier, infer from context:\n"
        "   office / meetings / daytime activity \u2192 DAY\n"
        "   sleep / darkness / late-night atmosphere \u2192 NIGHT\n"
        "   scene continuing directly without a time gap \u2192 CONTINUOUS\n"
        "   default when genuinely ambiguous \u2192 DAY\n"
        "   Never leave UNKNOWN in a scene heading.\n\n"
        "NEVER DO:\n"
        "- Rewrite, rephrase, or expand any sentence\n"
        "- Change any character name, location, or story detail\n"
        "- Add new events, characters, or dialogue\n"
        "- Remove any line that carries story content\n"
        "- Add notes, commentary, or explanations\n\n"
        "If the scene has no issues, return it completely unchanged.\n"
        "OUTPUT ONLY THE SCENE TEXT. Nothing else."
    )

    def _auto_transcript_environment_risks(self) -> list[str]:
        risks: list[str] = []
        try:
            root_source = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", "/"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
            if root_source.startswith("/dev/sd"):
                risks.append("Root filesystem is on /dev/sd* (often external/USB on this hardware).")
                try:
                    tran = subprocess.run(
                        ["lsblk", "-ndo", "TRAN", root_source],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    ).stdout.strip().lower()
                    if "usb" in tran:
                        risks.append("Root filesystem transport appears to be USB.")
                except Exception:
                    pass
        except Exception:
            pass

        try:
            mounts = subprocess.run(
                ["findmnt", "-rn", "-o", "TARGET,SOURCE"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.splitlines()
            media_mounts = [line for line in mounts if line.startswith("/media/")]
            if media_mounts:
                risks.append("Removable/media mounts are active under /media.")
        except Exception:
            pass
        return risks

    def _confirm_auto_transcript_environment(self) -> bool:
        risks = self._auto_transcript_environment_risks()
        if not risks:
            return True
        msg = (
            "Auto Transcript can stress GPU/storage while Ollama is running.\n\n"
            "Detected risk factors:\n- " + "\n- ".join(risks) + "\n\n"
            "Recommended:\n"
            "- Keep Safe mode enabled\n"
            "- Close heavy apps\n"
            "- Prefer running Linux from an internal drive\n\n"
            "Start Auto Transcript anyway?"
        )
        return messagebox.askyesno("Auto Transcript safety warning", msg)

    def _toggle_auto_transcript(self) -> None:
        if self._auto_transcript_running:
            self._auto_transcript_running = False
            self._auto_transcript_cancelled = True
            if self._auto_transcript_process:
                try:
                    self._auto_transcript_process.kill()
                except OSError:
                    pass
            self._auto_transcript_process = None
            self.writer_ai_generating = False
            self._close_progress_overlay()
            self._auto_transcript_block_start = None
            self._auto_transcript_block_end = None
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self.writer_ai_status_var.set("Auto transcript stopped.")
        else:
            self._start_auto_transcript()

    def _start_auto_transcript(self) -> None:
        if self.writer_ai_generating:
            self.writer_ai_status_var.set("Wait for current generation to finish.")
            return
        # Warn if file is unsaved — auto-save will silently skip each block
        if not self.current_file:
            if not messagebox.askyesno(
                "Auto Transcript — unsaved file",
                "Your document has not been saved yet.\n\n"
                "Auto Transcript saves after every block to protect your work.\n"
                "Without a file path it cannot save anything.\n\n"
                "Save the file now before starting?",
            ):
                return
            if not self.save_as_file():
                return
        if not self._confirm_auto_transcript_environment():
            self.writer_ai_status_var.set("Auto transcript cancelled by safety warning.")
            return
        if self._at_extract_knowledge_var.get():
            if not self.writer_ai_project_folder_var.get().strip():
                self._show_popup_error(
                    "Auto Transcript — Extract Knowledge",
                    "No project folder is set.\n\n"
                    "Set a project knowledge folder\n"
                    "in the Writer AI panel,\n"
                    "then retry."
                )
                return
        self._auto_transcript_cancelled = False
        self._auto_transcript_process = None
        self._at_known_chars = {}
        self._at_known_locs = {}
        self._at_current_loc = ""
        try:
            start_pos = self.text.index(tk.INSERT)
        except tk.TclError:
            start_pos = "1.0"
        # Use a floating mark so the position survives text insertions
        self.text.mark_set("_at_cursor", start_pos)
        self.text.mark_gravity("_at_cursor", "right")
        self._auto_transcript_block_num = 0
        self._at_start_line = int(start_pos.split(".")[0])
        self._at_total_lines_snapshot = int(self.text.index("end-1c").split(".")[0])
        self._at_progress_var.set(0.0)
        self._at_log_var.set(f"Started: L{self._at_start_line} | Block: 0 | Pos: L{self._at_start_line} | Saved: —")
        self._auto_transcript_running = True
        if self._auto_transcript_btn:
            self._auto_transcript_btn.configure(text="\u23f9 Stop Auto Transcript")
        self._auto_transcript_step()

    def _auto_transcript_step(self) -> None:
        """Kick off the next block, or finish if nothing remains."""
        if not self._auto_transcript_running:
            return
        if self.writer_ai_generating:
            self.root.after(600, self._auto_transcript_step)
            return
        result = self._auto_transcript_get_block()
        if result is None:
            self._auto_transcript_running = False
            self._at_progress_var.set(100.0)
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            try:
                self._at_end_line = int(self.text.index("_at_cursor").split(".")[0])
            except tk.TclError:
                self._at_end_line = self._at_start_line
            if (self._at_extract_knowledge_var.get()
                    and (self._at_known_chars or self._at_known_locs)):
                self.writer_ai_status_var.set("Writing knowledge files\u2026")
                self._at_log_var.set("Writing knowledge files\u2026")
                self.root.after(200, self._at_write_knowledge_files)
            else:
                self.writer_ai_status_var.set("Auto transcript complete.")
            return
        block_text, block_start, block_end = result
        self._auto_transcript_block_start = block_start
        self._auto_transcript_block_end = block_end
        # Highlight the block being processed
        self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
        self.text.tag_add(AUTO_TRANSCRIPT_TAG, block_start, block_end)
        self.text.see(block_start)
        n = block_text.count("\n") + 1
        self._auto_transcript_block_num += 1
        cur_line = int(block_start.split(".")[0])
        self._at_log_var.set(
            f"Started: L{self._at_start_line} | Block: {self._auto_transcript_block_num}"
            f" | Pos: L{cur_line} | Saved: {self._at_last_saved_label()}"
        )
        _pct = min(99.0, cur_line / max(1, self._at_total_lines_snapshot) * 100)
        self._at_progress_var.set(_pct)
        end_line = min(cur_line + n - 1, self._at_total_lines_snapshot)
        self._progress_detail_var.set(
            f"Block {self._auto_transcript_block_num}"
            f"  —  L{cur_line}–{end_line} of {self._at_total_lines_snapshot}"
        )
        # Load prompt from project folder (auto_transcript_prompt.txt) or use built-in default
        prompt = self._load_custom_prompt("auto_transcript_prompt.txt", self._AT_PROMPT_DEFAULT)
        project_context = self._read_project_knowledge()
        full_prompt = self._build_writer_ai_prompt(block_text, prompt, project_context)
        model = self.writer_ai_model_var.get().strip()
        if not model:
            self.writer_ai_status_var.set("Auto transcript: select a model first.")
            self._auto_transcript_running = False
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            return
        self.writer_ai_generating = True
        self._show_writer_ai_progress_overlay(f"Auto transcript ({n} lines)", model)
        threading.Thread(
            target=self._auto_transcript_thread,
            args=(model, full_prompt),
            daemon=True,
        ).start()

    def _auto_transcript_get_block(self) -> tuple[str, str, str] | None:
        """Return (block_text, start_idx, end_idx) for the next block, or None if done."""
        try:
            pos = self.text.index("_at_cursor")
        except tk.TclError:
            return None
        # Skip blank lines at cursor
        while self.text.compare(pos, "<", "end-1c"):
            line = self.text.get(f"{pos} linestart", f"{pos} lineend")
            if line.strip():
                break
            pos = self.text.index(f"{pos} + 1 line")
        if self.text.compare(pos, ">=", "end-1c"):
            return None
        start = self.text.index(f"{pos} linestart")
        current = start
        accumulated = 0
        last_blank: str | None = None
        last_scene: str | None = None
        while self.text.compare(current, "<", "end-1c"):
            line_end = self.text.index(f"{current} lineend")
            line = self.text.get(current, line_end)
            accumulated += len(line) + 1
            next_line = self.text.index(f"{current} + 1 line")
            stripped = line.strip()
            # Track natural break points
            if not stripped:
                last_blank = next_line
            elif (self._AT_SLUG_RE.match(stripped) or self._AT_TRANS_RE.match(stripped)) \
                    and accumulated > 120:
                last_scene = current   # break BEFORE this heading/transition
            max_chars = self._AT_SAFE_MAX_CHARS if self._auto_transcript_safe_mode_var.get() else self._AT_MAX_CHARS
            if accumulated >= max_chars:
                end = last_scene or last_blank or line_end
                break
            if self.text.compare(next_line, ">=", "end-1c"):
                end = self.text.index("end-1c")
                break
            current = next_line
        else:
            end = self.text.index("end-1c")
        block_text = self.text.get(start, end)
        if not block_text.strip():
            return None
        return block_text, start, end

    def _auto_transcript_thread(self, model: str, prompt: str) -> None:
        import os
        try:
            env = {**os.environ, "COLUMNS": "10000", "TERM": "dumb"}
            proc = subprocess.Popen(
                ["ollama", "run", model],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            self._auto_transcript_process = proc
            try:
                out, _err = proc.communicate(input=prompt.encode("utf-8"), timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.root.after(0, self._auto_transcript_finish, "", 1)
                return
            output = out.decode("utf-8", errors="replace")
            self.root.after(0, self._auto_transcript_finish, output, proc.returncode)
        except Exception:
            self.root.after(0, self._auto_transcript_finish, "", 1)

    def _auto_transcript_finish(self, output: str, returncode: int) -> None:
        self._close_progress_overlay()
        self.writer_ai_generating = False
        self._auto_transcript_process = None
        if self._auto_transcript_cancelled or not self._auto_transcript_running:
            self._auto_transcript_running = False
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self.writer_ai_status_var.set("Auto transcript stopped.")
            return
        if returncode != 0 or not output.strip():
            self._auto_transcript_running = False
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self.writer_ai_status_var.set("Auto transcript: model error — stopped.")
            return
        cleaned = self._sanitize_local_ai_output(output).strip()
        if not cleaned:
            self._auto_transcript_running = False
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self.writer_ai_status_var.set("Auto transcript: empty output — stopped.")
            return
        # Auto-replace the source block with the formatted output
        bs = self._auto_transcript_block_start
        be = self._auto_transcript_block_end
        try:
            self.text.delete(bs, be)
            self.text.insert(bs, cleaned + "\n\n")
            ins_end = self.text.index(f"{bs} + {len(cleaned) + 2}c")
            self._auto_tag_screenplay_block(self.text, bs, ins_end)
            # Advance the floating mark to just after inserted text
            self.text.mark_set("_at_cursor", ins_end)
            self.text.mark_gravity("_at_cursor", "right")
            self.text.see(ins_end)
            # Clear undo history after each block to prevent RAM accumulation
            # during long sessions (undo is not useful mid-AT-run anyway)
            self.text.edit_reset()
            self._auto_transcript_autosave()
            if self._at_extract_knowledge_var.get():
                self._at_parse_block_for_knowledge(cleaned)
        except tk.TclError as exc:
            self._auto_transcript_running = False
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self.writer_ai_status_var.set(f"Auto transcript error: {exc}")
            return
        # Small pause then process next block
        delay = self._AT_SAFE_NEXT_STEP_DELAY_MS if self._auto_transcript_safe_mode_var.get() else self._AT_NEXT_STEP_DELAY_MS
        self.root.after(delay, self._auto_transcript_step)

    def _at_last_saved_label(self) -> str:
        return getattr(self, "_at_last_saved_str", "\u2014")

    def _auto_transcript_autosave(self) -> None:
        """Silently save the file after each completed block; update the AT log."""
        try:
            cur_line = int(self.text.index("_at_cursor").split(".")[0])
        except tk.TclError:
            cur_line = 0
        if self.current_file:
            try:
                with open(self.current_file, "w", encoding="utf-8") as f:
                    f.write(self.text.get("1.0", "end-1c"))
                self.text.edit_modified(False)
                self._set_title()
                self._at_last_saved_str = f"L{cur_line}"
            except OSError as exc:
                self._at_last_saved_str = f"err: {exc}"
        else:
            self._at_last_saved_str = "unsaved"
        self._at_log_var.set(
            f"Started: L{self._at_start_line} | Block: {self._auto_transcript_block_num}"
            f" | Pos: L{cur_line} | Saved: {self._at_last_saved_label()}"
        )

    # ── AT Knowledge Extraction ──────────────────────────────────────────

    def _at_parse_block_for_knowledge(self, text: str) -> None:
        """Parse a formatted screenplay block; update character/location knowledge."""
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            # Scene heading
            if self._AT_SLUG_RE.match(line):
                heading = line.upper().rstrip()
                self._at_current_loc = heading
                if heading not in self._at_known_locs:
                    self._at_known_locs[heading] = []
                i += 1
                continue
            # Transition
            if self._AT_TRANS_RE.match(line):
                i += 1
                continue
            # Character name: ALL CAPS, no colon, no dash
            if (line == line.upper() and len(line) >= 2
                    and ':' not in line
                    and '\u2014' not in line
                    and '\u2013' not in line):
                char_name = re.sub(r'\s*\([^)]*\)\s*$', '', line).strip()
                if char_name and len(char_name) >= 2:
                    if char_name not in self._at_known_chars:
                        self._at_known_chars[char_name] = {
                            'dialogue': [], 'refs': [], 'scenes': set()
                        }
                    if self._at_current_loc:
                        self._at_known_chars[char_name]['scenes'].add(self._at_current_loc)
                    # Next non-empty line is the dialogue
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines):
                        dl = lines[j].strip()
                        # Dialogue is mixed-case (not pure uppercase action)
                        if dl and not (dl == dl.upper() and len(dl) > 3):
                            if len(self._at_known_chars[char_name]['dialogue']) < 30:
                                self._at_known_chars[char_name]['dialogue'].append(dl)
                            i = j + 1
                            continue
                i += 1
                continue
            # Action line — log under current location; note character mentions
            if self._at_current_loc and len(
                self._at_known_locs.get(self._at_current_loc, [])
            ) < 12:
                self._at_known_locs[self._at_current_loc].append(line)
            for char_name in list(self._at_known_chars):
                if char_name in line and len(
                    self._at_known_chars[char_name]['refs']
                ) < 30:
                    self._at_known_chars[char_name]['refs'].append(line)
            i += 1

    def _at_write_knowledge_files(self) -> None:
        """Append per-character and per-location .md files, then spawn project_memory."""
        folder = self.writer_ai_project_folder_var.get().strip()
        if not folder:
            self._at_log_var.set("Extract: no project folder set.")
            self.writer_ai_status_var.set("Auto transcript complete.")
            return
        folder_path = Path(folder)
        written = 0
        end_line = getattr(self, '_at_end_line', self._at_start_line)
        section_label = f"## New info found on lines {self._at_start_line}\u2013{end_line}"

        # Character files
        for char_name, data in self._at_known_chars.items():
            fname = re.sub(r'[^\w]', '_', char_name).strip('_')[:50] + '.md'
            fpath = folder_path / fname
            body_parts = []
            scenes = sorted(data.get('scenes', set()))
            if scenes:
                body_parts.append(f"**Appears in:** {len(scenes)} scene(s)\n\n")
                for s in scenes[:10]:
                    body_parts.append(f"- {s}\n")
                body_parts.append("\n")
            dialogue = data.get('dialogue', [])
            if dialogue:
                body_parts.append("### Dialogue\n\n")
                for dl in dialogue:
                    body_parts.append(f'- "{dl}"\n')
                body_parts.append("\n")
            refs = data.get('refs', [])
            if refs:
                body_parts.append("### Referenced in action\n\n")
                for r in refs:
                    body_parts.append(f"- {r}\n")
            body = "".join(body_parts)
            if fpath.exists():
                existing = fpath.read_text(encoding="utf-8").rstrip()
                fpath.write_text(
                    existing + f"\n\n{section_label}\n\n" + body,
                    encoding="utf-8",
                )
            else:
                fpath.write_text(
                    f"# {char_name}\n\n{section_label}\n\n" + body,
                    encoding="utf-8",
                )
            written += 1

        # Location files
        for loc_heading, action_lines in self._at_known_locs.items():
            slug = re.sub(
                r'^(INT\.|EXT\.|INT\./EXT\.|I/E\.)\s*', '', loc_heading,
                flags=re.IGNORECASE,
            )
            slug = re.sub(r'\s*[\u2014\u2013\-]+\s*.*$', '', slug).strip()
            slug = re.sub(r'[^\w]', '_', slug).strip('_')[:50]
            if not slug:
                continue
            fname = slug.upper() + '.md'
            fpath = folder_path / fname
            body_parts = []
            if action_lines:
                body_parts.append("### Action lines\n\n")
                for al in action_lines:
                    body_parts.append(f"- {al}\n")
            body = "".join(body_parts)
            if fpath.exists():
                existing = fpath.read_text(encoding="utf-8").rstrip()
                fpath.write_text(
                    existing + f"\n\n{section_label}\n\n" + body,
                    encoding="utf-8",
                )
            else:
                fpath.write_text(
                    f"# {loc_heading}\n\n{section_label}\n\n" + body,
                    encoding="utf-8",
                )
            written += 1

        self._at_log_var.set(f"Wrote {written} knowledge files. Generating project_memory\u2026")

        # project_memory.md — LLM synthesis
        model = self.writer_ai_model_var.get().strip()
        if not model or not shutil.which("ollama"):
            self.writer_ai_status_var.set("Auto transcript complete.")
            self._at_log_var.set(f"Wrote {written} files. (No model for project_memory.)")
            return

        char_summary = "\n".join(
            f"- {n}: {len(d.get('dialogue', []))} dialogue lines, "
            f"{len(d.get('scenes', set()))} scenes"
            for n, d in list(self._at_known_chars.items())[:40]
        )
        loc_list = "\n".join(
            f"- {loc}" for loc in list(self._at_known_locs.keys())[:40]
        )
        sample_dialogue_parts = []
        for n, d in list(self._at_known_chars.items())[:12]:
            for dl in d.get('dialogue', [])[:3]:
                sample_dialogue_parts.append(f'{n}: "{dl}"')

        pm_prompt = (
            "You are analysing a screenplay. Using the extracted data below, "
            "write a project_memory.md file in markdown with these sections:\n"
            "## Characters\nBrief role description for each character.\n"
            "## Key Events\nMajor plot beats inferred from the data.\n"
            "## Relationships\nNotable connections between characters.\n"
            "## Locations\nBrief description of each key location.\n\n"
            f"CHARACTERS:\n{char_summary}\n\n"
            f"LOCATIONS IN SCRIPT ORDER:\n{loc_list}\n\n"
            "SAMPLE DIALOGUE:\n" + "\n".join(sample_dialogue_parts[:30]) + "\n\n"
            "Output only the markdown content for project_memory.md."
        )
        threading.Thread(
            target=self._at_write_project_memory_thread,
            args=(folder_path, model, pm_prompt, section_label),
            daemon=True,
        ).start()

    def _at_write_project_memory_thread(
        self, folder_path: Path, model: str, prompt: str, section_label: str
    ) -> None:
        """Background thread: call Ollama and append a section to project_memory.md."""
        import os as _os
        try:
            ollama_bin = shutil.which("ollama") or "ollama"
            env = {**_os.environ, "COLUMNS": "10000", "TERM": "dumb"}
            proc = subprocess.Popen(
                [ollama_bin, "run", model],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            try:
                out, _ = proc.communicate(input=prompt.encode("utf-8"), timeout=300)
                content = out.decode("utf-8", errors="replace").strip()
                if content:
                    content = self._sanitize_local_ai_output(content)
                    pm_path = folder_path / "project_memory.md"
                    if pm_path.exists():
                        existing = pm_path.read_text(encoding="utf-8").rstrip()
                        pm_path.write_text(
                            existing + f"\n\n{section_label}\n\n" + content,
                            encoding="utf-8",
                        )
                    else:
                        pm_path.write_text(
                            f"# Project Memory\n\n{section_label}\n\n" + content,
                            encoding="utf-8",
                        )
                    self.root.after(0, lambda: self._at_log_var.set(
                        "Knowledge extraction complete — project_memory.md written."
                    ))
                    self.root.after(0, lambda: self.writer_ai_status_var.set(
                        "Auto transcript complete."
                    ))
                else:
                    self.root.after(0, lambda: self._at_log_var.set(
                        "Extract: project_memory.md — empty model output."
                    ))
                    self.root.after(0, lambda: self.writer_ai_status_var.set(
                        "Auto transcript complete."
                    ))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.root.after(0, lambda: self._at_log_var.set(
                    "Extract: project_memory.md — timed out."
                ))
                self.root.after(0, lambda: self.writer_ai_status_var.set(
                    "Auto transcript complete."
                ))
        except Exception as exc:
            self.root.after(0, lambda msg=str(exc): self._at_log_var.set(
                f"Extract error: {msg}"
            ))
            self.root.after(0, lambda: self.writer_ai_status_var.set(
                "Auto transcript complete."
            ))

    # ── Script Supervisor ───────────────────────────────────────────────

    def _toggle_script_supervisor(self) -> None:
        if self._script_supervisor_running:
            self._script_supervisor_running = False
            if self._script_supervisor_btn:
                self._script_supervisor_btn.configure(text="\u25b6 Script Supervisor")
            self.writer_ai_status_var.set("Script Supervisor stopped.")
            return
        self._start_script_supervisor()

    def _ss_get_scenes(self) -> list[tuple[str, str]]:
        """Return (start_idx, end_idx) pairs for each scene, split by Scene Heading.
        Always combines tagged 'Scene Heading' spans and regex-matched INT./EXT. lines
        so that partially-tagged documents are fully covered."""
        scene_line_set: set[int] = set()
        # Pass 1: tagged Scene Heading spans
        pos = "1.0"
        while True:
            rng = self.text.tag_nextrange("Scene Heading", pos)
            if not rng:
                break
            ln = int(self.text.index(f"{rng[0]} linestart").split(".")[0])
            scene_line_set.add(ln)
            pos = self.text.index(f"{rng[1]} + 1c")
            if self.text.compare(pos, ">=", "end-1c"):
                break
        # Pass 2: regex scan — catches untagged INT./EXT. lines (always runs)
        total_lines = int(self.text.index("end-1c").split(".")[0])
        for lineno in range(1, total_lines + 1):
            line = self.text.get(f"{lineno}.0", f"{lineno}.end").strip()
            if line and self._AT_SLUG_RE.match(line):
                scene_line_set.add(lineno)
        scene_starts = [f"{ln}.0" for ln in sorted(scene_line_set)]
        scenes: list[tuple[str, str]] = []
        # Preamble: text before the first scene heading (never captured otherwise)
        if scene_starts:
            first_line = int(scene_starts[0].split(".")[0])
            if first_line > 1:
                pre_end = self.text.index(f"{first_line - 1}.end")
                if self.text.get("1.0", pre_end).strip():
                    scenes.append(("1.0", pre_end))
        for i, start in enumerate(scene_starts):
            if i < len(scene_starts) - 1:
                next_line = int(scene_starts[i + 1].split(".")[0])
                end = self.text.index(f"{max(1, next_line - 1)}.end")
            else:
                end = self.text.index("end-1c")
            if self.text.get(start, end).strip():
                scenes.append((start, end))
        if not scenes and self.text.get("1.0", "end-1c").strip():
            scenes = [("1.0", self.text.index("end-1c"))]
        return scenes

    def _start_script_supervisor(self) -> None:
        if self.writer_ai_generating:
            # Only block if something is actually running; otherwise reset stale flag
            at_active = self._auto_transcript_running
            wa_active = (
                self._writer_ai_process is not None
                and self._writer_ai_process.poll() is None
            )
            if at_active or wa_active:
                self.writer_ai_status_var.set("Wait for current generation to finish.")
                return
            # Stale flag — reset and continue
            self.writer_ai_generating = False
        model = self.writer_ai_model_var.get().strip()
        if not model:
            messagebox.showwarning("Script Supervisor", "Select a model first.")
            return
        if not shutil.which("ollama"):
            messagebox.showerror(
                "Script Supervisor",
                "Ollama is not installed or not on PATH.\n\nInstall it at https://ollama.com/download\nthen run doctor.sh to verify.",
            )
            return
        if not self.current_file:
            if not messagebox.askyesno(
                "Script Supervisor — unsaved file",
                "Your document has not been saved yet.\n\n"
                "Script Supervisor saves after every scene to protect your work.\n"
                "Without a file path it cannot save anything.\n\n"
                "Save the file now before starting?",
            ):
                return
            if not self.save_as_file():
                return
        scenes = self._ss_get_scenes()
        if not scenes:
            messagebox.showinfo("Script Supervisor", "No scenes found to review.")
            return
        if self._ss_style_rewrite_var.get():
            folder = self.writer_ai_project_folder_var.get().strip()
            style_found = False
            if folder:
                base = Path(folder)
                for candidate in (base / "templates" / "style_reference.txt", base / "style_reference.txt"):
                    if candidate.is_file():
                        style_found = True
                        break
            if not style_found:
                msg = (
                    "style_reference.txt not found.\n\n"
                    "Place it in your project knowledge folder:\n"
                    "  <folder>/style_reference.txt\n"
                    "  or  <folder>/templates/style_reference.txt\n\n"
                    "Set the folder in the Writer AI panel, then retry."
                    if folder else
                    "No project folder is set.\n\n"
                    "Set a project knowledge folder\n"
                    "in the Writer AI panel, then add\n"
                    "style_reference.txt to it."
                )
                self._show_popup_error("Script Supervisor — Style Rewrite", msg)
                return
        self._ss_scene_list = scenes
        self._ss_scene_idx = 0
        self._ss_pending = None
        self._ss_applied_count = 0
        self._ss_clean_count = 0
        _knowledge_note = ""
        if self._ss_style_rewrite_var.get():
            _kb = self._read_project_knowledge()
            _knowledge_note = f", knowledge={'yes' if _kb else 'none'}"
        self._ss_last_saved_str = "—"
        self._ss_full_log = [f"SS started — {len(scenes)} scenes, style_rewrite={self._ss_style_rewrite_var.get()}{_knowledge_note}"]
        self._script_supervisor_running = True
        self._at_progress_var.set(0.0)
        if self._script_supervisor_btn:
            self._script_supervisor_btn.configure(text="\u23f9 Stop Supervisor")
        self._ss_log_var.set(f"0 / {len(scenes)} scenes")
        self.writer_ai_status_var.set("Script Supervisor starting\u2026")
        self._ss_step()

    def _ss_step(self) -> None:
        if not self._script_supervisor_running:
            return
        if self.writer_ai_generating:
            self.root.after(600, self._ss_step)
            return
        idx = self._ss_scene_idx
        total = len(self._ss_scene_list)
        if idx >= total:
            self._script_supervisor_running = False
            self._at_progress_var.set(100.0)
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._script_supervisor_btn:
                self._script_supervisor_btn.configure(text="\u25b6 Script Supervisor")
            _applied = getattr(self, "_ss_applied_count", 0)
            _clean = getattr(self, "_ss_clean_count", 0)
            if _applied:
                _s = "s" if _applied != 1 else ""
                _summary = f"Done \u2014 {_applied} scene{_s} rewritten, {_clean} unchanged."
            else:
                _summary = f"Complete \u2014 {total} scene{'s' if total != 1 else ''} reviewed, all clean."
            self._ss_log_var.set(_summary)
            self._ss_full_log.append(_summary)
            self._ss_full_log.append("--- end of session ---")
            self.writer_ai_status_var.set("Script Supervisor complete.")
            return
        start, end = self._ss_scene_list[idx]
        # Highlight and scroll to the scene being reviewed
        self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
        self.text.tag_add(AUTO_TRANSCRIPT_TAG, start, end)
        self.text.see(start)
        scene_text = self.text.get(start, end)
        # Fast pre-screen: skip clean scenes without calling the model
        if not self._ss_scene_needs_review(scene_text):
            self._ss_clean_count += 1
            _pct = min(99.0, (idx + 1) / max(1, total) * 100)
            self._at_progress_var.set(_pct)
            _msg = f"Scene {idx + 1}/{total}: clean \u2014 skipped"
            self._ss_log_var.set(_msg)
            self._ss_full_log.append(_msg)
            self._ss_scene_idx += 1
            self.root.after(30, self._ss_step)
            return
        style_ref = self._load_custom_prompt("style_reference.txt", "")
        if self._ss_style_rewrite_var.get():
            # Include a trimmed knowledge base for name/location reference
            _kb_raw = self._read_project_knowledge()
            knowledge_trimmed = _kb_raw[:2000] if _kb_raw else ""
            # Log what names were found in the knowledge base (first call only)
            if _kb_raw and self._ss_scene_idx == 0:
                import re as _re
                _names = _re.findall(r'\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b', _kb_raw[:1000])
                _uniq = list(dict.fromkeys(_names))[:8]
                _kb_detail = ", ".join(_uniq) if _uniq else "(no names found)"
                self._ss_full_log.append(f"Knowledge base loaded \u2014 {_kb_detail}")
            parts = [
                "You are a professional screenplay style editor.\n",
                f"SCENE TO REWRITE:\n{scene_text}\n",
                self._load_custom_prompt("ss_prompt_style.txt", self._SS_STYLE_INSTRUCTIONS_DEFAULT),
            ]
            if knowledge_trimmed:
                parts.append(
                    f"\nKNOWLEDGE BASE (character names and locations \u2014 reference only, "
                    f"do NOT add content from here):\n{knowledge_trimmed}\n"
                )
            if style_ref:
                parts.append(
                    f"\nREQUIRED OUTPUT STYLE \u2014 conform to every rule below:\n"
                    f"{'=' * 40}\n{style_ref}\n"
                )
        else:
            # Full prompt for standard SS: knowledge + context windows + scene + instructions
            prev_ctx = ""
            if idx > 0:
                p_start, p_end = self._ss_scene_list[idx - 1]
                prev_full = self.text.get(p_start, p_end)
                prev_ctx = prev_full[-400:].strip()
            next_ctx = ""
            if idx < total - 1:
                n_start, n_end = self._ss_scene_list[idx + 1]
                next_full = self.text.get(n_start, n_end)
                next_ctx = next_full[:400].strip()
            knowledge = self._read_project_knowledge()
            parts = [
                "You are a professional script supervisor reviewing a screenplay.\n"
                "It was auto-transcribed in blocks and may have artifacts at block boundaries.\n"
            ]
            if knowledge:
                parts.append(f"KNOWLEDGE BASE (names, locations \u2014 reference only, do NOT add content from here):\n{knowledge}\n")
            if prev_ctx:
                parts.append(f"PREVIOUS SCENE \u2014 ENDING (context only, do NOT include in output):\n{prev_ctx}\n")
            parts.append(f"SCENE TO REVIEW:\n{scene_text}\n")
            if next_ctx:
                parts.append(f"NEXT SCENE \u2014 OPENING (context only, do NOT include in output):\n{next_ctx}\n")
            # Basic SS always uses the hardcoded prompt — no local file override
            parts.append(self._SS_INSTRUCTIONS_DEFAULT)
            if style_ref:
                parts.append(
                    f"\nREQUIRED OUTPUT STYLE \u2014 your output MUST conform to every rule below:\n"
                    f"{'=' * 40}\n{style_ref}\n"
                )
        prompt = "\n".join(parts)
        model = self.writer_ai_model_var.get().strip()
        if self._ss_style_rewrite_var.get():
            _ref_note = " + style_ref" if style_ref else ""
            _kb_note = " + knowledge" if knowledge_trimmed else ""
            self._ss_log_var.set(f"Scene {idx + 1} / {total}{_ref_note}{_kb_note}")
        else:
            self._ss_log_var.set(f"Scene {idx + 1} / {total}")
        _pct = min(99.0, idx / max(1, total) * 100)
        self._at_progress_var.set(_pct)
        _start_line = int(start.split(".")[0])
        _end_line = int(end.split(".")[0])
        _total_lines = int(self.text.index("end-1c").split(".")[0])
        self._progress_detail_var.set(
            f"Scene {idx + 1} of {total}"
            f"  —  L{_start_line}–{_end_line} of {_total_lines}"
        )
        self.writer_ai_generating = True
        self._show_writer_ai_progress_overlay(
            f"Script Supervisor \u2014 scene {idx + 1}/{total}", model
        )
        _timeout = 300
        threading.Thread(
            target=self._ss_thread,
            args=(model, prompt, scene_text, start, end, idx, total, _timeout),
            daemon=True,
        ).start()

    def _ss_thread(
        self, model: str, prompt: str,
        original: str, start: str, end: str, scene_num: int, total: int,
        timeout: int = 360,
        finish_fn=None,
    ) -> None:
        import os
        _finish = finish_fn if finish_fn is not None else self._ss_finish
        try:
            ollama = shutil.which("ollama") or "ollama"
            env = {**os.environ, "COLUMNS": "10000", "TERM": "dumb"}
            proc = subprocess.Popen(
                [ollama, "run", model],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env,
            )
            self._writer_ai_process = proc
            try:
                out, _err = proc.communicate(input=prompt.encode("utf-8"), timeout=timeout)
                output = out.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                self.root.after(0, _finish, "", -2, original, start, end, scene_num, total)
                return
            self.root.after(0, _finish, output, proc.returncode, original, start, end, scene_num, total)
        except Exception:
            self.root.after(0, _finish, "", 1, original, start, end, scene_num, total)

    def _ss_finish(
        self, output: str, returncode: int,
        original: str, start: str, end: str, scene_num: int, total: int,
    ) -> None:
        self._close_progress_overlay()
        self.writer_ai_generating = False
        self._writer_ai_process = None
        if not self._script_supervisor_running:
            return
        if returncode != 0 or not output.strip():
            _code_str = "timeout \u2014 skipped" if returncode == -2 else f"exit code {returncode}"
            _msg = f"Scene {scene_num + 1}/{total}: no output ({_code_str})"
            self._ss_log_var.set(_msg)
            self._ss_full_log.append(_msg)
            self._ss_scene_idx += 1
            self.writer_ai_status_var.set(
                f"Script Supervisor — scene {min(scene_num + 2, total)}/{total} | saved: {getattr(self, '_ss_last_saved_str', '—')}"
            )
            self.root.after(400, self._ss_step)
            return
        import difflib
        try:
            proposed = self._strip_ss_commentary(
                self._sanitize_local_ai_output(output).strip()
            )
            if self._ss_style_rewrite_var.get():
                # Enforce content protection: restore any line where words changed
                proposed = self._ss_protect_content(original.strip(), proposed)
            ratio = difflib.SequenceMatcher(None, original.strip(), proposed).ratio()
            if self._ss_style_rewrite_var.get():
                # Style rewrite: skip if <1% changed, else auto-apply
                if ratio > 0.99:
                    self._ss_clean_count += 1
                    self._ss_scene_idx += 1
                    _msg = f"Scene {scene_num + 1}/{total}: unchanged ({ratio:.0%} similar)"
                    self._ss_log_var.set(_msg)
                    self._ss_full_log.append(_msg)
                    self.root.after(400, self._ss_step)
                    return
                self._ss_auto_apply(proposed, start, end, scene_num, total, ratio)
            else:
                # Standard SS: auto-apply minor fixes (≥89% similar); show comparison for bigger changes (<89%)
                if ratio >= 0.89:
                    self._ss_auto_apply(proposed, start, end, scene_num, total, ratio)
                else:
                    self._ss_pending = {
                        "original": original.strip(),
                        "proposed": proposed,
                        "start": start, "end": end,
                        "scene_num": scene_num, "total": total,
                    }
                    self._show_ss_comparison()
        except Exception as exc:
            _msg = f"Scene {scene_num + 1}/{total}: EXCEPTION — {exc}"
            self._ss_log_var.set(_msg)
            self._ss_full_log.append(_msg)
            self._ss_scene_idx += 1
            self.root.after(400, self._ss_step)

    def _ss_auto_apply(
        self, proposed: str, start: str, end: str, scene_num: int, total: int,
        ratio: float = 0.0,
    ) -> None:
        """Apply proposed rewrite directly without showing the comparison UI."""
        try:
            self.text.delete(start, end)
            self.text.insert(start, proposed)
            ins_end = self.text.index(f"{start} + {len(proposed)}c")
            self._auto_tag_screenplay_block(self.text, start, ins_end)
        except tk.TclError:
            pass
        # Clear undo history and save after every scene to protect against OOM freeze
        self.text.edit_reset()
        _saved = self._silent_save()
        if _saved:
            self._ss_last_saved_str = time.strftime("%H:%M:%S")
        self._ss_applied_count += 1
        pct_changed = int((1.0 - ratio) * 100)
        _save_note = "  ✓ saved" if _saved else "  ⚠ unsaved"
        _msg = f"Scene {scene_num + 1}/{total}: rewritten ({ratio:.0%} similar, {pct_changed}% changed){_save_note}"
        self._ss_log_var.set(_msg)
        self._ss_full_log.append(_msg)
        self.writer_ai_status_var.set(
            f"Script Supervisor — scene {scene_num + 1}/{total} | saved: {self._ss_last_saved_str}"
        )
        self._ss_pending = None
        self._ss_scene_list = self._ss_get_scenes()
        self._ss_scene_idx = scene_num + 1
        self.root.after(300, self._ss_step)

    def _show_popup_error(self, title: str, message: str) -> None:
        """Custom error dialog that wraps text properly (messagebox hard-wraps mid-word)."""
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(True, False)
        win.minsize(440, 80)
        win.configure(bg=c["ttk_bg"])
        frm = ttk.Frame(win, padding=20)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=message, wraplength=400, justify="left").pack(anchor="w")
        ttk.Button(frm, text="OK", command=win.destroy).pack(pady=(16, 0))
        win.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width() - win.winfo_width()) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{px}+{py}")
        win.wait_visibility()
        win.grab_set()
        win.focus_set()

    def _show_tp_log_window(self) -> None:
        """Open a scrollable window showing the full TP session log."""
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        win.title("Typewriter Postscript — Session Log")
        win.transient(self.root)
        win.geometry("600x420")
        win.configure(bg=c["ttk_bg"])
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word", font=("TkFixedFont", 9),
                      background=c["entry_bg"], foreground=c["ttk_fg"],
                      relief="flat", borderwidth=0)
        scr = ttk.Scrollbar(frm, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        log_text = ("\n".join(self._tp_full_log)
                    if self._tp_full_log
                    else "No log entries yet. Run Typewriter Postscript first.")
        txt.insert("1.0", log_text)
        txt.configure(state="disabled")
        ttk.Button(frm, text="Close", command=win.destroy).pack(pady=(8, 0))

    # ── Typewriter Postscript ──────────────────────────────────────────

    def _toggle_typewriter_postscript(self) -> None:
        if self._tp_running:
            self._tp_running = False
            if self._tp_btn:
                self._tp_btn.configure(text="▶ Typewriter Postscript")
            self.writer_ai_status_var.set("Typewriter Postscript stopped.")
            return
        self._start_typewriter_postscript()

    def _start_typewriter_postscript(self) -> None:
        if self.writer_ai_generating:
            at_active = self._auto_transcript_running
            wa_active = (
                self._writer_ai_process is not None
                and self._writer_ai_process.poll() is None
            )
            if at_active or wa_active:
                self.writer_ai_status_var.set("Wait for current generation to finish.")
                return
            self.writer_ai_generating = False
        model = self.writer_ai_model_var.get().strip()
        if not model:
            messagebox.showwarning("Typewriter Postscript", "Select a model first.")
            return
        if not shutil.which("ollama"):
            messagebox.showerror(
                "Typewriter Postscript",
                "Ollama is not installed or not on PATH.",
            )
            return
        if not self.current_file:
            if not messagebox.askyesno(
                "Typewriter Postscript — unsaved file",
                "Your document has not been saved yet.\n\n"
                "Typewriter Postscript saves after every scene to protect your work.\n"
                "Without a file path it cannot save anything.\n\n"
                "Save the file now before starting?",
            ):
                return
            if not self.save_as_file():
                return
        # Pre-pass: strip scene-card metadata before the TP scene loop if checked
        if self._tp_strip_metadata_var.get():
            _raw = self.text.get("1.0", "end-1c")
            _clean = self._clean_scene_card_metadata(_raw)
            if _clean != _raw.strip():
                self.text.delete("1.0", tk.END)
                self.text.insert("1.0", _clean)
                self.text.edit_modified(True)
        scenes = self._ss_get_scenes()
        if not scenes:
            messagebox.showinfo("Typewriter Postscript", "No scenes found to review.")
            return
        self._tp_scene_list = scenes
        self._tp_scene_idx = 0
        self._tp_applied_count = 0
        self._tp_clean_count = 0
        self._tp_full_log = [f"TP started — {len(scenes)} scenes"]
        self._tp_running = True
        self._at_progress_var.set(0.0)
        if self._tp_btn:
            self._tp_btn.configure(text="⏹ Stop Postscript")
        self._tp_log_var.set(f"0 / {len(scenes)} scenes")
        self.writer_ai_status_var.set("Typewriter Postscript starting…")
        self._tp_step()

    def _tp_step(self) -> None:
        if not self._tp_running:
            return
        if self.writer_ai_generating:
            self.root.after(600, self._tp_step)
            return
        idx = self._tp_scene_idx
        total = len(self._tp_scene_list)
        if idx >= total:
            self._tp_running = False
            self._at_progress_var.set(100.0)
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._tp_btn:
                self._tp_btn.configure(text="▶ Typewriter Postscript")
            _applied = self._tp_applied_count
            _clean = self._tp_clean_count
            if _applied:
                _s = "s" if _applied != 1 else ""
                _summary = f"Done — {_applied} scene{_s} cleaned, {_clean} unchanged."
            else:
                _summary = f"Complete — {total} scene{'s' if total != 1 else ''} reviewed, all clean."
            self._tp_log_var.set(_summary)
            self._tp_full_log.append(_summary)
            self._tp_full_log.append("--- end of session ---")
            self.writer_ai_status_var.set("Typewriter Postscript complete.")
            return
        start, end = self._tp_scene_list[idx]
        self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
        self.text.tag_add(AUTO_TRANSCRIPT_TAG, start, end)
        self.text.see(start)
        scene_text = self.text.get(start, end)
        # Formatting pre-screen: skip scenes already correctly formatted
        if not self._tp_scene_needs_formatting(scene_text):
            self._tp_clean_count += 1
            _pct = min(99.0, (idx + 1) / max(1, total) * 100)
            self._at_progress_var.set(_pct)
            _msg = f"Scene {idx + 1}/{total}: formatted \u2014 skipped"
            self._tp_log_var.set(_msg)
            self._tp_full_log.append(_msg)
            self._tp_scene_idx += 1
            self.root.after(30, self._tp_step)
            return
        knowledge = self._read_project_knowledge()
        parts: list[str] = []
        if knowledge:
            parts.append(
                f"KNOWLEDGE BASE (character names and locations — reference only):"
                f"\n{knowledge[:2000]}\n"
            )
        parts.append(f"SCENE TO REVIEW:\n{scene_text}\n")
        parts.append(self._load_custom_prompt("tp_prompt.txt", self._TP_INSTRUCTIONS_DEFAULT))
        prompt = "\n".join(parts)
        model = self.writer_ai_model_var.get().strip()
        self._tp_log_var.set(f"Scene {idx + 1} / {total}")
        _pct = min(99.0, idx / max(1, total) * 100)
        self._at_progress_var.set(_pct)
        _start_line = int(start.split(".")[0])
        _end_line = int(end.split(".")[0])
        _total_lines = int(self.text.index("end-1c").split(".")[0])
        self._progress_detail_var.set(
            f"Postscript {idx + 1} of {total}"
            f"  —  L{_start_line}–{_end_line} of {_total_lines}"
        )
        self.writer_ai_generating = True
        self._show_writer_ai_progress_overlay(
            f"Typewriter Postscript — scene {idx + 1}/{total}", model
        )
        threading.Thread(
            target=self._ss_thread,
            args=(model, prompt, scene_text, start, end, idx, total, 300),
            kwargs={"finish_fn": self._tp_finish},
            daemon=True,
        ).start()

    def _tp_finish(
        self, output: str, returncode: int,
        original: str, start: str, end: str, scene_num: int, total: int,
    ) -> None:
        self._close_progress_overlay()
        self.writer_ai_generating = False
        self._writer_ai_process = None
        if not self._tp_running:
            return
        if returncode != 0 or not output.strip():
            _code_str = "timeout \u2014 skipped" if returncode == -2 else f"exit code {returncode}"
            _msg = f"Scene {scene_num + 1}/{total}: no output ({_code_str})"
            self._tp_log_var.set(_msg)
            self._tp_full_log.append(_msg)
            self._tp_scene_idx += 1
            self.root.after(400, self._tp_step)
            return
        import difflib
        try:
            proposed = self._strip_ss_commentary(
                self._sanitize_local_ai_output(output).strip()
            )
            proposed = self._ss_protect_content(original.strip(), proposed)
            ratio = difflib.SequenceMatcher(None, original.strip(), proposed).ratio()
            # Guard: if model changed more than 40% the scene it went off-rails — skip
            if ratio < 0.60:
                _msg = f"Scene {scene_num + 1}/{total}: off-rails ({ratio:.0%} similar) \u2014 skipped"
                self._tp_log_var.set(_msg)
                self._tp_full_log.append(_msg)
                self._tp_scene_idx += 1
                self.root.after(300, self._tp_step)
                return
            if ratio > 0.99:
                self._tp_clean_count += 1
                self._tp_scene_idx += 1
                _msg = f"Scene {scene_num + 1}/{total}: unchanged"
                self._tp_log_var.set(_msg)
                self._tp_full_log.append(_msg)
                self.root.after(300, self._tp_step)
            else:
                pct = int((1.0 - ratio) * 100)
                try:
                    self.text.delete(start, end)
                    self.text.insert(start, proposed)
                    ins_end = self.text.index(f"{start} + {len(proposed)}c")
                    self._auto_tag_screenplay_block(self.text, start, ins_end)
                except tk.TclError:
                    pass
                # Clear undo history and save after every applied scene
                self.text.edit_reset()
                _saved = self._silent_save()
                self._tp_applied_count += 1
                _save_note = "  ✓ saved" if _saved else "  ⚠ unsaved"
                _msg = f"Scene {scene_num + 1}/{total}: cleaned ({pct}% changed){_save_note}"
                self._tp_log_var.set(_msg)
                self._tp_full_log.append(_msg)
                self._tp_scene_list = self._ss_get_scenes()
                self._tp_scene_idx = scene_num + 1
                self.root.after(300, self._tp_step)
        except Exception as exc:
            _msg = f"Scene {scene_num + 1}/{total}: EXCEPTION — {exc}"
            self._tp_log_var.set(_msg)
            self._tp_full_log.append(_msg)
            self._tp_scene_idx += 1
            self.root.after(400, self._tp_step)

    def _show_ss_log_window(self) -> None:
        """Open a scrollable window showing the full SS session log."""
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        win.title("Script Supervisor — Session Log")
        win.transient(self.root)
        win.geometry("600x420")
        win.configure(bg=c["ttk_bg"])
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word", font=("TkFixedFont", 9),
                      background=c["entry_bg"], foreground=c["ttk_fg"],
                      relief="flat", borderwidth=0)
        scr = ttk.Scrollbar(frm, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        log_text = ("\n".join(self._ss_full_log)
                    if self._ss_full_log
                    else "No log entries yet. Run Script Supervisor first.")
        txt.insert("1.0", log_text)
        txt.configure(state="disabled")
        ttk.Button(frm, text="Close", command=win.destroy).pack(pady=(8, 0))

    def _show_ss_comparison(self) -> None:
        item = self._ss_pending
        if not item:
            return
        c = DARK_COLORS if self._dark_mode else LIGHT_COLORS
        win = tk.Toplevel(self.root)
        win.title(f"Script Supervisor \u2014 Scene {item['scene_num'] + 1} of {item['total']}")
        win.transient(self.root)
        self.root.update_idletasks()
        w, h = 1100, 740
        rx = max(0, self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2)
        ry = max(0, self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2)
        win.geometry(f"{w}x{h}+{rx}+{ry}")
        win.minsize(700, 500)
        win.configure(bg=c["ttk_bg"])

        header = tk.Frame(win, bg=c["ttk_bg"])
        header.pack(side="top", fill="x", padx=10, pady=(8, 0))
        tk.Label(header,
                 text=f"Scene {item['scene_num'] + 1} of {item['total']}  \u2014  Original (read-only)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="left")
        tk.Label(header, text="Proposed by Script Supervisor  (editable)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="right", padx=(0, 10))

        btn_bar = tk.Frame(win, bg=c["ttk_bg"])
        btn_bar.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        # Instruction row
        tk.Label(btn_bar,
                 text="Edit the proposed text freely. Apply & Next to accept, Skip to keep original.",
                 bg=c["ttk_bg"], fg=c["status_fg"], anchor="w").pack(fill="x")
        # Countdown + buttons row
        _btn_row = tk.Frame(btn_bar, bg=c["ttk_bg"])
        _btn_row.pack(fill="x", pady=(4, 0))

        text_opts = dict(
            wrap="word", font=self.screenplay_font, padx=10, pady=10,
            background=c["text_bg"], foreground=c["text_fg"],
            insertbackground=c["insert"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
            inactiveselectbackground=c["sel_bg"],
        )

        pane = tk.PanedWindow(win, orient="horizontal",
                              bg=c["ttk_bg"], sashrelief="flat", sashwidth=6)
        pane.pack(side="top", fill="both", expand=True, padx=10, pady=(4, 0))

        orig_frame = tk.Frame(pane, bg=c["ttk_bg"])
        orig_text = tk.Text(orig_frame, state="normal", **text_opts)
        orig_scroll = tk.Scrollbar(orig_frame, command=orig_text.yview)
        orig_text.configure(yscrollcommand=orig_scroll.set)
        orig_scroll.pack(side="right", fill="y")
        orig_text.pack(fill="both", expand=True)
        orig_text.insert("1.0", item["original"])
        orig_text.configure(state="disabled")
        pane.add(orig_frame, stretch="always")

        prop_frame = tk.Frame(pane, bg=c["ttk_bg"])
        prop_text = tk.Text(prop_frame, state="normal", **text_opts)
        prop_scroll = tk.Scrollbar(prop_frame, command=prop_text.yview)
        prop_text.configure(yscrollcommand=prop_scroll.set)
        prop_scroll.pack(side="right", fill="y")
        prop_text.pack(fill="both", expand=True)
        prop_text.insert("1.0", item["proposed"])
        pane.add(prop_frame, stretch="always")

        # --- 5-minute inactivity auto-accept timer ---
        _AUTO_ACCEPT_SECS = 300
        _remaining = [_AUTO_ACCEPT_SECS]
        _timer_job = [None]
        _countdown_var = tk.StringVar()

        def _cancel_timer() -> None:
            if _timer_job[0] is not None:
                try:
                    win.after_cancel(_timer_job[0])
                except Exception:
                    pass
                _timer_job[0] = None

        def _reset_timer(event=None) -> None:
            _remaining[0] = _AUTO_ACCEPT_SECS

        def _tick() -> None:
            if not win.winfo_exists():
                return
            if _remaining[0] <= 0:
                _apply_and_next()
                return
            m, s = divmod(_remaining[0], 60)
            _countdown_var.set(f"Auto-accepting in {m}:{s:02d}  —  interact to reset")
            _remaining[0] -= 1
            _timer_job[0] = win.after(1000, _tick)

        def _apply_and_next() -> None:
            _cancel_timer()
            new_text = prop_text.get("1.0", "end-1c")
            s, e = item["start"], item["end"]
            try:
                self.text.delete(s, e)
                self.text.insert(s, new_text)
                ins_end = self.text.index(f"{s} + {len(new_text)}c")
                self._auto_tag_screenplay_block(self.text, s, ins_end)
            except tk.TclError:
                pass
            # Clear undo history and save after every accepted scene
            self.text.edit_reset()
            _saved = self._silent_save()
            if _saved:
                self._ss_last_saved_str = __import__("time").strftime("%H:%M:%S")
            win.destroy()
            self._ss_pending = None
            _save_note = "  ✓ saved" if _saved else "  ⚠ unsaved"
            _msg = f"Scene {item['scene_num'] + 1}/{item['total']}: accepted{_save_note}"
            self._ss_log_var.set(_msg)
            self._ss_full_log.append(_msg)
            self.writer_ai_status_var.set(
                f"Script Supervisor — scene {item['scene_num'] + 1}/{item['total']} | saved: {self._ss_last_saved_str}"
            )
            # Rebuild scene list to account for text changes, then advance
            self._ss_scene_list = self._ss_get_scenes()
            self._ss_scene_idx = item["scene_num"] + 1
            self.root.after(300, self._ss_step)

        def _skip_and_next() -> None:
            _cancel_timer()
            win.destroy()
            self._ss_pending = None
            self._ss_scene_idx = item["scene_num"] + 1
            self.root.after(300, self._ss_step)

        def _stop() -> None:
            _cancel_timer()
            win.destroy()
            self._ss_pending = None
            self._script_supervisor_running = False
            if self._script_supervisor_btn:
                self._script_supervisor_btn.configure(text="\u25b6 Script Supervisor")
            self.writer_ai_status_var.set("Script Supervisor stopped.")

        # Bind any interaction in the window to reset the inactivity timer
        for _w in (win, prop_text, orig_text):
            _w.bind("<Key>", _reset_timer, add="+")
            _w.bind("<Button>", _reset_timer, add="+")
            _w.bind("<Motion>", _reset_timer, add="+")

        win.protocol("WM_DELETE_WINDOW", _skip_and_next)

        # Countdown label above the buttons
        tk.Label(_btn_row, textvariable=_countdown_var,
                 bg=c["ttk_bg"], fg="#aaaaaa",
                 font=("TkDefaultFont", 8)).pack(side="left")

        tk.Button(_btn_row, text="Stop", width=8, command=_stop,
                  bg=c["entry_bg"], fg=c["ttk_fg"], relief="flat",
                  activebackground=c["sel_bg"]).pack(side="right", padx=(6, 0))
        tk.Button(_btn_row, text="Skip Scene", width=12, command=_skip_and_next,
                  bg=c["entry_bg"], fg=c["ttk_fg"], relief="flat",
                  activebackground=c["sel_bg"]).pack(side="right", padx=(6, 0))
        tk.Button(_btn_row, text="Apply & Next", width=14, command=_apply_and_next,
                  bg="#0e639c", fg="white", relief="flat",
                  activebackground="#1177bb").pack(side="right")

        _tick()  # start the countdown

    # ── Writer AI progress overlay ───────────────────────────────────────

    def _show_writer_ai_progress_overlay(self, detail: str, model: str) -> None:
        self._progress_win = tk.Toplevel(self.root)
        win = self._progress_win
        win.title("Generating\u2026")
        win.resizable(True, True)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        self.root.update_idletasks()
        w, h = 480, 480
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2
        win.geometry(f"{w}x{h}+{rx}+{ry}")
        win.lift()
        win.focus_force()

        # Bottom bar outside body — always visible, like SS comparison window
        bot = ttk.Frame(win, padding=(22, 6, 22, 10))
        bot.pack(side="bottom", fill="x")
        ttk.Separator(win).pack(side="bottom", fill="x")
        self._elapsed_var = tk.StringVar(value="Elapsed: 0:00")
        ttk.Label(bot, textvariable=self._elapsed_var,
                  foreground="#888", font=("TkDefaultFont", 9)).pack(side="left")
        ttk.Button(bot, text="Cancel",
                   command=self._cancel_writer_ai_edit).pack(side="right")

        outer = ttk.Frame(win, padding=(22, 16, 22, 8))
        outer.pack(fill="both", expand=True)

        # Contextual title — derived from detail rather than generic heading
        if detail.lower().startswith("auto transcript"):
            title = "Auto Transcript"
        elif "script supervisor" in detail.lower():
            title = "Script Supervisor"
        else:
            title = "Writer AI Edit"
        ttk.Label(outer, text=title,
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(outer, text=detail, wraplength=430,
                  font=("TkDefaultFont", 9)).pack(anchor="w", pady=(2, 0))
        ttk.Label(outer, text=f"Model:  {model}",
                  font=("TkDefaultFont", 9), foreground="#888").pack(anchor="w")

        ttk.Separator(outer).pack(fill="x", pady=(10, 8))

        # Animated activity bar (current block)
        _s = ttk.Style()
        _s.configure("Activity.Horizontal.TProgressbar", thickness=20)
        self._progress_bar = ttk.Progressbar(
            outer, mode="indeterminate",
            style="Activity.Horizontal.TProgressbar",
        )
        self._progress_bar.pack(fill="x")
        self._progress_bar.start(10)

        # Overall document progress
        self._progress_label_var = tk.StringVar(value="Document progress:  0%")
        ttk.Label(outer, textvariable=self._progress_label_var,
                  font=("TkDefaultFont", 8), foreground="#aaa").pack(anchor="w", pady=(10, 2))
        _s.configure("Overall.Horizontal.TProgressbar", thickness=14)
        ttk.Progressbar(
            outer, variable=self._at_progress_var,
            mode="determinate", maximum=100,
            style="Overall.Horizontal.TProgressbar",
        ).pack(fill="x")
        ttk.Label(outer, textvariable=self._progress_detail_var,
                  font=("TkDefaultFont", 8), foreground="#aaa").pack(anchor="w", pady=(3, 0))

        if "script supervisor" in detail.lower():
            ttk.Separator(outer).pack(fill="x", pady=(10, 4))
            ttk.Label(outer, textvariable=self._ss_log_var,
                      font=("TkDefaultFont", 8), foreground="#aaa",
                      wraplength=430).pack(anchor="w")

        self._generation_start_time = time.monotonic()
        self._tick_elapsed_timer()

    def _cancel_writer_ai_edit(self) -> None:
        if self._script_supervisor_running:
            self._script_supervisor_running = False
            proc = self._writer_ai_process
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
            self._writer_ai_process = None
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._script_supervisor_btn:
                self._script_supervisor_btn.configure(text="\u25b6 Script Supervisor")
            self._close_progress_overlay()
            self.writer_ai_generating = False
            self.writer_ai_status_var.set("Script Supervisor cancelled.")
            return
        if self._auto_transcript_running:
            self._auto_transcript_running = False
            self._auto_transcript_cancelled = True
            proc = self._auto_transcript_process
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
            self._auto_transcript_process = None
            self._auto_transcript_block_start = None
            self._auto_transcript_block_end = None
            self.text.tag_remove(AUTO_TRANSCRIPT_TAG, "1.0", tk.END)
            if self._auto_transcript_btn:
                self._auto_transcript_btn.configure(text="\u25b6 Auto Transcript")
            self._close_progress_overlay()
            self.writer_ai_generating = False
            self.writer_ai_status_var.set("Auto transcript cancelled.")
            return
        self._writer_ai_cancelled = True
        proc = self._writer_ai_process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        self._close_progress_overlay()
        self.writer_ai_generating = False
        self.writer_ai_status_var.set("Cancelled.")

    def _on_notebook_tab_changed(self, _event: tk.Event) -> None:
        selected = self.main_notebook.select()
        if selected == str(self.local_ai_tab):
            # Auto-save writer content before switching to Local AI
            if self.current_file:
                try:
                    content = self.text.get("1.0", "end-1c")
                    with open(self.current_file, "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass
        elif selected == str(self.editor_tab):
            # Reload writer from file on return
            # If no writer file is open but a Local AI dest file exists, default to it
            file_to_load = self.current_file
            if (
                not file_to_load
                and hasattr(self, "local_ai_dest_file")
                and self.local_ai_dest_file
                and Path(self.local_ai_dest_file).exists()
            ):
                file_to_load = self.local_ai_dest_file
                self.current_file = file_to_load
                self.root.title(f"FilmPad \u2014 {Path(file_to_load).name}")
            if file_to_load and Path(file_to_load).exists():
                try:
                    content = Path(file_to_load).read_text(encoding="utf-8")
                    self.text.delete("1.0", tk.END)
                    self.text.insert("1.0", content)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Local AI workspace
    # ------------------------------------------------------------------

    def _build_local_ai_workspace(self) -> None:
        sidebar_outer = ttk.Frame(self.local_ai_tab)
        sidebar_outer.pack(side="left", fill="y")

        toggle_row = ttk.Frame(sidebar_outer)
        toggle_row.pack(side="top", fill="x")
        self._sidebar_toggle_btn = ttk.Button(
            toggle_row, text="◀", width=3, command=self._toggle_local_ai_sidebar
        )
        self._sidebar_toggle_btn.pack(side="right", padx=(0, 4), pady=4)

        self._sidebar_content = ttk.Frame(sidebar_outer, padding=(10, 4, 10, 10))
        self._sidebar_content.pack(side="top", fill="y", expand=True)
        sidebar = self._sidebar_content

        main_area = ttk.Frame(self.local_ai_tab, padding=(0, 10, 10, 10))
        main_area.pack(side="left", fill="both", expand=True)

        ttk.Label(sidebar, text="Local AI Adaptation", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(
            sidebar,
            text="Step through source file, line range, model, and output.",
            wraplength=260,
        ).pack(anchor="w", pady=(2, 10))

        ttk.Label(sidebar, text="1) Source file").pack(anchor="w")
        source_entry = ttk.Entry(sidebar, textvariable=self.local_ai_source_path_var, width=34)
        source_entry.pack(fill="x", pady=(2, 4))
        ttk.Button(sidebar, text="Browse Source", command=self._pick_local_ai_source_file).pack(fill="x")

        lines_row = ttk.Frame(sidebar)
        lines_row.pack(fill="x", pady=(10, 2))
        ttk.Label(lines_row, text="2) Start").grid(row=0, column=0, sticky="w")
        ttk.Label(lines_row, text="End").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Entry(lines_row, textvariable=self.local_ai_start_line_var, width=10).grid(row=1, column=0, sticky="w")
        ttk.Entry(lines_row, textvariable=self.local_ai_end_line_var, width=10).grid(row=1, column=1, sticky="w", padx=(10, 0))

        ttk.Button(sidebar, text="Preview and Highlight Range", command=self._preview_local_ai_range).pack(fill="x", pady=(8, 0))

        ttk.Label(sidebar, text="3) Model").pack(anchor="w", pady=(10, 2))
        model_picker = ttk.Combobox(
            sidebar,
            textvariable=self.local_ai_model_var,
            values=LOCAL_AI_MODELS,
            state="readonly",
            width=31,
        )
        model_picker.pack(fill="x")

        ttk.Label(sidebar, text="4) Destination file").pack(anchor="w", pady=(10, 2))
        ttk.Label(
            sidebar,
            text="Open an existing screenplay into the result pane.",
            wraplength=260,
        ).pack(anchor="w")
        ttk.Button(sidebar, text="Open Destination File", command=self._open_local_ai_dest_file).pack(fill="x", pady=(4, 0))

        ttk.Label(
            sidebar,
            text="5) Click in result pane to mark insertion point, then generate.",
            wraplength=260,
        ).pack(anchor="w", pady=(10, 2))

        ttk.Button(sidebar, text="Generate With Ollama", command=self._generate_local_ai_adaptation).pack(fill="x", pady=(4, 0))
        ttk.Button(sidebar, text="Save Destination File", command=self._save_local_ai_result_to_output).pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(
            sidebar,
            text="Link pane scrolling",
            variable=self.local_ai_link_scroll_var,
        ).pack(anchor="w", pady=(8, 0))

        ttk.Separator(sidebar).pack(fill="x", pady=(10, 8))
        ttk.Label(sidebar, text="Chunks temp folder").pack(anchor="w")
        temp_row = ttk.Frame(sidebar)
        temp_row.pack(fill="x", pady=(2, 0))
        ttk.Entry(temp_row, textvariable=self.local_ai_temp_dir_var, width=26).pack(side="left", fill="x", expand=True)
        ttk.Button(temp_row, text="...", width=3, command=self._pick_local_ai_temp_dir).pack(side="left", padx=(4, 0))

        ttk.Separator(sidebar).pack(fill="x", pady=(10, 8))
        ttk.Label(sidebar, textvariable=self.local_ai_status_var, wraplength=260).pack(anchor="w")

        panes = ttk.Panedwindow(main_area, orient="horizontal")
        panes.pack(fill="both", expand=True)

        result_frame = ttk.Frame(panes)
        source_frame = ttk.Frame(panes)
        panes.add(result_frame, weight=1)
        panes.add(source_frame, weight=1)

        ttk.Label(result_frame, textvariable=self.local_ai_result_label_var, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
        result_inner = ttk.Frame(result_frame)
        result_inner.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.local_ai_result_line_canvas = tk.Canvas(
            result_inner,
            width=48,
            bg="#f0f0f0",
            highlightthickness=0,
        )
        self.local_ai_result_line_canvas.pack(side="left", fill="y")

        self.local_ai_result_text = tk.Text(
            result_inner,
            wrap="word",
            undo=True,
            font=self.screenplay_font,
            padx=12,
            pady=16,
        )
        result_scroll = tk.Scrollbar(result_inner, command=self.local_ai_result_text.yview)
        self.local_ai_result_scroll = result_scroll
        self.local_ai_result_text.configure(yscrollcommand=self._on_local_ai_result_y_scroll)
        result_scroll.pack(side="right", fill="y")
        self.local_ai_result_text.pack(side="left", fill="both", expand=True)
        self.local_ai_result_text.tag_configure(LOCAL_AI_RESULT_HIGHLIGHT_TAG, background="#fff2b3")
        self.local_ai_result_text.bind("<ButtonRelease-1>", self._on_result_pane_click)
        self.local_ai_result_text.bind("<Configure>", lambda _e: self._redraw_result_line_numbers())

        ttk.Label(source_frame, text="Source (Read-only, click lines to select range)", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
        source_inner = ttk.Frame(source_frame)
        source_inner.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        # Canvas gutter: redraws line numbers at exact pixel positions via dlineinfo
        # so they stay in lockstep with word-wrapped source text.
        self.local_ai_line_canvas = tk.Canvas(
            source_inner,
            width=48,
            bg="#f0f0f0",
            highlightthickness=0,
            cursor="arrow",
        )
        self.local_ai_line_canvas.pack(side="left", fill="y")
        self.local_ai_line_canvas.bind("<Button-1>", self._on_line_number_click)
        self.local_ai_line_canvas.bind("<B1-Motion>", self._on_line_number_drag)
        self.local_ai_line_canvas.bind("<ButtonRelease-1>", self._on_line_number_release)

        self.local_ai_source_text = tk.Text(
            source_inner,
            wrap="word",
            undo=False,
            font=self.screenplay_font,
            padx=12,
            pady=16,
            state="disabled",
        )
        source_scroll_y = tk.Scrollbar(source_inner, command=self.local_ai_source_text.yview)
        self.local_ai_source_scroll = source_scroll_y
        self.local_ai_source_text.configure(yscrollcommand=self._on_local_ai_source_y_scroll)
        # Selecting text in source pane auto-populates the line range fields
        self.local_ai_source_text.bind("<ButtonRelease-1>", self._on_source_text_selection_release)
        # Redraw line numbers whenever the widget is resized
        self.local_ai_source_text.bind("<Configure>", lambda _e: self._redraw_line_numbers())

        source_scroll_y.pack(side="right", fill="y")
        self.local_ai_source_text.pack(side="left", fill="both", expand=True)
        self.local_ai_source_text.tag_configure(LOCAL_AI_SOURCE_RANGE_TAG, background="#d9ebff")

    def _on_local_ai_result_y_scroll(self, first: str, last: str) -> None:
        self.local_ai_result_scroll.set(first, last)
        self._redraw_result_line_numbers()
        if not self.local_ai_link_scroll_var.get() or self._local_ai_syncing_scroll:
            return
        self._local_ai_syncing_scroll = True
        try:
            self.local_ai_source_text.yview_moveto(float(first))
        finally:
            self._local_ai_syncing_scroll = False

    def _on_local_ai_source_y_scroll(self, first: str, last: str) -> None:
        self.local_ai_source_scroll.set(first, last)
        # Redraw canvas gutter at correct pixel positions for current scroll position
        self._redraw_line_numbers()
        # Sync result pane if linked scrolling is on
        if self.local_ai_link_scroll_var.get() and not self._local_ai_syncing_scroll:
            self._local_ai_syncing_scroll = True
            try:
                self.local_ai_result_text.yview_moveto(float(first))
            finally:
                self._local_ai_syncing_scroll = False

    def _toggle_local_ai_sidebar(self) -> None:
        if self._sidebar_content.winfo_ismapped():
            self._sidebar_content.pack_forget()
            self._sidebar_toggle_btn.configure(text="▶")
        else:
            self._sidebar_content.pack(side="top", fill="y", expand=True)
            self._sidebar_toggle_btn.configure(text="◀")

    def _canvas_y_to_source_line(self, canvas_y: int) -> int:
        """Map a canvas gutter y pixel to the logical line number in source text."""
        try:
            idx = self.local_ai_source_text.index(f"@0,{canvas_y}")
            return int(idx.split(".")[0])
        except (tk.TclError, ValueError):
            return 1

    def _on_line_number_click(self, event: tk.Event) -> None:
        self.local_ai_selecting_range = True
        self.local_ai_range_start_click = self._canvas_y_to_source_line(event.y)

    def _on_line_number_drag(self, event: tk.Event) -> None:
        if not self.local_ai_selecting_range or self.local_ai_range_start_click is None:
            return
        current = self._canvas_y_to_source_line(event.y)
        start = min(self.local_ai_range_start_click, current)
        end = max(self.local_ai_range_start_click, current)
        self.local_ai_start_line_var.set(str(start))
        self.local_ai_end_line_var.set(str(end))

    def _on_line_number_release(self, event: tk.Event) -> None:
        self.local_ai_selecting_range = False
        if self.local_ai_range_start_click is not None:
            self._preview_local_ai_range()

    def _on_source_text_selection_release(self, event: tk.Event) -> None:
        """Auto-populate line range from a text selection made in the source pane."""
        try:
            sel_start = self.local_ai_source_text.index("sel.first")
            sel_end = self.local_ai_source_text.index("sel.last")
            start_line = int(sel_start.split(".")[0])
            end_line = int(sel_end.split(".")[0])
            if (start_line, end_line) != (int(self.local_ai_start_line_var.get()), int(self.local_ai_end_line_var.get())):
                self.local_ai_start_line_var.set(str(start_line))
                self.local_ai_end_line_var.set(str(end_line))
                self._preview_local_ai_range()
        except (tk.TclError, ValueError):
            pass

    def _redraw_line_numbers(self) -> None:
        """Redraw the line number canvas using dlineinfo pixel positions from the
        source text widget — the only approach that stays in sync with word wrap."""
        if not hasattr(self, "local_ai_line_canvas"):
            return
        canvas = self.local_ai_line_canvas
        text_widget = self.local_ai_source_text
        canvas.delete("all")
        index = text_widget.index("@0,0")
        last_logical = -1
        while True:
            dline = text_widget.dlineinfo(index)
            if dline is None:
                break
            _x, y, _w, h, _baseline = dline
            logical = int(index.split(".")[0])
            # Draw the number only at the first visual line of each logical line
            if logical != last_logical:
                canvas.create_text(
                    44, y + h // 2,
                    anchor="e",
                    text=str(logical),
                    font=self.screenplay_font,
                    fill="#555555",
                )
                last_logical = logical
            next_index = text_widget.index(f"{index}+1 display line")
            if next_index == index:
                break
            index = next_index

    def _redraw_result_line_numbers(self) -> None:
        """Same as _redraw_line_numbers but for the result/destination pane."""
        if not hasattr(self, "local_ai_result_line_canvas"):
            return
        canvas = self.local_ai_result_line_canvas
        text_widget = self.local_ai_result_text
        canvas.delete("all")
        index = text_widget.index("@0,0")
        last_logical = -1
        while True:
            dline = text_widget.dlineinfo(index)
            if dline is None:
                break
            _x, y, _w, h, _baseline = dline
            logical = int(index.split(".")[0])
            if logical != last_logical:
                canvas.create_text(
                    44, y + h // 2,
                    anchor="e",
                    text=str(logical),
                    font=self.screenplay_font,
                    fill="#555555",
                )
                last_logical = logical
            next_index = text_widget.index(f"{index}+1 display line")
            if next_index == index:
                break
            index = next_index

    def _pick_local_ai_source_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose source file",
            filetypes=[
                ("Text-like files", "*.txt *.md *.fountain *.screenplay"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.local_ai_source_path_var.set(path)
        self._load_local_ai_source_content()
        self.local_ai_status_var.set("Source loaded. Select a line range, then open your destination file.")

    def _open_local_ai_dest_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open destination file",
            filetypes=[
                ("Text-like files", "*.txt *.md *.fountain *.screenplay"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as err:
            messagebox.showerror("Open destination", str(err))
            return
        self.local_ai_dest_file = path
        self.local_ai_insert_index = tk.END
        self.local_ai_result_text.delete("1.0", tk.END)
        self.local_ai_result_text.insert("1.0", content)
        self.local_ai_result_text.edit_modified(False)
        name = Path(path).name
        self.local_ai_result_label_var.set(f"Result — {name}")
        self.local_ai_status_var.set(f"Opened {name}. Click in the result pane to set the insertion point.")

    def _read_aloud_selection(self) -> None:
        voice = self._piper_voice_var.get()
        if voice and voice != "spd-say" and _PIPER_PYTHON.exists():
            self._piper_read_aloud(voice)
        else:
            self._spd_read_aloud()

    def _spd_read_aloud(self) -> None:
        if not shutil.which("spd-say"):
            messagebox.showinfo(
                "Read Aloud",
                "spd-say is not installed.\n\nInstall with:\n  sudo apt install speech-dispatcher",
            )
            return
        target = self._active_editor_widget()
        try:
            text = target.get("sel.first", "sel.last")
        except tk.TclError:
            cursor = target.index(tk.INSERT)
            text = target.get(cursor, "end-1c")
        text = text[:3000]
        if not text.strip():
            return
        self._stop_read_aloud()
        if self._read_btn is not None:
            self._read_btn.configure(text="\u25a0 Stop Reading")
        self._speech_process = subprocess.Popen(
            ["spd-say", "-l", "en-US", "-t", "male1", "-r", "-20", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.root.after(300, self._poll_spd_say)

    def _piper_read_aloud(self, voice: str) -> None:
        """Start streaming Piper TTS from cursor (or selection) to end of document."""
        target = self._active_editor_widget()
        try:
            text = target.get("sel.first", "sel.last")
            text_start = target.index("sel.first")
        except tk.TclError:
            text_start = target.index(tk.INSERT)
            text = target.get(text_start, "end-1c")
        text = text[:50000].strip()
        if not text:
            return
        self._stop_read_aloud()
        self._tts_stop_event.clear()
        chunks = _split_tts_chunks(text)
        if not chunks:
            return

        # Configure sentence-highlight tag using system accent colour
        accent = _get_system_accent_sel_bg()
        target.tag_configure("tts_reading", background=accent, foreground="#ffffff")
        target.tag_raise("tts_reading")

        # Pre-compute widget index for the start of each chunk (main-thread safe)
        positions: list[tuple[str, str] | None] = []
        search_pos = text_start
        for chunk in chunks:
            needle = chunk[:50]
            hit = target.search(needle, search_pos, tk.END)
            if hit:
                positions.append((hit, f"{hit} + {len(chunk)}c"))
                search_pos = hit
            else:
                positions.append(None)

        if self._read_btn is not None:
            self._read_btn.configure(text="\u25a0 Stop Reading")
        self._tts_widget = target
        speed = self._tts_speed_var.get()
        self._tts_thread = threading.Thread(
            target=self._piper_stream_thread,
            args=(chunks, voice, positions, target, speed),
            daemon=True,
        )
        self._tts_thread.start()

    def _piper_stream_thread(
        self, chunks: list[str], voice: str,
        positions: list[tuple[str, str] | None], widget: tk.Text,
        speed: float = 1.0,
    ) -> None:
        """Double-buffer Piper TTS: generate chunk N+1 while chunk N plays."""
        voice_model = str(_PIPER_VOICES_DIR / f"{voice}.onnx")
        stop = self._tts_stop_event
        player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("ffplay")
        if not player:
            return
        # Two alternating tmp WAV files — lean on disk, always overwritten
        tmp_paths = [
            Path("/tmp/filmpad_tts_0.wav"),
            Path("/tmp/filmpad_tts_1.wav"),
        ]

        def _highlight(idx: int) -> None:
            pos = positions[idx] if idx < len(positions) else None
            try:
                widget.tag_remove("tts_reading", "1.0", tk.END)
                if pos:
                    widget.tag_add("tts_reading", pos[0], pos[1])
                    # Scroll only when the bottom of the highlight reaches
                    # the viewport bottom — then slide so the chunk tops the view.
                    end_bbox = widget.bbox(pos[1])
                    vh = widget.winfo_height()
                    if end_bbox is None or end_bbox[1] + end_bbox[3] >= vh - 10:
                        line = int(pos[0].split(".")[0])
                        total = max(int(widget.index("end-1c").split(".")[0]), 1)
                        widget.yview_moveto((line - 1) / total)
            except tk.TclError:
                pass

        def _clear_hl() -> None:
            try:
                widget.tag_remove("tts_reading", "1.0", tk.END)
            except tk.TclError:
                pass

        def generate(chunk: str, path: Path) -> bool:
            if stop.is_set():
                return False
            length_scale = round(1.0 / max(speed, 0.1), 2)
            try:
                proc = subprocess.Popen(
                    [str(_PIPER_PYTHON), "-m", "piper", "-m", voice_model,
                     "-f", str(path), "--length-scale", str(length_scale)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.communicate(input=chunk.encode("utf-8"))
                return proc.returncode == 0 and path.exists() and path.stat().st_size > 44
            except OSError:
                return False

        try:
            buf = 0
            # Pre-generate first chunk before starting playback loop
            if not generate(chunks[0], tmp_paths[0]):
                return
            for i, _chunk in enumerate(chunks):
                if stop.is_set():
                    break
                play_path = tmp_paths[buf]
                next_buf = buf ^ 1
                # Highlight the sentence currently being spoken
                self.root.after(0, _highlight, i)
                # Begin playback of current chunk
                if "ffplay" in player:
                    play_cmd = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(play_path)]
                else:
                    play_cmd = [player, str(play_path)]
                audio_proc = subprocess.Popen(
                    play_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._tts_audio_proc = audio_proc
                # Overlap: generate next chunk while current chunk plays
                next_ok = False
                if i + 1 < len(chunks):
                    next_ok = generate(chunks[i + 1], tmp_paths[next_buf])
                # Wait for current playback to finish
                audio_proc.wait()
                self._tts_audio_proc = None
                if stop.is_set():
                    break
                if i + 1 < len(chunks):
                    if not next_ok:
                        # Generation didn't overlap cleanly — try now (brief pause)
                        next_ok = generate(chunks[i + 1], tmp_paths[next_buf])
                    if next_ok:
                        buf = next_buf
                    else:
                        break
        finally:
            self._tts_audio_proc = None
            self.root.after(0, self._on_tts_finished)
            for p in tmp_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def _stop_read_aloud(self) -> None:
        # Signal Piper thread to stop and kill any active audio playback
        self._tts_stop_event.set()
        audio_proc = self._tts_audio_proc
        if audio_proc is not None:
            try:
                audio_proc.kill()
            except OSError:
                pass
            self._tts_audio_proc = None
        # Clear sentence highlight and reset button immediately
        w = self._tts_widget
        if w is not None:
            try:
                w.tag_remove("tts_reading", "1.0", tk.END)
            except tk.TclError:
                pass
        if self._read_btn is not None:
            try:
                self._read_btn.configure(text="\u25b6 Read Aloud")
            except tk.TclError:
                pass
        # Stop spd-say
        proc = self._speech_process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        self._speech_process = None
        if shutil.which("spd-say"):
            subprocess.Popen(
                ["spd-say", "-C"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _toggle_read_aloud(self) -> None:
        reading = (
            (self._tts_thread is not None and self._tts_thread.is_alive())
            or self._speech_process is not None
        )
        if reading:
            self._stop_read_aloud()
        else:
            self._read_aloud_selection()

    def _on_tts_finished(self) -> None:
        """Called on the main thread when TTS ends naturally; resets button and clears highlight."""
        w = self._tts_widget
        if w is not None:
            try:
                w.tag_remove("tts_reading", "1.0", tk.END)
            except tk.TclError:
                pass
        if self._read_btn is not None:
            try:
                self._read_btn.configure(text="\u25b6 Read Aloud")
            except tk.TclError:
                pass

    def _poll_spd_say(self) -> None:
        """Poll the spd-say subprocess and reset button when it finishes naturally."""
        proc = self._speech_process
        if proc is not None and proc.poll() is None:
            self.root.after(300, self._poll_spd_say)
        else:
            self._speech_process = None
            self._on_tts_finished()

    # \u2500\u2500 Dictation (whisper.cpp at cursor) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

    def _dictation_set_recording(self, active: bool) -> None:
        """Update toolbar button states to reflect recording state."""
        self._dictation_recording = active
        self._dictation_status_var.set("\u25cf REC" if active else "")
        try:
            if self._dictation_start_btn is not None:
                self._dictation_start_btn.configure(
                    state="disabled" if active else "normal"
                )
            if self._dictation_stop_btn is not None:
                self._dictation_stop_btn.configure(
                    state="normal" if active else "disabled"
                )
            if self._dictation_cancel_btn is not None:
                self._dictation_cancel_btn.configure(
                    state="normal" if active else "disabled"
                )
        except tk.TclError:
            pass

    def _start_dictation(self) -> None:
        if self._dictation_recording:
            return

        # -- Validate prerequisites --
        if not shutil.which("arecord"):
            messagebox.showerror(
                "Dictation \u2014 missing tool",
                "arecord is not installed.\n\nFix: sudo apt install alsa-utils",
            )
            return

        exe_path = self._dictation_exe_var.get().strip()
        whisper_exe = _find_whisper_cpp(exe_path)
        if whisper_exe is None:
            messagebox.showerror(
                "Dictation \u2014 missing tool",
                "whisper-cli not found.\n\n"
                "FilmPad uses whisper.cpp for local, offline transcription.\n\n"
                "Install it:\n"
                "  git clone https://github.com/ggerganov/whisper.cpp\n"
                "  cd whisper.cpp && cmake -B build && cmake --build build -j\n"
                "  cp build/bin/whisper-cli ~/.local/bin/\n\n"
                "Download a model:\n"
                "  bash models/download-ggml-model.sh tiny.en\n"
                "  mkdir -p ~/.local/share/whisper.cpp/models\n"
                "  cp models/ggml-tiny.en.bin ~/.local/share/whisper.cpp/models/",
            )
            return

        model_path = str(Path(self._dictation_model_var.get().strip()).expanduser())
        if not Path(model_path).is_file():
            messagebox.showerror(
                "Dictation \u2014 missing model",
                f"Model file not found:\n{model_path}\n\n"
                "Download the tiny English model:\n"
                "  cd whisper.cpp\n"
                "  bash models/download-ggml-model.sh tiny.en\n"
                "  mkdir -p ~/.local/share/whisper.cpp/models\n"
                "  cp models/ggml-tiny.en.bin ~/.local/share/whisper.cpp/models/",
            )
            return

        # -- Save insertion target --
        target = self._active_editor_widget()
        self._dictation_target = target
        self._dictation_cursor_pos = target.index(tk.INSERT)
        self._dictation_cancelled = False

        # -- Create temp WAV file --
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav", prefix="filmpad_dictation_", delete=False
        )
        tmp.close()
        self._dictation_tmp_wav = tmp.name

        # -- Build arecord command --
        device = self._dictation_device_var.get().strip()
        arecord_cmd = ["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1"]
        if device:
            arecord_cmd += ["-D", device]
        arecord_cmd.append(self._dictation_tmp_wav)

        try:
            self._dictation_process = subprocess.Popen(
                arecord_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            messagebox.showerror(
                "Dictation",
                f"Microphone recording failed to start:\n{exc}",
            )
            try:
                Path(self._dictation_tmp_wav).unlink(missing_ok=True)
            except Exception:
                pass
            self._dictation_tmp_wav = None
            return

        self._dictation_set_recording(True)

    def _stop_dictation_and_transcribe(self) -> None:
        """Stop recording and launch whisper.cpp transcription in a background thread."""
        if not self._dictation_recording:
            return
        self._dictation_set_recording(False)

        proc = self._dictation_process
        self._dictation_process = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except OSError:
                    pass

        wav_path = self._dictation_tmp_wav
        self._dictation_tmp_wav = None
        cursor_pos = self._dictation_cursor_pos
        target = self._dictation_target
        self._dictation_cursor_pos = None
        self._dictation_target = None

        if not wav_path or not cursor_pos or target is None:
            return

        exe_path = self._dictation_exe_var.get().strip()
        whisper_exe = _find_whisper_cpp(exe_path)
        model_path = str(Path(self._dictation_model_var.get().strip()).expanduser())
        lang = self._dictation_lang_var.get().strip() or "en"

        if whisper_exe is None:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass
            return

        def _run() -> None:
            transcript = ""
            error_msg = ""
            try:
                result = subprocess.run(
                    [
                        whisper_exe,
                        "-m", model_path,
                        "-f", wav_path,
                        "-l", lang,
                        "-nt",
                        "-np",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    raw = result.stdout.strip()
                    lines = [ln for ln in raw.splitlines() if not ln.startswith("[")]
                    transcript = " ".join(ln.strip() for ln in lines if ln.strip())
                else:
                    error_msg = (
                        f"whisper-cli exited with code {result.returncode}.\n"
                        + (result.stderr.strip()[-400:] if result.stderr else "")
                    ).strip()
            except subprocess.TimeoutExpired:
                error_msg = "Transcription timed out (120 s)."
            except OSError as exc:
                error_msg = f"Could not run whisper-cli:\n{exc}"
            except Exception as exc:
                error_msg = f"Transcription error:\n{exc}"
            finally:
                try:
                    Path(wav_path).unlink(missing_ok=True)
                except Exception:
                    pass

            if self._dictation_cancelled:
                return
            if transcript:
                self.root.after(
                    0, lambda t=transcript: self._insert_dictation(target, cursor_pos, t)
                )
            elif error_msg:
                self.root.after(
                    0, lambda m=error_msg: messagebox.showerror("Dictation", m)
                )
            else:
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Dictation", "No usable speech was detected in the recording."
                    ),
                )

        threading.Thread(target=_run, daemon=True).start()

    def _cancel_dictation(self) -> None:
        """Stop recording and discard the audio without transcribing."""
        if not self._dictation_recording:
            return
        self._dictation_cancelled = True
        self._dictation_set_recording(False)

        proc = self._dictation_process
        self._dictation_process = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except OSError:
                    pass

        wav_path = self._dictation_tmp_wav
        self._dictation_tmp_wav = None
        self._dictation_cursor_pos = None
        self._dictation_target = None
        try:
            if wav_path:
                Path(wav_path).unlink(missing_ok=True)
        except Exception:
            pass

    def _insert_dictation(self, target: tk.Text, pos: str, text: str) -> None:
        """Insert transcript at saved cursor position as one undoable operation."""
        if not text:
            return
        if not text.endswith(" "):
            text = text + " "
        target.edit_separator()
        target.insert(pos, text)
        target.edit_separator()
        new_pos = target.index(f"{pos}+{len(text)}c")
        target.mark_set(tk.INSERT, new_pos)
        target.see(tk.INSERT)

    def _pick_dictation_exe(self) -> None:
        path = filedialog.askopenfilename(title="Select whisper-cli executable")
        if path:
            self._dictation_exe_var.set(path)

    def _pick_dictation_model(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Whisper model (.bin)",
            filetypes=[("Whisper GGML model", "*.bin"), ("All files", "*")],
        )
        if path:
            self._dictation_model_var.set(path)
    def _pick_local_ai_temp_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose chunks temp folder")
        if path:
            self.local_ai_temp_dir_var.set(path)

    def _on_result_pane_click(self, _event: tk.Event) -> None:
        """Record the cursor position in the result pane as the insertion point."""
        self.local_ai_insert_index = self.local_ai_result_text.index(tk.INSERT)
        line = self.local_ai_insert_index.split(".")[0]
        self.local_ai_status_var.set(f"Insertion point: line {line}. Ready to generate.")

    def _load_local_ai_source_content(self) -> None:
        source_path = self.local_ai_source_path_var.get().strip()
        if not source_path:
            return
        try:
            with open(source_path, "r", encoding="utf-8") as src_file:
                source_text = src_file.read()
        except OSError as err:
            messagebox.showerror("Source file", str(err))
            return

        self.local_ai_source_text.configure(state="normal")
        self.local_ai_source_text.delete("1.0", tk.END)
        self.local_ai_source_text.insert("1.0", source_text)
        self.local_ai_source_text.tag_remove(LOCAL_AI_SOURCE_RANGE_TAG, "1.0", tk.END)
        self.local_ai_source_text.configure(state="disabled")
        
        # Schedule redraw after widget has rendered its new content
        self.root.after(20, self._redraw_line_numbers)

    def _parse_selected_line_range(self) -> tuple[int, int] | None:
        try:
            start_line = int(self.local_ai_start_line_var.get().strip())
            end_line = int(self.local_ai_end_line_var.get().strip())
        except ValueError:
            messagebox.showerror("Line range", "Start and end lines must be whole numbers.")
            return None

        if start_line <= 0 or end_line <= 0:
            messagebox.showerror("Line range", "Line numbers must be greater than 0.")
            return None

        if end_line < start_line:
            messagebox.showerror("Line range", "End line must be greater than or equal to start line.")
            return None

        return start_line, end_line

    def _preview_local_ai_range(self) -> None:
        source_path = self.local_ai_source_path_var.get().strip()
        if not source_path:
            messagebox.showinfo("Source file", "Choose a source file first.")
            return

        parsed = self._parse_selected_line_range()
        if parsed is None:
            return

        start_line, end_line = parsed
        line_count = end_line - start_line + 1
        if line_count > 100:
            messagebox.showerror("Line range", "Choose 100 lines or fewer for best adaptation quality.")
            return

        self._load_local_ai_source_content()
        self.local_ai_source_text.configure(state="normal")
        self.local_ai_source_text.tag_remove(LOCAL_AI_SOURCE_RANGE_TAG, "1.0", tk.END)
        self.local_ai_source_text.tag_add(
            LOCAL_AI_SOURCE_RANGE_TAG,
            f"{start_line}.0",
            f"{end_line}.0 lineend",
        )
        self.local_ai_source_text.see(f"{start_line}.0")
        self.local_ai_source_text.configure(state="disabled")
        self.local_ai_status_var.set(f"Highlighted source lines {start_line}-{end_line}.")

    def _get_local_ai_slice_text(self, source_path: str, start_line: int, end_line: int) -> str:
        with open(source_path, "r", encoding="utf-8") as src_file:
            lines = src_file.readlines()
        if start_line > len(lines):
            return ""
        selected = lines[start_line - 1:end_line]
        return "".join(selected)

    def _load_adaptation_template(self) -> str:
        template_path = resource_path("assets/templates/SCREENPLAY_SCENE_ADAPTATION_TEMPLATE.md")
        if template_path.exists():
            try:
                return template_path.read_text(encoding="utf-8")
            except OSError:
                pass
        return (
            "# Screenplay Scene Adaptation Template\n\n"
            "SCENE NUMBER:\nSOURCE RANGE:\nLOCATION:\nTIME:\n"
            "CHARACTERS PRESENT:\nSITUATIONAL CUES PRESENT:\n"
            "SOURCE DIALOGUE INSIDE THIS SCENE:\nADAPTED SCREENPLAY SCENE:\n"
            "NOTES:\nCONFIDENCE:\n"
        )

    def _build_local_ai_prompt(self, source_name: str, start_line: int, end_line: int, slice_text: str) -> str:
        template_text = self._load_adaptation_template()
        return (
            "You are a professional Hollywood screenplay adapter.\n"
            "Your job: convert the source prose below into correctly formatted screenplay scene cards.\n"
            "Use ONLY the source text. Do not invent, skip, or compress anything.\n\n"
            "TEMPLATE (fill one card per scene):\n"
            "====================================\n"
            f"{template_text}\n\n"
            f"SOURCE TEXT -- {source_name} lines {start_line}-{end_line}:\n"
            "=======================================================\n"
            f"{slice_text}\n\n"
            "===== MANDATORY RULES -- READ ALL BEFORE WRITING =====\n\n"
            "RULE A -- SCENE SPLITTING (most important rule):\n"
            "  - Every change of LOCATION or TIME OF DAY must begin a new, separate scene card.\n"
            "  - NEVER merge two locations or two time-of-day periods into one scene card.\n"
            "  - Number scenes sequentially within this output: 1, 2, 3 ...\n"
            "  - Example: morning in a car AND afternoon on a highway AND night on a road\n"
            "    = THREE separate scene cards, not one.\n\n"
            "RULE B -- SOURCE DIALOGUE (extract ALL quoted speech):\n"
            "  - Before writing anything, scan the entire source text for quotation marks.\n"
            "  - Every phrase inside quotation marks is spoken dialogue.\n"
            "  - Copy EVERY quoted line verbatim into the SOURCE DIALOGUE section,\n"
            "    labelled with the speaker's name if known.\n"
            "  - Example: source says: Victoria exclaimed, \"What on earth, Richard?!\"\n"
            "    -> list: VICTORIA: What on earth, Richard?!\n"
            "  - NEVER write 'No exact dialogue found' if quotation marks appear in the source.\n"
            "  - Only write 'No exact dialogue found' if there are literally zero quotation marks.\n\n"
            "RULE C -- ADAPTED SCREENPLAY SCENE formatting:\n"
            "  - Slug line: INT./EXT. LOCATION - DAY / AFTERNOON / NIGHT / CONTINUOUS\n"
            "  - Action lines: present tense, left margin, one complete sentence per line.\n"
            "  - Preserve EVERY named beat, object, action, and moment in the source.\n"
            "  - For each spoken line, format EXACTLY like this (no exceptions):\n"
            "\n"
            "        CHARACTER NAME\n"
            "        Exact dialogue text.\n"
            "\n"
            "  - CHARACTER NAME must be ALL CAPS on its own line.\n"
            "  - Dialogue text must appear on the very next line after the name.\n"
            "  - NEVER write a character name block without dialogue immediately following it.\n"
            "  - NEVER write a parenthetical under a character name with no dialogue below it.\n"
            "  - Only add a parenthetical if the source uses that EXACT word for the manner\n"
            "    of speaking (e.g. source says 'he whispered' -> (whispering) is allowed).\n"
            "  - No invented emotion, psychology, or subtext.\n"
            "  - No mid-word line breaks. Every sentence is one unbroken line.\n"
            "  - ASCII punctuation only.\n\n"
            "RULE D -- LOCATION field:\n"
            "  - Use the location explicitly stated or clearly implied in the source.\n"
            "  - If not stated, infer from context (room, building, setting described).\n"
            "  - Only write UNKNOWN if no inference is possible.\n\n"
            "RULE E -- NOTES field:\n"
            "  - List only actual changes made in this output.\n"
            "  - Do not generalise or invent examples not present in the source.\n"
        )

    def _show_progress_overlay(self, source_name: str, start_line: int, end_line: int, model: str) -> None:
        self._progress_win = tk.Toplevel(self.root)
        win = self._progress_win
        win.title("Generating…")
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # Block manual close

        self.root.update_idletasks()
        w, h = 440, 240
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2
        win.geometry(f"{w}x{h}+{rx}+{ry}")

        outer = ttk.Frame(win, padding=(24, 18, 24, 14))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Generating Screenplay Adaptation",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")

        detail_frame = ttk.Frame(outer, padding=(0, 8, 0, 8))
        detail_frame.pack(fill="x")
        ttk.Label(detail_frame, text=f"Source:  {source_name}   lines {start_line}–{end_line}").pack(anchor="w")
        ttk.Label(detail_frame, text=f"Model:   {model}").pack(anchor="w")

        self._progress_step_var = tk.StringVar(value="Step 1 / 3  —  Preparing source slice")
        ttk.Label(outer, textvariable=self._progress_step_var,
                  foreground="#555").pack(anchor="w", pady=(4, 2))

        self._elapsed_var = tk.StringVar(value="Elapsed: 0:00")
        ttk.Label(outer, textvariable=self._elapsed_var,
                  foreground="#888").pack(anchor="w", pady=(0, 4))
        self._generation_start_time = time.monotonic()
        self._tick_elapsed_timer()

        self._progress_bar = ttk.Progressbar(outer, mode="indeterminate", length=390)
        self._progress_bar.pack(fill="x")
        self._progress_bar.start(10)

        ttk.Button(outer, text="Cancel", command=self._cancel_local_ai_generation).pack(pady=(12, 0))

    def _tick_elapsed_timer(self) -> None:
        if self._progress_win and self._progress_win.winfo_exists():
            elapsed = int(time.monotonic() - self._generation_start_time)
            mins, secs = divmod(elapsed, 60)
            self._elapsed_var.set(f"Elapsed: {mins}:{secs:02d}")
            if hasattr(self, "_progress_label_var"):
                pct = self._at_progress_var.get()
                self._progress_label_var.set(f"Document progress:  {pct:.0f}%")
            self._progress_win.after(1000, self._tick_elapsed_timer)

    def _update_progress_step(self, step: int, message: str) -> None:
        if self._progress_win and self._progress_win.winfo_exists():
            self._progress_step_var.set(f"Step {step} / 3  —  {message}")

    def _close_progress_overlay(self) -> None:
        if self._progress_win and self._progress_win.winfo_exists():
            self._progress_bar.stop()
            self._progress_win.destroy()
        self._progress_win = None

    def _cancel_local_ai_generation(self) -> None:
        self._generation_cancelled = True
        proc = self._ollama_process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        self._close_progress_overlay()
        self.local_ai_generating = False
        self.root.config(cursor="")
        self.local_ai_status_var.set("Generation cancelled.")

    def _tp_scene_needs_formatting(self, scene_text: str) -> bool:
        """True = scene has detectable formatting issues TP should fix."""
        import re
        _HEADING = re.compile(r'^\s*(int|ext|i/e)\b', re.IGNORECASE)
        _TRANS = re.compile(
            r'^\s*(cut to|fade out|fade in|fade to|dissolve to'
            r'|smash cut|match cut|wipe to)\b', re.IGNORECASE
        )
        _CUE_LOWER = re.compile(r'^[A-Z][a-z][A-Za-z\s\'\-\.]{0,30}$')
        # Name: "dialogue" inline format
        _INLINE_DIALOGUE = re.compile(r'^[A-Za-z][A-Za-z\s,\.]{1,40}:\s+["\u201c]')
        # SCENE #: prefix
        _SCENE_NUM = re.compile(r'^SCENE\s*[#\d]+\s*[:\.]', re.IGNORECASE)
        # Placeholder words
        _PLACEHOLDER = re.compile(
            r'^(Not provided|Not Available|Unclear|Unknown|Unspecified'
            r'|\(None\)|None|N/A|TBD)$', re.IGNORECASE
        )
        # File references, LLM notes, template headers
        _JUNK = re.compile(
            r'\.md\b|^\(Note:|^Note:\s*(This scene|No changes|Scene is correct)'
            r'|^#\s+[A-Z][A-Z\s\-]+$', re.IGNORECASE
        )
        for ln in scene_text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if _HEADING.match(s) and s != s.upper():
                return True
            if _TRANS.match(s) and s != s.upper():
                return True
            if _CUE_LOWER.match(s):
                return True
            if _INLINE_DIALOGUE.match(s):
                return True
            if _SCENE_NUM.match(s):
                return True
            if _PLACEHOLDER.match(s):
                return True
            if _JUNK.search(s):
                return True
        return False

    def _ss_scene_needs_review(self, scene_text: str) -> bool:
        """Fast deterministic pre-screen: True = scene has detectable issues,
        send to model. False = scene appears clean, skip immediately."""
        import re
        lines = [ln for ln in scene_text.splitlines() if ln.strip()]
        if not lines:
            return False

        # 1. Known artifact markers
        _ART = re.compile(
            r'\[(?:continued|end of block|inaudible|transcription|scene continues|cut here)\]'
            r'|5-ACT\b|HERO.S JOURNEY|ordinary world|call to adventure|purpose\s*:'
            r'|\bACT [IVX]+\s*[\u2014\-/]'
            r'|\.md\b'  # file references
            r'|^\(Note:|^Note:\s*(This scene|No changes)'  # LLM notes
            r'|^SCENE\s*[#\d]+\s*[:\.]'  # SCENE #: prefix
            r'|^(Not provided|Unclear|Unknown|\(None\)|None)$',  # placeholders
            re.IGNORECASE,
        )
        if any(_ART.search(ln) for ln in lines):
            return True

        # 2. Exact duplicate adjacent lines
        for i in range(len(lines) - 1):
            if lines[i].strip() and lines[i].strip() == lines[i + 1].strip():
                return True

        _HEADING = re.compile(r'^\s*(INT\.|EXT\.|I/E\.)', re.IGNORECASE)
        _TRANS   = re.compile(r'^(CUT TO|FADE|DISSOLVE|SMASH|MATCH CUT)', re.IGNORECASE)
        _CUE     = re.compile(r'^[A-Z][A-Z0-9 \'\-\.]+(?:\s*\([A-Z\.\s\'/\- ]+\))?$')

        # 3. Past-tense verbs in non-heading, non-cue lines (prose action leftovers)
        _PAST = re.compile(
            r'\b(walked|ran|said|asked|told|replied|looked|turned|picked|grabbed'
            r'|sat|stood|opened|closed|entered|left|came|went|saw|heard|felt'
            r'|knew|thought|realized|noticed|moved|stepped|reached|pulled|pushed'
            r'|nodded|smiled|laughed|whispered|shouted|cried|watched|stared'
            r'|glanced|held|took|made|put|got|gave|found|brought|kept|began'
            r'|started|stopped|continued|remained|appeared|seemed|became)\b'
        )
        for raw in lines:
            s = raw.strip()
            if not s or s.isupper() or _HEADING.match(s) or _TRANS.match(s) or _CUE.match(s):
                continue
            if _PAST.search(s):
                return True

        # 4. Conversational-sounding lines without an ALL CAPS character cue above them.
        #    Screenplay dialogue has NO quote marks — detect by speech-start patterns.
        _SPEECH = re.compile(
            r'^(I |I\'|You |We |They |He |She |It\'|What |Why |How |When |Where |Who '
            r'|Is |Are |Do |Did |Can |Will |Would |Could |Should |Shall '
            r'|No[,\.! ]|Yes[,\.! ]|Well[,\-\ ]|Oh[,\.! ]|Ah[,\.! ]'
            r'|Look[,\.! ]|Wait[,\.! ]|Come on|Don\'t|That\'s|There\'s'
            r'|Get |Stop |Help|Please|Sorry|Listen|Right\b)',
            re.IGNORECASE,
        )
        for i, raw in enumerate(lines):
            s = raw.strip()
            if not s or s.isupper() or len(s) > 100 or _HEADING.match(s) or _TRANS.match(s):
                continue
            if _SPEECH.match(s):
                prev = lines[i - 1].strip() if i > 0 else ""
                if not _CUE.match(prev):
                    return True

        return False

    def _ss_is_inline_attribution(self, line: str) -> bool:
        """Return True if line looks like inline prose attribution:
        e.g. 'Richard: "text"'  or  'Victoria (voice on phone): "text"'"""
        import re
        s = line.strip()
        if not s or len(s) > 300:
            return False
        # Pattern: Name (optional note): content
        return bool(re.match(
            r'^[A-Za-z][A-Za-z\s\.]+(?:\s*\([^)]+\))?\s*:',
            s
        ))

    def _ss_is_character_cue(self, line: str) -> bool:
        """Return True if line looks like a character cue (ALL CAPS name above dialogue)."""
        import re
        s = line.strip()
        if not s or len(s) > 50:
            return False
        # ALL CAPS, optionally followed by (V.O.), (O.S.), (CONT'D), (O.C.) etc.
        return bool(re.match(r"^[A-Z][A-Z0-9 '\-\.]+(?:\s*\([A-Z\.'/\- ]+\))?$", s))

    def _ss_is_artifact_line(self, line: str) -> bool:
        """Return True if this line is a known artifact safe to delete."""
        import re
        s = line.strip()
        if not s:
            return False
        _ART = re.compile(
            r"^("
            r"5-ACT\b|HERO.S JOURNEY|HERO'S JOURNEY"
            r"|ACT [IVX]+\s*[\u2014\-\u2013/].+"   # "ACT I — ORDINARY WORLD ..."
            r"|ordinary world|call to adventure|refusal of the call"
            r"|meeting the mentor|crossing the threshold|ordeal|road back"
            r"|return with the elixir|reward\b"
            r"|purpose\s*:"
            r"|inciting disturbance|inciting incident"
            r"|\d+\.\s+[A-Z][A-Z\s]+$"             # "1. ORDINARY WORLD"
            r"|\[end of block\]|\[continued\]|\[inaudible\]"
            r"|\[transcription|\[scene continues\]|\[cut here\]"
            r")",
            re.IGNORECASE,
        )
        return bool(_ART.match(s))

    def _ss_is_formatting_only(self, original: str, proposed: str) -> bool:
        """Return True if proposed differs from original only in capitalisation/punctuation/spacing."""
        import re
        def _norm(s: str) -> str:
            s = re.sub(r"[^\w\s]", " ", s.lower())
            return re.sub(r"\s+", " ", s).strip()
        return _norm(original) == _norm(proposed)

    def _ss_protect_content(self, original: str, proposed: str) -> str:
        """
        Post-process SS style output so that:
        - Artifact lines (matched by _ss_is_artifact_line) may be deleted.
        - Lines that differ only in capitalisation/punctuation/spacing are accepted.
        - Any other change to an existing line is rejected: the original line is restored.
        - Lines inserted by the model that have no counterpart are dropped.
        """
        import difflib
        orig_lines = original.splitlines()
        prop_lines = proposed.splitlines()
        matcher = difflib.SequenceMatcher(None, orig_lines, prop_lines, autojunk=False)
        result: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                result.extend(prop_lines[j1:j2])
            elif tag == "delete":
                # Model wants to remove orig_lines[i1:i2]
                for ln in orig_lines[i1:i2]:
                    if not self._ss_is_artifact_line(ln):
                        result.append(ln)   # restore — not an artifact
            elif tag == "replace":
                ob = orig_lines[i1:i2]
                pb = prop_lines[j1:j2]
                if len(ob) == len(pb):
                    for o, p in zip(ob, pb):
                        if self._ss_is_artifact_line(o):
                            pass            # allow deletion
                        elif self._ss_is_formatting_only(o, p):
                            result.append(p)  # accept formatting fix
                        else:
                            result.append(o)  # restore original words
                else:
                    # Size mismatch: allow inline attribution reformatting
                    # e.g. 'Richard: "text"' → RICHARD / (note) / text
                    if (len(ob) == 1
                            and self._ss_is_inline_attribution(ob[0])
                            and pb
                            and self._ss_is_character_cue(pb[0])):
                        result.extend(pb)  # accept the screenplay expansion
                    else:
                        # Preserve originals unless known artifacts
                        for o in ob:
                            if not self._ss_is_artifact_line(o):
                                result.append(o)
            elif tag == "insert":
                # Allow insertion of character cue lines (formatting fix — missing attribution)
                for p in prop_lines[j1:j2]:
                    if self._ss_is_character_cue(p):
                        result.append(p)
        return "\n".join(result)

    def _strip_ss_commentary(self, text: str) -> str:
        """Remove model preamble/commentary lines that are not screenplay content."""
        import re
        _COMMENT_RE = re.compile(
            r"^(note[:\-]|rewritten|below is|here is|i have|the following|summary[:\-]"
            r"|changes[:\-]|output[:\-]|result[:\-]|scene rewritten|as requested"
            r"|according to|formatting applied|artifacts removed)",
            re.IGNORECASE,
        )
        # Strip any standalone (Note: ...) lines anywhere in the text
        _INLINE_NOTE_RE = re.compile(
            r"(?mi)^\s*\(Note:.*?\)\s*$"
        )
        _NOTE_LINE_RE = re.compile(
            r"(?mi)^\s*Note:\s*(This scene|The scene|No changes|Scene is correct|Scene appears).*$"
        )
        text = _INLINE_NOTE_RE.sub("", text)
        text = _NOTE_LINE_RE.sub("", text)
        lines = text.splitlines()
        _SCREENPLAY_RE = re.compile(
            r"^(INT\.|EXT\.|I/E\.|INT /|EXT /|[A-Z][A-Z ]+$|[A-Z]{2}|\s*\(|CUT TO|FADE|SMASH|MATCH|DISSOLVE|THE END)"
        )
        start = 0
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped:
                continue
            if _COMMENT_RE.match(stripped):
                start = i + 1
            elif _SCREENPLAY_RE.match(stripped):
                break
            elif i <= 2 and _COMMENT_RE.match(stripped):
                start = i + 1
        end = len(lines)
        for i in range(len(lines) - 1, start - 1, -1):
            stripped = lines[i].strip()
            if not stripped:
                end = i
                continue
            if _COMMENT_RE.match(stripped):
                end = i
            else:
                break
        return "\n".join(lines[start:end]).strip()

    @staticmethod
    def _clean_scene_card_metadata(content: str) -> str:
        """Core strip logic: remove scene-card metadata fields and return cleaned text."""
        _META = re.compile(
            r"^(SCENE NUMBER|SOURCE RANGE|LOCATION|TIME|CHARACTERS PRESENT"
            r"|SITUATIONAL CUES PRESENT|SOURCE DIALOGUE INSIDE THIS SCENE"
            r"|ADAPTED SCREENPLAY SCENE|NOTES|CONFIDENCE):[ \t]*.*$",
            re.MULTILINE,
        )
        cleaned = _META.sub("", content)
        cleaned = re.sub(r"(?m)^\d+\s*$", "", cleaned)
        # .md file references in any form
        cleaned = re.sub(r"(?mi)^.*?\.md\b.*$", "", cleaned)
        cleaned = re.sub(r"(?m)^[ \t]*[-*][ \t]+.+$", "", cleaned)
        # SCENE #: / SCENE 3: / SCENE N. prefixes on scene headings
        cleaned = re.sub(r"(?mi)^SCENE\s*[#\d]+\s*[:\.]\s*", "", cleaned)
        # Template / project headers: # TITLE - SUBTITLE
        cleaned = re.sub(r"(?m)^#\s+[A-Z][A-Z\s\-]+$", "", cleaned)
        # Standalone placeholder words
        cleaned = re.sub(
            r"(?mi)^\s*(Not provided|Not Available|Unclear|Unknown|Unspecified"
            r"|\(None\)|None|N/A|TBD)\s*$", "", cleaned
        )
        # Inline / standalone LLM notes
        cleaned = re.sub(
            r"(?mi)^\s*\(Note:.*?\)\s*$", "", cleaned
        )
        cleaned = re.sub(
            r"(?mi)^\s*Note:\s*(This scene|The scene|No changes|Scene is correct).*$",
            "", cleaned
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _strip_scene_card_metadata(self) -> None:
        """Menu action: strip scene-card metadata from the current document."""
        content = self.text.get("1.0", "end-1c")
        if not any(marker in content for marker in (
            "SCENE NUMBER:", "SOURCE RANGE:", "CHARACTERS PRESENT:",
            "SITUATIONAL CUES PRESENT:", "SOURCE DIALOGUE INSIDE THIS SCENE:",
            "ADAPTED SCREENPLAY SCENE:",
        )):
            messagebox.showinfo("Strip Metadata", "No scene-card metadata found in this document.")
            return
        cleaned = self._clean_scene_card_metadata(content)
        if cleaned == content.strip():
            messagebox.showinfo("Strip Metadata", "Nothing to strip \u2014 document unchanged.")
            return
        removed = len(content) - len(cleaned)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", cleaned)
        self.text.edit_modified(True)
        messagebox.showinfo(
            "Strip Metadata",
            f"Done. Removed approximately {removed} characters of scene-card metadata.",
        )

    def _sanitize_local_ai_output(self, text: str) -> str:
        replacements = {
            "â€”": "-",
            "â€“": "-",
            "â€˜": "'",
            "â€™": "'",
            "â€œ": '"',
            "â€�": '"',
            "â€¦": "...",
            "—": "-",
            "–": "-",
            "‘": "'",
            "’": "'",
            "“": '"',
            "”": '"',
            "…": "...",
        }
        cleaned = text
        for bad, good in replacements.items():
            cleaned = cleaned.replace(bad, good)
        cleaned = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", cleaned)
        cleaned = cleaned.replace("\r", "")
        # Repair line-wrap artifacts where a word was split mid-word by the terminal,
        # e.g. "fr\nfrom Bronxville" -> "from Bronxville"
        def _rejoin_split_words(m: re.Match) -> str:
            first, second = m.group(1), m.group(2)
            if second.startswith(first):
                return second
            return first + second
        # Prefix-overlap split: "fr\nfrom", "shiftin\nshifting" (extended to 12 chars)
        cleaned = re.sub(r"(\b\w{1,12})\n(\1\w+)", _rejoin_split_words, cleaned)
        # Exact word repeated at line break: "with\nwith rest" -> "with rest"
        cleaned = re.sub(r"\b(\w+) *\n\1\b", r"\1", cleaned)
        return cleaned.strip("\n") + "\n"

    def _extract_screenplay_scenes(self, text: str) -> str:
        """Strip scene-card metadata; return only the ADAPTED SCREENPLAY SCENE content.

        Works on output that contains one or more scene cards in the template format
        (SCENE NUMBER / SOURCE RANGE / ... / ADAPTED SCREENPLAY SCENE: / NOTES:).
        If no card markers are found the text is returned unchanged.
        """
        if "ADAPTED SCREENPLAY SCENE:" not in text:
            return text

        scenes: list[str] = []
        # Split on SCENE NUMBER: to isolate individual cards
        cards = re.split(r"(?m)^SCENE NUMBER:", text)
        for card in cards:
            m = re.search(
                r"ADAPTED SCREENPLAY SCENE:\s*\n(.*?)(?=\n(?:NOTES:|SCENE NUMBER:)|\Z)",
                card, re.DOTALL,
            )
            if m:
                scene_text = m.group(1).strip()
                if scene_text:
                    scenes.append(scene_text)

        if scenes:
            return "\n\n".join(scenes) + "\n"

        # Fallback: couldn't isolate cards cleanly — strip known metadata field headers
        # and any indented bullet lists that belong to metadata sections.
        _META_HEADERS = re.compile(
            r"^(SCENE NUMBER|SOURCE RANGE|LOCATION|TIME|CHARACTERS PRESENT"
            r"|SITUATIONAL CUES PRESENT|SOURCE DIALOGUE INSIDE THIS SCENE"
            r"|ADAPTED SCREENPLAY SCENE|NOTES|CONFIDENCE):.*$",
            re.MULTILINE,
        )
        cleaned = _META_HEADERS.sub("", text)
        # Remove bare bullet lines that are metadata lists (not screenplay action)
        cleaned = re.sub(r"(?m)^[ \t]*[-*][ \t]+.+$", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip() + "\n"

    def _generate_local_ai_adaptation(self) -> None:
        if self.local_ai_generating:
            return

        source_path = self.local_ai_source_path_var.get().strip()
        if not source_path:
            messagebox.showinfo("Source file", "Choose a source file first.")
            return

        parsed = self._parse_selected_line_range()
        if parsed is None:
            return
        start_line, end_line = parsed

        line_count = end_line - start_line + 1
        if line_count > 100:
            messagebox.showerror("Line range", "Choose 100 lines or fewer for best adaptation quality.")
            return

        try:
            slice_text = self._get_local_ai_slice_text(source_path, start_line, end_line)
        except OSError as err:
            messagebox.showerror("Source file", str(err))
            return

        if not slice_text.strip():
            messagebox.showerror("Line range", "No text found in the selected line range.")
            return

        self.local_ai_last_slice = slice_text
        # Write temp chunk silently — never shown in the UI
        try:
            tmp_dir = Path(self.local_ai_temp_dir_var.get().strip() or "/tmp/filmpad")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / f"chunk_{start_line}_{end_line}.txt").write_text(slice_text, encoding="utf-8")
        except OSError:
            pass
        source_name = Path(source_path).name
        prompt = self._build_local_ai_prompt(source_name, start_line, end_line, slice_text)
        model = self.local_ai_model_var.get().strip() or LOCAL_AI_MODELS[0]

        self.local_ai_generating = True
        self._generation_cancelled = False
        # Capture any result-pane selection NOW so it can be replaced on insert
        try:
            self.local_ai_replace_range = (
                self.local_ai_result_text.index("sel.first"),
                self.local_ai_result_text.index("sel.last"),
            )
        except tk.TclError:
            self.local_ai_replace_range = None
        self._show_progress_overlay(source_name, start_line, end_line, model)
        self.root.config(cursor="watch")

        thread = threading.Thread(
            target=self._run_local_ai_generation,
            args=(model, prompt),
            daemon=True,
        )
        thread.start()
        # Advance overlay to step 2 once the thread has launched
        self.root.after(200, lambda: self._update_progress_step(2, f"Running Ollama — {model}"))

    def _run_local_ai_generation(self, model: str, prompt: str) -> None:
        import os
        env = {**os.environ, "COLUMNS": "10000", "TERM": "dumb"}
        try:
            self._ollama_process = subprocess.Popen(
                ["ollama", "run", model],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            stdout, stderr = self._ollama_process.communicate(input=prompt, timeout=900)
            returncode = self._ollama_process.returncode
        except subprocess.TimeoutExpired:
            if self._ollama_process:
                self._ollama_process.kill()
            self.root.after(0, self._finish_local_ai_generation, "", "Timed out after 900 s", 1)
            return
        except OSError as err:
            self.root.after(0, self._finish_local_ai_generation, "", str(err), 1)
            return
        finally:
            self._ollama_process = None

        if self._generation_cancelled:
            return

        self.root.after(0, self._finish_local_ai_generation, stdout, stderr, returncode)

    def _finish_local_ai_generation(self, output: str, stderr: str, returncode: int) -> None:
        self.local_ai_generating = False
        self.root.config(cursor="")

        if returncode != 0 and not self._generation_cancelled:
            self._close_progress_overlay()
            messagebox.showerror("Ollama", (stderr or "Ollama generation failed").strip())
            self.local_ai_status_var.set("Generation failed. Check Ollama and try again.")
            return

        if self._generation_cancelled:
            return

        self._update_progress_step(3, "Processing output")

        cleaned_output = self._sanitize_local_ai_output(output)
        cleaned_output = self._extract_screenplay_scenes(cleaned_output)
        # If the user had a selection in the result pane, replace it; otherwise insert at cursor
        if self.local_ai_replace_range:
            sel_start, sel_end = self.local_ai_replace_range
            self.local_ai_result_text.delete(sel_start, sel_end)
            insert_at = sel_start
            self.local_ai_replace_range = None
        else:
            try:
                insert_at = self.local_ai_result_text.index(self.local_ai_insert_index)
            except tk.TclError:
                insert_at = self.local_ai_result_text.index(tk.END)
        self.local_ai_result_text.tag_remove(LOCAL_AI_RESULT_HIGHLIGHT_TAG, "1.0", tk.END)
        self.local_ai_result_text.insert(insert_at, cleaned_output)
        # Highlight only the newly inserted block
        insert_end = self.local_ai_result_text.index(f"{insert_at}+{len(cleaned_output)}c")
        self.local_ai_result_text.tag_add(LOCAL_AI_RESULT_HIGHLIGHT_TAG, insert_at, insert_end)
        self.local_ai_result_text.see(insert_at)
        # Advance insertion point to after the inserted block for chained generations
        self.local_ai_insert_index = insert_end
        line = insert_at.split(".")[0]

        self._close_progress_overlay()
        self.local_ai_status_var.set(f"Done. Inserted at line {line}. Click to set next insertion point.")
        self.main_notebook.select(self.local_ai_tab)
        self.root.after(20, self._redraw_result_line_numbers)

    def _save_local_ai_result_to_output(self) -> None:
        if not self.local_ai_dest_file:
            path = filedialog.asksaveasfilename(
                title="Save destination file",
                defaultextension=".md",
                filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt"), ("All files", "*.*")],
            )
            if not path:
                return
            self.local_ai_dest_file = path
            self.local_ai_result_label_var.set(f"Result — {Path(path).name}")

        content = self.local_ai_result_text.get("1.0", "end-1c")
        out_path = Path(self.local_ai_dest_file)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        except OSError as err:
            messagebox.showerror("Save destination", str(err))
            return
        self.local_ai_result_text.edit_modified(False)
        self.local_ai_status_var.set(f"Saved {out_path.name}")

    def _on_font_menu_selected(self) -> None:
        self.screenplay_font.configure(family=self.font_var.get(), size=11)
        self._configure_screenplay_tags()

    def _apply_named_format(self, format_name: str) -> None:
        self.format_var.set(format_name)
        self.apply_screenplay_format()

    # ------------------------------------------------------------------
    # Spell checking (uses aspell or hunspell via subprocess)
    # ------------------------------------------------------------------

    def _find_spellcheck_tool(self) -> str | None:
        for tool in ("aspell", "hunspell"):
            if shutil.which(tool):
                return tool
        return None

    def _check_spelling(self) -> None:
        tool = self._find_spellcheck_tool()
        if tool is None:
            messagebox.showinfo(
                "Spell Check",
                "No spell-checking tool found.\n\n"
                "Install one with:\n  sudo apt install aspell",
            )
            return
        target = self._active_editor_widget()
        target.tag_remove(SPELL_TAG, "1.0", tk.END)
        content = target.get("1.0", "end-1c")
        for line_idx, line in enumerate(content.split("\n"), start=1):
            if not line.strip():
                continue
            for col_start, col_end in self._aspell_check_line(tool, line):
                target.tag_add(SPELL_TAG, f"{line_idx}.{col_start}", f"{line_idx}.{col_end}")

    def _aspell_check_line(self, tool: str, line: str) -> list[tuple[int, int]]:
        errors: list[tuple[int, int]] = []
        try:
            result = subprocess.run(
                [tool, "-a", "--lang=en"],
                input=line + "\n",
                capture_output=True,
                text=True,
                timeout=5,
            )
            for out_line in result.stdout.splitlines():
                m = re.match(r"^[&#] (\S+) (?:\d+ )?(\d+)", out_line)
                if m:
                    word = m.group(1)
                    offset = int(m.group(2)) - 1  # aspell offset is 1-based
                    errors.append((offset, offset + len(word)))
        except (subprocess.TimeoutExpired, OSError):
            pass
        return errors

    def _clear_spelling(self) -> None:
        self._active_editor_widget().tag_remove(SPELL_TAG, "1.0", tk.END)

    def _set_title(self) -> None:
        name = self.current_file if self.current_file else "Untitled"
        self.root.title(f"FilmPad - {name}")

    def _confirm_discard(self) -> bool:
        if self.text.edit_modified():
            answer = messagebox.askyesnocancel("Unsaved changes", "Save changes first?")
            if answer is None:
                return False
            if answer:
                if not self.save_file():
                    return False
        return True

    def _silent_save(self) -> bool:
        """Save to current_file without showing any dialogs. Returns True on success."""
        if not self.current_file:
            return False
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end-1c"))
            self.text.edit_modified(False)
            self._set_title()
            return True
        except OSError:
            return False

    def new_file(self) -> None:
        if not self._confirm_discard():
            return
        self.text.delete("1.0", tk.END)
        self.current_file = None
        self.text.edit_modified(False)
        self._set_title()

    def open_file(self) -> None:
        if not self._confirm_discard():
            return

        path = filedialog.askopenfilename(
            title="Open text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            messagebox.showerror("Open failed", str(e))
            return

        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.current_file = path
        self.text.edit_modified(False)
        self._set_title()
        self._add_to_recent(path)

    def save_file(self) -> bool:
        if not self.current_file:
            return self.save_as_file()

        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end-1c"))
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return False

        self.text.edit_modified(False)
        self._set_title()
        return True

    def save_as_file(self) -> bool:
        path = filedialog.asksaveasfilename(
            title="Save text file",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return False
        self.current_file = path
        result = self.save_file()
        if result:
            self._add_to_recent(path)
        return result

    def _add_to_recent(self, path: str) -> None:
        """Prepend path to the recent list, cap at 10, persist and rebuild menu."""
        p = str(Path(path).resolve())
        if p in self._recent_files:
            self._recent_files.remove(p)
        self._recent_files.insert(0, p)
        self._recent_files = self._recent_files[:10]
        _save_recent_files(self._recent_files)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        """Repopulate the Open Recent submenu from self._recent_files."""
        m = self._recent_menu
        if m is None:
            return
        m.delete(0, tk.END)
        if not self._recent_files:
            m.add_command(label="No recent files", state="disabled")
            return
        for path in self._recent_files:
            exists = Path(path).exists()
            label = Path(path).name + "   —   " + str(Path(path).parent)
            m.add_command(
                label=label,
                command=lambda p=path: self._open_recent(p),
                state="normal" if exists else "disabled",
            )
        m.add_separator()
        m.add_command(label="Clear Recent", command=self._clear_recent)

    def _open_recent(self, path: str) -> None:
        if not self._confirm_discard():
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Open failed", str(e))
            self._recent_files = [p for p in self._recent_files if p != path]
            _save_recent_files(self._recent_files)
            self._rebuild_recent_menu()
            return
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.current_file = path
        self.text.edit_modified(False)
        self._set_title()
        self._add_to_recent(path)

    def _clear_recent(self) -> None:
        self._recent_files = []
        _save_recent_files(self._recent_files)
        self._rebuild_recent_menu()

    def on_exit(self) -> None:
        self._stop_read_aloud()
        if self._confirm_discard():
            self.root.destroy()


def _install_icons_early(exec_cmd: str) -> None:
    """Install icons and .desktop file BEFORE tk.Tk() is called so Plank sees
    the desktop entry the moment the X11 window appears.
    Uses file-size comparison so corrupted/wrong-sized installs are always fixed."""
    sizes = [
        ("16x16",   "filmpad-icon-16.png"),
        ("22x22",   "filmpad-icon-22.png"),
        ("24x24",   "filmpad-icon-24.png"),
        ("32x32",   "filmpad-icon-32.png"),
        ("48x48",   "filmpad-icon-48.png"),
        ("64x64",   "filmpad-icon-64.png"),
        ("128x128", "filmpad-icon-128.png"),
        ("256x256", "filmpad-icon-256.png"),
        ("512x512", "filmpad-icon-512.png"),
    ]
    icons_base = Path.home() / ".local/share/icons/hicolor"
    icon_changed = False
    for size_str, fname in sizes:
        src = resource_path(f"assets/{fname}")
        if not src.exists():
            continue
        dest_dir = icons_base / size_str / "apps"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "filmpad.png"
        # Compare by file size — catches wrong-sized icons installed by older runs
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            try:
                shutil.copy2(src, dest)
                icon_changed = True
            except Exception:
                pass
    # Also install the scalable SVG so GTK/Plank can render it at any size without
    # resampling, giving a perfectly crisp dock icon regardless of dock scale.
    svg_src = resource_path("assets/filmpad-icon.svg")
    if svg_src.exists():
        svg_dest_dir = icons_base / "scalable/apps"
        svg_dest_dir.mkdir(parents=True, exist_ok=True)
        svg_dest = svg_dest_dir / "filmpad.svg"
        if not svg_dest.exists() or svg_dest.stat().st_size != svg_src.stat().st_size:
            try:
                shutil.copy2(svg_src, svg_dest)
                icon_changed = True
            except Exception:
                pass
    if icon_changed:
        try:
            (icons_base / "icon-theme.cache").unlink(missing_ok=True)
        except Exception:
            pass
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", "-t", str(icons_base)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        except Exception:
            pass
        # Restart Plank so it reloads the freshly installed icons
        try:
            if subprocess.run(["pgrep", "-x", "plank"], capture_output=True).returncode == 0:
                subprocess.Popen(
                    ["bash", "-c", "pkill plank; sleep 0.8; plank &"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    # Use the icon theme name so GTK picks the best size (SVG > 256px) automatically.
    # This is more reliable than an absolute path which some compositors ignore.
    apps_dir = Path.home() / ".local/share/applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    desktop_dest = apps_dir / "filmpad.desktop"
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=FilmPad\n"
        "Comment=Screenplay editor with local AI adaptation\n"
        f"Exec={exec_cmd}\n"
        "Icon=filmpad\n"
        "Terminal=false\n"
        "Categories=Utility;TextEditor;\n"
        "StartupWMClass=Filmpad\n"
    )
    try:
        existing = desktop_dest.read_text(encoding="utf-8") if desktop_dest.exists() else ""
        if existing != desktop_content:
            desktop_dest.write_text(desktop_content, encoding="utf-8")
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
    except Exception:
        pass


def main() -> None:
    import os
    try:
        appimage_path = os.environ.get("APPIMAGE")
        exec_cmd = appimage_path if appimage_path else f"python3 {Path(sys.argv[0]).resolve()}"
        # Install icons and .desktop BEFORE the window appears so Plank sees them immediately
        _install_icons_early(exec_cmd)
        root = tk.Tk(className="Filmpad")  # WM_CLASS class = Filmpad, matches StartupWMClass in .desktop
        app = FilmPad(root)
        app._set_title()
        # Start in dark mode by default
        app._dark_mode = True
        app._apply_theme()
        app._theme_btn.configure(text="\u2600 Light")
        root.protocol("WM_DELETE_WINDOW", app.on_exit)
        root.mainloop()
    except Exception:
        cache_dir = Path.home() / ".cache" / "filmpad"
        cache_dir.mkdir(parents=True, exist_ok=True)
        log_path = cache_dir / "launch-error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror(
                "FilmPad launch failed",
                "FilmPad could not start.\n\n"
                f"Error details were saved to:\n{log_path}",
            )
            fallback.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
