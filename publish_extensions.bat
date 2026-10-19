@echo off
setlocal
cd /d "%~dp0"
rem Repackage extensions (all, or the ids given) and push them - no app release needed.
rem   publish_extensions.bat                 -> every extension in extensions\
rem   publish_extensions.bat my-extension    -> just that one
rem Remember to raise "version" in the extension's manifest.json first.
python tools\build_extensions.py %* || goto :error
git add updates extensions || goto :error
git commit -m "Update extensions %*" || echo Nothing new to commit.
git push || goto :error
echo Done - users get the update next time Easy-Cut starts.
pause
exit /b 0
:error
pause
exit /b 1
