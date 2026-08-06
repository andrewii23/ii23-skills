---
name: video-understand
description: Watch and fully understand any video — local file or URL — by packing its frames into grid images (many scenes per image, ~7x cheaper than reading frames one by one) and pairing them with a timestamped transcript. Use this whenever the user wants a video watched, summarized, explained, spoiled, recapped, searched, or asked questions about — "what happens in this video", "summarize this clip", "สปอยคลิปนี้", "ดูวิดีโอนี้ให้หน่อย", "recap this episode", "what did they say at 3:20", "find the part where X happens", "อธิบายคลิปนี้" — or when they paste a video path/URL and ask anything about its contents. Also use for reviewing footage, checking what is on screen, or locating a moment. Do NOT use for editing, cutting, rendering, or generating video.
---

# Video Understand

Read a video the way a person does: see the picture, hear the words, tie them to
the clock. Two scripts produce that; you do the understanding.

- `scripts/frames.py` — extract the frames that matter, drop the duplicates,
  pack them into grid images + a timestamp manifest.
- `scripts/transcript.py` — a timestamped transcript (ElevenLabs by default).

**Both halves are required for a real answer.** A grid shows what is on screen
and never what was said. On a 24-minute episode the grid alone gives the arc
(someone is accused, a gadget appears, a shadow chases them) while every fact
that matters — what was stolen, the gadget's name and rule, how it resolves —
lives entirely in the audio. Skipping the transcript produces confident,
plausible, wrong summaries. Skip it only when the video has no speech, or the
user explicitly asks for visuals only.

## Resolve `SKILL_DIR` first

Every command below runs a script under `SKILL_DIR/scripts/`. Set `SKILL_DIR` to
the absolute path of the directory holding THIS SKILL.md (your harness reported
it when you read this file). Scripts are always a direct sibling of this file.
On Windows substitute `python` for `python3`.

## Step 1 — frames

```bash
python3 "$SKILL_DIR/scripts/frames.py" "<video>" --out-dir <work-dir> --cells 64
```

Prints `MANIFEST: <path>`. Pick `--cells` by the QUESTION, not the video length —
the real limit is how many pixels each cell survives at after downscaling:

| `--cells` | px per cell | Use for |
| --- | --- | --- |
| 16 | ~392 | reading small on-screen text, UI, subtitles |
| 36 | ~261 | facial expression, fine action, motion beats |
| **64** | ~196 | **plot, scene inventory, recaps, spoilers (default)** |
| 100 | ~157 | rough skim of very long footage; small text is lost |

Useful flags: `--start`/`--end` (`SS`, `MM:SS`, `HH:MM:SS`) to focus a section —
always prefer this over a sparse scan when the user asks about one moment;
`--max-grids N` to cap cost (frames are thinned evenly across the whole range,
never truncated at the tail); `--fps` for the uniform extractor; `--force` to
override extractor choice.

For a URL, download it first (`yt-dlp -f 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best' -o video.mp4 "<url>"`)
and pass the local file.

## Step 2 — transcript

```bash
python3 "$SKILL_DIR/scripts/transcript.py" "<video>" --out <work-dir>/transcript.json --lang th
```

Prints `TRANSCRIPT: <path>`. Sources tried in order (override with `--source`):

1. **elevenlabs** — Scribe v2, word-level timing. Default and best for Thai.
   Needs `ELEVENLABS_API_KEY` (shell env or a `.env` above the working dir).
2. **captions** — native subtitles via yt-dlp. Free and instant, URLs only.
3. **whisper** — local faster-whisper. Free, offline, weaker on Thai.

Omit `--lang` to auto-detect. If every source fails the script exits non-zero —
say so plainly and continue with frames only, rather than inventing dialogue.

## Step 3 — read the grids

`Read` every `grids[].path` from the manifest, **in one message** (parallel tool
calls) so you see them together, then read `transcript.json`.

Each grid is cells laid left-to-right, top-to-bottom, in `grids[g].cols` ×
`grids[g].rows` (the last grid may be smaller so it carries no blank cells).
Cell *i* of grid *g* is `grids[g].cells[i]`, carrying `t_ms` and a human
`t_label`.

**Get timestamps from the manifest, never from the picture.** The grid encodes
order and content; it does not encode the clock. Cells are NOT evenly spaced in
time — dedup removes redundant frames, so the gap between adjacent cells varies.
Map cell → time through the manifest, then align to the transcript by `t_ms`.

## Step 4 — answer

Combine both streams: frames say what is shown, the transcript says what is said,
`t_ms` ties them together. Cite timestamps from the manifest/transcript.

If the user asked something specific, answer it directly. Otherwise summarize
what happens — structure, key beats, notable visuals, and what is actually said.
Never paste the raw transcript back; synthesize it.

Clean up the work dir with `rm -rf` when the user is unlikely to follow up.

## What this cannot do

Say so plainly rather than guessing:

- **Continuous motion** — easing, velocity, bounce, overshoot. Grids give
  positions, not the curve between them; a 250 ms ease is one frame at 4 fps.
  Discrete, staged motion (text animating in, items appearing one by one,
  arrows drawing) does read fine.
- **Frame-exact timing.** Timestamps are as precise as the sampled frame, not
  the cut.
- **Anything inaudible and off-screen.** If neither stream carries it, it is not
  in the answer.

## Cost

Measured: 64 frames read individually ≈ 12.5k tokens; the same 64 as one grid
≈ 1.9k — about 7x cheaper. Past a 1568 px long edge every grid costs the same
~1.9k regardless of cell count, so extra cells are free in tokens and paid for
in per-cell resolution. A 24-minute episode at `--cells 64` is ~7 grids ≈ 13k
tokens for full visual coverage.

## Requirements

`ffmpeg` + `ffprobe` on PATH. Python 3.9+, stdlib only. Optional: `yt-dlp`
(URLs, native captions), `faster-whisper` (offline transcripts),
`ELEVENLABS_API_KEY` (best transcripts, especially Thai).
