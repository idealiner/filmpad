#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, messagebox


class BasicPad:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BasicPad")
        self.root.geometry("900x600")

        self.current_file = None

        self.text = tk.Text(root, wrap="word", undo=True)
        self.scroll = tk.Scrollbar(root, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scroll.set)

        self.scroll.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

        self._build_menu()

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menu_bar)

        self.root.bind("<Control-n>", lambda _e: self.new_file())
        self.root.bind("<Control-o>", lambda _e: self.open_file())
        self.root.bind("<Control-s>", lambda _e: self.save_file())

    def _set_title(self) -> None:
        name = self.current_file if self.current_file else "Untitled"
        self.root.title(f"BasicPad - {name}")

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
    app = BasicPad(root)
    app._set_title()
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
