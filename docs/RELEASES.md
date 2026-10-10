# PhotoSelect releases

## 1.8.0
- **Fixed: stars now appear in Lightroom by themselves after any import.** In 1.5–1.7 they only came
  automatically after Open in Lightroom Import with Add. After an ordinary import you had to run
  Library → Plug-in Extras → Apply PhotoSelect Selections….
  - Cause: the plug-in's search for newly imported photos failed every time inside Lightroom, without
    any message.
  - Now photos imported in any way (Add, Copy, renamed, as DNG) get their stars and keywords within
    about 30 s.
  - If the search by capture date finds nothing, the plug-in also searches by file name.
- **Problems are visible.** The Send to Lightroom… window shows the plug-in's last search in your
  catalog (e.g. "capture date 2026-05-01 to 2026-05-01: 27 photos"), and any problem it reported in
  the last hour.
- **Update the plug-in once:** Send to Lightroom… → Reinstall plug-in, then quit and reopen Lightroom
  Classic. Until you do, PhotoSelect reports that an older plug-in is running.
- Tested: the installed DMG passed all 113 acceptance checks on macOS 14.8 and 15.7 (run 38034081519).
  The plug-in tests now behave like Lightroom when it searches the catalog; the 1.7 plug-in fails four
  of them.

## 1.7.0
- **Numbered steps.** The three main actions in the top bar show their order: **1** Choose folder,
  **2** Analyse photos, **3** Send to Lightroom….
  - The numbers are larger than the button text, in the app's light grey. On the teal Analyse photos
    button, the number is a faded dark teal so it stays readable.
  - The top bar keeps its height, and screen readers announce each button as "Step 1: Choose folder",
    and so on.
- The Lightroom plug-in is unchanged (1.6.0): no reinstall is needed.
- Tested: the installed DMG passed all 113 acceptance checks on macOS 14.8 and 15.7 (run 38020186387).

## 1.6.0
- **Main actions always at hand.** A top bar stays in place while you scroll. It holds the folder
  (full path on hover), **Choose folder**, **Analyse photos** (**Cancel** while analysing),
  **Send to Lightroom…**, the status line and the progress line. Filters and Export stay in the
  toolbar. On a narrow window the bar wraps.
- **Review passes in Lightroom.** The plug-in adds a **PhotoSelect** collection set with Smart
  Collections:
  - **1 Rescue** (★), **2 Confirm** (★★★), **3 Decide** (★★), **Liked** (★★★★★) and **Borderline**;
  - send all groups once, then work through them in Lightroom, where you can edit before deciding;
  - a photo moves between collections as you change its stars;
  - *Borderline* (a new keyword) marks photos without your own decision whose score is within
    5 points of the Keep or Consider threshold: the close calls.
- **Your Lightroom changes come back to PhotoSelect.** Change the stars of a photo PhotoSelect rated,
  and within about 30 s PhotoSelect updates its decision:
  - 5★ Liked, 3★ or 4★ Keep, 2★ Consider, 1★ Drop; removing the stars changes nothing;
  - a summary shows what changed, e.g. "From Lightroom: 6 Drop → Keep, 2 Keep → Drop";
  - the changes count as your decisions for *Learn from my decisions*;
  - the next Send to Lightroom keeps them rather than undoing them.
- The title bar shows only the version (e.g. v1.6.0).
- Update once: Send to Lightroom… → Reinstall plug-in, then restart Lightroom Classic.
- Tested: the installed DMG passed all 111 acceptance checks on macOS 14.8 and 15.7 (run 38003122912).
  250 RAW files took 168–179 s on the test Mac (235–243 s in 1.5.0).

## 1.5.0
- **Stars appear in Lightroom by themselves.** The 1.5 plug-in rates photos once they are in your
  catalog, with no command to run.
  - This works however you import: through Open in Lightroom Import, or by importing the folder in
    Lightroom yourself (Add, Copy, renamed or as DNG), within 14 days of sending.
  - Each photo is rated once, stars you set in Lightroom are kept, and Lightroom shows "PhotoSelect:
    stars applied to N imported photos".
  - PhotoSelect's Lightroom window shows whether the plug-in is running, its version and what it
    last did. It tells you if an older plug-in is loaded or Lightroom needs a restart.
  - Update once: Send to Lightroom… → Reinstall plug-in, remove any other PhotoSelect entry in
    Lightroom's Plug-in Manager, then restart Lightroom.
- **About twice as fast.** On the test Mac, 250 RAW files took 4 minutes instead of 8–11.
  - Analysis now decodes each RAW only as large as the scores need: half size for 33 MP and larger,
    a fast demosaic for smaller files. On 13 cameras this was 2.9× faster per photo: 45–61 MP photos
    take 0.6–1.6 s instead of 2.8–4.4 s.
  - Rankings are essentially unchanged: rank correlation 0.995, scores within 2–3 points.
  - Inspection still uses the full-quality decode.
- **Lighter on your Mac:**
  - each photo needs about a quarter less memory while being analysed;
  - analysis runs at background priority, with up to 6 workers depending on your Mac (4 on an
    8 GB M2);
  - capture time and camera are read without loading 8 MB of every file, which matters on cards and
    drives.
- **Bursts sooner:** photos are analysed in capture order, so each burst completes together.
- **Instant inspection:** after you first open full resolution, the next and previous photos are
  prepared in the background. Use ← → inside the inspector to step at the same zoom. Full-size
  renders are cached on disk (up to 1.5 GB).
- The diagnostic report shows the time to the first analysed photo, CPU time per file and the
  worker count.
- Existing folders are re-analysed once with the new decode (scores change by a few points at most).
- Tested: the installed DMG passed all 105 acceptance checks on macOS 14.8 and 15.7 (run 37935799010).

## 1.4.0
- **Send to Lightroom…** now opens a window with:
  - whether the plug-in is installed, with **Install plug-in** and **Show plug-in in Finder** buttons;
  - a checkbox and count for each group: ★★★ Keep, ★★ Consider, ★ Drop, ★★★★★ ♥ Liked.
- **Open in Lightroom Import** starts Lightroom Classic and opens its own Import window with only the
  photos in the ticked groups. Choose Add or Copy there and click Import.
  - The plug-in then adds the stars and keywords automatically a few seconds after the import. This
    needs the 1.4 plug-in, and Lightroom restarted once after installing it.
  - **Only save selections** keeps the earlier route: import first, then Apply PhotoSelect Selections.
- **Lightroom plug-in 1.4:**
  - with one photo or none selected, it checks every photo shown, and says which photos it checked;
  - it matches photos imported with Copy as DNG, and capture times a whole number of hours apart
    (time zones);
  - its summary lists any photos that did not match.

  The plug-in is also attached to this release as `PhotoSelect-Lightroom-plugin.zip`. If you added
  the 1.3 plug-in yourself, remove it in Lightroom → File → Plug-in Manager, then install the new one.
- **Nikon High Efficiency NEF from the Z50 II** (and other bodies that LibRaw reports as a "data
  error") are analysed from the camera's own JPEG and labelled CAMERA PREVIEW. They are no longer
  reported as damaged.
- **Sony A7 and A9 series:** every body from the A7 to the A7 V, A7R to A7R V, A7S to A7S III, A7C,
  A7C II, A7CR, and A9 to A9 III was checked against public sample files, 58 files in total.
  - All of them decode as RAW, except the A7 V's new "compressed" mode, which the bundled LibRaw
    cannot read yet. Those files are analysed from the camera's full-size JPEG and labelled CAMERA
    PREVIEW. A7 V lossless compressed files decode as RAW.
  - There is a new **Sony ARW** option in the file-format filter.
- Help → **Show Lightroom Plug-in in Finder**.
- Tested: the installed DMG passed all acceptance checks on macOS 14.8 and 15.7 (run 37922521013).
  - The hand-off to Lightroom was tested with a stand-in app, because Lightroom cannot run on the
    test machines. The Import window and automatic stars still need a check in your Lightroom (field
    test T15).
  - Photos handed to Lightroom keep their content and dates. macOS only records a "last opened" date
    on them, as it does whenever a file is opened in any app.

## 1.3.0
- **Bursts by % likeness.** Bursts now use how alike frames look (0–100 %) as well as capture time.
  - Set *Similarity ≥ %* under Burst matching (default 70 %, the same grouping as before).
  - The viewer shows how alike each frame is to its burst's top frame. Compare this burst shows each
    frame's likeness to #1 and the burst's average likeness.
  - The CSV and diagnostic report include likeness too.
- **Near-identical shots a few seconds apart** are grouped together, even with other shots in between,
  and marked NEAR-IDENTICAL. The defaults are ≥ 90 % alike within 10 s; both can be adjusted, and a
  window of 0 turns it off.
- **Learn from my decisions.** After marking 30 or more photos, PhotoSelect suggests slider and
  threshold settings that match your choices.
  - It explains why, and shows how many of your decisions the settings match before and after.
  - Nothing changes until you click Apply, and you can undo it.
  - Settings can be saved as named profiles, or remembered for a folder.
- **Adobe Lightroom Classic.** Install the plug-in with Help → Install Lightroom Plug-in…. Cull, then
  click **Send to Lightroom**.
  - After importing, choose Library → Plug-in Extras → Apply PhotoSelect Selections….
  - Stars: Keep ★★★, Consider ★★, Drop ★, Liked ★★★★★. Keywords are added under PhotoSelect.
  - A summary is shown first, and stars you already set in Lightroom are kept unless you choose to
    replace them.
  - Nothing is written into your photo folders.
- Brighter teal accent colour.
- The status line no longer shows the decoder version (still in About and the diagnostic report).
- Photo cards for camera-preview photos are shorter. The CAMERA PREVIEW badge stays, and the full
  explanation is in the viewer.
- Tested: the installed DMG passed all acceptance checks on macOS 14.8 and 15.7 (run 37895394093). The
  Lightroom plug-in has not yet been tried in a real Lightroom Classic; see field test T15.

## 1.2.0
- Click the Keep, Consider or Drop tile above the grid to show only that group; click it again, or
  Photos analysed, to show everything. The active tile is outlined and matches the filter menu.
- "Skip suggestion" is now **Drop**, in orange, everywhere (tiles, labels, buttons, filter, CSV).
  Decisions saved as Skip in earlier versions become Drop automatically. Viewer shortcut: D.

## 1.1.0
- RAW files whose pixels LibRaw cannot decode (for example Nikon Z6III High Efficiency NEF) are analysed
  from the camera's embedded full-size JPEG, labelled CAMERA PREVIEW on cards, viewer, comparisons, status
  line, diagnostics and CSV (ported from PhotoSelect 0.3.1). Damaged or non-RAW files never fall back.
- Status line shows the correct photo count as soon as a scan finishes.

## 1.0.2
- Nikon High Efficiency (HE / HE★) NEFs are identified by name in "Files that could not be analysed",
  with the camera setting to use instead (NEF (RAW) compression → Lossless compressed). LibRaw cannot
  decode these files.

## 1.0.1
- Help → Create Diagnostic Report… for testing on your own Mac (no image data, no full paths).

## 1.0.0
- First standalone Apple silicon app: native window, bundled Python and LibRaw, offline, DMG install.
