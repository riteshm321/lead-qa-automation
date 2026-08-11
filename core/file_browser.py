import tkinter as tk
from tkinter import filedialog


def browse_for_file(file_types: list[tuple[str, str]] | None = None) -> str | None:
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    path = filedialog.askopenfilename(
        filetypes=file_types or [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    root.destroy()
    return path or None
