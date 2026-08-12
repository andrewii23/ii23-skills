# Budget frames for the whole run instead of sampling at a fixed rate

Uniform sampling originally ran at a fixed 4fps. That is fine for a 44-second
clip and ruinous for a feature-length one: a 67-minute film produced 16,227
frames, 12,306 survived dedup, and those tiled into **193 grids** — roughly
359k tokens for one video, against 7 grids for a 24-minute episode. 2.8x the
runtime cost 27x the tokens.

The mistake was treating frames-per-second as the constant. What should stay
roughly constant is the *bill*; what should shrink on a long video is coverage
per minute. So `--budget` caps total frames for the run (default 512 = 8 grids
at 64 cells), and the uniform sampler derives its fps from that budget and the
clip's duration.

The cap applies to the keyframe path too. A cut-heavy three-hour film blows the
same hole through keyframes that a fixed rate blows through uniform sampling, so
budgeting only one engine would just move the failure.

Frames are thinned evenly across the full range rather than truncated at the
tail, which keeps whole-runtime coverage: the 67-minute film now yields 512
frames spanning 00:00 to 1:07:28 of a 1:07:36 runtime, one frame per 8 seconds,
in 8 grids at about 15k tokens.

Thinning is reported on stderr and recorded in the manifest
(`frames_thinned_for_budget`, `budget`, `sampling_fps`). Silent truncation would
read as "this is everything" when it is not — the same reason `--max-grids`
thins evenly rather than stopping early.
