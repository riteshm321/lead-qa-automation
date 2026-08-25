import tkinter as tk
from tkinter import filedialog


def browse_for_file(file_types: list[tuple[str, str]] | None = None) -> str | None:
    root = tk.Tk()
    try:
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askopenfilename(
            filetypes=file_types or [
                ("Excel/CSV files", "*.xlsx *.xls *.csv"), ("Excel files", "*.xlsx *.xls"),
                ("CSV files", "*.csv"), ("All files", "*.*"),
            ]
        )
    finally:
        # Without this in a finally, an exception from the dialog itself
        # (e.g. a Tcl error) would leak this hidden Tk root permanently —
        # this function runs fresh on every "Browse..." click.
        root.destroy()
    return path or None


def browse_for_folder() -> str | None:
    root = tk.Tk()
    try:
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory()
    finally:
        root.destroy()
    return path or None
