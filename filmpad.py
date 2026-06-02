#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import subprocess
import sys
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


class FilmPad:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FilmPad")
        self.root.geometry("900x600")
        self.icon_image = None
        self.available_fonts = self._available_screenplay_fonts()
        self.font_var = tk.StringVar(value=self.available_fonts[0])
        self.format_var = tk.StringVar(value="Action")
        self.screenplay_font = tkfont.Font(family=self.font_var.get(), size=12)
        self.screenplay_font_bold = tkfont.Font(family=self.font_var.get(), size=12, weight="bold")
        self.screenplay_font_scene = tkfont.Font(family=self.font_var.get(), size=12, weight="bold", underline=True)

        self.current_file = None

        self.toolbar = ttk.Frame(root, padding=(10, 8))
        self.toolbar.pack(side="top", fill="x")
        self._build_toolbar()

        self.editor_frame = ttk.Frame(root)
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

    def _on_font_selected(self, _event: tk.Event) -> None:
        self.screenplay_font.configure(family=self.font_var.get(), size=12)
        self._configure_screenplay_tags()

    def _configure_screenplay_tags(self) -> None:
        family = self.font_var.get()
        self.screenplay_font_bold.configure(family=family, size=12, weight="bold")
        self.screenplay_font_scene.configure(family=family, size=12, weight="bold", underline=True)

        cw = max(self.screenplay_font.measure("0"), 8)
        ls = max(self.screenplay_font.metrics("linespace"), 12)

        self.text.configure(font=self.screenplay_font, tabs=(cw * 4,))

        # Action — full-width, no indent; the baseline for all measurements
        self.text.tag_configure(
            "Action",
            font=self.screenplay_font,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=4, spacing3=4,
            justify="left",
        )
        # Scene Heading — full-width, bold+underline, double blank line above (WGA standard)
        self.text.tag_configure(
            "Scene Heading",
            font=self.screenplay_font_scene,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls * 2, spacing3=6,
            justify="left",
        )
        # Character — centred in the column (~22 chars from left, WGA ~3.7" from page edge)
        self.text.tag_configure(
            "Character",
            font=self.screenplay_font,
            lmargin1=cw * 22, lmargin2=cw * 22, rmargin=cw * 20,
            spacing1=ls, spacing3=0,
            justify="left",
        )
        # Parenthetical — narrower than dialogue, sits between character and dialogue
        self.text.tag_configure(
            "Parenthetical",
            font=self.screenplay_font,
            lmargin1=cw * 16, lmargin2=cw * 16, rmargin=cw * 16,
            spacing1=2, spacing3=2,
            justify="left",
        )
        # Dialogue — indented block, wider than parenthetical, standard ~2.5" from page edge
        self.text.tag_configure(
            "Dialogue",
            font=self.screenplay_font,
            lmargin1=cw * 10, lmargin2=cw * 10, rmargin=cw * 10,
            spacing1=2, spacing3=4,
            justify="left",
        )
        # Transition — right-justified flush, double blank line above
        self.text.tag_configure(
            "Transition",
            font=self.screenplay_font,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls * 2, spacing3=ls,
            justify="right",
        )
        # Shot — full-width bold (sub-heading style), single blank line above
        self.text.tag_configure(
            "Shot",
            font=self.screenplay_font_bold,
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=ls, spacing3=4,
            justify="left",
        )
        # Spell-check highlight — red underline, lowest priority
        self.text.tag_configure(SPELL_TAG, underline=True, foreground="#cc0000")
        self.text.tag_lower(SPELL_TAG)

    def apply_screenplay_format(self) -> None:
        try:
            selection_start = self.text.index("sel.first")
            selection_end = self.text.index("sel.last")
        except tk.TclError:
            messagebox.showinfo(
                "Select text",
                "Select the text you want to reformat first.",
            )
            return

        start = self.text.index(f"{selection_start} linestart")
        end = self.text.index(f"{selection_end} lineend")
        format_name = self.format_var.get()

        for existing_format in SCREENPLAY_FORMATS:
            self.text.tag_remove(existing_format, start, end)

        selected_text = self.text.get(start, end)
        replacement = self._format_screenplay_text(selected_text, format_name)

        self.text.delete(start, end)
        self.text.insert(start, replacement)
        new_end = self.text.index(f"{start} + {len(replacement)}c")
        self.text.tag_add(format_name, start, new_end)
        self.text.edit_modified(True)

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

    def _on_font_menu_selected(self) -> None:
        self.screenplay_font.configure(family=self.font_var.get(), size=12)
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
        self.text.tag_remove(SPELL_TAG, "1.0", tk.END)
        content = self.text.get("1.0", "end-1c")
        for line_idx, line in enumerate(content.split("\n"), start=1):
            if not line.strip():
                continue
            for col_start, col_end in self._aspell_check_line(tool, line):
                self.text.tag_add(SPELL_TAG, f"{line_idx}.{col_start}", f"{line_idx}.{col_end}")

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
        self.text.tag_remove(SPELL_TAG, "1.0", tk.END)

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
