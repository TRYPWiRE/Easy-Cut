@echo off
setlocal
cd /d "%~dp0"
rem Publishes the version built by build.bat:
rem   1. creates GitHub release v<version> with the installer attached
rem   2. commits + pushes updates\manifest.json (installed copies read it on startup)
rem Needs: git, and the GitHub CLI (https://cli.github.com) logged in with "gh auth login".

for /f "delims=" %%v in ('python -c "import easycut; print(easycut.__version__)"') do set VER=%%v
if not exist "release\EasyCutSetup-%VER%.exe" (
    echo release\EasyCutSetup-%VER%.exe not found - run build.bat first.
    goto :error
)
where gh >nul 2>nul || (echo GitHub CLI "gh" not found - install it from https://cli.github.com & goto :error)

gh release view v%VER% >nul 2>nul
if errorlevel 1 (
    gh release create v%VER% "release\EasyCutSetup-%VER%.exe" --title "Easy-Cut %VER%" --notes "Easy-Cut %VER%" || goto :error
) else (
    gh release upload v%VER% "release\EasyCutSetup-%VER%.exe" --clobber || goto :error
)

git add -A || goto :error
git commit -m "Release Easy-Cut %VER%" || echo Nothing new to commit.
git push || goto :error

echo.
echo Published Easy-Cut %VER%. Installed copies will offer the update next time they start.
pause
exit /b 0
:error
pause
exit /b 1
