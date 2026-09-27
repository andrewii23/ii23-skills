## What it does

`video-understand` watches a video — local file or URL — and answers questions
about it: a summary, a recap, a spoiler, "what did they say at 3:20", "find the
part where X happens".

It sees every **shot**. One cheap pass finds each cut in the video, and every
shot gets at least one frame, so a two-hour film cannot hide a scene between
samples. Frames are packed into timestamp-labelled **grid** images instead of
being sent one at a time, and alongside them come a timestamped transcript and
a text **index** of the video: where the cuts are, what moves, where the sound
spikes or goes quiet, what words appear on screen. The grid and the transcript
are both mandatory whenever there is speech:
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
| A full-length film: spoiler, recap, pick the scenes worth cutting | This skill — every shot is covered |
| A video with no speech: a sight gag, a room tour, b-roll | This skill — `index.py --ocr` carries the words |
| Fifty downloaded clips, which are usable? | This skill — `cull.py` |
| "What did they say around 12:00?" | This skill — use `--start`/`--end` to focus |
| "Find the moment the logo appears" | This skill |
| Reading small on-screen text, a UI label, a timestamp | This skill, at `--cells 16` |
| The speaker says "look here" at 4:32 and the grid missed it | This skill — `frames.py --at 4:32` |
| Sorting a pile of downloads into "has subtitles" vs "clean footage" | This skill — `text_check.py` |
| Cutting, trimming, or rendering the video | Not this skill — it only reads |
| Generating video | Not this skill |

## Prerequisites

`ffmpeg` and `ffprobe` on your PATH (`brew install ffmpeg`) — required.

The text screen (`text_check.py`) needs macOS with Xcode command-line tools
(`swiftc`), or `tesseract` on any OS.

An `ELEVENLABS_API_KEY` is strongly recommended and not required. It produces
the most accurate transcripts, especially for Thai. Without it the skill falls
back to native subtitles via `yt-dlp` (URLs only) or a local `faster-whisper`
install.

## Shots, not frames

Earlier versions sampled a fixed 512 frames per video. On a 2h05m film that put
a frame in 29% of its 1,727 shots, and skipped shots up to 28 seconds long. A
shot you never see is a scene you cannot pick or spoil, so frames now start
from the shot list: one frame per shot (its sharpest moment), plus extra frames
through long takes. The same film now shows every shot, in 27 grids.

Finding the shots is its own problem. The usual ffmpeg recipe (`scene > 0.3`)
found **0 of 32** cuts in two 30-second stretches of that film checked frame by
frame by hand — shot/reverse-shot in one room never scores that high. An
adaptive rule, a score that spikes well above its neighbours, found 30 of 32
with no false cuts.

| | Old default | Now |
| --- | --- | --- |
| Shots on a 2h05m film with a frame | 494 / 1,727 | 1,727 / 1,727 |
| Grids | 8 | 27 |
| Cells | unlabelled | stamped with their time |

## The index: what frames cannot show

`index.py` writes one line per shot plus the sound and the on-screen text. It
is what a silent video has instead of a transcript:

| Line | Tells you |
| --- | --- |
| `#12 03:21.5-03:25.0 (3.5s) \| high motion, dark, loud` | an action beat, at night, with noise |
| `sound hit 00:41.3` | a slam, a laugh, a music sting — in silent comedy, the punchline |
| a silence after a line | a beat meant to land |
| `00:09.0-00:11.0 找小三` (with `--ocr`) | burned-in captions: the words of a muted clip |

Measured: the 2h05m film indexed in 69s; a 2:45 phone room tour with `--ocr`
in 7s, every caption pulled out as timed text.

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

Every cell is stamped with its time in the corner. Cells are not evenly spaced
— one per shot plus fill — so the stamp, not the cell's position, is the time.
Portrait phone video gets a grid with more columns so the image stays
near-square instead of a tall strip.

## Screening for burned-in text

Picking reusable footage is a different question from understanding one video:
across fifty downloads you only need to know which ones someone already typed
over. `text_check.py` answers that without building a single grid. It OCRs six
full-resolution frames per clip and marks each `clean` or `TEXT`.

Measured on 54 RedNote clips (8s to 10min, 720p–1080p), macOS Vision backend:

| | Result |
| --- | --- |
| Speed | 106s for all 54, about 2s per clip |
| OCR noise on clean footage | at most 4 characters (a stray dash, a sign in the background) |
| Smallest real overlay | 18 characters (a phone screenshot's status bar) |
| Burned-in subtitles | 30 to 1,122 characters |
| Default `--max-chars` | 8, the gap between noise and real text |

Frames are checked at full resolution on purpose. An earlier version that
downscaled to 720px wide and dropped low-confidence reads marked a clip with
small subtitles as clean; this one reports 100 characters on it.

Six samples are six moments. A subtitle that flashes for a second between them
can slip through, so treat `clean` as "worth a look", not a guarantee.

## Culling footage

`cull.py` ranks a batch of clips by sharpness, steadiness, exposure, burned-in
text and length, and returns one contact sheet — each clip's sharpest frame,
labelled with its rank — so the whole batch is judged from one image. Scores
are relative to the batch, because blur and motion numbers do not transfer
between cameras. Near-black and murky frames are left out of the sharpness
measure: on the first test batch they made two dark night clips look like the
sharpest footage. 20 clips ranked in 48s.

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

**Why 27 grids for one film?**
Because it has 1,727 shots and each gets a frame. The budget rises to the shot
count (capped at 2,048 frames). If the question is about one scene, that is
more than you need: cap it with `--budget 512` and zoom into the scene with
`--start`/`--end`. For a recap, spoiler or scene selection, seeing every shot
is the point.

**Do I have to crop a frame to read on-screen text?**
No, and you should not. Re-run with `--cells 16` plus `--start`/`--end` over
that moment instead — you get a whole grid of the region at full cell
resolution for the same cost as one cropped still.

## It's working if

- `frames.py` prints how many shots it found and that every one got an anchor
  frame.
- Every grid cell shows a timestamp in its corner.
- `index.md` has one line per shot, and with `--ocr` the video's captions as
  timed text.
- Every timestamp in the answer can be traced to a cell in `manifest.json`.
- The summary states facts that appear nowhere in the pictures — names, rules,
  reasons — which means the transcript was actually read.
- Where something is genuinely unclear, the answer says so instead of guessing.
- `text_check.py` ends with a line like `vision: 7/54 clean`, and the clips it
  calls clean show no subtitles when you open them.

## Where it fits

A reach-for-it-anytime standalone: it reads video and produces an
understanding, and hands off to nothing. Pair it with
[`image-gen-router`](./image-gen-router.md) only in the loose sense that both
are single-purpose tools in this repo. The decisions behind its design live in
[.agents/adr/](../.agents/adr/).
