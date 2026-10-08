# PhotoSelect v0.3 — Nikon NEF and Olympus ORF

A working first version for importing a folder, ranking photo quality, comparing burst frames, and exporting a shortlist. All image decoding happens on your computer. Originals are read only; no deletion, moving or uploading is implemented.

## Start on a current Apple Mac

This package targets **Apple silicon Macs (M1 and later), macOS 11 or newer**, with native ARM64 Python 3.12–3.14. Use the macOS 64-bit universal2 installer from https://www.python.org/downloads/macos/. An Intel or Rosetta Python installation is deliberately rejected rather than attempting to compile a RAW decoder.

1. Unzip the package into a writable folder such as your home folder.
2. Double-click `Start-Mac.command`. If compatible Python is missing, it opens the official Python downloads page and explains what to install.
3. First-time setup downloads prebuilt dependencies. Subsequent launches reuse the dedicated app environment without reinstalling.
4. Your default browser opens http://127.0.0.1:8765. Keep the Terminal window open; press Control+C to stop.

If macOS blocks the launcher, open Terminal, type `bash ` (with a trailing space), drag `Start-Mac.command` into Terminal, and press Return. The launcher never removes macOS quarantine flags or disables Gatekeeper.

The Mac folder chooser uses the native macOS Choose Folder dialog via AppleScript, without requiring Tkinter. For an external drive, allow macOS file access when prompted. If access is blocked, review System Settings → Privacy & Security → Files and Folders for Terminal. You can also paste the full folder path into the app.

This is a local browser app with a launcher, **not a signed standalone .app or DMG**. It still requires one Python installation. Mac hardware execution has not been tested in the Linux development environment; dependency-wheel availability is checked separately.

## Windows / Linux

Windows: install Python 3.11 or 3.12, then double-click `Start-Windows.bat`.
Linux: in this folder run `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, then `.venv/bin/python app.py`.

If the native folder picker is unavailable (some Python installations omit Tk), paste the full folder path. On Mac you can drag a folder into Terminal to obtain its path; remove shell quotation marks or backslash escaping before pasting into the app.

## Review a shoot

- Start with 20–50 photos. Choose a folder, optionally include subfolders, then Analyse photos. RAW decoding can take several seconds per image. Images are processed sequentially to limit memory use.
- Adjust sharpness, subject focus, composition and exposure weights. Weight values are normalised; their effective percentages appear when adjusted. All weights at zero yield a score of zero.
- Keep / Consider / Skip are suggestions based on your thresholds. Nothing is removed.
- Open a frame and drag a rectangle over the subject. This replaces the default central focus region and recalculates focus rankings across the folder. Regions are session-only; exported CSV records them.
- Use full-resolution detail to check critical focus at native image size. This opens a decoded JPEG in another browser tab. It is not an embedded camera preview. Colour is a basic camera-white-balance rendering, not your Lightroom edits.
- Burst matching requires EXIF capture time and combines time gap, a perceptual difference hash and mean colour. Subsecond timestamps are used if present. Frames without usable capture times remain separate. Matching is heuristic; review the groups, especially when panning or subject motion changes the frame.
- Burst winners only shows the highest weighted score in each group. Like photos and compare liked photos to rank a shortlist across groups.
- Override any recommendation with Keep / Consider / Skip; use ↺ to restore automatic scoring.
- Export decisions downloads a CSV containing original paths, scores, decisions, weights, focus regions and burst winners. Importing this CSV into Lightroom is not implemented.

Manual decisions, likes, weights and thresholds are stored in your browser's local storage by folder and original path, and return after reopening and rescanning the same folder. RAW pixels and analysis previews are not stored in browser local storage. Other analysis results and focus regions are rebuilt each session. Do not clear browser storage if you want to retain these preferences. Export CSV before changing browser or moving files.

## What scores mean

Sharpness: variance of a Laplacian edge response, divided by local contrast, on a decoded image resized to a maximum 1,600-pixel long edge.
Focus: the same measurement inside the central half of the image or a user-selected subject region. This is a detail proxy, not autofocus-point detection or a trained subject model.
Sharpness and focus are normalised against the folder's 10th and 90th percentiles. These are relative rankings, not calibrated probabilities. Even a folder of uniformly soft photographs can contain a high-ranking frame. Noise, waves, foliage, exposure, lens rendering and shallow depth of field can influence scores.
Composition: an edge-energy centroid's proximity to rule-of-thirds intersections, penalised for detail near borders. This is a transparent heuristic, not an aesthetic model. It may undervalue centred compositions and cannot reliably detect cropped masts, sailor expressions, clean backgrounds or decisive sporting moments.
Exposure: fraction of pixels outside near-black / near-white thresholds in the rendered image; it does not measure RAW highlight recovery.

For sailing, start with focus 50 / sharpness 30 / composition 15 / exposure 5. Select a region containing the sailors or boat details so sharp water is less likely to win. Treat the automatic shortlist as a starting point and inspect close contenders at full resolution.

## Nikon and Olympus / OM System RAW support

- Nikon: `.nef` and `.nrw`.
- Olympus / OM System: `.orf`.
- Lowercase, uppercase and mixed-case extensions work (for example `.NEF`, `.ORF` and `.Orf`).
- Mixed folders of Nikon, Olympus and other images are supported. Use the new camera-format filter to review Nikon or Olympus frames separately.
- RAW files are demosaiced by rawpy / LibRaw; scoring does not use an embedded JPEG thumbnail. Each card identifies its format and whether it was RAW decoded.
- Unsupported camera encodings and damaged RAW files are reported individually, while the scan continues.

Extension recognition and decoder routing were tested. Genuine Nikon/Olympus RAW samples were not available, so successful decoding on your exact cameras is not yet verified. Accepted extensions do not guarantee all camera models or special shooting modes are supported.

## RAW support and limits

Uses rawpy / LibRaw for actual RAW decoding. NEF, NRW, ARW, CR2, CR3, DNG, RAF, ORF, RW2, PEF and SRW extensions are accepted, plus JPEG, PNG and TIFF. Support depends on the camera, encoding and the installed LibRaw build; an accepted extension is not a guarantee. Unsupported files appear in the error list. No camera-specific RAW files were available during development, so your Nikon/Fuji files need validation on your computer.

This is source software, not a signed standalone installer. Full-resolution decoding can consume substantial RAM for large sensors. Preview files are written into an OS temporary folder outside your photo folder. The server binds only to localhost and guards API requests with a session token. No external service is called while reviewing photos. No semantic AI model, automatic eye detection, motion-blur classifier, XMP writeback, cancellation or background scan resumption is included in this first version.

## Development checks

Run `python -m unittest test_analysis.py`. Tests cover blur discrimination, subject-region behaviour, missing timestamps, similarity-based burst separation, and app routes using generated JPEGs. See `TEST_RESULTS.txt` for checks performed when packaged.
