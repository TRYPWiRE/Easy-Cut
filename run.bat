@echo off
setlocal
cd /d "%~dp0"
python -c "import PyQt6, cv2, numpy, imageio_ffmpeg" 2>nul || (
    echo Installing requirements...
    python -m pip install -r requirements.txt || goto :error
)
python main.py %*
exit /b 0
:error
pause
exit /b 1
