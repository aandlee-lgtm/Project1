# PhotoSelect validation report (1.0.0, updated for 1.6.0)

## 1.6.0 results
Build and acceptance run: https://github.com/aandlee-lgtm/Project1/actions/runs/38003122912. The installed
DMG passed on clean macOS 14.8 and 15.7 runners: 111 passed or informational, 0 failed, on each. The
first 1.6.0 run (38002583793) stopped at one unit test, which built a path by hand. macOS resolves
/var to /private/var, so it did not match; the test now uses the analysed photo's path, as the app does.

**New checks:**
- The top bar stays on screen when scrolled: Choose folder, Analyse photos, Send to Lightroom… and the
  status remain within the top 60 px. Checked in WebKit before and after relaunch.
- The title bar shows only the version (v1.6.0).
- Star changes from Lightroom: the UI check writes a change as the plug-in would. PhotoSelect then
  shows "From Lightroom: 1 Keep → Drop" and the decision changes. Unit tests cover the mapping, a photo
  changed twice, removed stars and unknown photos.
- Plug-in (Lua 5.1, simulated catalog; 17 plug-in tests, 70 in total):
  - stars are tracked after applying and changes are reported once;
  - changes survive a Lightroom restart;
  - photos removed from the catalog are forgotten;
  - the PhotoSelect collection set gets five Smart Collections with the right rules;
  - *From PhotoSelect* goes only on photos PhotoSelect rated.

**250-RAW-file folder** (same files and runner type as before, 2 workers): 179 s on macOS 14 and
169 s on macOS 15 (1.25–1.33 files/s; 1.5.0: 235–243 s). Peak memory was 1.6 / 2.1 GB, and the first
analysed photo came after 26–31 s. These are run-to-run variation on shared runners; 1.6.0 did not
change analysis.

**Not tested:** the 1.6 plug-in inside a real Lightroom Classic. In particular, whether
`createSmartCollection` accepts the combined rating + keyword rules as simulated, and the
`getPhotoByLocalId` look-ups. Field test T18 covers this.

## 1.5.0 results
Build and acceptance run: https://github.com/aandlee-lgtm/Project1/actions/runs/37935799010. The installed
DMG passed on clean macOS 14.8 and 15.7 runners: 105 passed or informational, 0 failed, on each.

**Speed and resources, 250-RAW-file folder** (same files and runner type as 1.4.0: virtual M1, 3 cores,
7 GB):

| | 1.4.0 (runs 37895394093, 37922521013) | 1.5.0 macOS 14 | 1.5.0 macOS 15 |
|---|---|---|---|
| Analysis workers | 1 | 2 | 2 |
| Whole folder | 457–685 s (0.33–0.49 files/s) | 235 s (0.95 files/s) | 243 s (0.92 files/s) |
| CPU time per file | not measured | 1.46 s | 1.59 s |
| All camera previews shown | not measured | 41 s | 37 s |
| First photo fully analysed | not measured | 42 s | 38 s |
| App peak memory | 1.1–1.5 GB | 1.3 GB | 1.9 GB |
| Interface during analysis (p95 / max) | 15–32 / 180–410 ms | 152 / 447 ms | 65 / 207 ms |
| Cancel → stopped | 2.1–2.7 s | 1.6 s | 0.8 s |

Peak memory for the whole app is higher with two photos analysed at once, although each needs less.
On an 8 GB M2, 4 workers are expected to peak at about 2.5–3 GB (estimated, not measured).

**Analysis decode benchmark** (run 37931855801: Apple silicon, 13 genuine RAW files, 5–61 MP; each file
decoded and analysed in a fresh process):
- 45–61 MP (Nikon D850, Z7, Z7 II, Z9; Sony A1, A7R IV, A7R V, A7CR), half-size decode: 2.8–4.4 s →
  0.6–1.6 s per photo, peak memory 640–810 → 480–620 MB.
- 5–24 MP, fast demosaic: 1.6–1.8 s → 1.2 s for 24 MP.
- Overall 2.86× faster. Rank correlation with 1.4.0's scores: sharpness 0.995, focus 0.995,
  composition 1.0, exposure 1.0. Folder scores differ by 2.2 (sharpness) and 3.3 (focus) points on
  average out of 100.
- Rejected alternative: half size for every file would be 3.41× faster but changes focus rankings
  (rank correlation 0.77).
- The analysis preview is now made without copying the full image (0.42 → 0.24 s for 24 MP,
  identical metrics). This was measured locally after the benchmark run.

**New checks:**
- The inspector steps to the next photo at the same zoom, before and after relaunch.
- Plug-in status is reported to PhotoSelect (unit tests).
- Automatic rating runs after any import: path, capture-date and DNG matching, once per photo,
  expiry. Tested in the Lua 5.1 plug-in tests against a simulated catalog (15 plug-in tests, 67 in
  total).

**Not tested:** the 1.5 plug-in inside a real Lightroom Classic. In particular, whether Lightroom's
catalog search by capture date behaves as in the simulation, and how quickly stars appear. Field test
T15 covers this. Speed on your M2 with 4 workers is covered by field test T17.

## 1.4.0 results
Build and acceptance run: https://github.com/aandlee-lgtm/Project1/actions/runs/37922521013. The installed
DMG passed every check on clean macOS 14.8 and 15.7 runners (macOS 15: 0 failed). New checks:

| Check | Result |
|---|---|
| Sony ARW decoded by the installed app and matching Apple's own RAW render (A7R V lossless compressed: 0.978; A7S: 0.967) | PASS |
| Send to Lightroom window shows plug-in status and the four star groups with counts | PASS |
| Open in Lightroom hands exactly the chosen groups' files to the Lightroom app (stand-in applet recorded 15 of 15 chosen) and requests automatic rating | PASS |
| Lightroom Classic not installed: explained in the window, selections still saved, no page errors | PASS |
| Originals unchanged: content, size, modification date and permissions of all 270 files | PASS |
| Photos handed to Lightroom: macOS added only its "last opened" attribute (com.apple.lastuseddate#PS) on 15 files | INFO |

**Sony A7 / A9 coverage** (separate check, every public raw.pixls.us sample through the bundled
rawpy 0.27.1 / LibRaw 0.22.1, run 37921740555):
- All 21 bodies (A7 to A7 V, A7R to A7R V incl. IIIA / IVA, A7S to A7S III, A7C, A7C II, A7CR, A9 to
  A9 III) were tested with 58 files, covering uncompressed, compressed and lossless compressed
  (L / M / S) modes.
- All decode as RAW except the **A7 V "compressed" mode** (3 files). The bundled LibRaw does not
  recognise it, so these files are analysed from the camera's own JPEG (7008 × 4672 full frame,
  4608 × 3072 APS-C) and labelled CAMERA PREVIEW. No newer rawpy release exists yet.
- Bodies before about 2020 embed only a 1616 × 1080 (or 1920 × 1080) JPEG. That is irrelevant
  because their RAW decodes. Newer bodies embed near full-size JPEGs.
- Sub-second capture times, used for burst grouping, are recorded by the A7 IV, A7 V, A7R V,
  A7S III, A7C, A7C II, A7CR, A9 II and A9 III, but not by older bodies.

**Tested from source only:**
- The Z50 II High Efficiency NEF fallback was checked on your DSC_1312.NEF (5568 × 3712 camera JPEG,
  upright) and in unit tests. No public Z50 II HE sample was found for the macOS run.
- The Lightroom plug-in 1.4 runs under Lua 5.1 against a simulated catalog: matching, selection
  scope, unmatched-name summary, automatic rating after import, expiry, and shutdown.

**Not tested:** Lightroom Classic itself. In particular, whether Lightroom opens its Import window
for files handed to it, and the background rating after import, need field test T15 on your Mac.

## 1.3.0 results

Build and acceptance run: https://github.com/aandlee-lgtm/Project1/actions/runs/37895394093. The DMG was
installed on clean macOS 14.8 and 15.7 runners. Both passed every check (macOS 15: 95 passed or
informational, 0 failed), and the 1.0 checks below were repeated. New checks, run on the installed app
before and after a relaunch:

| Check | Result |
|---|---|
| Status line has no decoder version ("13 photos analysed … · 9 bursts / single frames · 4 could not be analysed") | PASS |
| Accent colour is the new teal #4fe0c8 | PASS |
| Burst Similarity ≥ % and near-identical settings saved and applied (Regroup) | PASS |
| Viewer shows likeness to the burst's top frame; burst comparison shows likeness to #1 and the burst average | PASS |
| Camera-preview photo cards omit the long sentence (Z6III HE sample) | PASS |
| Learn from my decisions is disabled until 30 photos are marked | PASS |
| Settings profile saved, loaded, restored after relaunch, deleted; settings remembered per folder | PASS |
| Lightroom plug-in installed (Help → Install Lightroom Plug-in…) and selections sent | PASS |
| Originals unchanged and no files added to photo folders (Lightroom selections are kept in ~/Library) | PASS |
| No JavaScript errors | PASS |

**Tested only from source, not on the packaged app:**
- *Learn → Apply → Undo* (the CI folder has only 13 photos). It passed against the source server with
  a 40-photo folder (Chromium).
- Likeness and near-identical grouping, the 1.2 → 1.3 preference migration and the Lightroom
  endpoints are covered by unit tests: 51 in total.
- The plug-in's Lua code runs under Lua 5.1 (Lightroom's version). This includes the menu command
  against a simulated Lightroom catalog: stars, keyword replacement, existing stars kept, Replace,
  Cancel, and "no selections found".

**Not tested:** the plug-in inside a real Adobe Lightroom Classic. Lightroom cannot run on the test
machines. The SDK calls are written to Adobe's documented API but have only been exercised against
the simulation. Field test T15 covers this on your Mac.

## 1.0.0 results

What was verified, how, and what remains untested. Every result below comes from automated
runs of the **packaged app installed from the DMG**, unless marked as a source-level test.
Raw output: the `acceptance-macos-14` / `acceptance-macos-15` artifacts and the job summaries of
the GitHub Actions workflow *Build and test macOS app (Apple silicon)* in this repository.

## Environments

| Role | Machine |
|---|---|
| Development and unit tests | Linux x86_64 cloud container (cannot build or run macOS apps) |
| Build | GitHub `macos-14` runner: Apple M1 (virtual), arm64, macOS 14.8 |
| Acceptance tests | Fresh GitHub runners: macOS **14.8.9** and macOS **15.7.9**, Apple M1 (virtual), 3 cores, 7 GB RAM |

The acceptance machines are virtual M1s, **not your M2**, and have no attached physical drives.
The build (`scripts/build_mac.sh`) and test harness (`scripts/acceptance_mac.py`) are in the
repository, so the same checks can be repeated on your Mac.

## Build and packaging

| Check | Result |
|---|---|
| Native arm64 CPython 3.12.10 (python.org) bundled by PyInstaller 6.22.3 | PASS |
| Exact pinned dependencies, all from prebuilt macOS 11+ arm64/universal2 wheels (NumPy's 11.0 build forced) | PASS |
| Every bundled Mach-O binary inspected; universal binaries thinned to arm64; main executable arm64 only | PASS |
| No binary links outside the bundle or macOS (no developer Python/Homebrew paths) | PASS |
| Highest minimum OS among bundled binaries = **macOS 11.0** → written to `LSMinimumSystemVersion` | PASS (measured) |
| Ad-hoc code signature; `codesign --verify --deep --strict` on build and again after installation | PASS |
| DMG (`hdiutil verify`) contains `PhotoSelect.app` and an `Applications` shortcut | PASS |
| Third-party licence notices bundled (`Help → Third-Party Notices`) | PASS (generated at build) |
| Gatekeeper `spctl --assess` | **Rejected**, as expected for an ad-hoc, non-notarised build (see Limitations) |
| App size 67 MB; DMG 29 MB | — |

## Packaged-app acceptance tests (macOS 14.8 and 15.7)

**Installation and launch**
- Mount the DMG, copy the app to /Applications, eject, verify the signature of the copy. PASS
- Launch the installed app with python.org Python **and Homebrew moved away**, a minimal
  environment (`PATH=/usr/bin:/bin:…`) and a sandbox profile that **denies all outbound network
  traffic except loopback**: ready in ~1.5 s. PASS
- Loaded libraries (via `lsof`): only the bundle and macOS (68–73 libraries). PASS
- Network sockets: one listener on `127.0.0.1` (OS-assigned port). Requests without the session
  token, or with a foreign Host header (DNS rebinding), are refused (403). PASS
- Relaunch through LaunchServices (`open -a`, equivalent to double-clicking). PASS

**Photos and decoding.** The test library was placed on a *separately mounted APFS volume* named
"Photo Drive", in folders with spaces. Genuine camera files came from raw.pixls.us (CC0):

| Camera (file) | Format | Decoded size | Correlation with Apple's render | macOS 14 | macOS 15 |
|---|---|---|---|---|---|
| Nikon D7200 (`DSC_0979.NEF`) | NEF, uppercase ext. | 6016 × 4016 | 0.998 | PASS | PASS |
| Nikon D5600 (`…0792.nef`) | NEF, lowercase ext. | 6016 × 4016 | 0.981 | PASS | PASS |
| Olympus XZ-1 (`p1319978.Orf`) | ORF, mixed-case ext. | 3680 × 2760 | 0.856 | PASS | PASS |
| Nikon D3S (NASA ISS file, earlier runs) | NEF | 4284 × 2844 | 0.995 | PASS | PASS |
| Nikon NRW (Coolpix) | NRW | — | — | NOT TESTED (no sample obtained) | NOT TESTED |

Correlation is between PhotoSelect's full-resolution LibRaw decode and macOS's own RAW
renderer (`sips` / Core Image) for the same file, both downsampled to greyscale. Values near 1
confirm the decoded content and orientation are right. Apple's renderer also applies the lens
corrections stored in some files (notably Olympus) and crops slightly differently, which
lowers the correlation without indicating a decoding error.

- Upper-, lower- and mixed-case extensions (`.NEF`, `.nef`, `.Orf`) in one mixed folder with
  JPEG, PNG, 8-bit and 16-bit TIFF. PASS
- Subfolders included when requested. PASS
- `._` AppleDouble files ignored. PASS
- Truncated NEF, random-data ORF, empty NRW, and a NEF without read permission are each listed
  with a specific reason, not scored, and the rest of the folder is analysed. PASS
- Full-resolution inspector shows the native pixel size. The 100% view maps one image pixel to
  one screen pixel on a 2× display. PASS

**Workflow (UI driven in WebKit against the packaged app's own server)**
- Weight sliders re-rank immediately. Thresholds change the Keep/Consider/Drop (then called Skip) counts. PASS
- Manual Keep + Like applied. After quitting and relaunching: decisions, likes, weights,
  thresholds and the drawn focus region are all restored, and the region is re-applied
  without a re-decode. PASS
- Focus region measured on the full-resolution decode. Recommendation reasons displayed. PASS
- Burst comparison with 100% crops. Liked-shortlist comparison. CSV export (written by the
  app, then read back). PASS
- A 5-frame JPEG burst with sub-second EXIF times is grouped together, and the sharpest frames
  get the highest focus scores (95 vs 52 / 19 / 15 for the blurred frames). PASS
- No JavaScript errors. PASS

**Performance and robustness: 250 RAW files on the test volume** (APFS clones of the genuine samples above, mostly the 24 MP NEFs)

| | macOS 14.8 | macOS 15.7 |
|---|---|---|
| Analysis workers chosen (7 GB / 3-core VM) | 1 | 1 |
| Time for 250 files, first pass | 438 s (0.51 files/s) | 538 s (0.42 files/s) |
| Peak memory of the app process | 909 MB | 926 MB |
| Cancel → stopped | 1.6 s | 2.5 s |
| API latency during analysis (median / p95 / max) | 4 / 15 / 201 ms | 8 / 25 / 340 ms |
| Fully cached rescan of 250 files | 0.5 s | 0.6 s |

- Cancelling keeps finished results, and re-analysing resumes from the cache. PASS
- The final run: **macOS 14.8 and macOS 15.7 each passed every check (70 per platform, 0
  failures)**, apart from the NRW item marked NOT TESTED.

**Shutdown, persistence, safety**
- Quit via the standard Quit Apple Event (the ⌘Q / menu path): exits in under 1 s. No
  PhotoSelect process remains and the port is closed. PASS
- Settings and results are stored in `~/Library/Application Support/PhotoSelect`, caches in
  `~/Library/Caches/PhotoSelect`, and logs in `~/Library/Logs/PhotoSelect`. PASS
- **Originals unchanged:** SHA-256, size, modification time, permissions and extended
  attributes of every test file were identical before and after, and no files were added to
  photo folders. PASS
- **App bundle unchanged after use:** identical tree hash and signature still valid. PASS

**Source-level unit tests** (Linux and macOS build, 30 tests). They cover metric behaviour
(blur, regions, noise compensation, scale comparability, clipping), burst grouping,
case-insensitive routing, damaged/empty/unsupported files, ORF EXIF header handling, a
genuine LibRaw decode of a synthetic DNG, the cache, cancellation, persistence and the HTTP API.
PASS

## Not tested / known limitations

- **Nikon Z6III High Efficiency NEF (v1.1.0).** LibRaw 0.22.1 cannot decode these. This was confirmed on
  your DSC_2094.NEF and on raw.pixls.us Z6III HE/HE★ samples, while the Lossless compressed samples decode.
  They are analysed from the full-size embedded camera JPEG and labelled CAMERA PREVIEW. This is
  verified end to end on DSC_2094.NEF from source, and on a raw.pixls.us Z6III HE sample in the
  packaged-app acceptance run.
- **Your cameras and your photos.** Genuine Nikon (D7200, D5600, D3S) and Olympus (XZ-1) files
  were tested. No **NRW** file and no current Nikon Z or OM System body (OM-1, etc.) was obtained
  from the public archive in these runs. Your own bodies, your bursts and special modes were not tested (e.g. Nikon High Efficiency
  NEF, OM System high-res or pro-capture files). Please send a few NEF/ORF files, ideally
  including a burst. If a mode isn't supported by LibRaw 0.22.1, the app says so per file.
- **Real burst sequences from a camera** were not available. Burst grouping was verified with
  generated JPEG bursts carrying sub-second EXIF times, and with unit tests.
- **Your M2 hardware** was not tested, only virtual M1 runners. macOS 11–13 and 26 were not
  tested. The minimum version (11.0) is derived from the binaries, not from running on 11.
- **A physical external drive** (USB/SD, exFAT) was not tested. A separately mounted APFS
  volume with spaces in its path was used instead. The macOS privacy prompt for removable
  volumes ("PhotoSelect would like to access files on a removable volume") was not exercised.
- **Native dialogs** (Choose folder, Save CSV) were not clicked by the automation, which used the
  same code paths via an export directory and typed paths.
- **Closing the window with the red button** was not automated (no Accessibility permission on
  the runners). It runs the same shutdown path as Quit, which was tested.
- **Gatekeeper / downloaded installs:** the build is ad-hoc signed and **not notarised**. A
  downloaded copy is blocked until you click **Open Anyway** (see INSTALL.md). Removing that
  step needs an Apple Developer ID and notarisation. The workflow supports both
  (`CODESIGN_IDENTITY`, `NOTARY_PROFILE`), but neither was available or tested.
- **Throughput:** the 7 GB runner used one worker (about 0.5 RAW files/s for 24 MP files). An 8 GB
  M2 will use 2 workers and a 16 GB machine 4, but this hasn't been measured. Expect a first pass
  over thousands of 45 MP files to take tens of minutes; later passes are cached.
- **Scoring quality** is heuristic. Detail can still be inflated by real texture (waves,
  foliage, a sharp background) inside the measured region. Composition is not a trained
  model. There is no eye, face or subject detection and no motion-blur detection.
- **Colour:** LibRaw renders with the camera's white balance, sRGB and no lens corrections. It will
  differ from Lightroom or the camera JPEG and is meant for judging focus and exposure.
