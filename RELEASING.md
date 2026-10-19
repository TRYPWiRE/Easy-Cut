# Releasing Easy-Cut

This works the same way as Lumen: the app reads `updates/manifest.json` from the GitHub repo every time it starts.

## One-time setup

1. Create the repo **github.com/TRYPWiRE/Easy-Cut**. It must be **public**, because the app reads the manifest
   without logging in. To use a different repo, edit `GITHUB_OWNER` / `GITHUB_REPO` in `easycut/config.py` and
   `MyAppURL` in `installer/easycut.iss`.
2. Push this folder to it (`git init`, `git remote add origin ...`, `git push -u origin main`).
3. Install:
   - [Inno Setup 6.3+](https://jrsoftware.org/isdl.php)
   - the [GitHub CLI](https://cli.github.com), then run `gh auth login`

## Releasing a new version of the app

1. Raise `__version__` in `easycut/__init__.py`, for example `0.1.1`.
2. Run `build.bat`. It:
   - runs the tests
   - builds the app and the installer
   - writes the new version, download URL and SHA-256 into `updates/manifest.json`
3. Run `publish.bat`. It creates GitHub release `v0.1.1` with the installer attached, then commits and pushes
   the manifest.

The next time someone opens Easy-Cut, a bar offers **Update now**. The app then:
1. downloads the installer
2. checks the SHA-256 (it refuses a mismatch)
3. closes, upgrades silently and reopens

Settings, themes and extensions in `%APPDATA%\Easy-Cut` are kept.

To add release notes to the update bar, run `python tools\release.py release\EasyCutSetup-0.1.1.exe "Your notes"`
before publishing.

## Extensions

An extension is a folder in `extensions/<id>/` holding `manifest.json` and `main.py` (copy `extensions/_template`,
which is a working example that adds a filter, an animation and a video effect).

```python
def register(api):
    api.register_filter(id, name, matrix=3x3, contrast=1.0, brightness=0.0, lift=0.0)   # or ffmpeg=..., preview=...
    api.register_animation(id, name, scale="...", dx="...", dy="...", fade=False)     # expressions in E (0..1)
    api.register_effect(id, name, ffmpeg="filter chain using {amount}", preview=fn(bgr, amount))
```

Items an extension registers appear in the Filters, Animations and Effects panels automatically.
The Extensions page lists everything in the manifest, with Install, Update and Remove buttons.

- **Publish or update extensions without an app release:** raise `version` in the extension's manifest, then run
  `publish_extensions.bat` (all extensions) or `publish_extensions.bat <id>` (just one).
- **Test locally:** zip the folder and use *Extensions ▸ Install from file…*.
- Folders starting with `_` are never published.
- `min_app` in an extension's manifest hides it from app versions too old to run it.
