"""
Volume Overlay — Windows 11 styled.
Frameless, always-on-top overlay for master + per-app volume.
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, ttk

try:
    from comtypes import CLSCTX_ALL
    from ctypes import POINTER, cast
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except ImportError:
    print("Missing dependencies. Run:  pip install pycaw comtypes")
    sys.exit(1)


CONFIG_PATH = Path.home() / ".volume_overlay.json"

# Windows 11 Fluent palettes
THEMES = {
    "dark": {
        "bg": "#202020",
        "surface": "#2b2b2b",
        "border": "#3a3a3a",
        "accent": "#60cdff",
        "text": "#ffffff",
        "muted": "#a0a0a0",
        "track": "#454545",
    },
    "light": {
        "bg": "#f3f3f3",
        "surface": "#fbfbfb",
        "border": "#e5e5e5",
        "accent": "#0078d4",
        "text": "#1c1c1c",
        "muted": "#5a5a5a",
        "track": "#d0d0d0",
    },
}

DEFAULTS = {
    "alpha": 0.95,
    "theme": "dark",
    "accent": None,           # None = use theme default
    "x": 80,
    "y": 80,
    "locked": False,
    "selected_apps": ["__master__"],
    "width": 320,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as exc:
        print(f"save_config failed: {exc}")


def palette(cfg: dict) -> dict:
    """Return effective color palette (theme + optional accent override)."""
    p = dict(THEMES[cfg.get("theme", "dark")])
    if cfg.get("accent"):
        p["accent"] = cfg["accent"]
    return p


# ---------------- Audio ----------------
class AudioController:
    def __init__(self) -> None:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self.master = cast(interface, POINTER(IAudioEndpointVolume))

    def get_master(self) -> float:
        return float(self.master.GetMasterVolumeLevelScalar())

    def set_master(self, v: float) -> None:
        self.master.SetMasterVolumeLevelScalar(max(0.0, min(1.0, v)), None)

    def master_muted(self) -> bool:
        return bool(self.master.GetMute())

    def set_master_mute(self, muted: bool) -> None:
        self.master.SetMute(1 if muted else 0, None)

    def list_sessions(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for s in AudioUtilities.GetAllSessions():
            if s.Process is None:
                continue
            try:
                name = s.Process.name()
            except Exception:
                continue
            seen.setdefault(name, {"name": name})
        return sorted(seen.values(), key=lambda x: x["name"].lower())

    def get_app_volume(self, name: str) -> float | None:
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.name() == name:
                return float(s.SimpleAudioVolume.GetMasterVolume())
        return None

    def set_app_volume(self, name: str, v: float) -> None:
        v = max(0.0, min(1.0, v))
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.name() == name:
                s.SimpleAudioVolume.SetMasterVolume(v, None)

    def app_muted(self, name: str) -> bool | None:
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.name() == name:
                return bool(s.SimpleAudioVolume.GetMute())
        return None

    def set_app_mute(self, name: str, muted: bool) -> None:
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.name() == name:
                s.SimpleAudioVolume.SetMute(1 if muted else 0, None)


# ---------------- Overlay ----------------
class VolumeOverlay:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.audio = AudioController()
        self.p = palette(self.cfg)

        self.root = tk.Tk()
        self.root.title("Volume Mixer")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.geometry(f"{self.cfg['width']}x340+{self.cfg['x']}+{self.cfg['y']}")
        self.root.configure(bg=self.p["bg"])

        self._drag = {"x": 0, "y": 0, "active": False}
        self.rows: dict[str, dict] = {}
        self.settings_win: tk.Toplevel | None = None

        self._build_ui()
        self._poll()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        p = self.p

        # Card with subtle border (Win11 style)
        self.card = tk.Frame(
            self.root, bg=p["bg"], padx=14, pady=12,
            highlightthickness=1, highlightbackground=p["border"])
        self.card.pack(fill="both", expand=True)

        # Header
        self.header = tk.Frame(self.card, bg=p["bg"])
        self.header.pack(fill="x", pady=(0, 10))

        self.title_lbl = tk.Label(
            self.header, text="Volume Mixer", fg=p["text"], bg=p["bg"],
            font=("Segoe UI Variable Display", 12, "bold"))
        self.title_lbl.pack(side="left")

        # window-control buttons (Win11-ish)
        self.close_btn = self._make_chrome_btn("✕", self.shutdown)
        self.close_btn.pack(side="right")
        self.lock_btn = self._make_chrome_btn(
            "🔒" if self.cfg["locked"] else "🔓", self.toggle_lock)
        self.lock_btn.pack(side="right", padx=2)
        self.gear_btn = self._make_chrome_btn("⚙", self.open_settings)
        self.gear_btn.pack(side="right", padx=2)

        for w in (self.card, self.header, self.title_lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._stop_drag)

        # Sliders container
        self.rows_frame = tk.Frame(self.card, bg=p["bg"])
        self.rows_frame.pack(fill="x")
        self._build_rows()

    def _make_chrome_btn(self, text, cmd):
        p = self.p
        lbl = tk.Label(self.header, text=text, fg=p["muted"], bg=p["bg"],
                       font=("Segoe UI", 10), cursor="hand2",
                       padx=6, pady=2)
        lbl.bind("<Button-1>", lambda e: cmd())
        lbl.bind("<Enter>", lambda e: lbl.configure(bg=p["surface"], fg=p["text"]))
        lbl.bind("<Leave>", lambda e: lbl.configure(bg=p["bg"], fg=p["muted"]))
        return lbl

    def _build_rows(self) -> None:
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.rows.clear()
        p = self.p

        # ttk slider style: thin track, accent fill
        style = ttk.Style()
        try:
            style.theme_use("default")
        except tk.TclError:
            pass
        style.configure(
            "Win11.Horizontal.TScale",
            background=p["bg"], troughcolor=p["track"],
            bordercolor=p["bg"], lightcolor=p["accent"],
            darkcolor=p["accent"], sliderlength=12, sliderthickness=12,
        )

        any_added = False
        for idx, name in enumerate(self.cfg["selected_apps"]):
            if name == "__master__":
                display = "Speakers / Master"
                cur = self.audio.get_master()
                muted = self.audio.master_muted()
                icon = "🔊"
            else:
                v = self.audio.get_app_volume(name)
                if v is None:
                    continue
                display = name.replace(".exe", "").title()
                cur = v
                muted = self.audio.app_muted(name) or False
                icon = self._app_icon(name)

            if idx > 0 and any_added:
                tk.Frame(self.rows_frame, bg=p["border"], height=1).pack(
                    fill="x", pady=6)

            row = tk.Frame(self.rows_frame, bg=p["bg"])
            row.pack(fill="x", pady=3)
            any_added = True

            top = tk.Frame(row, bg=p["bg"])
            top.pack(fill="x")
            tk.Label(top, text=icon, fg=p["text"], bg=p["bg"],
                     font=("Segoe UI Emoji", 12)).pack(side="left")
            tk.Label(top, text=display, fg=p["text"], bg=p["bg"],
                     font=("Segoe UI", 10), padx=8).pack(side="left")
            pct_var = tk.StringVar(value=f"{int(cur * 100)}")
            tk.Label(top, textvariable=pct_var, fg=p["muted"], bg=p["bg"],
                     font=("Segoe UI", 10)).pack(side="right")

            bottom = tk.Frame(row, bg=p["bg"])
            bottom.pack(fill="x", pady=(4, 0))

            mute_var = tk.BooleanVar(value=muted)
            mute_lbl = tk.Label(bottom, text="🔇" if muted else "🔈",
                                fg=p["muted"] if muted else p["text"],
                                bg=p["bg"], font=("Segoe UI Emoji", 11),
                                cursor="hand2")
            mute_lbl.pack(side="left", padx=(0, 6))

            scale = ttk.Scale(bottom, from_=0, to=100, orient="horizontal",
                              style="Win11.Horizontal.TScale")
            scale.set(int(cur * 100))
            scale.pack(side="left", fill="x", expand=True)

            scale.configure(
                command=lambda v, n=name, pv=pct_var: self._on_scale(n, v, pv))

            def toggle_mute(n=name, ml=mute_lbl, mv=mute_var):
                mv.set(not mv.get())
                ml.configure(text="🔇" if mv.get() else "🔈",
                             fg=p["muted"] if mv.get() else p["text"])
                if n == "__master__":
                    self.audio.set_master_mute(mv.get())
                else:
                    self.audio.set_app_mute(n, mv.get())
            mute_lbl.bind("<Button-1>", lambda e, t=toggle_mute: t())

            self.rows[name] = {
                "scale": scale, "pct": pct_var,
                "mute_lbl": mute_lbl, "mute_var": mute_var,
            }

        if not self.rows:
            tk.Label(self.rows_frame,
                     text="No apps selected.\nClick ⚙ → tick the apps you want.",
                     fg=p["muted"], bg=p["bg"],
                     font=("Segoe UI", 9), justify="center").pack(pady=24)

    def _app_icon(self, name: str) -> str:
        """Pick an emoji-ish hint per common app type."""
        n = name.lower()
        if "discord" in n:  return "💬"
        if "spotify" in n:  return "🎵"
        if "chrome" in n or "firefox" in n or "msedge" in n: return "🌐"
        if "valorant" in n or "league" in n or "cs" in n or "overwatch" in n: return "🎮"
        if "obs" in n: return "🎥"
        if "vlc" in n or "media" in n: return "▶"
        return "📱"

    # ---------------- Slider handler ----------------
    def _on_scale(self, name, value, pct_var) -> None:
        v = float(value) / 100.0
        pct_var.set(f"{int(v * 100)}")
        try:
            if name == "__master__":
                self.audio.set_master(v)
            else:
                self.audio.set_app_volume(name, v)
        except Exception:
            pass

    # ---------------- Drag ----------------
    def _start_drag(self, e):
        if self.cfg["locked"]:
            return
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()
        self._drag["active"] = True

    def _do_drag(self, e):
        if self.cfg["locked"] or not self._drag["active"]:
            return
        x = e.x_root - self._drag["x"]
        y = e.y_root - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _stop_drag(self, e):
        if self.cfg["locked"]:
            return
        if self._drag["active"]:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            save_config(self.cfg)
        self._drag["active"] = False

    def toggle_lock(self):
        self.cfg["locked"] = not self.cfg["locked"]
        self.lock_btn.configure(text="🔒" if self.cfg["locked"] else "🔓")
        save_config(self.cfg)

    # ---------------- Poll for external changes ----------------
    def _poll(self) -> None:
        try:
            for name, r in list(self.rows.items()):
                v = self.audio.get_master() if name == "__master__" else self.audio.get_app_volume(name)
                if v is None:
                    continue
                target = int(v * 100)
                cur = int(r["scale"].get())
                if abs(cur - target) > 2:
                    r["scale"].set(target)
                    r["pct"].set(f"{target}")
        except Exception:
            pass
        self.root.after(1000, self._poll)

    # ---------------- Settings ----------------
    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        p = self.p
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title("Settings")
        win.configure(bg=p["bg"])
        win.geometry("400x600")
        win.attributes("-topmost", True)

        def section(title):
            tk.Label(win, text=title, fg=p["text"], bg=p["bg"],
                     font=("Segoe UI Variable Display", 11, "bold")
                     ).pack(anchor="w", padx=18, pady=(14, 6))

        # Theme
        section("Appearance")
        theme_row = tk.Frame(win, bg=p["bg"])
        theme_row.pack(fill="x", padx=18, pady=2)
        tk.Label(theme_row, text="Theme", fg=p["text"], bg=p["bg"],
                 font=("Segoe UI", 10)).pack(side="left")
        theme_var = tk.StringVar(value=self.cfg["theme"])
        combo = ttk.Combobox(theme_row, values=["dark", "light"],
                             textvariable=theme_var, state="readonly", width=10)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>",
                   lambda e: self._set_theme(theme_var.get()))

        # Transparency
        tk.Label(win, text="Transparency", fg=p["text"], bg=p["bg"],
                 font=("Segoe UI", 10)).pack(anchor="w", padx=18, pady=(10, 0))
        alpha_pct = tk.Label(win, text=f"{int(self.cfg['alpha']*100)}%",
                             fg=p["accent"], bg=p["bg"])
        alpha_pct.pack(anchor="e", padx=18)
        a = ttk.Scale(win, from_=20, to=100, orient="horizontal")
        a.set(self.cfg["alpha"] * 100)
        a.pack(fill="x", padx=18)

        def on_a(v):
            self.cfg["alpha"] = float(v) / 100.0
            self.root.attributes("-alpha", self.cfg["alpha"])
            alpha_pct.configure(text=f"{int(self.cfg['alpha']*100)}%")
            save_config(self.cfg)
        a.configure(command=on_a)

        # Accent color
        tk.Label(win, text="Accent color", fg=p["text"], bg=p["bg"],
                 font=("Segoe UI", 10)).pack(anchor="w", padx=18, pady=(10, 0))
        acc_row = tk.Frame(win, bg=p["bg"])
        acc_row.pack(fill="x", padx=18, pady=4)
        sw = tk.Frame(acc_row, bg=self.p["accent"], width=30, height=22,
                      bd=1, relief="solid")
        sw.pack(side="left")

        def pick_acc():
            _, color = colorchooser.askcolor(initialcolor=self.p["accent"], parent=win)
            if color:
                self.cfg["accent"] = color
                sw.configure(bg=color)
                save_config(self.cfg)
                self._refresh_theme()
        tk.Button(acc_row, text="Pick", command=pick_acc,
                  bg=p["surface"], fg=p["text"], bd=1,
                  relief="solid", padx=10).pack(side="left", padx=8)

        def reset_acc():
            self.cfg["accent"] = None
            sw.configure(bg=palette(self.cfg)["accent"])
            save_config(self.cfg)
            self._refresh_theme()
        tk.Button(acc_row, text="Reset", command=reset_acc,
                  bg=p["surface"], fg=p["muted"], bd=1,
                  relief="solid", padx=10).pack(side="left")

        # App picker
        section("Visible Apps")
        tk.Label(win, text="Choose which volumes appear on the overlay.",
                 fg=p["muted"], bg=p["bg"],
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)

        list_frame = tk.Frame(win, bg=p["bg"])
        list_frame.pack(fill="both", expand=True, padx=18, pady=8)

        canvas = tk.Canvas(list_frame, bg=p["bg"], highlightthickness=0, height=180)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=p["bg"])
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        items = [("__master__", "Speakers / Master")] + \
                [(s["name"], s["name"]) for s in self.audio.list_sessions()]
        cvars: dict[str, tk.BooleanVar] = {}
        for name, display in items:
            var = tk.BooleanVar(value=name in self.cfg["selected_apps"])
            tk.Checkbutton(inner, text=display, variable=var,
                           bg=p["bg"], fg=p["text"],
                           selectcolor=p["surface"],
                           activebackground=p["bg"],
                           activeforeground=p["text"],
                           font=("Segoe UI", 10), anchor="w"
                           ).pack(anchor="w", fill="x", pady=1)
            cvars[name] = var

        btn_row = tk.Frame(win, bg=p["bg"])
        btn_row.pack(fill="x", padx=18, pady=12)

        def apply():
            self.cfg["selected_apps"] = [n for n, v in cvars.items() if v.get()]
            if not self.cfg["selected_apps"]:
                self.cfg["selected_apps"] = ["__master__"]
            save_config(self.cfg)
            self._build_rows()

        tk.Button(btn_row, text="Apply", command=apply,
                  bg=self.p["accent"], fg="white", bd=0,
                  font=("Segoe UI", 10, "bold"),
                  padx=22, pady=7).pack(side="left")
        tk.Button(btn_row, text="Refresh", command=lambda: (win.destroy(), self.open_settings()),
                  bg=p["surface"], fg=p["text"], bd=1, relief="solid",
                  padx=14, pady=6).pack(side="right")

    def _set_theme(self, theme: str):
        self.cfg["theme"] = theme
        save_config(self.cfg)
        self._refresh_theme()

    def _refresh_theme(self):
        self.p = palette(self.cfg)
        p = self.p
        self.root.configure(bg=p["bg"])
        self.card.configure(bg=p["bg"], highlightbackground=p["border"])
        self.header.configure(bg=p["bg"])
        self.title_lbl.configure(fg=p["text"], bg=p["bg"])
        for btn in (self.close_btn, self.lock_btn, self.gear_btn):
            btn.configure(bg=p["bg"], fg=p["muted"])
        self.rows_frame.configure(bg=p["bg"])
        self._build_rows()
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.destroy()
            self.open_settings()

    # ---------------- Lifecycle ----------------
    def shutdown(self):
        save_config(self.cfg)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    VolumeOverlay().run()
