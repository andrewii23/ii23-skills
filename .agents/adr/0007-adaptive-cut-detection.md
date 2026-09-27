# Find cuts with a fixed floor plus an adaptive ratio, not a fixed 0.3

The common recipe — ffmpeg `select='gt(scene,0.3)'` — misses most cuts in
ordinary film. Shot/reverse-shot in one location, two faces in the same light,
a cut inside a dark room: the scene score jumps, but not to 0.3.

We checked by eye. Two 30-second windows of a 2h05m 720p film (a night
dinner scene and a daylight standoff) were laid out at 2 frames a second and
every cut marked by hand: 32 real cuts.

| Detector | Real cuts found | False cuts |
| --- | --- | --- |
| `scene > 0.3` | 0 / 32 | 0 |
| adaptive (below) | 30 / 32 (94%) | 0 |

The adaptive rule, PySceneDetect's AdaptiveDetector idea in stdlib Python over
ffmpeg's per-frame scene score:

- a cut is certain at score ≥ 0.30;
- otherwise it is a cut when the score is ≥ 0.12 **and** at least 3x the mean of
  the 4 frames either side — a spike, not a busy stretch;
- cuts closer than 0.4s to the previous one are dropped (flicker, flash
  frames), including one at the very start.

Over the whole film this finds 1,727 shots where `scene > 0.3` finds 824. Both
misses were cuts between two dark shots of the same room; the fill frames of
[0006](./0006-one-frame-per-shot.md) still put a frame in that shot.

The score is computed on every frame, at 160px wide: cuts are one frame wide,
so sampling at a few fps would step over them. One decode of the 2h05m film
took 69s wall-clock on Apple Silicon, including the audio pass. Dissolves and
slow fades are the known blind spot of any frame-difference detector; a learned
model (TransNetV2) handles them but needs TensorFlow, which this stdlib-only
repo does not take on.
