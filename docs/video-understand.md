## What it does

`video-understand` watches a video — local file or URL — and answers questions
about it: a summary, a recap, a spoiler, "what did they say at 3:20", "find the
part where X happens".

It never sends frames one at a time. Frames are packed into tiled **grid**
images, so a 24-minute episode arrives as 7 pictures instead of hundreds, and
every grid is paired with a timestamped transcript. Both halves are mandatory:
a grid shows what is on screen and never what was said, and a summary built from
pictures alone is confident, coherent, and wrong often enough that the skill
treats skipping the transcript as a defect rather than a shortcut.

## When to reach for it

Type `/video-understand`, or the agent reaches for it on its own when a request
fits — it is model-invoked and fires on a pasted video path or URL with a
question attached.

| Your situation | Where to go |
| --- | --- |
| "What happens in this video?" / summarize / recap / spoil | This skill |
| "What did they say around 12:00?" | This skill — use `--start`/`--end` to focus |
| "Find the moment the logo appears" | This skill |
| Reading small on-screen text, a UI label, a timestamp | This skill, at `--cells 16` |
| Cutting, trimming, or rendering the video | Not this skill — it only reads |
| Generating video | Not this skill |

## Prerequisites

`ffmpeg` and `ffprobe` on your PATH (`brew install ffmpeg`) — required.

An `ELEVENLABS_API_KEY` is strongly recommended and not required. It produces
the most accurate transcripts, especially for Thai. Without it the skill falls
back to native subtitles via `yt-dlp` (URLs only) or a local `faster-whisper`
install.

## Grids, and how many cells

The cell count is a **resolution** decision, not a cost one. Images are
downscaled to a 1568px long edge before tokenizing, so past that point a grid
costs about the same no matter how many cells it holds — extra cells are free in
tokens and paid for in per-cell resolution.

| `--cells` | px per cell | Good for |
| --- | --- | --- |
| 16 | ~392 | small on-screen text, UI labels, timestamps |
| 36 | ~261 | facial expression, fine action |
| 64 | ~196 | plot, scene inventory, recaps — the default |
| 100 | ~157 | rough skim of long footage; small text is lost |

Measured on 720p source: burned-in captions and full-screen title cards —
including dense Japanese — are legible at 196px. Player-UI text like a
`0:01 / 20:56` counter needs 392px.

Grids carry order and content, not the clock. Cells are not evenly spaced,
because near-duplicate frames are dropped. Timestamps come from the emitted
`manifest.json`, never from reading the picture.

## What it cannot do

- **Continuous motion** — easing, velocity, bounce, overshoot. Grids give
  positions, not the curve between them; a 250ms ease is one frame at 4fps.
  Discrete, staged motion (text animating in, items appearing one by one) reads
  fine.
- **Frame-exact timing.** Timestamps are as precise as the sampled frame, not
  the cut.
- **Anything inaudible and off-screen.** If neither stream carries it, it is not
  in the answer, and the skill is instructed to say so rather than fill the gap.

## Common questions

**Why did it get the plot wrong when the pictures were clear?**
Because pictures without dialogue produce a story that hangs together and is
false. In testing, grids showed a gadget, a boy turning into a black shadow, a
fox appearing, a monkey falling — the obvious read was "a cursed gadget that
summons creatures". One transcript line explained all of it: the gadget makes
figures of speech literally real. The shadow was "life is gloomy"; the fox was
an idiom for confusion. That link is language-only and no amount of visual
resolution contains it. This is why the skill insists on reading the transcript
whole rather than sampling it.

**Can I speed it up by splitting the audio into chunks?**
No — measured, that is 2.2x slower (142s vs 65s), because the API rate-limits
per key so concurrent uploads queue against each other. Shrinking the upload
does not help either: a 2.7x smaller Opus file took 3x longer for a
byte-equivalent transcript. See
[.out-of-scope/parallel-audio-chunks.md](../.out-of-scope/parallel-audio-chunks.md).

**How long does a long video take?**
A 67-minute film: 78s for the transcript, 90s for the frames, **95s wall-clock**
when run concurrently — which is what the skill tells the agent to do. The
transcript is mostly fixed overhead, so it scales far better than duration
suggests: 24 minutes takes 65s, 67 minutes takes 80s.

**Why did it only give me 8 grids for a whole film?**
A frame budget caps the run (default 512 frames). Without it, 67 minutes at a
fixed sampling rate produced 193 grids — about 359k tokens for one video.
Frames are thinned evenly across the whole runtime, not truncated, so coverage
still spans the film end to end. Raise it with `--budget` if you want more.

**Do I have to crop a frame to read on-screen text?**
No, and you should not. Re-run with `--cells 16` plus `--start`/`--end` over
that moment instead — you get a whole grid of the region at full cell
resolution for the same cost as one cropped still.

## It's working if

- The run prints which extractor it chose and the distinct-% behind that choice.
- A 24-minute video produces roughly 7 grids; a feature-length one produces
  about 8 and still spans the full runtime.
- Every timestamp in the answer can be traced to a cell in `manifest.json`.
- The summary states facts that appear nowhere in the pictures — names, rules,
  reasons — which means the transcript was actually read.
- Where something is genuinely unclear, the answer says so instead of guessing.

## Where it fits

A reach-for-it-anytime standalone: it reads video and produces an
understanding, and hands off to nothing. Pair it with
[`image-gen-router`](./image-gen-router.md) only in the loose sense that both
are single-purpose tools in this repo. The decisions behind its design live in
[.agents/adr/](../.agents/adr/).
