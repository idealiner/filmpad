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


class FilmPad:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FilmPad")
        self.root.geometry("900x600")
        self.icon_image = None
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
        widget.tag_configure(SPELL_TAG, underline=True, foreground="#cc0000")
        widget.tag_lower(SPELL_TAG)

    def _configure_screenplay_tags(self) -> None:
        self._configure_screenplay_tags_for_widget(self.text)
        if hasattr(self, "local_ai_result_text"):
            self._configure_screenplay_tags_for_widget(self.local_ai_result_text)

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
        icon_path = resource_path("assets/filmpad-icon.png")
        if not icon_path.exists():
            return

        try:
            self.icon_image = tk.PhotoImage(file=icon_path)
            self.root.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

        format_menu = tk.Menu(menu_bar, tearoff=0)

        font_menu = tk.Menu(format_menu, tearoff=0)
        for font_name in self.available_fonts:
            font_menu.add_radiobutton(
                label=font_name,
                value=font_name,
                variable=self.font_var,
                command=self._on_font_menu_selected,
            )

        screenplay_menu = tk.Menu(format_menu, tearoff=0)
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
            "You are a professional screenplay scene adapter. "
            "Use ONLY the source text below. Do not use memory, prior knowledge, or invention.\n\n"
            "TEMPLATE:\n"
            "=========\n"
            f"{template_text}\n\n"
            f"SOURCE TEXT: {source_name} lines {start_line}-{end_line} only\n"
            "=======================================================\n"
            f"{slice_text}\n\n"
            "TASK:\n"
            "Convert the source text into one or more screenplay scene cards using the template above.\n\n"
            "OUTPUT FORMAT RULES (follow exactly):\n"
            "\n"
            "1. LOCATION field:\n"
            "   - Use the location stated or clearly implied in the source.\n"
            "   - If the location is genuinely unknowable, write: UNKNOWN\n"
            "   - NEVER write: Unknown (place name). Either use the place or write UNKNOWN.\n"
            "\n"
            "2. SOURCE DIALOGUE INSIDE THIS SCENE:\n"
            "   - Include only spoken lines, direct quotes, or inner quoted thoughts from the source.\n"
            "   - Copy them word for word. Do not paraphrase.\n"
            "   - Do not include narration or description here.\n"
            "\n"
            "3. ADAPTED SCREENPLAY SCENE formatting:\n"
            "   - Begin with a slug line: INT./EXT. LOCATION - DAY/NIGHT\n"
            "   - Action lines: left margin, present tense, one sentence per line, \n"
            "     describe only what can be seen or heard.\n"
            "   - Every spoken line MUST appear like this:\n"
            "\n"
            "         CHARACTER NAME\n"
            "         Exact dialogue copied from source.\n"
            "\n"
            "   - CHARACTER NAME must be in ALL CAPS on its own line above every dialogue line.\n"
            "   - NEVER omit the character name before a dialogue line.\n"
            "   - NEVER write 'NO EXACT DIALOGUE FOUND' if SOURCE DIALOGUE has content.\n"
            "   - If a character name is genuinely unknown, write: UNKNOWN SPEAKER\n"
            "   - Do NOT add parentheticals like (quietly), (feigning calm) unless the source\n"
            "     explicitly states that exact tone or manner in those words.\n"
            "   - Do NOT describe psychology, motivation, subtext, or emotion unless it is\n"
            "     physically visible or explicitly stated in the source.\n"
            "   - Preserve concrete cues: weather, objects, posture, sound, silence, gesture.\n"
            "   - Do NOT wrap lines mid-word. Write each sentence on one complete line.\n"
            "   - Use plain ASCII punctuation only.\n"
            "\n"
            "4. NOTES field:\n"
            "   - Reference only what actually changed in this output.\n"
            "   - Do not invent examples not present in the source range.\n"
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
        cleaned = re.sub(r"(\b\w{1,4})\n(\1\w+)", _rejoin_split_words, cleaned)
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


def main() -> None:
    root = tk.Tk()
    app = FilmPad(root)
    app._set_title()
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
