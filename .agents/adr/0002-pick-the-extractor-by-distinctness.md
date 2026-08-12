# Pick the frame extractor by measuring distinctness, not keyframe density

Two extractors cover different footage. `-skip_frame nokey` decodes I-frames
only, which encoders emit at scene cuts, so on cut-heavy material those frames
*are* the distinct moments — 404 of them out of a 24-minute episode in about
1.2s. Low-cut footage (screen recordings, talking heads) needs uniform sampling
instead, because its I-frames track the encoder rather than the content.

Choosing between them by keyframe *density* is wrong, and wrong in the direction
that looks right:

| Source | Keyframes/s | Distinct after dedup |
| --- | --- | --- |
| 24-min anime (real scene cuts) | 0.28 | 100% |
| 44s screen recording at 120fps | 1.02 | 71% |
| 67-min 1080p VP9 film | 30.0 | 39% |

The screen recording has 3.6x the keyframe rate of the anime and needs the
*other* extractor. A density threshold picks backwards on both of the last two
rows. The VP9 file marks every frame as a keyframe, which is a real encode, not
a corruption.

So we run a bounded keyframe pass and measure what fraction survives dedup. That
answers the only question worth asking — are these frames actually distinct? —
and it is cheap. The probe stops at 400 frames, because writing all 121,701
keyframes of that VP9 file just to reject the engine cost minutes and gigabytes;
when the probe hits its limit, the rate is computed over the span it actually
covered so a dense encode cannot read as sparse.

Thresholds: at least 0.15 keyframes/s (below that the clip is too sparse to
cover) and at least 80% distinct.
