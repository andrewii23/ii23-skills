# ii23-skills

Agent skills for Claude Code (and any skills-compatible agent), built for work
that keeps hitting the same walls: an agent that cannot watch video, and image
generation that bills per picture.

```bash
npx skills add andrewii23/ii23-skills
```

Pick the skills you want; your agent picks them up next time it runs.

---

## Why these exist

### #1: Your agent cannot watch video

**The problem.** Claude reads still images, not video. Hand it a 24-minute
episode and there is no "watch this" — there are 43,000 frames. Read them one at
a time and the bill is brutal: 64 frames at 512px costs about **12,500 tokens**,
and 64 frames does not cover 24 minutes.

So the obvious workarounds fail in opposite directions. Sample a handful of
frames and you miss the story. Sample enough frames and you cannot afford it.

**The fix** is to stop sending frames one at a time. `video-understand` packs
many frames into a single tiled image — a whole 24-minute episode fits in 7
pictures — and pairs them with a timestamped transcript.

| | Cost |
| --- | --- |
| 64 frames, read individually | ~12,500 tokens |
| The same 64 frames, one grid | **~1,900 tokens** |

That is roughly **7x cheaper**. A 24-minute episode costs about 13k tokens for
full visual coverage. A 2h05m film with 1,727 shots is 27 grids, about 51k
tokens, with every shot seen once — cap it with `--budget` when a question
only needs one scene.

Published research is more conservative than what current models can actually
do. [IG-VLM](https://arxiv.org/abs/2403.18406) peaks at 6 frames per grid;
[Video Panels](https://arxiv.org/html/2509.23724v2) peaks at 2x2 and degrades by
4x4 — both measured on older, smaller models. Tested here on a 24-minute 720p
episode, **36 and 64 cells stayed fully legible**, and 100 still carried the
plot.

→ **[`video-understand`](./skills/video-understand/SKILL.md)** · [docs](./docs/video-understand.md)

### #2: Claude can't generate images. Your ChatGPT and Google accounts can.

**The problem.** Claude reads images and can draw in code (SVG, HTML), but it
cannot generate a picture. The usual workaround is an image API: a new key and a
per-image charge, on top of the ChatGPT or Google plan you already pay for.

**The fix** is to drive the official CLIs you are already signed into.
`image-gen-router` runs the OpenAI **Codex CLI** (`codex exec` with its built-in
`$imagegen`, `gpt-image-2`) under your ChatGPT login, and the Google
**Antigravity CLI** (`agy -p`, headless) under your Google login. No API key, no
per-image bill: it uses your plan's own usage, the same as typing the prompt
into those tools yourself. Both run exactly as their docs describe: read-only
sandbox for Codex, no permission bypass for `agy`.

| Backend | Runs | Measured (2026-11-04, one square image) |
| --- | --- | --- |
| GPT | `codex exec "$imagegen …"` (Codex CLI 0.166) | 27–35 s |
| Gemini | `agy -p "…"` (Antigravity CLI 1.5.0) | 50–60 s |

Its defining behaviour is the choice: name a backend and it uses it; stay silent
and it asks which one *before* generating, rather than picking for you.

→ **[`image-gen-router`](./skills/image-gen-router/SKILL.md)** · [docs](./docs/image-gen-router.md)

---

## Skills

| Skill | What it does |
| --- | --- |
| **[video-understand](./skills/video-understand/SKILL.md)** | Watch and understand any video, from a clip to a full film, with or without speech — every shot indexed and seen once, in timestamped grids, plus a transcript. Also culls piles of clips and screens them for burned-in text. |
| **[image-gen-router](./skills/image-gen-router/SKILL.md)** | Generate an image with the Codex CLI (ChatGPT login) or the Antigravity CLI (Google login), API-key-free. |

---

## Requirements

Install only what the skills you took actually need.

**video-understand**

| Need | Why |
| --- | --- |
| `ffmpeg` + `ffprobe` | Required — frame extraction and audio. `brew install ffmpeg` |
| `ELEVENLABS_API_KEY` | Recommended. The most accurate transcripts, especially for Thai. Set it in your shell or a `.env`. |
| `yt-dlp` | Optional — URLs, and free native captions. |
| `faster-whisper` | Optional — free offline transcripts. |
| `swiftc` (macOS) or `tesseract` | Optional — on-screen text: `index.py --ocr`, `text_check.py`, `cull.py --text`. |

Without an ElevenLabs key it falls back to native subtitles (via `yt-dlp`, URLs
only) or offline `faster-whisper`, so the skill still works.

**image-gen-router** — install whichever backend you plan to use, and be logged in:

| Backend | Needs |
| --- | --- |
| GPT | [Codex CLI](https://github.com/openai/codex) on PATH, signed in with ChatGPT (`codex login status`), `image_generation` enabled (`codex features list`) |
| Gemini | [Antigravity CLI `agy`](https://antigravity.google/) on PATH, signed in once through an interactive `agy` session |

Python 3.9+, standard library only.

---

## Repo layout

```
ii23-skills/
├── skills/                  # the skills themselves
│   ├── video-understand/
│   │   ├── SKILL.md         # the agent contract
│   │   └── scripts/         # frames.py, transcript.py
│   └── image-gen-router/
│       ├── SKILL.md
│       └── scripts/         # gen_gpt.py, gen_gemini.py
├── docs/                    # human-facing page per skill
├── .agents/adr/             # why a decision was made
├── .out-of-scope/           # what was deliberately not built, and why
├── CLAUDE.md                # rules for agents editing this repo
└── skills.sh.json           # skills.sh manifest
```

## Manual install

If you would rather not use `npx skills`:

```bash
git clone https://github.com/andrewii23/ii23-skills
cp -R ii23-skills/skills/video-understand ~/.claude/skills/
cp -R ii23-skills/skills/image-gen-router ~/.claude/skills/
```

Restart your agent (or start a new session) so it picks up the new skills.

## License

[MIT](LICENSE)
