@echo off
setlocal

echo ============================================
echo  Volume Overlay - Building Windows .exe
echo ============================================
echo.

REM 1) Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

REM 2) Build the .exe (single file, no console window)
pyinstaller --noconfirm --onefile --windowed ^
    --name VolumeOverlay ^
    --hidden-import=comtypes.stream ^
    volume_overlay.py

if not exist "dist\VolumeOverlay.exe" (
    echo.
    echo *** BUILD FAILED ***
    echo Check the output above for errors.
    pause
    exit /b 1
)

REM 3) Drop the .exe + a shortcut/README into a Desktop folder
set TARGET=%USERPROFILE%\Desktop\VolumeOverlay
if not exist "%TARGET%" mkdir "%TARGET%"

copy /Y "dist\VolumeOverlay.exe" "%TARGET%\VolumeOverlay.exe" >nul
copy /Y "README.md" "%TARGET%\README.md" >nul 2>nul

echo.
echo ============================================
echo  Build complete.
echo  Find it on your Desktop in:
echo     %TARGET%
echo  Double-click VolumeOverlay.exe to launch.
echo ============================================
echo.

REM Open the folder so you can see it
start "" "%TARGET%"

pause
