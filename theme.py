"""Shared dark theme (ttk 'clam' re-skinned) for the TrainzLib GUI and 3D viewer."""
import sys
import tkinter as tk

import i18n
from tkinter import font as tkfont
from tkinter import ttk

# "Brunswick" livery: deep locomotive green surfaces, brass coachlining as the one accent,
# signal-lamp colours for status. Change the values here and every window follows.
BG = "#0f1a16"          # window (green-black, like cab-side paint in shadow)
SURFACE = "#16261f"     # cards
SURFACE2 = "#203529"    # buttons / raised
SURFACE3 = "#2c4638"    # hover
FIELD = "#0b1310"       # inputs
BORDER = "#2b4437"
FG = "#ebeee6"
MUTED = "#90a99c"
ACCENT = "#d9a441"      # brass
ACCENT_HOVER = "#ecbb5c"
ACCENT_DIM = "#6e5521"
ON_ACCENT = "#1b1405"   # text that sits on brass
GOOD = "#6fe3a1"        # signal green
WARN = "#f4c24f"        # caution amber
BAD = "#ff7d6e"         # signal red
VIEWPORT = "#091210"

# 3D viewer drawing colours
GRID = "#1a2b23"
GRID_MID = "#2f4a3b"
MESH_EDGE = "#07100c"
AXIS_X, AXIS_Y, AXIS_Z = "#ff7d6e", "#6fe3a1", "#7db8ff"
BONE_DOT = "#ff7d6e"
BONE_RING = "#0f1a16"
LABEL = "#ebeee6"
MESH_PALETTE = [(0.74, 0.78, 0.70), (0.82, 0.64, 0.30), (0.34, 0.62, 0.50), (0.80, 0.42, 0.36),
                (0.52, 0.62, 0.76), (0.68, 0.56, 0.72)]

_FAMILY = None


def family():
    """Bahnschrift (the DIN-style transport-signage face in Windows 10/11), then Segoe UI, then any sans."""
    global _FAMILY
    if _FAMILY is None:
        have = set(tkfont.families())
        cjk = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC",
               "WenQuanYi Micro Hei") if i18n.is_zh() else ()
        for name in cjk + ("Bahnschrift", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "DejaVu Sans"):
            if name in have:
                _FAMILY = name
                break
        else:
            _FAMILY = "TkDefaultFont"
    return _FAMILY


def reset_fonts():
    """Forget the cached font so the next family() call re-picks it (used after the language is chosen)."""
    global _FAMILY
    _FAMILY = None


def mono():
    have = set(tkfont.families())
    for name in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"):
        if name in have:
            return name
    return "TkFixedFont"


def apply_theme(root):
    root.configure(background=BG)
    fam = family()
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=10)
        except tk.TclError:
            pass
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=BORDER,
                lightcolor=BG, darkcolor=BG, troughcolor=FIELD, focuscolor=BG, font=(fam, 10))

    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=SURFACE)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("Card.TLabel", background=SURFACE, foreground=FG)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED)
    s.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=(fam, 9))
    s.configure("Title.TLabel", font=(fam, 20, "bold"))
    s.configure("Heading.TLabel", background=SURFACE, foreground=FG, font=(fam, 11, "bold"))
    s.configure("Key.TLabel", background=SURFACE, foreground=MUTED, font=(fam, 9))
    s.configure("Val.TLabel", background=SURFACE, foreground=FG, font=(fam, 9, "bold"))
    s.configure("Status.TLabel", background=BG, foreground=MUTED, font=(fam, 9))

    s.configure("TButton", background=SURFACE2, foreground=FG, borderwidth=0, padding=(14, 7), relief="flat", width=0)
    s.map("TButton", background=[("disabled", SURFACE), ("pressed", ACCENT_DIM), ("active", SURFACE3)],
          foreground=[("disabled", MUTED)])
    s.configure("Accent.TButton", background=ACCENT, foreground=ON_ACCENT, font=(fam, 10, "bold"), padding=(20, 8))
    s.map("Accent.TButton", background=[("disabled", ACCENT_DIM), ("pressed", ACCENT_DIM), ("active", ACCENT_HOVER)],
          foreground=[("disabled", "#8d7640")])

    # segmented / toggle buttons (Radiobutton + Checkbutton drawn as buttons)
    for sty, on, on_fg in (("Seg.Toolbutton", ACCENT, ON_ACCENT), ("Tog.Toolbutton", ACCENT_DIM, FG)):
        s.configure(sty, background=SURFACE2, foreground=MUTED, borderwidth=0, padding=(12, 6), relief="flat", anchor="center")
        s.map(sty, background=[("selected", on), ("pressed", SURFACE3), ("active", SURFACE3)],
              foreground=[("selected", on_fg), ("active", FG)])

    s.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, padding=7)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)],
          fieldbackground=[("disabled", SURFACE)], foreground=[("disabled", MUTED)])
    s.configure("TCombobox", fieldbackground=FIELD, background=SURFACE2, foreground=FG, arrowcolor=MUTED,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6, selectbackground=FIELD,
                selectforeground=FG)
    s.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", SURFACE)],
          foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    for sty in ("TRadiobutton", "TCheckbutton"):
        s.configure("Card." + sty, background=SURFACE, foreground=FG, indicatorbackground=FIELD,
                    indicatorforeground=ACCENT, indicatorcolor=FIELD, bordercolor=BORDER, padding=(2, 3))
        s.map("Card." + sty, background=[("active", SURFACE)], indicatorcolor=[("selected", ACCENT), ("active", SURFACE3)],
              foreground=[("disabled", MUTED)])

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(20, 10), borderwidth=0, font=(fam, 10, "bold"))
    s.configure("TNotebook.Tab", bordercolor=BG, lightcolor=BG, darkcolor=BG)
    s.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", FG), ("active", FG)],
          bordercolor=[("selected", SURFACE)], lightcolor=[("selected", SURFACE)], darkcolor=[("selected", SURFACE)],
          expand=[("selected", (0, 0, 0, 0))])
    s.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [("Notebook.label", {"side": "top", "sticky": ""})]})]})])

    s.configure("Horizontal.TScale", background=ACCENT, troughcolor=FIELD, bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=SURFACE2, borderwidth=0,
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=4)
    s.configure("Vertical.TScrollbar", background=SURFACE2, troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=MUTED,
                lightcolor=SURFACE2, darkcolor=SURFACE2, gripcount=0, relief="flat")
    s.map("Vertical.TScrollbar", background=[("active", SURFACE3)])
    s.configure("TSeparator", background=BORDER)
    return s


def enable_dark_titlebar(root):
    """Windows 10/11 only: make the native title bar dark. Silently does nothing elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def resource_path(name):
    """Path of a bundled file, both when run as a script and inside a PyInstaller one-file exe."""
    import os
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def set_icon(root):
    """Use the bundled trainzlib.ico for the title bar / taskbar if it is there."""
    try:
        root.iconbitmap(default=resource_path("trainzlib.ico"))
    except Exception:
        pass


def logo(parent, size=40):
    """Small brass plate with a length of track receding into the distance, drawn on a canvas (no image files)."""
    c = tk.Canvas(parent, width=size, height=size, background=BG, highlightthickness=0)
    s = size / 40.0
    c.create_rectangle(1, 1, size - 1, size - 1, outline=ACCENT, width=2)
    cx = size / 2
    for i in range(4):                                   # sleepers, wider as they come toward the viewer
        y = (11 + i * 7.5) * s
        half = (4 + i * 3.2) * s
        c.create_line(cx - half - 2 * s, y, cx + half + 2 * s, y, fill=ACCENT_DIM, width=max(1, int(2 * s)))
    c.create_line(cx - 3 * s, 7 * s, cx - 12 * s, size - 6 * s, fill=ACCENT, width=max(1, int(2 * s)))
    c.create_line(cx + 3 * s, 7 * s, cx + 12 * s, size - 6 * s, fill=ACCENT, width=max(1, int(2 * s)))
    return c


class Card(tk.Frame):
    """A bordered dark card with an optional heading; put content in `.body`."""

    def __init__(self, parent, title=None, subtitle=None, **kw):
        super().__init__(parent, background=SURFACE, highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=BORDER, **kw)
        self.body = ttk.Frame(self, style="Card.TFrame", padding=(14, 12, 14, 14))
        if title:
            head = ttk.Frame(self, style="Card.TFrame", padding=(14, 12, 14, 0))
            head.pack(fill="x")
            ttk.Label(head, text=title, style="Heading.TLabel").pack(anchor="w")
            if subtitle:
                ttk.Label(head, text=subtitle, style="CardMuted.TLabel", wraplength=470, justify="left").pack(anchor="w", pady=(2, 0))
            self.body.configure(padding=(14, 10, 14, 14))
        self.body.pack(fill="both", expand=True)
