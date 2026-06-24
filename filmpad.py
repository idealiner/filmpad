#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


PREFERRED_SCREENPLAY_FONTS = [
    "Courier Prime",
    "Courier Screenplay",
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
    "spell_fg": "#cc0000",   "status_fg": "#555555",
    "ttk_bg": "#f0f0f0",     "ttk_fg": "#000000",
    "entry_bg": "white",
}
DARK_COLORS = {
    "text_bg": "#1e1e1e",    "text_fg": "#d4d4d4",      "insert": "#d4d4d4",
    "sel_bg": "#264f78",     "sel_fg": "#ffffff",
    "gutter_bg": "#252526",  "gutter_fg": "#858585",
    "result_hl": "#3a3a00",  "source_hl": "#1a3550",
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
        self.screenplay_font = tkfont.Font(family=self.font_var.get(), size=11)
        self.screenplay_font_bold = tkfont.Font(family=self.font_var.get(), size=11, weight="bold")
        self.screenplay_font_scene = tkfont.Font(family=self.font_var.get(), size=11, weight="bold", underline=True)

        self.current_file = None

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

        self.editor_frame = ttk.Frame(self.editor_tab)
        self.editor_frame.pack(fill="both", expand=True)

        self.text = tk.Text(
            self.editor_frame,
            wrap="word",
            undo=True,
            font=self.screenplay_font,
            padx=36,
            pady=24,
        )
        self.scroll = tk.Scrollbar(self.editor_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)
        self._configure_screenplay_tags()

        self.writer_ai_project_folder_var = tk.StringVar(value="")
        self.writer_ai_model_var = tk.StringVar(value=LOCAL_AI_MODELS[0])
        self.writer_ai_status_var = tk.StringVar(value="Select text then write a prompt.")
        self.writer_ai_generating = False
        self._writer_ai_cancelled = False
        self._writer_ai_process: subprocess.Popen | None = None
        self._writer_ai_sel_start: str | None = None
        self._writer_ai_sel_end: str | None = None

        self._build_writer_ai_panel()
        self.scroll.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

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

        self._build_local_ai_workspace()

        self._set_window_icon()
        self._build_menu()

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

        ttk.Separator(self.toolbar, orient="vertical").pack(side="left", fill="y", padx=(14, 10))
        ttk.Button(
            self.toolbar,
            text="\u25b6 Read Aloud",
            command=self._read_aloud_selection,
        ).pack(side="left")
        ttk.Button(
            self.toolbar,
            text="\u25a0 Stop",
            command=self._stop_read_aloud,
        ).pack(side="left", padx=(6, 0))

        ttk.Separator(self.toolbar, orient="vertical").pack(side="right", fill="y", padx=(10, 14))
        self._theme_btn = ttk.Button(
            self.toolbar, text="\U0001f319 Dark", width=8, command=self._toggle_dark_mode
        )
        self._theme_btn.pack(side="right")

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
            background=[("active", c["entry_bg"]), ("pressed", c["sel_bg"])],
            foreground=[("active", c["ttk_fg"])],
            bordercolor=[("active", bd), ("pressed", c["sel_bg"])],
            darkcolor=[("active", bd)], lightcolor=[("active", bd)],
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
        # Remove the highlight ring on the root and toolbar
        self.root.configure(bg=c["ttk_bg"],
            highlightbackground=c["ttk_bg"], highlightcolor=c["ttk_bg"],
            highlightthickness=0)
        self.toolbar.configure(style="TFrame")

        # --- tk.Text widgets ---
        text_opts = dict(
            background=c["text_bg"], foreground=c["text_fg"],
            insertbackground=c["insert"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
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
        for menu_attr in ("_menu_bar", "_file_menu", "_format_menu", "_font_menu", "_screenplay_menu"):
            if hasattr(self, menu_attr):
                try:
                    getattr(self, menu_attr).configure(**menu_opts)
                except Exception:
                    pass

        # --- toolbar highlight borders ---
        self.toolbar.configure(style="Dark.TFrame" if self._dark_mode else "TFrame")
        style.configure("Dark.TFrame", background=c["ttk_bg"])

        self._configure_screenplay_tags()

    def _on_font_selected(self, _event: tk.Event) -> None:
        self.screenplay_font.configure(family=self.font_var.get(), size=11)
        self._configure_screenplay_tags()

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
        # Transition -- right-justified flush, double blank line above
        widget.tag_configure(
            "Transition",
            font=self.screenplay_font,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls * 2, spacing3=ls,
            justify="right",
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
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_file)
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
        self.root.config(menu=menu_bar)

        self.root.bind("<Control-n>", lambda _e: self.new_file())
        self.root.bind("<Control-o>", lambda _e: self.open_file())
        self.root.bind("<Control-s>", lambda _e: self.save_file())
        self.root.bind("<F7>", lambda _e: self._check_spelling())

    # ------------------------------------------------------------------
    # Writer AI panel
    # ------------------------------------------------------------------

    def _build_writer_ai_panel(self) -> None:
        outer = ttk.Frame(self.editor_frame)
        outer.pack(side="right", fill="y")

        self._writer_ai_toggle_btn = ttk.Button(
            outer, text="\u25b6", width=3, command=self._toggle_writer_ai_sidebar
        )
        self._writer_ai_toggle_btn.pack(side="top", padx=(4, 4), pady=4)

        self._writer_ai_content = ttk.Frame(outer, padding=(6, 2, 10, 10))
        # Starts collapsed — content is not packed yet

        ttk.Label(
            self._writer_ai_content, text="Writer AI", font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w")
        ttk.Label(
            self._writer_ai_content,
            text="Select text in editor, write a prompt, then generate.",
            wraplength=240,
        ).pack(anchor="w", pady=(2, 8))

        ttk.Label(self._writer_ai_content, text="Project knowledge folder").pack(anchor="w")
        folder_row = ttk.Frame(self._writer_ai_content)
        folder_row.pack(fill="x", pady=(2, 6))
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
        ).pack(fill="x", pady=(2, 8))

        ttk.Label(self._writer_ai_content, text="Prompt").pack(anchor="w")
        prompt_frame = ttk.Frame(self._writer_ai_content)
        prompt_frame.pack(fill="x", pady=(2, 6))
        self.writer_ai_prompt_text = tk.Text(
            prompt_frame, width=30, height=8, wrap="word", padx=6, pady=6
        )
        prompt_scroll = tk.Scrollbar(prompt_frame, command=self.writer_ai_prompt_text.yview)
        self.writer_ai_prompt_scroll = prompt_scroll
        self.writer_ai_prompt_text.configure(yscrollcommand=prompt_scroll.set)
        prompt_scroll.pack(side="right", fill="y")
        self.writer_ai_prompt_text.pack(side="left", fill="both", expand=True)

        ttk.Button(
            self._writer_ai_content,
            text="\u2728 Transcribe into Script Format",
            command=self._transcribe_to_script_format,
        ).pack(fill="x", pady=(2, 0))
        ttk.Button(
            self._writer_ai_content, text="Edit Selection", command=self._run_writer_ai_edit
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(
            self._writer_ai_content, text="\u25a7 Review Last Output",
            command=self._show_writer_ai_comparison,
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(
            self._writer_ai_content, text="Save", command=self.save_file
        ).pack(fill="x", pady=(4, 0))

        ttk.Separator(self._writer_ai_content).pack(fill="x", pady=(10, 6))
        ttk.Label(
            self._writer_ai_content,
            textvariable=self.writer_ai_status_var,
            wraplength=240,
        ).pack(anchor="w")

    def _toggle_writer_ai_sidebar(self) -> None:
        if self._writer_ai_content.winfo_ismapped():
            self._writer_ai_content.pack_forget()
            self._writer_ai_toggle_btn.configure(text="\u25b6")
        else:
            self._writer_ai_content.pack(side="top", fill="y", expand=True)
            self._writer_ai_toggle_btn.configure(text="\u25c4")

    def _pick_writer_ai_project_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Project Knowledge Folder")
        if folder:
            self.writer_ai_project_folder_var.set(folder)

    def _read_project_knowledge(self) -> str:
        folder = self.writer_ai_project_folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            return ""
        MAX_CHARS = 8000
        chunks: list[str] = []
        total = 0
        for ext in ("*.md", "*.txt", "*.fdx"):
            for fpath in sorted(Path(folder).glob(ext)):
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
            "Use ONLY the context provided. Do not invent beyond what is given.\n\n",
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
            out, _err = proc.communicate(input=prompt.encode("utf-8"))
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
        w, h = 1000, 600
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2
        win.geometry(f"{w}x{h}+{rx}+{ry}")
        win.configure(bg=c["ttk_bg"])

        header = tk.Frame(win, bg=c["ttk_bg"])
        header.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(header, text="Original  (read-only)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="left", padx=(0, 0))
        tk.Label(header, text="Proposed  (editable before accepting)",
                 font=("TkDefaultFont", 10, "bold"),
                 bg=c["ttk_bg"], fg=c["ttk_fg"]).pack(side="right", padx=(0, 10))

        pane = tk.PanedWindow(win, orient="horizontal",
                              bg=c["ttk_bg"], sashrelief="flat", sashwidth=6)
        pane.pack(fill="both", expand=True, padx=10, pady=(4, 0))

        text_opts = dict(
            wrap="word", font=self.screenplay_font, padx=10, pady=10,
            background=c["text_bg"], foreground=c["text_fg"],
            insertbackground=c["insert"],
            selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
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

        btn_bar = tk.Frame(win, bg=c["ttk_bg"])
        btn_bar.pack(fill="x", padx=10, pady=8)
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

    def _transcribe_to_script_format(self) -> None:
        default_prompt = (
            "You are a screenplay FORMATTER — not an editor or writer. "
            "Your sole job is to apply standard screenplay layout to the source text. "
            "Do not rewrite, summarise, condense, or omit anything.\n\n"
            "ABSOLUTE RULES (breaking any of these is wrong):\n"
            "1. PRESERVE EVERYTHING VERBATIM. Every sentence, phrase, and word from the "
            "source must appear in the output unchanged — action lines, descriptions, "
            "situational notes, all of it.\n"
            "2. PRESERVE ALL DIALOGUE VERBATIM, word for word, whether or not it appears "
            "in quotation marks.\n"
            "3. PRESERVE ALL TRANSITIONS EXACTLY: \"CUT TO —\", \"INTERCUT —\", "
            "\"FADE TO BLACK\", \"FADE OUT.\", etc. — copy them as-is on their own line.\n"
            "4. PRESERVE ALL SCENE HEADINGS: INT., EXT., or bare location lines — keep "
            "every one that exists; do NOT invent or remove any.\n"
            "5. Do NOT merge, reorder, or split scenes.\n\n"
            "FORMATTING rules (apply these without altering any text):\n"
            "- Scene headings: INT./EXT. LOCATION – TIME (ALL CAPS, own line)\n"
            "- Transitions (CUT TO, INTERCUT, FADE TO, etc.): ALL CAPS, own line\n"
            "- Character names: ALL CAPS on their own line immediately before their speech\n"
            "- Dialogue: lines directly below the character name\n"
            "- Parentheticals: (in parentheses) between character name and dialogue, "
            "only if present in the source — never invent them\n"
            "- Action/description: plain paragraph lines\n\n"
            "Output the formatted screenplay text only — no commentary, no preamble."
        )
        self.writer_ai_prompt_text.delete("1.0", tk.END)
        self.writer_ai_prompt_text.insert("1.0", default_prompt)
        self._run_writer_ai_edit()

    def _show_writer_ai_progress_overlay(self, detail: str, model: str) -> None:
        self._progress_win = tk.Toplevel(self.root)
        win = self._progress_win
        win.title("Generating\u2026")
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        self.root.update_idletasks()
        w, h = 420, 220
        rx = self.root.winfo_rootx() + self.root.winfo_width() // 2 - w // 2
        ry = self.root.winfo_rooty() + self.root.winfo_height() // 2 - h // 2
        win.geometry(f"{w}x{h}+{rx}+{ry}")

        outer = ttk.Frame(win, padding=(24, 18, 24, 14))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Writer AI \u2014 Generating",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")

        detail_frame = ttk.Frame(outer, padding=(0, 8, 0, 8))
        detail_frame.pack(fill="x")
        ttk.Label(detail_frame, text=f"Prompt:  {detail}", wraplength=360).pack(anchor="w")
        ttk.Label(detail_frame, text=f"Model:   {model}").pack(anchor="w")

        self._elapsed_var = tk.StringVar(value="Elapsed: 0:00")
        ttk.Label(outer, textvariable=self._elapsed_var,
                  foreground="#888").pack(anchor="w", pady=(4, 4))
        self._generation_start_time = time.monotonic()
        self._tick_elapsed_timer()

        self._progress_bar = ttk.Progressbar(outer, mode="indeterminate", length=370)
        self._progress_bar.pack(fill="x")
        self._progress_bar.start(10)

        ttk.Button(outer, text="Cancel", command=self._cancel_writer_ai_edit).pack(pady=(12, 0))

    def _cancel_writer_ai_edit(self) -> None:
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
            text = target.get("1.0", "end-1c")
        text = text[:3000]
        if not text.strip():
            return
        self._stop_read_aloud()
        self._speech_process = subprocess.Popen(
            ["spd-say", "-l", "en-US", "-t", "male1", "-r", "-20", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _stop_read_aloud(self) -> None:
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
            "  - If genuinely unknowable, write: UNKNOWN\n"
            "  - NEVER write: Unknown (place name).\n\n"
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
        return self.save_file()

    def on_exit(self) -> None:
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


if __name__ == "__main__":
    main()
