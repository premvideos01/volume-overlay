"""
Volume Overlay
==============
A frameless, always-on-top Windows overlay for controlling master + per-app
volume while gaming. Movable, lockable, transparency + color customization.

Requires: Windows 10/11, Python 3.9+, pycaw, comtypes.
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

DEFAULTS = {
    "alpha": 0.85,
    "bg": "#14141c",
    "accent": "#7c5cff",
    "text": "#f0f0f5",
    "muted": "#8888a0",
    "x": 80,
    "y": 80,
    "locked": False,
    "selected_apps": ["__master__"],
    "width": 280,
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


class AudioController:
    """Thin wrapper around pycaw for master + per-app volume."""

    def __init__(self) -> None:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self.master = cast(interface, POINTER(IAudioEndpointVolume))

    def get_master(self) -> float:
        return float(self.master.GetMasterVolumeLevelScalar())

    def set_master(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        self.master.SetMasterVolumeLevelScalar(v, None)

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


class VolumeOverlay:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.audio = AudioController()

        self.root = tk.Tk()
        self.root.title("Volume Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.geometry(f"{self.cfg['width']}x300+{self.cfg['x']}+{self.cfg['y']}")
        self.root.configure(bg=self.cfg["bg"])

        self._drag = {"x": 0, "y": 0, "active": False}
        self.sliders: dict[str, tuple[ttk.Scale, tk.StringVar]] = {}
        self.settings_win: tk.Toplevel | None = None

        self._build_ui()
        self._poll()

    # ---------------- UI build ----------------
    def _build_ui(self) -> None:
        cfg = self.cfg
        self.frame = tk.Frame(self.root, bg=cfg["bg"], padx=12, pady=10,
                              highlightthickness=1, highlightbackground=cfg["accent"])
        self.frame.pack(fill="both", expand=True)

        # ---- Header (drag handle) ----
        self.header = tk.Frame(self.frame, bg=cfg["bg"])
        self.header.pack(fill="x", pady=(0, 8))

        self.title_lbl = tk.Label(
            self.header, text="🔊 Volume", fg=cfg["accent"], bg=cfg["bg"],
            font=("Segoe UI", 11, "bold"))
        self.title_lbl.pack(side="left")

        self.close_btn = tk.Label(
            self.header, text="✕", fg=cfg["muted"], bg=cfg["bg"],
            font=("Segoe UI", 11), cursor="hand2")
        self.close_btn.pack(side="right", padx=(4, 0))
        self.close_btn.bind("<Button-1>", lambda e: self.shutdown())

        self.lock_btn = tk.Label(
            self.header, text="🔒" if cfg["locked"] else "🔓",
            fg=cfg["muted"], bg=cfg["bg"],
            font=("Segoe UI", 11), cursor="hand2")
        self.lock_btn.pack(side="right", padx=4)
        self.lock_btn.bind("<Button-1>", lambda e: self.toggle_lock())

        self.gear_btn = tk.Label(
            self.header, text="⚙", fg=cfg["muted"], bg=cfg["bg"],
            font=("Segoe UI", 12), cursor="hand2")
        self.gear_btn.pack(side="right", padx=4)
        self.gear_btn.bind("<Button-1>", lambda e: self.open_settings())

        for w in (self.frame, self.header, self.title_lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._stop_drag)

        # ---- Sliders container ----
        self.sliders_frame = tk.Frame(self.frame, bg=cfg["bg"])
        self.sliders_frame.pack(fill="x")
        self._build_sliders()

    def _build_sliders(self) -> None:
        for w in self.sliders_frame.winfo_children():
            w.destroy()
        self.sliders.clear()

        cfg = self.cfg
        style = ttk.Style()
        try:
            style.theme_use("default")
        except tk.TclError:
            pass
        style.configure("Vol.Horizontal.TScale",
                        background=cfg["bg"], troughcolor="#2a2a3a",
                        bordercolor=cfg["bg"], lightcolor=cfg["accent"],
                        darkcolor=cfg["accent"])

        for name in self.cfg["selected_apps"]:
            if name == "__master__":
                display = "Master"
                cur = self.audio.get_master()
            else:
                v = self.audio.get_app_volume(name)
                if v is None:
                    continue  # app not running right now
                display = name.replace(".exe", "")
                cur = v

            row = tk.Frame(self.sliders_frame, bg=cfg["bg"])
            row.pack(fill="x", pady=3)

            label_row = tk.Frame(row, bg=cfg["bg"])
            label_row.pack(fill="x")
            tk.Label(label_row, text=display, fg=cfg["text"], bg=cfg["bg"],
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
            pct_var = tk.StringVar(value=f"{int(cur * 100)}%")
            tk.Label(label_row, textvariable=pct_var, fg=cfg["accent"],
                     bg=cfg["bg"], font=("Segoe UI", 9)).pack(side="right")

            scale = ttk.Scale(row, from_=0, to=100, orient="horizontal",
                              style="Vol.Horizontal.TScale")
            scale.set(int(cur * 100))
            scale.pack(fill="x", pady=(2, 0))
            scale.configure(command=lambda v, n=name, pv=pct_var: self._on_scale(n, v, pv))
            self.sliders[name] = (scale, pct_var)

        # Empty hint
        if not self.sliders:
            tk.Label(self.sliders_frame,
                     text="No volumes selected.\nClick ⚙ to pick apps.",
                     fg=self.cfg["muted"], bg=cfg["bg"],
                     font=("Segoe UI", 9), justify="center").pack(pady=20)

    # ---------------- Slider handler ----------------
    def _on_scale(self, name: str, value, pct_var: tk.StringVar) -> None:
        v = float(value) / 100.0
        pct_var.set(f"{int(v * 100)}%")
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

    def toggle_lock(self) -> None:
        self.cfg["locked"] = not self.cfg["locked"]
        self.lock_btn.configure(text="🔒" if self.cfg["locked"] else "🔓")
        save_config(self.cfg)

    # ---------------- Poll for external changes ----------------
    def _poll(self) -> None:
        try:
            for name, (scale, pct_var) in list(self.sliders.items()):
                v = self.audio.get_master() if name == "__master__" else self.audio.get_app_volume(name)
                if v is None:
                    continue
                target = int(v * 100)
                cur = int(scale.get())
                if abs(cur - target) > 2:  # avoid fighting user drag
                    scale.set(target)
                    pct_var.set(f"{target}%")
        except Exception:
            pass
        self.root.after(1000, self._poll)

    # ---------------- Settings ----------------
    def open_settings(self) -> None:
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return

        cfg = self.cfg
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title("Volume Overlay — Settings")
        win.configure(bg=cfg["bg"])
        win.geometry("380x560")
        win.attributes("-topmost", True)

        # Transparency
        tk.Label(win, text="Transparency", fg=cfg["text"], bg=cfg["bg"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 4))
        alpha_pct_lbl = tk.Label(win, text=f"{int(cfg['alpha'] * 100)}%",
                                 fg=cfg["accent"], bg=cfg["bg"])
        alpha_pct_lbl.pack(anchor="e", padx=14)
        alpha_scale = ttk.Scale(win, from_=20, to=100, orient="horizontal")
        alpha_scale.set(cfg["alpha"] * 100)
        alpha_scale.pack(fill="x", padx=14)

        def on_alpha(v):
            a = float(v) / 100.0
            cfg["alpha"] = a
            self.root.attributes("-alpha", a)
            alpha_pct_lbl.configure(text=f"{int(a * 100)}%")
            save_config(cfg)
        alpha_scale.configure(command=on_alpha)

        # Colors
        tk.Label(win, text="Colors", fg=cfg["text"], bg=cfg["bg"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 4))

        swatches: dict[str, tk.Frame] = {}
        for key, label in [("bg", "Background"), ("accent", "Accent"), ("text", "Text")]:
            row = tk.Frame(win, bg=cfg["bg"])
            row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=label, fg=cfg["text"], bg=cfg["bg"],
                     font=("Segoe UI", 9)).pack(side="left")
            swatch = tk.Frame(row, bg=cfg[key], width=28, height=20,
                              bd=1, relief="solid")
            swatch.pack(side="right", padx=6)
            swatches[key] = swatch

            def pick(k=key, sw=swatch):
                _, color = colorchooser.askcolor(initialcolor=cfg[k], parent=win)
                if color:
                    cfg[k] = color
                    sw.configure(bg=color)
                    save_config(cfg)
                    self._apply_colors()
            tk.Button(row, text="Pick", command=pick,
                      bg=cfg["bg"], fg=cfg["text"], bd=1,
                      relief="solid", padx=8).pack(side="right")

        # App selector
        tk.Label(win, text="Visible Volumes", fg=cfg["text"], bg=cfg["bg"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 0))
        tk.Label(win, text="Tick which sliders to show on the overlay.",
                 fg=cfg["muted"], bg=cfg["bg"],
                 font=("Segoe UI", 8)).pack(anchor="w", padx=14)

        list_frame = tk.Frame(win, bg=cfg["bg"])
        list_frame.pack(fill="both", expand=True, padx=14, pady=4)

        canvas = tk.Canvas(list_frame, bg=cfg["bg"], highlightthickness=0, height=200)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=cfg["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        items = [("__master__", "Master")] + [(s["name"], s["name"]) for s in self.audio.list_sessions()]
        check_vars: dict[str, tk.BooleanVar] = {}
        for name, display in items:
            var = tk.BooleanVar(value=name in cfg["selected_apps"])
            tk.Checkbutton(inner, text=display, variable=var,
                           bg=cfg["bg"], fg=cfg["text"],
                           selectcolor=cfg["bg"],
                           activebackground=cfg["bg"],
                           activeforeground=cfg["text"],
                           font=("Segoe UI", 9), anchor="w"
                           ).pack(anchor="w", fill="x")
            check_vars[name] = var

        btn_row = tk.Frame(win, bg=cfg["bg"])
        btn_row.pack(fill="x", padx=14, pady=10)

        def apply():
            cfg["selected_apps"] = [n for n, v in check_vars.items() if v.get()]
            if not cfg["selected_apps"]:
                cfg["selected_apps"] = ["__master__"]
            save_config(cfg)
            self._build_sliders()

        tk.Button(btn_row, text="Apply", command=apply,
                  bg=cfg["accent"], fg="white", bd=0,
                  font=("Segoe UI", 10, "bold"),
                  padx=20, pady=6).pack(side="left")
        tk.Button(btn_row, text="Refresh app list",
                  command=lambda: (win.destroy(), self.open_settings()),
                  bg=cfg["bg"], fg=cfg["muted"], bd=0,
                  font=("Segoe UI", 9)).pack(side="right")

    # ---------------- Theming ----------------
    def _apply_colors(self) -> None:
        cfg = self.cfg
        self.root.configure(bg=cfg["bg"])
        self.frame.configure(bg=cfg["bg"], highlightbackground=cfg["accent"])
        self.header.configure(bg=cfg["bg"])
        self.title_lbl.configure(fg=cfg["accent"], bg=cfg["bg"])
        self.close_btn.configure(bg=cfg["bg"], fg=cfg["muted"])
        self.lock_btn.configure(bg=cfg["bg"], fg=cfg["muted"])
        self.gear_btn.configure(bg=cfg["bg"], fg=cfg["muted"])
        self.sliders_frame.configure(bg=cfg["bg"])
        self._build_sliders()

    # ---------------- Lifecycle ----------------
    def shutdown(self) -> None:
        save_config(self.cfg)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    VolumeOverlay().run()
