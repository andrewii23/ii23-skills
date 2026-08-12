# Pack frames into grids instead of reading them one at a time

A model that cannot watch video has to read stills. Reading them individually is
the obvious approach and the expensive one: 64 frames at 512px costs about
12,500 tokens, and 64 frames does not cover a 24-minute episode.

We tile many frames into one image instead. The same 64 frames as a single grid
cost about 1,900 tokens — roughly **7x cheaper** — because images are downscaled
to a 1568px long edge before tokenizing. Past that point a grid costs the same
regardless of how many cells it holds, so extra cells are free in tokens and
paid for in per-cell resolution.

That makes cell count a resolution decision, not a cost one. Measured on 720p
source:

| Cells | px per cell | Legible for |
| --- | --- | --- |
| 16 | ~392 | small UI text, timestamps, chapter labels |
| 36 | ~261 | facial expression, fine action |
| 64 | ~196 | plot, scene inventory, recaps (default) |
| 100 | ~157 | rough skim; small text lost |

Burned-in captions and full-screen title cards — including dense Japanese — read
fine at 196px. Player-UI text needs 392px.

Published work is more conservative. [IG-VLM](https://arxiv.org/abs/2403.18406)
peaks at 6 frames per grid and [Video Panels](https://arxiv.org/html/2509.23724v2)
at 2x2, degrading by 4x4 — both on older, smaller models. We tested 36, 64, and
100 cells directly rather than inheriting those limits, and 64 is comfortably
legible. Do not cap at 6 on the strength of the papers.

The trade-off is real and bounded: a grid encodes order and content but not the
clock, and dedup makes cell spacing uneven. Timestamps therefore come from the
emitted manifest, never from reading the picture.
