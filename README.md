# Easy-Cut v2.0.0

An easy-going video editor (CapCut-style workflow) with a serious engine underneath (Vegas-style power):
multi-track timeline, real compositing, and exports done by FFmpeg in native, multi-threaded code - using your
graphics card's video encoder when it has one.

## Features

**New in 2.0**

*File Explorer (Vegas-style)*
- A built-in browser for every storage location in one place: Quick access (Easy-Cut Recordings, Desktop,
  Videos, Music, Pictures, Downloads, Documents, OneDrive), every drive with a capacity bar, favourites and
  recent folders.
- Grid view with thumbnails or a details list. You can search, filter by type and sort.
- Breadcrumb path bar with back, forward and up.
- A details strip that plays a preview of the selected file.
- Double-click or drag a file onto the timeline. Right-click to add to Media.
- Open it to full view, or minimise the whole library panel to give the timeline more room.

*Music & audio editing*
- Each clip gets its own channel strip:
  - volume and pan
  - fade in/out, dragged straight from the clip's corners on the timeline
  - 3-band EQ with presets (Bass boost, Voice, Bright, Warm, Telephone)
  - noise removal, compressor and reverb
  - one-click Normalize
- Detach audio from a video onto its own track.
- Solo (S) on audio tracks.
- A stereo level meter (peak and RMS) under the preview.

*Export to any format*
- One-click presets:
  - YouTube 1080p / 4K
  - TikTok and Instagram
  - Discord (under 10 MB) and Email (under 25 MB)
  - HEVC, a ProRes master and GIF
  - MP3, WAV, FLAC
  - Podcast and Apple Music
- Your own saved presets.
- Every setting is there for pros:
  - Video formats: MP4 (H.264 / H.265), WebM (VP9 / AV1), MOV ProRes, MKV, GIF, animated WebP and PNG sequence.
  - Audio-only formats: MP3, WAV, FLAC, M4A (AAC / Apple Lossless), OGG, Opus and AIFF.
  - Constant quality, bitrate, or **target file size** (2-pass, hits the size).
  - Custom resolution and 10-bit.
  - Audio bitrate, bit depth, sample rate and channels.
  - **Loudness normalisation** for streaming, broadcast or podcasts.
  - Export the whole timeline, the selection or a custom range.
- A live file-size estimate.
- A render **queue** that exports several versions one after another.

*Record (screen, gameplay, webcam, audio)*
- **Record** button at the top, or Ctrl+R.
- Screen capture uses the graphics card (DXGI desktop duplication, smooth in games) and falls back to GDI.
  It encodes with NVENC / Quick Sync / AMF when available.
- Choose 30 / 60 / 120 fps and native, 1440p, 1080p or 720p resolution.
- Webcam picture-in-picture (pick the corner and size), microphone, and **system audio**: game sound, music and
  voice chat.
- 3-second countdown, and Easy-Cut can hide itself while you record.
- A floating REC bar that is kept out of the recording itself.
- **Ctrl+Shift+R** starts and stops recording from anywhere, even inside a full-screen game.
- When you stop, everything lands on the timeline already lined up:
  - the screen on a video track
  - the webcam above it in its corner
  - the mic and system audio on their own audio tracks
- Recordings are saved to *Videos\Easy-Cut Recordings* (you can change this).

*🍏 Mode redesign*
- macOS-style window:
  - a borderless window with working traffic-light buttons
  - a unified toolbar title bar showing the document state
  - rounded corners on Windows 11
- Inter font, list-style sidebar, segmented controls, green switches and system-blue accents.
- Light and dark variants.

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

**Transitions (new in 1.0)**
- Cross Dissolve, Dip to Black and Slide are built in, and more come in packs.
- To add one, select the clip the transition should lead into and pick a transition. It plays over the end of
  the clip before it.
- A marker on the timeline shows where each transition is. Click it to change the transition, or right-click
  to remove it.

**Packs (new in 1.0)**
Each browser shows *every* item, including ones you haven't downloaded yet. Those are greyed out with a lock.
Click one and Easy-Cut offers its free pack: it downloads, installs and applies the item straight away.

There are 13 packs with 5 items each, sorted into 6 categories on the Extensions screen:

| Category | Packs |
|---|---|
| Filters | Cinematic Filters, Vibe Filters |
| Transitions | Essential Transitions, Dynamic Transitions |
| Animations | Motion Pack, Fun Pack |
| Effects | Retro FX (VHS, Film Grain, Vignette, Pixelate, RGB Split), Stylize FX (Blur, Sharpen, Glow, Posterize, Emboss) |
| Text | Neon & Glow Text, Bold Text Styles, Text Animations (Typewriter and reveals) |
| Fonts | Display Fonts, Retro & Script Fonts (10 Open Font License fonts) |

- You can get packs one at a time, or every pack in a category at once. They update themselves separately
  from the app.
- Packs released after a version of Easy-Cut ships still appear in it, because the list is read from the
  online update manifest.
- Effects have an amount slider, and text styles are also chosen from the Text panel.

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
- **Quality:** 480p to 2160p (4K), or any custom size.
- **Frame rate:** 10, 15, 24, 25, 30, 50 or 60 fps.
- **Formats:** 17 video and audio formats (see *New in 2.0*).
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

`run_tests.bat` (or `python -m unittest discover -s tests -t .`). There are 88 tests. They cover:
- every filter matching FFmpeg pixel-for-pixel, plus chroma key, crop, flip and mirror
- full renders in every format, compared frame by frame with the preview
- speed and pitch, checked by measuring the actual audio frequency
- stabilization and cancelling a render
- every one of the 65 pack items, rendered and compared frame by frame with the preview
- the locked item → download → apply flow (against a local test server)
- extensions, the updater and themes
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
  effects.py            crop / flip / mirror / chroma key / stabilize / speed & pitch / audio channel strip
  exportfmt.py          export formats, presets, rate control, loudness and size estimates
  capture.py            screen / webcam / mic / system-audio recording
  filters.py            colour filters (+ extension effects registry)
  animations.py         motion engine: in/out animations + transitions (one expression drives preview and export)
  catalog.py            the list of packs and what's inside them (bundled copy + online manifest)
  thumbs.py             preview thumbnails for every kind of item
  compositor.py         preview frames
  render.py             export: whole timeline -> one FFmpeg filter graph
  textrender.py         text clips -> images
  theme.py              themes + stylesheet
  extensions.py         extension loader / installer
  updater.py            GitHub update checks
  ui/                   main window, timeline, preview, inspector, library panels, dialogs
    explorer.py         the built-in File Explorer
    recorder.py         the Record window, REC bar and global hotkey
    chrome.py           🍏 Mode window chrome (traffic lights, drag bar, edge resize)
extensions/             the 13 packs (+ _template, a working example to copy)
assets/catalog/         bundled pack list + thumbnails (built by tools/build_catalog.py)
assets/fonts/           Inter (Open Font License) for 🍏 Mode
installer/easycut.iss   Inno Setup script
tools/                  icon, release and extension packaging scripts
updates/manifest.json   what installed copies check on startup
```
