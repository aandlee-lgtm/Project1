# PhotoSelect releases

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
