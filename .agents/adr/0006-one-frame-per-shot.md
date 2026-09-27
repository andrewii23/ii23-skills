# One frame per shot is the floor, not a frame budget

Supersedes [0002](./0002-pick-the-extractor-by-distinctness.md) as the default
extractor and changes the default of [0003](./0003-budget-frames-by-duration.md).

The keyframe/uniform extractors plus a fixed 512-frame budget were built to keep
the token bill flat. On a feature film that bill bought the wrong thing. On a
2h05m 720p Thai film (1,727 shots per the index below), the old default kept
512 keyframes, thinned evenly, and put a frame in **494 shots — 29%**. The
shots it skipped were not flashes: the longest missed ran 27.8s. Keyframes do
not line up with shots either, so thinning them evenly thins the wrong axis.

A shot you never see is a scene you cannot pick, summarize, or spoil. So the
default extractor now starts from the shot list:

1. Find every cut (see [0007](./0007-adaptive-cut-detection.md)).
2. Take one frame per shot at its sharpest sampled moment, excluding
   near-black and low-contrast frames. These **anchors** are exempt from dedup.
3. Spend whatever budget remains on evenly spaced fill frames, so long takes (a
   walkthrough, a speech, a pan) get more than one look. Fill density falls
   with length: 4/s under a minute, 2/s under five, 1/s beyond.

The default budget rises to meet the shot count, capped at 2,048 frames (32
grids at `--cells 64`); an explicit `--budget` still wins. Measured on the same
film: every one of the 1,727 shots gets a frame, in 27 grids, extracted in 56s
from an existing index (parallel seeks, 8 workers).

| Extractor | Shots with a frame | Grids | Longest shot missed |
| --- | --- | --- | --- |
| keyframe + 512 budget (old default) | 494 / 1,727 (29%) | 8 | 27.8s |
| shots (new default) | 1,727 / 1,727 (100%) | 27 | — |

The cost is real: 27 grids instead of 8. For a question about one scene that
is waste, which is why the skill tells the agent to cap with `--budget` and zoom
with `--start`/`--end` when full coverage is not the job. For recaps, spoilers
and scene selection it is the job.

Each cell also carries its timestamp, drawn with a built-in 5x7 bitmap font
because Homebrew's ffmpeg has no `drawtext` (no freetype). Labels in one grid
are padded to equal width: ffmpeg re-initialises the overlay when an input
frame changes size, and a grid mixing `9` and `10` came out holding only its
second half.
