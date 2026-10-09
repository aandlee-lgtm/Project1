# PhotoSelect: product history, decisions and definitions

This is a running record of the owner's discussions about PhotoSelect: what was asked for, what was
explained and decided, and what shipped in each version. It is the source material for the user
instructions, the definitions (glossary) and the release notes. Entries are added as the
conversation happens, newest version at the bottom of each section.

Related files: open feature requests are in [BACKLOG.md](BACKLOG.md), published release notes in
[RELEASES.md](RELEASES.md), and test results in [../VALIDATION_REPORT.md](../VALIDATION_REPORT.md).

---

## 1. Version history and the discussions behind each version

### Starting point: PhotoSelect 0.3 / 0.3.1 (Python prototype, supplied by the owner)
- A Python program run from Terminal. It culls bursts of sailing and sports photos by scoring them.
- 0.3.1 already fell back to the camera's embedded JPEG when RAW pixels could not be decoded.

### 1.0.0: first standalone Mac app
**Asked for.** The prototype turned into a normal Apple silicon Mac app in a .dmg:
- no Python, Terminal or Homebrew needed; works offline; photos never leave the Mac;
- original photos are only read, never changed, moved or deleted;
- reads Nikon NEF/NRW and Olympus/OM System ORF RAW, plus JPEG, PNG and TIFF;
- the full culling workflow, plus an installation guide and an honest test report.

**Decided.**
- The app is a native Mac window showing a local page. A private server inside the app is reachable
  only from the Mac itself, and only with a per-launch password (session token).
- RAW decoding uses LibRaw (via rawpy), bundled inside the app.
- Scores are relative to the folder being reviewed, and every suggestion lists its reasons.
  The weaknesses of each score are stated openly.
- Settings, decisions and results are saved in the standard macOS locations under ~/Library.
- The app is signed ad hoc, not notarised by Apple, so the first launch needs **Open Anyway** in
  System Settings.

**Shipped.**
- Folder chooser; grid; importance sliders; Keep / Consider thresholds.
- Manual decisions and likes; burst grouping and burst comparison; 100% crops.
- Full-resolution inspector; drawn focus region; CSV export.
- Cancel and resume; cache; About, log folder and third-party notices.

### 1.0.1: testing on the owner's own Mac
**Asked for.** "Can I test these locally?" Uploading bursts of RAW files would take too long, so the
owner asked for step-by-step test cases with fields to enter results.

**Decided and shipped.**
- **Help → Create Diagnostic Report…** saves a plain-text report: timings, cameras and formats,
  decode results, failures grouped by reason, bursts and settings. It contains no image data and no
  full paths.
- A field test sheet (docs/field-tests.html) to record results.

### 1.0.2: Nikon Z6III files that would not open
**Reported.** 41 photos from the owner's Nikon Z6III "could not be analysed" (example: DSC_2094.NEF).

**Found.**
- The files are **High Efficiency (HE / HE★) NEF**. They use a licensed compression (intoPIX TicoRAW)
  that LibRaw cannot decode.
- Lossless-compressed Z6III NEFs decode normally.
- Apple's own RAW engine in macOS 15.7 does not list the Z6III either.

**Shipped.** The error now names High Efficiency NEF and the camera setting that avoids it:
NEF (RAW) compression → **Lossless compressed**.

### 1.1.0: camera preview fallback
**Discussed.**
- The owner pointed out that the Python version did analyse these files. It used the camera's
  embedded JPEG when the RAW pixels couldn't be decoded, and the owner supplied the 0.3.1 source.
- Initially the owner said not to add a fallback. They then asked to regenerate the app from the
  0.3.1 source *with* the fallback.

**Decided.**
- For RAW files that open but can't be decoded, PhotoSelect analyses the full-size JPEG the camera
  stores inside the file. Nikon stores 6048 × 4032 on the Z6III.
- Such photos are clearly labelled **CAMERA PREVIEW** everywhere. Their scores include the camera's
  sharpening and noise reduction, so they are not measurements of the RAW pixels.
- Damaged or non-RAW files never fall back. Previews smaller than 1,000 px on the long edge are not
  used.

**Shipped.** The fallback; the CAMERA PREVIEW labels; the correct photo count as soon as a scan
finishes.

### 1.2.0: bucket filters and "Drop"
**Discussed.**
- The owner asked what **"Skip suggestion"** meant. It is the app's suggestion that a frame is the
  weakest by the current weights and thresholds: its combined score fell below the Consider threshold.
- It is only a suggestion. Nothing is deleted or moved, and the owner's own decision always wins.

**Asked for.**
- Clicking a summary tile (Keep, Consider, Skip) should show only that group's photos in the grid,
  for every tile.
- Rename Skip suggestion to **Drop**, in an orange colour palette.

**Shipped.**
- The Keep / Consider / Drop tiles filter the grid. Click the tile again, or Photos analysed, to show
  all photos.
- "Skip" renamed **Drop** everywhere, in orange. Old Skip decisions convert automatically.
- New viewer shortcut: D.

**Working rule agreed.**
- From here on, all feedback is recorded as a feature request in BACKLOG.md.
- No new version is built until the owner's message includes **build_new**.

### 1.3.0: likeness bursts, learning, profiles, Lightroom Classic
Built when the owner sent **build_new** on 2026-10-09. The seven backlog items below were requested
and discussed first, then shipped together. Each item says what was decided and, under "Shipped in
1.3.0", what was built.

1. **Bursts by % likeness.** The owner asked for bursts to mean more than timing: frames should also
   be a % alike.
   - Today the app already compares a tiny greyscale fingerprint and average colour, but it never
     shows a %.
   - Decided: a "Similarity ≥ N %" slider, likeness shown in the burst view and viewer, and average
     likeness in the CSV and diagnostic report.
2. **Near-identical shots a few seconds apart.** The owner wants these seen together too.
   - Decided: frames at least about 90 % alike and within about 10 s are grouped. Both values are
     adjustable, and these frames are marked "near-identical".
3. **Status line without "LibRaw 0.22.1".** The owner liked the key data in the status line but not
   the decoder version.
   - The version stays in Help → About and the diagnostic report.
4. **Brighter teal accent.** The current accent (#ade1c5) reads as light teal, almost lime green.
   - Decided: make it a tad brighter while staying in the teal family, with readable text.
5. **Learn from my decisions.** The owner asked whether the app learns what they keep and drop.
   - Answer: not yet. Suggestions are fixed rules (scores × the owner's weights, then the
     thresholds), and decisions are saved but never fed back into scoring.
   - Decided: after about 30 or more hand-marked photos, propose weights and thresholds that match
     the owner's decisions. The proposal shows the reason and how many past decisions it matches.
   - It is applied only on approval, can be undone, and can be saved per folder or as a named
     profile. Everything stays on the Mac.

6. **Selections into Adobe Lightroom Classic.** The owner wants PhotoSelect's selections and
   recommendations in Lightroom Classic.
   - Explained: Lightroom keeps Pick/Reject flags only in its catalog, never in files. Sending them
     needs a Lightroom plug-in. XMP sidecar files can carry stars, labels and keywords, but they write
     into the photo folders, and re-reading them into photos already in Lightroom can disturb edits.
   - Owner chose:
     - cull **before import**;
     - a **Lightroom plug-in**, not XMP sidecars;
     - **star ratings**: Keep 3★, Consider 2★, Drop 1★, ♥ Like 5★, plus PhotoSelect keywords.
   - Decided:
     - PhotoSelect saves a selections file outside the photo folders. After import, Library →
       Plug-in Extras → Apply PhotoSelect Selections applies it. Lightroom has no import hook, so this
       one step is needed.
     - Photos are matched by file name and capture time, so files Lightroom copied or renamed still
       match.
     - A summary is shown first, and existing Lightroom stars are not overwritten unless asked.
     - The plug-in is installed from Help → Install Lightroom Plug-in….

7. **Shorter cards for camera-preview photos.** Looking at the grid, the owner asked to remove the sentence
   "Scored from the embedded camera JPEG (camera sharpening and noise reduction included), not the RAW pixels."
   from the photo cards, to save space.
   - Decided: the card shows its normal reason line instead.
   - The CAMERA PREVIEW badge stays, so it is still clear which photos were scored from the camera JPEG.
   - The full explanation stays in the viewer, the CSV and the diagnostic report.

**Shipped in 1.3.0.**
- Bursts are grouped by capture time **and % likeness**. There is a *Similarity ≥ %* slider (default
  70 %, equal to 1.2's default), plus *Near-identical ≥ %* (default 90 %) and a *near-identical window*
  (default 10 s, 0 = off). Likeness is shown:
  - in the viewer ("Looks 93 % like the burst's top frame");
  - in the burst comparison ("93 % alike #1" and the burst average);
  - in the CSV (`likeness_to_burst_top_pct`, `burst_average_likeness_pct`, `near_identical`);
  - in the diagnostic report.
- The status line no longer shows the LibRaw version.
- The accent is now a brighter teal (#4fe0c8, was #ade1c5) on buttons, sliders, badges, bars and the
  app icon.
- *Learn from my decisions*:
  - a proposal with "Matches X of your Y decisions (current settings match Z)", the weight and
    threshold changes, and a "why" line;
  - Apply and Undo;
  - named profiles, and settings remembered per folder.
- Lightroom Classic:
  - **Send to Lightroom** saves the selections;
  - **Help → Install Lightroom Plug-in…** installs the plug-in, and **Library → Plug-in Extras →
    Apply PhotoSelect Selections…** applies the stars and keywords after a summary;
  - matching is by file, then name and capture time, then a unique name, then a unique capture time
    and file type;
  - existing Lightroom stars are kept unless *Replace* is ticked.
- Photo cards for camera-preview photos show the normal reason line. The CAMERA PREVIEW badge stays.

### After 1.3.0 (planned for the next version: waiting for build_new)
8. **Z50 II High Efficiency NEF reported as damaged.** The owner sent DSC_1312.NEF, which 1.3.0 listed
   as "Nikon NEF: the RAW data is damaged or truncated (Data error or unsupported file format)".
   - Found: the file is not damaged.
     - It is a **Nikon Z50 II High Efficiency NEF**: it contains the intoPIX TicoRAW marker, taken
       2026-07-15.
     - LibRaw starts decoding the HE data and stops with a *data error*. For Z6III HE files it reports
       *unsupported* instead, and only that error triggered the camera-preview fallback added in 1.1.0.
     - The file holds a full-size camera JPEG (5568 × 3712), so it can be analysed as CAMERA PREVIEW
       like the Z6III files.
   - Decided: on a NEF with the High Efficiency marker, treat a data error the same as an unsupported
     error and use the camera preview. Files without the marker that fail with a data error are still
     reported as damaged and never fall back.

---

## 2. Definitions (draft glossary for the user instructions)

| Term | Meaning |
|---|---|
| **Photos analysed** | Files in the chosen folder that were decoded and scored. Clicking this tile shows all photos. |
| **Keep (suggestion)** | Combined score at or above the Keep threshold (default 75). A suggestion only. |
| **Consider (suggestion)** | Combined score between the Consider threshold (default 45) and the Keep threshold. Worth a look. |
| **Drop (suggestion)** | Combined score below the Consider threshold: the weakest frames by your current settings. Called "Skip" before 1.2.0. Nothing is ever deleted or moved. A frame is never suggested Drop just for not winning its burst. |
| **Decision** | Your own Keep / Consider / Drop choice for a photo. It overrides the suggestion and is saved automatically. |
| **Like (♥)** | Your shortlist marker, independent of decisions. Use **Compare liked photos** to review them side by side. |
| **Score** | 0–100, relative to the current folder (the folder's 10th–90th percentile maps to 15–95). It is not an absolute quality rating: even a folder of soft photos has a top frame. |
| **Sharpness** | Edge detail across the whole frame, divided by contrast. Water, foliage and noise also count as detail. |
| **Subject focus** | Edge detail inside the focus region, measured on the full-resolution image, with expected sensor noise subtracted. |
| **Focus region** | The area where subject focus is measured: the central half by default, or a rectangle you drag over the subject. It is remembered per photo. |
| **Composition** | A heuristic: where the detail sits relative to rule-of-thirds points, minus clutter at the edges. Not an aesthetic judgement. |
| **Exposure** | The share of pixels not clipped to near-black or near-white. |
| **Weights (importance sliders)** | How much each of the four scores counts towards the combined score. Defaults: sharpness 30, focus 50, composition 15, exposure 5. |
| **Thresholds** | The combined scores that separate Keep, Consider and Drop. |
| **Burst** | Frames taken close together in time (default within 2 s) that also look alike. They are compared and ranked together. From the next version, likeness is shown as a %. |
| **Close to burst top** | A frame within 3 points of its burst's best frame. Worth comparing by eye. |
| **Likeness %** | How alike two frames look, from 0 % (unrelated) to 100 % (identical). It compares a 16 × 12 grey-level version of each frame and its average colour. |
| **Similarity ≥ %** | The minimum likeness for a frame to continue a burst (default 70 %). Replaces 1.2's "similarity tolerance"; the old default 14 equals 70 %. |
| **Near-identical** | Frames at least the near-identical % alike (default 90 %) that are grouped even when shot up to the near-identical window apart (default 10 s), with other frames in between. Marked with a NEAR-IDENTICAL badge. |
| **Burst average likeness** | The average likeness of a burst's frames to its top frame. Shown in the burst comparison title, the CSV and the diagnostic report. |
| **Learn from my decisions** | Proposes the slider weights and thresholds whose suggestions best match the photos you marked (at least 30; ♥ liked counts as Keep). Applied only when you click Apply, and can be undone. |
| **Settings profile** | A named set of slider weights and Keep / Consider thresholds (e.g. Sailing), saved on this Mac. |
| **Folder settings** | Settings remembered for one folder and used automatically whenever that folder is analysed. |
| **Send to Lightroom** | Saves the current selections for the Lightroom Classic plug-in, in ~/Library/Application Support/PhotoSelect/Lightroom (never in the photo folders). |
| **Apply PhotoSelect Selections** | The Lightroom Classic command (Library → Plug-in Extras) that applies the stars and keywords after import, showing a summary first. |
| **CAMERA PREVIEW** | The photo was analysed from the JPEG the camera stored inside the RAW file, because the RAW pixels could not be decoded (e.g. Nikon High Efficiency NEF). Its scores include the camera's own sharpening and noise reduction. |
| **High Efficiency NEF (HE / HE★)** | A Nikon RAW compression (seen on the Z6III and Z50 II) that LibRaw cannot decode. To get full RAW analysis, shoot with NEF (RAW) compression set to Lossless compressed. |
| **Could not be analysed** | A file that was listed but not scored, with a specific reason (damaged, empty, unreadable or unsupported). |
| **Diagnostic report** | Help → Create Diagnostic Report…: a text file for troubleshooting, with no images and no full paths. |
| **Lightroom stars** | How PhotoSelect results appear in Lightroom Classic: Keep 3★, Consider 2★, Drop 1★, Liked 5★. Your decision wins over the suggestion. |
| **PhotoSelect keywords** | Keywords added in Lightroom under PhotoSelect › (Keep, Consider, Drop, Liked, Burst NNN, Near-identical, Camera preview) for Smart Collections. They are not included when exporting images. |
| **build_new** | The owner's keyword that authorises building and releasing a new version from the planned backlog items. First used for 1.3.0. |

---

## 3. Material for user instructions (to be expanded)

- Installing: see [../INSTALL.md](../INSTALL.md) (drag to Applications; Open Anyway on first launch).
- Everyday workflow: see "Using it" in [../README.md](../README.md):
  1. choose a folder;
  2. analyse;
  3. adjust the sliders;
  4. draw a focus region;
  5. inspect and compare;
  6. decide, then export.
- Keyboard shortcuts in the viewer:
  - ← → move between photos;
  - K Keep, C Consider, D Drop;
  - L Like;
  - F full resolution.
- Shooting tip for Nikon Z bodies: use Lossless compressed NEF so RAW pixels are analysed directly.
