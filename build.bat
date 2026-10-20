@echo off
setlocal
cd /d "%~dp0"
rem ============================================================
rem  Easy-Cut build: pack catalog -> tests -> app (PyInstaller) -> installer (Inno Setup) -> update manifest + packs
rem  Needs: Python 3.10+ on PATH, and Inno Setup 6.3+ for the installer step.
rem ============================================================

echo === 1/6  Installing build requirements ===
python -m pip install -r requirements-build.txt || goto :error

for /f "delims=" %%v in ('python -c "import easycut; print(easycut.__version__)"') do set VER=%%v
echo Building Easy-Cut %VER%

echo === 2/6  Building the pack catalog (previews of every pack item) ===
python tools\build_catalog.py || goto :error

echo === 3/6  Running tests ===
python -m unittest discover -s tests -t . || goto :error

echo === 4/6  Building the app (dist\Easy-Cut\Easy-Cut.exe) ===
if exist build rmdir /s /q build
if exist "dist\Easy-Cut" rmdir /s /q "dist\Easy-Cut"
python -m PyInstaller --noconfirm --clean --windowed --name "Easy-Cut" ^
  --icon assets\easycut.ico ^
  --add-data "assets;assets" ^
  --collect-data imageio_ffmpeg ^
  --collect-data soundcard --hidden-import soundcard.mediafoundation --hidden-import _cffi_backend ^
  --exclude-module tkinter --exclude-module matplotlib --exclude-module PyQt6.QtWebEngineCore ^
  --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.Qt3DCore --exclude-module PyQt6.QtQuick ^
  --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtPdf --exclude-module PyQt6.QtBluetooth ^
  main.py || goto :error

echo === 5/6  Building the installer ===
set "ISCC="
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do (
    if exist %%p set "ISCC=%%~p"
)
if "%ISCC%"=="" (
    echo Inno Setup 6 was not found, so no installer was made.
    echo Install it from https://jrsoftware.org/isdl.php and run build.bat again.
    echo The portable app is ready in dist\Easy-Cut\Easy-Cut.exe
    goto :done
)
"%ISCC%" /Qp /DMyAppVersion=%VER% installer\easycut.iss || goto :error

echo === 6/6  Updating updates\manifest.json and packaging the packs ===
python tools\release.py release\EasyCutSetup-%VER%.exe || goto :error
python tools\build_extensions.py || goto :error

echo.
echo Installer: release\EasyCutSetup-%VER%.exe
echo Run publish.bat to put this version on GitHub.
:done
pause
exit /b 0
:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
