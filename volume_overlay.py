"""
Volume Overlay — Pins the native Windows Volume Mixer on top of your game.

Uses sndvol.exe (the classic Windows volume mixer with master + per-app
sliders) and forces it always-on-top with optional transparency.

A tiny floating control bar gives you:
  - Transparency slider
  - Lock toggle (snaps the mixer back if anything moves it)
  - Show/Hide button
  - Quit button

Global hotkey Ctrl+H toggles mixer visibility from anywhere (even in-game).
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk

try:
    from pynput import keyboard as kb
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False


CONFIG_PATH = Path.home() / ".volume_overlay.json"

DEFAULTS = {
    "alpha": 95,            # percent
    "locked": False,
    "lock_x": None,
    "lock_y": None,
    "hotkey": "<ctrl>+h",
    "panel_x": 30,
    "panel_y": 30,
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
    except Exception:
        pass


# ---------------- Win32 helpers ----------------
user32 = ctypes.windll.user32
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOW = 5

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_mixer_by_title() -> int | None:
    """English Windows: 'Volume Mixer'. Returns 0/None if not found."""
    return user32.FindWindowW(None, "Volume Mixer") or None


def find_mixer_by_pid(pid: int) -> int | None:
    """Find a top-level visible window owned by `pid`."""
    found = []

    def cb(hwnd, _lparam):
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid and user32.IsWindowVisible(hwnd):
            # Only accept windows with non-empty title
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def pin_topmost(hwnd: int, topmost: bool = True) -> None:
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST,
        0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def set_alpha(hwnd: int, alpha_percent: int) -> None:
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(
        hwnd, 0, max(40, min(255, int(alpha_percent * 255 / 100))), LWA_ALPHA)


def get_pos(hwnd: int) -> tuple[int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top


def move_to(hwnd: int, x: int, y: int) -> None:
    user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)


def show_window(hwnd: int, visible: bool = True) -> None:
    user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)


def is_window_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def get_or_launch_mixer() -> int | None:
    """Return an HWND for sndvol.exe's window, launching it if needed."""
    hwnd = find_mixer_by_title()
    if hwnd:
        return hwnd

    try:
        proc = subprocess.Popen(["sndvol.exe"], shell=False)
    except FileNotFoundError:
        proc = subprocess.Popen("sndvol.exe", shell=True)

    # Wait up to 5s
    for _ in range(50):
        time.sleep(0.1)
        hwnd = find_mixer_by_title()
        if hwnd:
            return hwnd
        hwnd = find_mixer_by_pid(proc.pid)
        if hwnd:
            return hwnd
    return None


# ---------------- Control panel ----------------
class ControlPanel:
    def __init__(self) -> None:
        self.cfg = load_config()
        self._stop = False
        self._listener = None

        self.hwnd = get_or_launch_mixer()
        if not self.hwnd:
            self._fatal("Couldn't find the Windows Volume Mixer window.\n"
                        "Make sure sndvol.exe is on your PATH (it ships with Windows).")
            return

        pin_topmost(self.hwnd, True)
        set_alpha(self.hwnd, self.cfg["alpha"])
        if self.cfg["locked"] and self.cfg["lock_x"] is not None:
            move_to(self.hwnd, self.cfg["lock_x"], self.cfg["lock_y"])

        self._start_hotkey()
        threading.Thread(target=self._watchdog, daemon=True).start()
        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("Mixer Pin")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"260x170+{self.cfg['panel_x']}+{self.cfg['panel_y']}")
        BG = "#202020"
        SUR = "#2b2b2b"
        BORDER = "#3a3a3a"
        ACC = "#60cdff"
        TXT = "#ffffff"
        MUT = "#a0a0a0"
        self.root.configure(bg=BG)

        card = tk.Frame(self.root, bg=BG, padx=12, pady=10,
                        highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True)

        # Header (drag handle)
        hdr = tk.Frame(card, bg=BG)
        hdr.pack(fill="x")
        title = tk.Label(hdr, text="🔊  Mixer Pin", fg=TXT, bg=BG,
                         font=("Segoe UI Variable Display", 11, "bold"))
        title.pack(side="left")

        hk_lbl = tk.Label(hdr, text="  Ctrl+H", fg=MUT, bg=BG,
                          font=("Segoe UI", 9))
        hk_lbl.pack(side="left")

        close = tk.Label(hdr, text="✕", fg=MUT, bg=BG, cursor="hand2",
                         font=("Segoe UI", 11), padx=6)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.shutdown())

        # Drag bindings
        self._drag = {"x": 0, "y": 0, "on": False}
        for w in (card, hdr, title, hk_lbl):
            w.bind("<ButtonPress-1>", self._d_start)
            w.bind("<B1-Motion>", self._d_move)
            w.bind("<ButtonRelease-1>", self._d_end)

        # Transparency
        tk.Label(card, text="Mixer transparency", fg=TXT, bg=BG,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
        pct_var = tk.StringVar(value=f"{self.cfg['alpha']}%")
        pct_lbl = tk.Label(card, textvariable=pct_var, fg=ACC, bg=BG,
                           font=("Segoe UI", 9))
        pct_lbl.pack(anchor="e")
        scale = ttk.Scale(card, from_=40, to=100, orient="horizontal")
        scale.set(self.cfg["alpha"])
        scale.pack(fill="x")

        def on_alpha(v):
            a = int(float(v))
            pct_var.set(f"{a}%")
            self.cfg["alpha"] = a
            save_config(self.cfg)
            if is_window(self.hwnd):
                set_alpha(self.hwnd, a)
        scale.configure(command=on_alpha)

        # Buttons row
        btn_row = tk.Frame(card, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))

        self.lock_btn = tk.Button(
            btn_row, text="🔒 Lock" if self.cfg["locked"] else "🔓 Unlocked",
            command=self.toggle_lock, bd=0,
            bg=ACC if self.cfg["locked"] else SUR,
            fg="white" if self.cfg["locked"] else TXT,
            activebackground=ACC, font=("Segoe UI", 9, "bold"),
            padx=12, pady=6)
        self.lock_btn.pack(side="left", padx=(0, 4))

        self.toggle_btn = tk.Button(
            btn_row, text="👁 Hide", command=self.toggle_visibility,
            bd=0, bg=SUR, fg=TXT, activebackground=ACC,
            font=("Segoe UI", 9, "bold"), padx=12, pady=6)
        self.toggle_btn.pack(side="left", padx=4)

    def _d_start(self, e):
        self._drag["x"] = e.x_root - self.root.winfo_x()
        self._drag["y"] = e.y_root - self.root.winfo_y()
        self._drag["on"] = True

    def _d_move(self, e):
        if not self._drag["on"]:
            return
        x = e.x_root - self._drag["x"]
        y = e.y_root - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _d_end(self, e):
        if self._drag["on"]:
            self.cfg["panel_x"] = self.root.winfo_x()
            self.cfg["panel_y"] = self.root.winfo_y()
            save_config(self.cfg)
        self._drag["on"] = False

    def toggle_lock(self):
        self.cfg["locked"] = not self.cfg["locked"]
        if self.cfg["locked"] and is_window(self.hwnd):
            x, y = get_pos(self.hwnd)
            self.cfg["lock_x"], self.cfg["lock_y"] = x, y
            self.lock_btn.configure(text="🔒 Lock", bg="#60cdff", fg="white")
        else:
            self.lock_btn.configure(text="🔓 Unlocked", bg="#2b2b2b", fg="#ffffff")
        save_config(self.cfg)

    def toggle_visibility(self):
        if not is_window(self.hwnd):
            self.hwnd = get_or_launch_mixer()
            if not self.hwnd:
                return
            pin_topmost(self.hwnd)
            set_alpha(self.hwnd, self.cfg["alpha"])
        visible = is_window_visible(self.hwnd)
        show_window(self.hwnd, not visible)
        if not visible:  # we just showed it again
            pin_topmost(self.hwnd)
            self.toggle_btn.configure(text="👁 Hide")
        else:
            self.toggle_btn.configure(text="👁 Show")

    # ---------------- Hotkey ----------------
    def _start_hotkey(self):
        if not _HAS_PYNPUT:
            return
        try:
            self._listener = kb.GlobalHotKeys({
                self.cfg["hotkey"]: lambda: self.root.after(0, self.toggle_visibility),
            })
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            print(f"hotkey: {e}")

    # ---------------- Watchdog ----------------
    def _watchdog(self):
        """Re-pin every second; if locked, snap mixer back if it moves."""
        while not self._stop:
            time.sleep(1)
            if not self.hwnd or not is_window(self.hwnd):
                continue
            pin_topmost(self.hwnd)
            if self.cfg["locked"] and self.cfg["lock_x"] is not None:
                x, y = get_pos(self.hwnd)
                if (x, y) != (self.cfg["lock_x"], self.cfg["lock_y"]):
                    move_to(self.hwnd, self.cfg["lock_x"], self.cfg["lock_y"])

    # ---------------- Lifecycle ----------------
    def _fatal(self, msg):
        root = tk.Tk()
        root.title("Volume Overlay")
        root.configure(bg="#202020")
        tk.Label(root, text=msg, fg="#ffffff", bg="#202020",
                 font=("Segoe UI", 10), justify="left",
                 padx=20, pady=20, wraplength=380).pack()
        tk.Button(root, text="OK", command=root.destroy,
                  bg="#60cdff", fg="white", bd=0,
                  font=("Segoe UI", 10, "bold"),
                  padx=20, pady=6).pack(pady=(0, 14))
        root.mainloop()
        sys.exit(1)

    def shutdown(self):
        self._stop = True
        if self._listener:
            try: self._listener.stop()
            except Exception: pass
        if self.hwnd and is_window(self.hwnd):
            pin_topmost(self.hwnd, False)  # un-pin before exit
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    cp = ControlPanel()
    cp.run()
