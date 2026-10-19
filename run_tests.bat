@echo off
setlocal
cd /d "%~dp0"
echo === Installing / checking requirements ===
python -m pip install -r requirements.txt || goto :error
echo.
echo === Running tests ===
python -m unittest discover -s tests -t . -v || goto :error
echo.
echo All tests passed.
pause
exit /b 0
:error
echo.
echo Tests failed - see the messages above.
pause
exit /b 1
