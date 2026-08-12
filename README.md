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
full visual coverage; a 67-minute film costs about 15k.

Published research is more conservative than what current models can actually
do. [IG-VLM](https://arxiv.org/abs/2403.18406) peaks at 6 frames per grid;
[Video Panels](https://arxiv.org/html/2509.23724v2) peaks at 2x2 and degrades by
4x4 — both measured on older, smaller models. Tested here on a 24-minute 720p
episode, **36 and 64 cells stayed fully legible**, and 100 still carried the
plot.

→ **[`video-understand`](./skills/video-understand/SKILL.md)** · [docs](./docs/video-understand.md)

### #2: Pictures shouldn't cost money you already pay

**The problem.** Generating an image usually means an API key and a per-image
charge — on top of the ChatGPT or Google subscription you are already paying
for.

**The fix** is to drive the tools you are already logged into. `image-gen-router`
runs GPT through the Codex CLI and Gemini through the Antigravity CLI. No API
key, no per-image billing — the same as typing the prompt into those tools
yourself.

Its defining behaviour is the choice: name a backend and it uses it; stay silent
and it asks which one *before* generating, rather than picking for you.

→ **[`image-gen-router`](./skills/image-gen-router/SKILL.md)** · [docs](./docs/image-gen-router.md)

---

## Skills

| Skill | What it does |
| --- | --- |
| **[video-understand](./skills/video-understand/SKILL.md)** | Watch and understand any video — grid-packed frames plus a timestamped transcript. |
| **[image-gen-router](./skills/image-gen-router/SKILL.md)** | Generate an image via GPT (Codex) or Gemini (Antigravity), API-key-free. |

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

Without an ElevenLabs key it falls back to native subtitles (via `yt-dlp`, URLs
only) or offline `faster-whisper`, so the skill still works.

**image-gen-router** — install whichever backend you plan to use, and be logged in:

| Backend | Needs |
| --- | --- |
| GPT | [`codex` CLI](https://github.com/openai/codex) on PATH, logged in, with an imagegen-capable default model in `~/.codex/config.toml` |
| Gemini | [Antigravity `agy` CLI](https://antigravity.google/) on PATH and logged in |

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
