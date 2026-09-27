# Rank footage within the batch, and judge sharpness only on lit frames

`cull.py` ranks clips for reuse from ffmpeg measurements: `blurdetect` for
sharpness, `signalstats` for exposure and frame-to-frame change. Two things
about those numbers decided the design.

**Absolute values do not transfer.** Blur and motion depend on the camera,
resolution and grade, so every score is a z-score within the batch being
ranked. The output is an ordering, not a pass/fail.

**A frame with no picture reads as sharp.** `blurdetect` measures how wide
edges are; a near-black frame or a murky low-contrast one has almost no edges,
so it scores as crisp. On a batch of 20 RedNote b-roll clips, two dark night
clips ranked 4th and 5th on the strength of near-black frames, and the contact
sheet showed black squares as their "sharpest" moment. Sharpness is now
measured only on frames with mean luma 25–235 **and** at least 60 levels between
the 10th and 90th percentile (YHIGH − YLOW). The dark clip fell from 4th to 6th,
and every contact-sheet frame shows actual picture. The same rule picks each
shot's representative frame in `index.py`.

Jitter — the mean change in frame-to-frame motion, divided by motion — is a
rough stand-in for shake: a steady pan has high motion and low jitter,
handheld shake has both. ffmpeg's `vidstabdetect` would measure shake properly
but is missing from common builds, Homebrew's included, so jitter is labelled
as a ranking signal only.

Measured: 20 clips (8s to 7m54s, 720p–1080p, landscape and portrait) ranked with text screening in 48s.
