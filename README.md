# Easy-Cut v0.1.0

An easy-going video editor (CapCut-style workflow) with a serious engine underneath (Vegas-style power):
multi-track timeline, real compositing, and exports done by FFmpeg in native, multi-threaded code - using your
graphics card's video encoder when it has one.

## Features

**Editing**
- Multi-track timeline: video, photo, text and audio tracks; add or remove tracks; hide or mute tracks.
- Drag to move clips, drag edges to trim, and snap to clips and the playhead (hold Alt to skip snapping).
- Split, duplicate and delete. Undo and redo everything. Close gaps on a track.
- Drag files in from Explorer, onto the timeline or the preview.
- Canvas follows your first clip (a portrait video switches the canvas to TikTok Style).

**Preview**
- Live preview with every effect. Drag a clip in the preview to move it, or drag a corner to resize it.
- Playback with mixed audio.
- Preview quality: Performance, Balanced or High (*View ▸ Preview quality*).

**Look**
- Filters (handful): Vivid, Warm, Cool, B&W, Vintage, Noir. Each has an intensity slider.
- Adjust: brightness, contrast and saturation.
- Animations (handful), each usable as an in or an out animation: Fade, Zoom, Pop, Slide Left, Slide Right,
  Slide Up and Drop.
- Text: six styles, any font, size and colour, plus outline or background box.

**Video Effects & Compositing**
- **Chroma key** (green screen): pick the key colour with an eyedropper on the preview, then set strength and smoothness.
- **Crop**, **flip** (horizontal or vertical) and **mirror** (four directions).
- **Speed** from 0.1x to 10x. Pitch is kept by default, or turn that off for a tape-style effect. Pitch shift
  of ±12 semitones.
- **Image stabilization**: two-pass vid.stab when FFmpeg has it, deshake otherwise. It's applied on export.
- Transform: scale, position, rotation and opacity.

**Export**
- **Shapes:** Movie Style (Landscape 16:9), TikTok Style (Portrait 9:16), Insta Square (1:1), Insta Portrait (4:5),
  Cinematic (21:9), Classic TV (4:3) and Feed Landscape (5:4).
- **Quality:** 1080p, 1440p and 2160p (4K).
- **Frame rate:** 10 fps (GIFs), 30 fps or 60 fps.
- **Formats:** MP4 (H.264), WebM (VP9) and animated GIF (palette-optimised).
- **Encoder:** Automatic picks NVIDIA NVENC, Intel Quick Sync or AMD AMF when available, falling back to the CPU
  (x264) automatically if the GPU encoder fails.
- **Keep my PC responsive:** exports run at lower priority.
- A slim, smooth progress bar with time remaining, plus Open video and Show in folder when it's done.

**App**
- Themes:
  - Dark (default)
  - Light
  - 🍏 Mode (Apple-style)
  - Cyberpunk (yellow and purple, sharp corners)
  - Custom: an editor for every colour, the corner radius and the font. You can save themes and set one as default.
- **Extensions** section, highlighted with a NEW badge in the sidebar. More filters, animations and video effects
  will arrive there.
- **Auto-updates:** checks GitHub on every start; the installed app downloads, verifies and installs updates
  itself. Extensions update separately.
- **Hidden app data:** everything (settings, themes, extensions, caches, autosave) lives in `%APPDATA%\Easy-Cut`.
  If the app closes unexpectedly, it offers to recover your project.
- Projects save as `.ecut` files. If media has moved, the app asks you to find it.

## Run from source

```
pip install -r requirements.txt
python main.py
```

FFmpeg comes with the `imageio-ffmpeg` package, so nothing else is needed.

## Run the tests

`run_tests.bat` (or `python -m unittest discover -s tests -t .`). There are 65 tests. They cover:
- every filter matching FFmpeg pixel-for-pixel, plus chroma key, crop, flip and mirror
- full renders in every format, compared frame by frame with the preview
- speed and pitch, checked by measuring the actual audio frequency
- stabilization and cancelling a render
- extensions, the updater (against a local test server) and themes
- the main window driven like a user would

## Build the app + installer

Run `build.bat`. It installs the build tools, runs the tests, then:
- builds `dist\Easy-Cut\Easy-Cut.exe`
- makes the installer `release\EasyCutSetup-<version>.exe` (needs Inno Setup 6.3+)
- updates `updates\manifest.json` for the updater

The installer is per-user, so no admin prompt. It adds a Start Menu entry and offers a desktop shortcut,
opening `.ecut` projects, and an "Open with" entry for videos.

See **RELEASING.md** for publishing updates and extensions.

## Layout

```
main.py                 entry point
easycut/
  project.py            tracks, clips, save/load, undo history
  media.py              FFmpeg discovery, probing, frame readers, thumbnails, hardware encoder detection
  effects.py            crop / flip / mirror / chroma key / stabilize / speed & pitch (preview + FFmpeg)
  filters.py            colour filters (+ extension effects registry)
  animations.py         in/out animations (one expression drives preview and export)
  compositor.py         preview frames
  render.py             export: whole timeline -> one FFmpeg filter graph
  textrender.py         text clips -> images
  theme.py              themes + stylesheet
  extensions.py         extension loader / installer
  updater.py            GitHub update checks
  ui/                   main window, timeline, preview, inspector, library panels, dialogs
extensions/_template/   a working example extension to copy
installer/easycut.iss   Inno Setup script
tools/                  icon, release and extension packaging scripts
updates/manifest.json   what installed copies check on startup
```
