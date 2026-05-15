@echo off
REM Build a standalone Windows .exe with PyInstaller.
REM Run this on Windows from this folder.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --onefile --windowed ^
    --name VolumeOverlay ^
    --hidden-import=comtypes.stream ^
    volume_overlay.py

echo.
echo Build complete. Exe is at: dist\VolumeOverlay.exe
pause
