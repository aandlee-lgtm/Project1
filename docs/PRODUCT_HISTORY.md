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

### 1.4.0: Z50 II HE NEF, Sony A7 / A9, Lightroom Import with chosen groups
Built when the owner sent **build_new** after items 8–12 were discussed (below). "Shipped in 1.4.0"
at the end lists what was built.
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

9. **Sony A7 and A9 series.** The owner wants PhotoSelect to work for every Sony A7 and A9 body, though
   they have no sample file yet.
   - Current state: .ARW files are accepted and passed to LibRaw 0.22.1, but no Sony file has been
     tested.
   - Planned:
     - verify every A7/A9 body and RAW mode (uncompressed, compressed, lossless compressed) using the
       public raw.pixls.us samples, in the macOS acceptance run;
     - update the decoder or fall back to the camera preview where needed (Sony's embedded JPEG is often
       small, about 1616 × 1080);
     - check burst timing;
     - add a Sony ARW format filter;
     - report models without a sample as NOT TESTED.

10. **"Send to Lightroom does not seem to do anything"; where and how to install the plug-in.**
    - Explained:
      - Send to Lightroom only saves the selections file, and confirms it with one line of text under the
        progress bar. The stars appear in Lightroom only after the plug-in's command is run there.
      - Install with PhotoSelect **Help → Install Lightroom Plug-in…**. It copies `PhotoSelect.lrplugin` to
        `~/Library/Application Support/Adobe/Lightroom/Modules/`, which Lightroom Classic loads
        automatically when it starts.
      - To install by hand: Lightroom **File → Plug-in Manager… → Add**, then choose that
        `PhotoSelect.lrplugin` folder.
      - Then restart Lightroom, import, and run Library → Plug-in Extras → Apply PhotoSelect Selections….
    - Planned (backlog 10): a confirmation dialog with plug-in status, an Install button and the next steps.
    - The owner could not find `PhotoSelect.lrplugin` on their Mac. ~/Library is hidden in Finder, and
      the folder may not exist if Help → Install Lightroom Plug-in… was never run. They were sent the
      plug-in as `PhotoSelect-Lightroom-plugin.zip` (identical to the one in 1.3.0) to unzip and add
      through Lightroom's Plug-in Manager. Backlog 10 now also covers a release .zip and a Show in
      Finder action.

11. **First real Lightroom run: "0 of 1 photos match … (27 photos available)".** The owner asked whether
    something must be done in PhotoSelect first.
    - Explained: no. Send to Lightroom had worked, because the plug-in found 27 photos' selections. But
      Lightroom passed the command only one photo, the one selected in the grid, and its name and capture
      time did not match any of the 27. The next step is to select all imported photos (⌘A) and run it
      again. If they still don't match, check whether the import renamed the files or used Copy as DNG.
    - Planned (backlog 11): explain the selection in the summary, list unmatched names, match DNG copies,
      and tolerate time-zone offsets.
    - Cause found: Lightroom's "Previous Import" was an earlier day's photos, not the 27 analysed. The 27
      had not been imported into Lightroom yet. Next step: import them, then run the command on the new
      import.
    - Proposed: the plug-in could also add the analysed photos to the catalog itself, in place, and apply
      the stars in the same step (Lightroom's SDK supports adding photos).

12. **Open Lightroom's Import page with only chosen star levels.** The owner asked for Send to Lightroom
    to launch Lightroom (if not open), go to the Import page, and import only selected groups, e.g. only
    3★ (Keep), 2★ (Consider) or 1★ (Drop).
    - Decided: PhotoSelect shows a dialog with a checkbox for each group, with counts. It then opens
      Lightroom Classic with only those files. macOS hands them to Lightroom the same way as dragging
      files onto its icon, which opens Lightroom's Import window with exactly those photos.
    - The user still confirms the import (Add or Copy) in Lightroom. Applying the stars stays one click
      (Apply PhotoSelect Selections), or becomes automatic if the plug-in can detect the new import.
    - Needs a real-Lightroom check on the owner's Mac.

**Shipped in 1.4.0.**
- (8) A High Efficiency NEF that LibRaw reports as a *data error* now falls back to the camera preview.
  The NEF must carry the HE codec marker; other data errors are still reported as damage. The owner's
  DSC_1312.NEF (Z50 II) is analysed from its 5568 × 3712 camera JPEG. The macOS tests also fetch other
  HE samples, such as a Z50 II one, when the archive has them.
- (9) Sony ARW: a *Sony ARW* format filter and Sony mentioned in the app and README.
  - Coverage result: all 21 A7 / A9 bodies (58 public sample files) decode as RAW, except the A7 V's new
    "compressed" mode.
  - The bundled LibRaw 0.22.1 cannot open that mode, and no newer rawpy exists. PhotoSelect now
    analyses any genuine camera file that LibRaw cannot open from the camera's own full-size JPEG,
    found inside the file and labelled CAMERA PREVIEW.
- Release note: v1.4.0 was first published by mistake with the 1.3.0 DMG, because the first 1.4.0
  commit touched the release workflow. Within minutes it was replaced by the tested 1.4.0 DMG (run
  37922521013). The release workflow now only publishes a DMG built from the same version.
  - The Lightroom hand-off test showed that macOS records a "last opened" date attribute on files
    handed to an app. Content and dates are unchanged; this is documented as expected.
  - A CI job decodes every A7 / A9 sample on raw.pixls.us with the bundled LibRaw. It reports, per body
    and mode, the result, the embedded JPEG size and sub-second capture times; bodies without a sample
    are NOT TESTED.
  - Two Sony samples are also tested end to end in the installed app.
- (10, 12) **Send to Lightroom…** opens a window with:
  - the plug-in status, with Install / Reinstall and Show plug-in in Finder;
  - ★ group checkboxes with counts (Keep and Liked ticked by default);
  - **Open in Lightroom Import**, which hands only the chosen photos to Lightroom Classic so its Import
    window opens with them;
  - automatic star rating after the import, done by the plug-in's background task (needs one
    Lightroom restart after installing);
  - **Only save selections**.

  Help also has **Show Lightroom Plug-in in Finder**, and each GitHub Release has
  `PhotoSelect-Lightroom-plugin.zip`.
- (11) The plug-in checks every photo shown when at most one is selected, and says which photos it
  checked. It matches Copy as DNG imports and capture times that are whole hours apart. Its summary
  lists unmatched names and the range of PhotoSelect names, with a hint to import that folder first.

### 1.5.0: stars applied automatically after any import; faster, lighter analysis
Built when the owner sent **build_new** after items 13 and 14 were discussed (below).
13. **Automate star rating after import.** The owner still has to import and then run the plug-in
    command before stars appear.
    - Explained: 1.4.0 rates automatically only after **Open in Lightroom Import**, with the automatic
      option ticked, and only once the 1.4 plug-in is running. If the 1.3 copy added by hand is still
      in the Plug-in Manager, or Lightroom was not restarted after installing, only the manual command
      works. Imports started in Lightroom itself are never rated automatically in 1.4.0.
    - Planned (backlog 13):
      - rate automatically after any import of photos that have PhotoSelect selections;
      - the plug-in reports that it is running and its version, and PhotoSelect shows this;
      - a confirmation in Lightroom after rating.
14. **Optimise for speed and low resource use.** The owner wants the app as resource-efficient as possible,
    since its purpose is to cut the time spent culling and inspecting large numbers of shots.
    - Baseline from the 1.4.0 test run: 250 × 24 MP RAW at 0.43–0.49 files/s with one worker on a 7 GB
      virtual Mac (about 9 minutes), and 1.1–1.5 GB peak memory.
    - Planned (backlog 14):
      - decode RAW only at the size the scores need, keeping scores equivalent;
      - analyse burst by burst so complete bursts are ready early;
      - lower memory per worker, allowing more workers, at low priority;
      - prefetched full-resolution renders for instant ← → and 100% zoom;
      - a faster grid;
      - before / after measurements in the validation and diagnostic reports.

**Shipped in 1.5.0.**
- (13) Plug-in 1.5 rates matching photos by itself once they are in the catalog. It looks them up by
  capture date about every 30 s, so any import works (Add, Copy, renamed, DNG):
  - for selections sent in the last 14 days with automatic rating ticked;
  - every few seconds for photos handed over with Open in Lightroom Import.

  Each photo is rated once (applied.txt), existing stars are kept, and Lightroom shows a "stars
  applied" message. The plug-in writes plugin-status.txt, and PhotoSelect's Lightroom window shows:
  running, version, last rated, waiting, or warnings for an older plug-in or a needed restart.
- (14) Performance, measured on an Apple silicon test Mac with 13 cameras:
  - analysis decodes at the size the scores need (half size for 33 MP+, fast demosaic below): 2.86×
    faster decode + analysis, peak memory per photo 806 → 617 MB, rankings unchanged (rank
    correlation 0.995). Decoding half size for every photo was rejected: it changed focus rankings
    (0.77);
  - the analysis preview is made without copying the full image (about 1.8× faster);
  - one lazy EXIF read instead of two 4 MB reads per photo;
  - up to 6 workers at background (utility) priority;
  - analysis in capture-time order, so bursts finish together;
  - full-resolution renders prefetched and cached on disk (1.5 GB);
  - ← → inside the inspector;
  - slider redraws batched;
  - new timings in the diagnostic report and the acceptance tests.

### 1.6.0: top bar, review passes in Lightroom, Lightroom changes flow back
Built when the owner sent **build_new** after items 15–19 were discussed (below; 16 was withdrawn).
15. **Main actions in a persistent top bar.** The owner wants Send to Lightroom placed near the top, and
    asked for the title bar to stay visible while scrolling, holding Choose folder, Analyse photos and
    Send to Lightroom.
    - Planned (backlog 15): a sticky top bar with the brand, the folder (shortened), Choose folder,
      Analyse / Cancel, Send to Lightroom…, a thin progress bar and a one-line status. The toolbar keeps
      the filters and Export.
16. **Guided review passes.** After using the app, the owner described their workflow: send 1★ to
    Lightroom and rescue any that deserve 3★; then send 3★ and demote any to 1★; then send 2★ and
    promote any to 3★. That is three round trips between the apps.
    - Explained: until a new version, everything can be sent once and reviewed by star level in
      Lightroom with the Library filter bar (Attribute → stars), or with Smart Collections on the
      PhotoSelect keywords.
    - Planned (backlog 16): a Review mode in PhotoSelect with Rescue (Drop, most promising first),
      Confirm (Keep, weakest first) and Decide (Consider, best first) passes. Keys 3 / 2 / 1 match
      Lightroom's stars and advance automatically. Progress is shown and remembered, and everything
      is sent to Lightroom once at the end.
    - **Withdrawn the same day.** The owner pointed out that final decisions depend on editing in
      Lightroom (e.g. lifting shadows to recover detail), which PhotoSelect's viewer cannot do, and
      prefers PhotoSelect clean and simple. Agreed: PhotoSelect does the fast first pass and the
      hand-off, and Lightroom is where final calls are made. Replaced by item 18.
17. **Lightroom changes flow back.** Star changes made in Lightroom on PhotoSelect-rated photos update
    PhotoSelect's decisions, are not undone by the next send, and count as decisions for learning.
18. **Review passes in Lightroom.** The plug-in creates Smart Collections for the owner's passes: 1 Rescue
    (1★), 2 Confirm (3★), 3 Decide (2★) and Liked (5★). Photos close to a threshold get a Borderline
    keyword. Nothing is added to PhotoSelect, and all groups are sent once.
19. **Title bar label.** The owner likes the version shown at the top of the app, but asked to remove
    "LOCAL PROCESSING" and "ORIGINALS UNTOUCHED" there. Those facts stay in Help → About and the docs.

**Shipped in 1.6.0.**
- (15) A top bar that stays in place while scrolling: PhotoSelect, the folder (full path on hover;
  the end of the path stays visible), Subfolders, **Choose folder**, **Analyse photos** (**Cancel** while
  analysing), **Send to Lightroom…**, the one-line status, messages and the progress line. Filters and
  Export stay in the toolbar. On a narrow window the bar wraps.
- (17) Star changes made in Lightroom come back:
  - the plug-in remembers the stars each photo had after PhotoSelect rated it (tracked.txt, for 90
    days) and checks about every 16 s for changes, writing them to lightroom-changes.tsv;
  - PhotoSelect reads them every 15 s and when its window comes to the front, and sets the decision:
    5★ Liked (and Keep), 3★ or 4★ Keep, 2★ Consider, 1★ Drop; removing the stars (0★) changes nothing;
  - the message line shows a summary, e.g. "From Lightroom: 6 Drop → Keep, 2 Keep → Drop";
  - they become your own decisions, so they count for **Learn from my decisions**, and the next
    Send to Lightroom carries them (PhotoSelect reads the changes first) instead of undoing them.
- (18) The plug-in creates a **PhotoSelect** collection set with Smart Collections **1 Rescue** (1★),
  **2 Confirm** (3★), **3 Decide** (2★), **Liked** (5★) and **Borderline**. Each holds photos PhotoSelect
  rated (keyword *From PhotoSelect*) that now have those stars, so a photo moves between them as you
  change its stars. Photos without your own decision whose score is within 5 points of the Keep or
  Consider threshold get the keyword *PhotoSelect › Borderline*. Nothing was added to PhotoSelect
  except one line in the Lightroom window's steps.
- (19) The title bar shows only the version, e.g. "v1.6.0".

### 1.7.0: step numbers on the main actions
Built when the owner sent **build_new** after item 20 was discussed (below).
20. **Step numbers on the main actions.** The owner asked for a larger, light-grey **1**, **2** and **3**
    on Choose folder, Analyse photos and Send to Lightroom…, to show them as steps.
    - Planned (backlog 20): a quiet light-grey number before each button label, larger than the label
      text. Cancel keeps step 2's place while analysing. Screen readers hear "Step 1: Choose folder"
      and so on. The numbers stay with their buttons when the bar wraps.
    - The owner left the size and colour to our discretion, for cohesion. Decided:
      - about 1.5× the label size, semi-bold;
      - the app's light grey (the muted text colour) on the dark buttons;
      - on the teal Analyse photos button, its own dark text colour at reduced opacity, because grey
        would wash out on teal;
      - one baseline with the label, and no change to the bar's height.

**Shipped in 1.7.0.**
- (20) Choose folder, Analyse photos and Send to Lightroom… show **1**, **2** and **3** before their
  labels:
  - 1.5× the label size, semi-bold, in the muted grey (#9eabb4);
  - on the teal Analyse photos button, the number uses the button's dark text colour, faded;
  - the top bar's height is unchanged;
  - screen readers hear "Step 1: Choose folder", and so on.
- The Lightroom plug-in is unchanged (still 1.6.0), so no reinstall is needed.

### 1.8.0: stars added automatically after any import (fix)
Built when the owner sent **build_new** after item 22 was reported (below). Item 21 (XMP sidecars) is
still waiting for the owner's decision.
21. **Why a plug-in? Can it be bypassed?** The owner asked why the plug-in is needed and whether the
    step can be skipped.
    - Explained:
      - Lightroom Classic keeps stars, keywords and collections in its catalog, a database that only
        Lightroom itself (and plug-ins running inside it) may change while it is open. Adobe offers no
        other way in: writing the catalog from outside risks corrupting it.
      - The plug-in is a one-time install. Since 1.5 it works by itself in the background: it rates
        photos after any import, creates the PhotoSelect Smart Collections, and sends star changes
        back to PhotoSelect.
    - The only route without the plug-in is **XMP sidecar files**: small `.xmp` files next to each RAW
      file (e.g. `DSC_1234.xmp`) holding the stars and keywords. Lightroom reads them when it imports
      the RAW files, so the stars appear with no plug-in. Limits:
      - they only take effect at the first import, not for photos already in Lightroom;
      - they work for RAW files, not JPEG, HEIC or DNG (Lightroom reads those files' own metadata,
        and PhotoSelect never changes your files);
      - they add files to the photo folders or card (the originals are untouched);
      - no Smart Collections are made automatically, and no star changes come back to PhotoSelect;
      - existing sidecars (from another app) would have to be merged.
    - This was the trade-off considered for 1.3, when the owner chose the plug-in.
    - Offered: an optional "Write XMP sidecars (no plug-in)" choice in the Send to Lightroom window,
      next to the plug-in. Waiting for the owner's decision.
22. **Stars still need the manual command after import.** The owner reports that even with 1.7.0 they
    import, then run the plug-in command before the stars appear.
    - Found: automatic rating after an ordinary import depends on a catalog search by capture date,
      which runs in the plug-in's background task. That search is wrapped in Lua's plain `pcall`.
      Lightroom pauses the task during catalog searches, and plain `pcall` cannot handle the pause, so
      the search failed every time without any message. Only photos handed over with Open in
      Lightroom Import and imported with Add (found by file path, without a search) could be rated
      automatically. The tests used a simulated catalog that never paused, so they passed.
    - Planned (backlog 22): the fix, a file-name fallback search, visible plug-in errors in PhotoSelect's
      Lightroom window, and tests that simulate Lightroom's pauses.
    - Until then: Open in Lightroom Import with **Add** in Lightroom's Import window rates automatically;
      otherwise use the menu command.

**Shipped in 1.8.0.**
- (22) Plug-in 1.8.0:
  - the catalog search runs under `LrTasks.pcall`, so photos imported in any way are found and rated
    within about 30 s;
  - if the capture-date search finds nothing or fails, the plug-in searches by file name;
  - it reports its last search and last error, and PhotoSelect's Lightroom window shows them,
    e.g. "Last search in Lightroom: capture date 2026-05-01 to 2026-05-01: 27 photos";
  - the plug-in tests now run each step as a Lightroom background task whose catalog calls pause, as
    in Lightroom. With the old code, four tests fail.
- Update once: Send to Lightroom… → Reinstall plug-in, then restart Lightroom (PhotoSelect warns while
  the older plug-in is running).

### 1.9.0: best of each series
Built when the owner sent **build_new** after item 23 was discussed (below).
23. **Too many frames kept from a series of similar photos.** The owner tested with many similar photos:
    PhotoSelect did not keep just the best of each series, but suggested Keep for quite a few.
    - Explained: until now each frame's suggestion depended only on its own score against the Keep and
      Consider thresholds. That was a deliberate rule from 1.2 ("a frame is never suggested Drop just
      for not winning its burst"): the burst rank was shown, but did not change the suggestion. So in
      a series of good, similar frames, all of them could be Keep.
    - Planned (backlog 23): a **Best of each series** setting (default: keep 1). The rest of the
      series is suggested Drop, except frames within 3 points of the best, which are suggested
      Consider. Your own decisions still win.
    - Asked: were the similar frames grouped into one series (a "BURST n · TOP OF k" badge, sorted by
      Burst order), and how far apart were they shot? If they were not grouped, the grouping also needs
      widening for similar shots taken further apart.
    - The owner confirmed the frames were grouped into one series: the change needed is to pick the
      best of that series. Grouping stays unchanged; backlog 23 covers the selection only.

**Shipped in 1.9.0.**
- (23) **Best of each series**, a new setting under Recommendation thresholds:
  - Keep the best frame (default), the best 2, the best 3, or all that reach Keep;
  - in each burst or near-identical series, only those frames can be suggested Keep;
  - other frames within 3 points of the best are suggested Consider (compare them), and the rest of
    the series is suggested Drop;
  - the reason line says why, e.g. "Drop: #4 of 9 in this series, 12.0 points below the best frame
    (weighted score 78.1 would be Keep on its own)";
  - your own decisions still win;
  - the setting is saved with profiles and folder settings, and Learn from my decisions also
    proposes it;
  - Lightroom stars, keywords and Smart Collections follow the new suggestions.
- Plug-in unchanged (1.8.0): no reinstall needed.

---

## 2. Definitions (draft glossary for the user instructions)

| Term | Meaning |
|---|---|
| **Photos analysed** | Files in the chosen folder that were decoded and scored. Clicking this tile shows all photos. |
| **Keep (suggestion)** | Combined score at or above the Keep threshold (default 75). A suggestion only. |
| **Consider (suggestion)** | Combined score between the Consider threshold (default 45) and the Keep threshold. Worth a look. |
| **Drop (suggestion)** | Combined score below the Consider threshold, or (since 1.9) a frame of a series that lost to a better frame by more than 3 points (see Best of each series). Called "Skip" before 1.2.0. Nothing is ever deleted or moved. |
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
| **Best of each series** | How many frames of each burst or near-identical series are suggested Keep (default 1). The others are suggested Drop, or Consider when within 3 points of the best. |
| **Likeness %** | How alike two frames look, from 0 % (unrelated) to 100 % (identical). It compares a 16 × 12 grey-level version of each frame and its average colour. |
| **Similarity ≥ %** | The minimum likeness for a frame to continue a burst (default 70 %). Replaces 1.2's "similarity tolerance"; the old default 14 equals 70 %. |
| **Near-identical** | Frames at least the near-identical % alike (default 90 %) that are grouped even when shot up to the near-identical window apart (default 10 s), with other frames in between. Marked with a NEAR-IDENTICAL badge. |
| **Burst average likeness** | The average likeness of a burst's frames to its top frame. Shown in the burst comparison title, the CSV and the diagnostic report. |
| **Learn from my decisions** | Proposes the slider weights and thresholds whose suggestions best match the photos you marked (at least 30; ♥ liked counts as Keep). Applied only when you click Apply, and can be undone. |
| **Settings profile** | A named set of slider weights and Keep / Consider thresholds (e.g. Sailing), saved on this Mac. |
| **Folder settings** | Settings remembered for one folder and used automatically whenever that folder is analysed. |
| **Send to Lightroom…** | Opens the Lightroom window: the plug-in status, the star groups to import, **Open in Lightroom Import** and **Only save selections**. Selections are saved in ~/Library/Application Support/PhotoSelect/Lightroom (never in the photo folders). |
| **Open in Lightroom Import** | Starts Lightroom Classic and opens its Import window with only the photos in the ticked star groups; you choose Add or Copy and click Import. |
| **Automatic star rating** | The plug-in adds the stars and keywords by itself a few seconds after photos with PhotoSelect selections are in the catalog, however they were imported (within 14 days of Send to Lightroom; 3 hours for Open in Lightroom Import). Each photo is rated once; stars already set in Lightroom are kept. |
| **Borderline** | A PhotoSelect keyword in Lightroom for photos without your own decision whose score is within 5 points of the Keep or Consider threshold: the close calls worth a second look. Also a Smart Collection. |
| **Top bar** | The bar at the top of PhotoSelect that stays visible while scrolling: folder, Choose folder, Analyse photos / Cancel, Send to Lightroom…, status and progress. |
| **Steps 1–2–3** | The numbered main actions in the top bar: 1 Choose folder, 2 Analyse photos, 3 Send to Lightroom…. |
| **PhotoSelect collection set** | Smart Collections the plug-in makes in Lightroom for the review passes: 1 Rescue (1★), 2 Confirm (3★), 3 Decide (2★), Liked (5★) and Borderline. They hold only photos PhotoSelect rated, and update as stars change. |
| **From Lightroom** | Star changes you make in Lightroom on photos PhotoSelect rated update PhotoSelect's decisions (5★ Liked, 3★/4★ Keep, 2★ Consider, 1★ Drop) and count for Learn from my decisions. Shown as e.g. "From Lightroom: 6 Drop → Keep". |
| **Plug-in status** | The top line of PhotoSelect's Lightroom window: whether the plug-in is running in Lightroom, its version, and when it last rated photos. |
| **Analysis decode** | How PhotoSelect decodes RAW for scoring: half size for 33 MP+ photos, a fast demosaic for smaller ones. Inspection always uses the full-quality decode. |
| **Sony ARW** | Sony's RAW format; A7 and A9 bodies are checked against the public sample archive in every build. |
| **Apply PhotoSelect Selections** | The Lightroom Classic command (Library → Plug-in Extras) that applies the stars and keywords after import, showing a summary first. |
| **CAMERA PREVIEW** | The photo was analysed from the JPEG the camera stored inside the RAW file, because the RAW pixels could not be decoded (e.g. Nikon High Efficiency NEF). Its scores include the camera's own sharpening and noise reduction. |
| **High Efficiency NEF (HE / HE★)** | A Nikon RAW compression (seen on the Z6III and Z50 II) that LibRaw cannot decode. To get full RAW analysis, shoot with NEF (RAW) compression set to Lossless compressed. |
| **Could not be analysed** | A file that was listed but not scored, with a specific reason (damaged, empty, unreadable or unsupported). |
| **Diagnostic report** | Help → Create Diagnostic Report…: a text file for troubleshooting, with no images and no full paths. |
| **Lightroom stars** | How PhotoSelect results appear in Lightroom Classic: Keep 3★, Consider 2★, Drop 1★, Liked 5★. Your decision wins over the suggestion. |
| **PhotoSelect keywords** | Keywords added in Lightroom under PhotoSelect › (Keep, Consider, Drop, Liked, Burst NNN, Near-identical, Camera preview, Borderline, From PhotoSelect) for Smart Collections. They are not included when exporting images. |
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
