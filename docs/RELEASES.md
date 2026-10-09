# PhotoSelect releases

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
