# agent-skills

A small collection of [Agent Skills](https://www.skills.sh/) for Claude Code (and any
skills-compatible agent). Install any skill with one command.

```bash
npx skills add andrewii23/agent-skills
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

## Repo layout

```
agent-skills/
├── skills.sh.json          # skills.sh manifest (groupings)
├── skills/
│   └── image-gen-router/
│       ├── SKILL.md         # the skill definition
│       └── scripts/
│           ├── gen_gpt.py     # GPT (codex) backend
│           └── gen_gemini.py  # Gemini (agy) backend
├── README.md
└── LICENSE
```

## Manual install

If you'd rather not use `npx skills`, copy the skill folder into your skills dir:

```bash
git clone https://github.com/andrewii23/agent-skills
cp -R agent-skills/skills/image-gen-router ~/.claude/skills/
```

## License

[MIT](LICENSE)
