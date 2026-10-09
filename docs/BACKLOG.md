# PhotoSelect feature backlog

Feedback from testing is recorded here as product features. Nothing in this list is built,
versioned or released until the owner's message includes **build_new**; then the open items are
implemented, tested and shipped together as one new version.

| # | Requested | Feature | Status |
|---|---|---|---|
| 1 | 2026-10-09 | **Bursts defined by visual likeness as well as timing.** Compute a "% likeness" between frames (0–100 %, from how alike the images look) and use it explicitly in burst grouping: frames belong to the same burst when they are close in time **and** at least N % alike. Show the % to the user: a "Similarity ≥ N %" slider replacing the current tolerance number, each frame's likeness to the burst's top frame in the burst comparison and viewer, and a burst's average likeness in the diagnostic report and CSV. | Planned |
| 2 | 2026-10-09 | **Near-identical shots a few seconds apart count as a burst.** Extend item 1: frames that are very alike (a higher "near-identical" likeness, e.g. ≥ 90 %, adjustable) are grouped even when they are several seconds apart (adjustable window, default about 10 s), not only within the normal burst gap. The burst view marks such frames as near-identical. | Planned |
| 3 | 2026-10-09 | **Status line without the decoder version.** Remove "· LibRaw 0.22.1" from the status line after a scan; keep everything else (photos analysed, time, cache, camera previews, bursts / single frames, could not be analysed). The decoder version stays available in Help → About and the diagnostic report. | Planned |
| 4 | 2026-10-09 | **Brighter teal accent colour.** The current accent (`#ade1c5`, a pale teal that reads almost lime green) becomes a slightly brighter, clearer teal, staying in the teal family. The related shades change with it: score bars, badge borders, pill backgrounds and the text on primary buttons. Text must stay easy to read on the dark panels. | Planned |
| 5 | 2026-10-09 | **Learn from my decisions (on this Mac, with my approval).** Once enough photos have been marked by hand (about 30 or more Keep / Consider / Drop decisions and likes), PhotoSelect suggests the slider weights (sharpness, subject focus, composition, exposure) and Keep / Consider thresholds that best match those decisions. It shows the proposed change and why, for example "you keep frames with high subject focus even when composition is low", with how many of your past decisions it would have matched before and after. Nothing changes until I click Apply, and I can undo it. Learned settings can be saved per folder or as named profiles for kinds of shoot (e.g. sailing, portraits). Everything stays on the Mac: no upload and no hidden model, and the reasons shown for each photo stay a complete explanation. | Planned |

(Released so far: see docs/RELEASES.md — current release 1.2.0.)
