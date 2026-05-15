# Volume Overlay

Pin the **native Windows Volume Mixer** on top of your game.

Instead of a custom UI, this uses Windows' own `sndvol.exe` (the classic volume mixer with master + per-app vertical sliders) and adds:

- 📌 **Always-on-top** — sits over fullscreen-borderless games
- 🌫️ **Transparency** — slider from 40% to 100%
- 🔒 **Lock position** — snaps the mixer back if anything tries to move it
- ⌨️ **Ctrl + H** — global hotkey to show/hide while gaming
- 👁 **Show / Hide** button on the floating control panel

## Quick start (Windows)

Double-click `build_exe.bat`. It will:
1. Install the build tools
2. Compile `VolumeOverlay.exe`
3. **Create `Desktop\VolumeOverlay\`** with the .exe inside
4. Open that folder in Explorer

Then double-click `VolumeOverlay.exe`. The Windows Volume Mixer pops up, gets pinned on top, and a small dark control panel appears next to it.

To autostart on login, drop a shortcut to `VolumeOverlay.exe` into `shell:startup`.

## Run from source (no build)

```bat
pip install -r requirements.txt
python volume_overlay.py
```

## Controls

| Action | How |
| --- | --- |
| Show / hide mixer | **Ctrl + H** (or the 👁 button) |
| Adjust transparency | Slider on control panel |
| Lock mixer in place | 🔓 / 🔒 button on control panel |
| Move control panel | Drag the header |
| Quit | ✕ on control panel |

## How it works

- Launches `sndvol.exe` if it's not already running
- Finds the Volume Mixer window via Win32 `FindWindow` / `EnumWindows`
- Calls `SetWindowPos(HWND_TOPMOST)` to pin it
- Calls `SetLayeredWindowAttributes` for transparency
- A 1-second watchdog re-pins it and (if locked) snaps it back to saved position
- Hotkey handled by `pynput`'s `GlobalHotKeys` on a daemon thread

## Config file

Settings live at `%USERPROFILE%\.volume_overlay.json`:

```json
{
  "alpha": 95,
  "locked": false,
  "lock_x": null,
  "lock_y": null,
  "hotkey": "<ctrl>+h",
  "panel_x": 30,
  "panel_y": 30
}
```

Delete it to reset to defaults.

## Notes

- The classic mixer (`sndvol.exe`) ships with all Windows versions including Windows 11. On Win11 the speaker icon now opens the Settings-app mixer; this tool uses the classic one directly.
- Works with **borderless-windowed** or **windowed** games. Exclusive-fullscreen will cover any overlay (Windows limitation, not ours).

## License

MIT.
