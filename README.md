# ii23-skills

A small collection of [Agent Skills](https://www.skills.sh/) for Claude Code (and any
skills-compatible agent) — image generation and video understanding. Install any
skill with one command.

```bash
npx skills add andrewii23/ii23-skills
```

This lets you pick which skills to install from this repo. The agent picks them up
automatically the next time it runs.

---

## Skills

### 🎨 image-gen-router

Generate an image from a text prompt, choosing between **two local, headless,
API-key-free backends**:

| Backend | Runs via | Auth |
| --- | --- | --- |
| **GPT** | Codex CLI `imagegen` | your ChatGPT login |
| **Gemini** | Antigravity `agy` CLI | your Google login |

Neither path uses an API key or incurs per-image API billing — it draws on your
existing ChatGPT / Google account, exactly as if you typed the prompt into that
tool yourself.

**The defining feature is model choice:**

- If you name a backend in your request (`"use gemini to…"`, `"with gpt, draw…"`),
  it uses it directly.
- If you **don't** name one, it asks which to use *before* generating — GPT or
  Gemini, presented as equals.

**Examples that trigger it:**

> "generate an image of a mountain at sunset"
> "use gemini to make a flat-vector server icon"
> "with gpt, draw a watercolor fox curled up asleep, save to ~/Desktop/fox.png"

See [`skills/image-gen-router/`](skills/image-gen-router/) for the full skill.

#### Requirements

Install whichever backend(s) you want to use and make sure you're logged in:

- **GPT backend** — the [`codex` CLI](https://github.com/openai/codex) on your PATH,
  logged in (`codex login status`), with a default model that supports image
  generation (e.g. `gpt-5.5`) in `~/.codex/config.toml`.
- **Gemini backend** — the [Antigravity `agy` CLI](https://antigravity.google/)
  on your PATH and logged in (`agy --version`).

You only need the backend(s) you actually plan to use.

---

### 🎬 video-understand

Watch and actually understand a video — local file or URL. Ask for a summary, a
spoiler/recap, "what did they say at 3:20", or "find the part where X happens".

**How it works.** Instead of reading frames one at a time, it packs many frames
into **grid images** (a 24-minute episode fits in ~7 pictures) and pairs them
with a **timestamped transcript**. The agent reads the pictures and the words
together, then answers.

**Why grids.** Measured: 64 frames read individually ≈ 12.5k tokens; the same 64
packed into one grid ≈ 1.9k — **about 7x cheaper**, and a 24-minute episode
costs ~13k tokens for full visual coverage.

> Published work is more conservative than what current models can actually do.
> [IG-VLM](https://arxiv.org/abs/2403.18406) peaks at 6 frames per grid and
> [Video Panels](https://arxiv.org/html/2509.23724v2) at 2×2, degrading by 4×4 —
> both on older, smaller VLMs. Tested here on a 24-minute 720p episode, **36 and
> 64 cells stayed fully legible** and 100 still carried the plot. Pick cell count
> by the question, not the clip length:

| `--cells` | px per cell | Use for |
| --- | --- | --- |
| 16 | ~392 | reading small on-screen text, UI, subtitles |
| 36 | ~261 | facial expression, fine action, motion beats |
| **64** | ~196 | **plot, recaps, spoilers (default)** |
| 100 | ~157 | rough skim; small text is lost |

**Two extractors, picked automatically.** Cut-heavy footage (film, anime) is
covered by keyframes — 404 of them pulled from a 24-minute episode in ~1.2s.
Low-cut footage (screen recordings, talking heads) has keyframes that follow the
encoder rather than the content, so it falls back to uniform sampling. The choice
is made by probing how many frames are actually *distinct*, not by counting them:
on the test clips that was 100% vs 71%, and picking by raw density chose exactly
backwards.

**Deduplication does the heavy lifting.** Measured on a screen recording, **88%
of frames at 12fps** and 54% at 4fps were near-identical to the one before, while
real events scored a 10–40x higher delta. Raising the frame rate mostly buys
duplicates; dropping them is what buys coverage.

**Both halves are required.** Grids show what is on screen and never what was
said — on the test episode the pictures gave the arc, but what was stolen, the
gadget's name, and how it resolved lived entirely in the audio.

**Honest limits:** continuous motion (easing, velocity, bounce) is *not*
readable — grids give positions, not the curve between them. Discrete, staged
motion (text animating in, items appearing one by one) reads fine.

**Examples that trigger it:**

> "summarize this video" · "สปอยคลิปนี้ให้หน่อย" · "what happens in ~/Movies/ep12.mp4"
> "what did they say around 3:20?" · "find the part where the logo appears"

See [`skills/video-understand/`](skills/video-understand/) for the full skill.

#### Requirements

- **`ffmpeg` + `ffprobe`** on your PATH (`brew install ffmpeg`) — required.
- **`ELEVENLABS_API_KEY`** — recommended, and the most accurate option for Thai.
  Set it in your shell or a `.env` file. Without it the skill falls back to
  native subtitles (via `yt-dlp`, URLs only) or offline `faster-whisper`.
- **`yt-dlp`** — optional, for URLs and free native captions.
- **`faster-whisper`** — optional, for free offline transcripts.

Python 3.9+, standard library only.

---

## Repo layout

```
ii23-skills/
├── skills.sh.json          # skills.sh manifest (groupings)
├── skills/
│   ├── image-gen-router/
│   │   ├── SKILL.md         # the skill definition
│   │   └── scripts/
│   │       ├── gen_gpt.py     # GPT (codex) backend
│   │       └── gen_gemini.py  # Gemini (agy) backend
│   └── video-understand/
│       ├── SKILL.md         # the skill definition
│       └── scripts/
│           ├── frames.py      # extract → dedup → grid-pack + manifest
│           └── transcript.py  # ElevenLabs / captions / whisper
├── README.md
└── LICENSE
```

## Manual install

If you'd rather not use `npx skills`, copy the skill folder into your skills dir:

```bash
git clone https://github.com/andrewii23/ii23-skills
cp -R ii23-skills/skills/image-gen-router ~/.claude/skills/
cp -R ii23-skills/skills/video-understand ~/.claude/skills/
```

Restart your agent (or start a new session) so it picks up the new skill.

## License

[MIT](LICENSE)
