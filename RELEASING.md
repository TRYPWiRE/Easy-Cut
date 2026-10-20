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

## Packs (extensions)

Each pack is a folder in `extensions/<id>/` containing `manifest.json`, `main.py`, and any files it bundles
(fonts, for example). `extensions/_template` is a working example to copy.

```json
{"id": "my-pack", "name": "My Pack", "version": "1.0.0", "category": "Effects",
 "description": "...", "min_app": "1.0.0",
 "items": [{"type": "effect", "id": "my-fx", "name": "My FX"}]}
```

- **category:** one of Filters, Transitions, Animations, Effects, Text or Fonts. It decides where the pack shows
  on the Extensions screen.
- **items:** lists everything the pack registers. The browsers use this list to show the items greyed out
  before anyone downloads the pack. `tools/build_catalog.py` checks that it matches what `main.py` actually
  registers.

```python
def register(api):
    api.register_filter(id, name, matrix=3x3, contrast=1.0, brightness=0.0, lift=0.0)
    api.register_transition(id, name, scale="...", dx="...", dy="...", rot="...", alpha="fade|half|none",
                            veil="#rrggbb" or None, reveal="left|right|up|down" or None)
    api.register_animation(id, name, scale="...", dx="...", dy="...", rot="...", fade=False, reveal=None, steps=0)
    api.register_effect(id, name, ffmpeg="chain" or fn(amount, w, h, uid), preview=fn(bgr, amount))
    api.register_text_style(id, name, paint=fn(painter, ctx), pad=0.2)
    api.register_font(id, name, "fonts/MyFont.ttf")
```

Motion expressions use `E` (eased progress) and `P` (linear progress). See `easycut/animations.py`.

**Publishing:**
- `build.bat` rebuilds the bundled catalog (`assets/catalog`), packages every pack into `updates/extensions/`
  and lists them in `updates/manifest.json`.
- `publish.bat` pushes all of that along with the app.
- To update packs without an app release:
  1. Raise `version` in the pack's manifest.
  2. Run `publish_extensions.bat <id>`.
  3. Installed copies offer the update the next time they start.

**Adding a brand-new pack:**
- Add the folder and run `publish_extensions.bat`. It appears in existing installs straight away, because the
  online manifest lists its items.
- Its locked previews only get thumbnails once you run `build.bat` for the next app version.
- **Test locally:** zip the folder and use *Extensions ▸ Install from file…*.
- Folders starting with `_` are never published.
- `min_app` hides a pack from app versions too old to run it.
