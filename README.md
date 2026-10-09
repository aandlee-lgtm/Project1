# PhotoSelect 1.3 — Apple silicon Mac app

PhotoSelect helps you cull bursts of sailing and sports photos. Point it at a folder of Nikon
(NEF/NRW), Olympus / OM System (ORF), other RAW, JPEG, PNG or TIFF files. It decodes each photo
on your Mac, groups bursts, ranks frames with transparent scores you can weight, and lets you
mark Keep / Consider / Drop and likes, then export a CSV. Originals are only ever read:
nothing is deleted, renamed, moved, uploaded, or written to your photo folders.

* **Install:** see [INSTALL.md](INSTALL.md) (drag from the DMG to Applications).
* **What was tested, and what wasn't:** [VALIDATION_REPORT.md](VALIDATION_REPORT.md).
* **Testing on your own Mac:** open [docs/field-tests.html](docs/field-tests.html) in a browser and use
  **Help → Create Diagnostic Report…** in the app. The report has timings, decode results, bursts and
  errors, with no image data and no full paths.

## Using it

1. **Choose folder** (native macOS dialog; external drives work). Tick *Include subfolders* if needed.
2. **Analyse photos.** RAW files first show the camera's embedded preview, labelled
   *"embedded camera preview · analysis pending"*. Each file is then fully decoded by LibRaw
   and scored. Scores are provisional until the scan finishes. **Cancel** keeps everything
   analysed so far, and analysing the same folder again reuses it.
3. Adjust the **importance sliders** (sharpness, subject focus, composition, exposure) and the
   **Keep / Consider thresholds**. Rankings update immediately.
4. Open a frame. **Drag a rectangle over the sailors or boat** so focus is measured there rather
   than on textured water. The region is measured on the full-resolution decode and is
   remembered for that file.
5. **Inspect full resolution** shows the decoded original inside the app at fit, 100%
   (one image pixel per screen pixel) or 200%. Click to zoom to a point.
6. **Compare this burst** ranks the burst side by side. Tick *100% crops of the focus region* to
   compare critical focus. **Compare liked photos** does the same for your shortlist.
7. Mark Keep / Consider / Drop or ♥ Like (keys in the viewer: ← → K C D L F). Click the Keep, Consider or Drop tile above the grid to show only that group; click it again (or Photos analysed) to show all.
   **Export decisions** saves a CSV with paths, scores, decisions, reasons and burst results.
8. **Learn from my decisions.** After marking at least 30 photos (♥ liked photos count as Keep), click
   *Suggest settings from my decisions*. PhotoSelect proposes slider weights and thresholds that match
   your choices, explains why, and shows how many of your decisions they match before and after.
   Nothing changes until you click **Apply**, and **Undo learned settings** restores the previous ones.
   Save settings as named **profiles** (e.g. Sailing), or tick *Use these settings whenever this folder
   is analysed*.
9. **Send to Lightroom** (Adobe Lightroom Classic). Install the plug-in once with **Help → Install
   Lightroom Plug-in…** and restart Lightroom. Cull first, click **Send to Lightroom**, import the folder
   in Lightroom, then choose **Library → Plug-in Extras → Apply PhotoSelect Selections…**:
   * stars: Keep ★★★, Consider ★★, Drop ★, ♥ Liked ★★★★★ (your decision wins over the suggestion);
   * keywords under *PhotoSelect*: Keep / Consider / Drop / Liked / Burst NNN / Near-identical /
     Camera preview, for Smart Collections (not included when exporting images);
   * photos are matched by file, then file name + capture time, then a unique capture time, so
     copied or renamed imports still match. A summary is shown first. Star ratings already set in
     Lightroom are kept unless you tick *Replace*.

   The selections are saved in `~/Library/Application Support/PhotoSelect/Lightroom/`, never in your
   photo folders, and no XMP sidecar files are written.

Decisions, likes, focus regions, preferences and analysis results are saved automatically:

| What | Where |
|---|---|
| Decisions, likes, regions, preferences, analysis results | `~/Library/Application Support/PhotoSelect/photoselect.db` |
| Thumbnails and previews (safe to clear: Help → About → Clear analysis cache) | `~/Library/Caches/PhotoSelect/` |
| Log file (Help → Open Log Folder) | `~/Library/Logs/PhotoSelect/` |
| Selections sent to Lightroom | `~/Library/Application Support/PhotoSelect/Lightroom/` |
| Lightroom plug-in (Help → Install Lightroom Plug-in…) | `~/Library/Application Support/Adobe/Lightroom/Modules/PhotoSelect.lrplugin` |

Nothing is written inside the app bundle or the disk image.

## What the scores mean (and don't)

All scores are **relative to the current folder** (folder 10th–90th percentile → 15–95), not
probabilities or absolute quality. Even a folder of soft photos has a top frame.

| Score | How it is measured | Known weaknesses |
|---|---|---|
| Sharpness | Laplacian edge detail of the whole frame at 1,600 px, divided by contrast | Waves, foliage, rigging, a sharp background and noise all count as "detail" |
| Subject focus | Same idea in the subject region (default: central half; or the region you draw), cropped from the **full-resolution decode**, resampled to a common 4,000 px-long-edge scale, lightly low-pass filtered, with the variance expected from **estimated sensor noise subtracted** | Real texture (water, foliage) inside the region still counts. Frames smaller than 4,000 px are measured at native size. Not autofocus-point or eye detection |
| Composition | Edge-energy centre near rule-of-thirds points minus border clutter | A heuristic, not a trained aesthetic model. Can under-rate centred subjects. Cannot see cropped masts, expressions or the decisive moment |
| Exposure | Share of pixels not clipped to near-black/near-white in the rendered image | Does not measure RAW highlight headroom |

Each photo lists the **reasons** behind its suggestion: threshold comparison, weighted
contributions, where focus was measured, clipping, a *high noise* warning when the frame is
among the noisiest in the folder, and its rank and gap within its burst. A frame is **never
marked Drop just for not winning its burst**. Frames within 3 points of the burst's top frame
are flagged *close to burst top · compare*.

**Not implemented:** eye or face detection, subject recognition, motion-blur detection, artistic
judgement, XMP sidecar files. The learning feature only fits the four slider weights and two
thresholds to your decisions; it is not a trained image model.

**Burst grouping** uses EXIF capture time (with sub-seconds when the camera records them) and
**% likeness**: how alike two frames look, from a 16 × 12 grey-level version of each frame and its
average colour (100 % = the same). A frame joins a burst when it was shot within the frame gap
(default 2 s) of the previous frame and is at least *Similarity ≥* % alike (default 70 %), so panning
sequences stay together. Frames at least *Near-identical ≥* % alike (default 90 %) are also grouped
when shot up to the *near-identical window* apart (default 10 s), even with other frames between them,
and are marked **NEAR-IDENTICAL**. The viewer shows each frame's likeness to its burst's top frame,
the burst comparison shows likeness to #1, and the CSV and diagnostic report include it. Frames
without capture times stay ungrouped.

**RAW rendering:** LibRaw with the camera's white balance, sRGB output, the camera orientation
flag, and no per-image auto-brightening, so a burst renders consistently. It will not match
your Lightroom edits.

**When RAW pixels can't be decoded — camera preview fallback.** Some RAW files can be opened but not
decoded by LibRaw, notably **Nikon High Efficiency (HE / HE★) NEF**, such as the Z6III's, which uses
a licensed codec. If the camera stored a usable JPEG inside the file (Nikon stores a full-size one,
6048 × 4032 on the Z6III), PhotoSelect analyses that JPEG instead. Such photos are labelled
**CAMERA PREVIEW** on the card, in the viewer, in comparisons and in the CSV (`analysis_source`,
`source_notice`). Their scores include the camera's sharpening, noise reduction and Picture Control,
so they are not measurements of the RAW pixels. Damaged or non-RAW files never fall back. Previews
smaller than 1,000 px on the long edge are not used. For full RAW analysis on a Nikon Z, shoot NEF
(RAW) compression → Lossless compressed.

## Architecture

* `desktop.py`: entry point. A native window (WKWebView via pywebview) shows the interface,
  served by an in-process Waitress server bound to `127.0.0.1` on an OS-assigned port. Every API
  call needs a per-launch random token, and the Host header must match (DNS-rebinding
  protection). The window, server and analysis threads share one process. Closing the window
  or quitting ends it, so nothing keeps running.
* `engine.py`: scanning, bounded worker pool, progressive previews, cancellation, caching.
  rawpy/LibRaw, NumPy and Pillow release Python's GIL during heavy work, so threads give real
  parallelism without child processes. The worker count is limited by CPU count and RAM
  (about 4 GB per worker, at most 4).
* `raw_io.py`: decoding (rawpy/LibRaw for RAW, Pillow for JPEG/PNG/TIFF), EXIF capture times
  (including ORF's non-standard TIFF header), clear errors for damaged, empty, unsupported or
  unreadable files.
* `lightroom/PhotoSelect.lrplugin`: the Lightroom Classic plug-in (Lua). `SelectionsCore.lua` holds
  the matching logic and is unit-tested under Lua 5.1 (`tests/test_lightroom_plugin.py`, needs
  `lupa`), including a run of the menu command against a simulated Lightroom catalog.
* `analysis.py`: the metrics above and burst grouping. `store.py`: SQLite persistence and
  standard macOS locations. `app.py`: HTTP API. `static/index.html`: the interface.

## Building

On an Apple silicon Mac with python.org CPython 3.12 (needed by the build machine only):

```
bash scripts/build_mac.sh            # → dist/PhotoSelect.app, dist/PhotoSelect-AppleSilicon.dmg
```

The script installs exact pinned wheels for macOS 11+ arm64 (`requirements-mac.txt`,
`requirements-build.txt`) and runs the unit tests. It then builds with PyInstaller
(`packaging/PhotoSelect.spec`), thins all binaries to arm64, and checks that no binary links
outside the bundle or OS. It sets `LSMinimumSystemVersion` from the highest minimum OS version
found in the bundled binaries, ad-hoc signs and verifies the app, and creates the DMG with an
Applications shortcut.

To sign with the hardened runtime, set `CODESIGN_IDENTITY="Developer ID Application: …"`. To
also notarise and staple, set `NOTARY_PROFILE=<notarytool keychain profile>`.

`.github/workflows/build-mac.yml` builds the DMG on a GitHub Apple-silicon runner. It then
installs that DMG on separate clean macOS 14 and 15 runners and runs
`scripts/acceptance_mac.py` against the installed app (see the validation report).

Development from source on any OS: `pip install -r requirements.txt && python app.py`, which
opens the interface in your browser. Unit tests: `cd tests && python -m unittest`. The DNG
tests need the `pidng` package.
