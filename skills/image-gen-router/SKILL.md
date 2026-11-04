---
name: image-gen-router
description: >-
  Generate an image from a text prompt using one of two local headless backends
  - GPT (Codex CLI, under your ChatGPT login) or Gemini (Antigravity agy CLI,
  under your Google login). Both are API-key-free with no per-image billing. Use
  whenever the user wants to create, generate, draw, make, or render a picture,
  illustration, icon, thumbnail, logo, poster, artwork, or background from a
  description - "generate an image of a mountain at sunset", "make me a
  flat-vector server icon", "draw a cat in watercolor". The defining feature is
  model choice: if the user names a backend (GPT, OpenAI, codex OR Gemini,
  Google, agy, antigravity, nano banana), use it directly; if they do NOT name
  one, ASK which to use before generating. Trigger even when no backend is
  named - any free-form image-generation request not already pointing at a
  different tool (Midjourney, Stable Diffusion, DALL-E API, OpenAI Images API)
  belongs here. Do NOT use for editing an existing image, removing backgrounds,
  or HTML/CSS-rendered graphics.
---

# Image Gen Router

Claude cannot generate a raster image, but the user's ChatGPT and Google accounts can. This skill
generates a raster image by driving one of two **official CLIs, headless**, under
the account the user is already signed into: no API key, no per-image API bill,
exactly as if the user typed the prompt into that tool themselves.

- **GPT** — the OpenAI **Codex CLI** (`codex exec` with its built-in `$imagegen`
  skill, model `gpt-image-2`), under the user's ChatGPT login. It counts toward
  the Codex plan's usage limits.
- **Gemini** — the Google **Antigravity CLI** (`agy -p`, headless mode, its
  built-in image tool), under the user's Google login. It uses the plan's
  Antigravity quota.

The whole point of this skill is letting the user pick the model. Everything
else (subject, style, aspect, palette, mood) flows straight from the prompt into
the chosen backend.

## The one decision that matters: which backend

Before generating, you must know which backend to use. There are exactly two
cases:

**1. The user already named a backend → use it, don't ask.** Honor whatever
they said and skip straight to generation. Map their words like this:

- GPT, OpenAI, ChatGPT, codex, "the gpt one", DALL·E *(as a model family, not
  the API)* → **gpt**
- Gemini, Google, agy, Antigravity, "nano banana", "the google one" → **gemini**

Asking again when they've already told you is annoying and wastes a turn — the
user was explicit for a reason.

**2. The user did NOT name a backend → ask, with no default.** Use the
`AskUserQuestion` tool with a single question and exactly two options, presented
as equals (neither marked "recommended" — the user didn't express a preference,
so don't manufacture one). For example:

```
AskUserQuestion(questions=[{
  "question": "Which model should generate this image?",
  "header": "Image model",
  "multiSelect": false,
  "options": [
    {"label": "GPT (codex)", "description": "OpenAI image model via Codex CLI, under your ChatGPT login."},
    {"label": "Gemini (agy)", "description": "Google image model via Antigravity CLI, under your Google login."}
  ]
}])
```

Read the answer, map it to `gpt` or `gemini`, and proceed. (If the user picks
"Other" and types something, interpret it — e.g. "whatever's faster" → pick
either and say which you used.)

Once you know the backend, never re-ask within the same request.

## Where to save the file

Ask the user for an output path **only if** the request is about a deliverable
where location obviously matters and they haven't said. Otherwise don't block on
it:

- If they gave a path or an obvious destination ("save it to my Desktop"), pass
  it via `--out`.
- If they don't care, omit `--out` — the script reports wherever the file
  landed.

## Running the chosen backend

Each backend has its own script. Both take the same arguments and both print the
final location on their **last line** as `IMAGE: <abs-path>`. Parse that line to
learn where the file is, then show or describe it to the user.

**GPT backend:**

```bash
python3 ~/.claude/skills/image-gen-router/scripts/gen_gpt.py "<prompt>" [--out <path>] [--timeout <sec>]
```

**Gemini backend:**

```bash
python3 ~/.claude/skills/image-gen-router/scripts/gen_gemini.py "<prompt>" [--out <path>] [--timeout <sec>]
```

Shared options:

- **positional prompt** — subject + style. Be specific: medium, lighting,
  palette, composition, aspect ratio. Both models honor detail. Example:
  `"isometric 3D illustration of a coffee shop, warm pastel palette, soft shadows, 16:9"`.
- **`--prompt-file <path>`** — for long prompts, avoids shell-quoting pain.
- **`--out <path>`** — destination image (`.png` or `.jpg`). Omit to let the
  backend keep its own file and just report the path.
- **`--timeout <sec>`** — default 600. Measured 2026-11-04 (codex 0.166, agy
  1.5.0, one square sticker): GPT 27–35 s, Gemini 50–60 s. Cold starts are
  slower, so don't lower this without reason.

What each script actually runs (both close stdin, or the CLI waits for more
prompt text until the timeout):

| Backend | Command | Where the image lands, and how the script finds it |
| --- | --- | --- |
| GPT | `codex exec --skip-git-repo-check --ephemeral --json --sandbox read-only -c model_reasoning_effort=low "$imagegen …"` | `$CODEX_HOME/generated_images/<thread_id>/`, thread id from the `--json` events; the script copies it (Codex itself is never asked to write) |
| Gemini | `agy -p "…" --output-format json --print-timeout <t>`, run inside `~/.cache/agy-imagegen/workspace` | `~/.gemini/antigravity-cli/brain/<conversation_id>/` (JPEG), id from the JSON envelope; the script copies it, converting with macOS `sips` when `--out` asks for PNG |

Neither run needs a permission bypass: image generation needs no approval, and
no agent is asked to write a file.

After it runs, parse the `IMAGE:` line and tell the user the absolute path. When
helpful, Read the image to confirm it matches the request before reporting
success.

## Worked examples

**1 — user named the model, gave a path:**
> "use gemini to make a minimalist line-art mountain logo, black on white, save to ~/Desktop/logo.png"

Backend is explicit (gemini) and path is explicit → no questions, just run:
```bash
python3 ~/.claude/skills/image-gen-router/scripts/gen_gemini.py \
  "minimalist line-art mountain logo, single weight stroke, black on white" \
  --out ~/Desktop/logo.png
```

**2 — user did NOT name the model:**
> "generate an image of a red panda astronaut floating in space, cinematic photorealistic"

No backend named → `AskUserQuestion` (GPT vs Gemini, no default) → run the
chosen script with the prompt. Don't ask about the path; they didn't mention one
and it's a casual request, so omit `--out` and report where it landed.

**3 — long prompt, model named, no path:**
> "with gpt, render this scene:" (followed by a long paragraph)

Write the paragraph to a temp file and use `--prompt-file`:
```bash
python3 ~/.claude/skills/image-gen-router/scripts/gen_gpt.py \
  --prompt-file /tmp/scene_prompt.txt
```

## Failure handling

Both scripts exit non-zero and explain themselves on stderr:

- **exit 2** — the backend's CLI is missing or not signed in. For GPT, that's
  `codex login status`; for Gemini, the user runs `agy` once interactively and
  signs in (headless reuses those cached credentials). Tell the user exactly
  which login to fix.
- **exit 3** — the CLI ran but produced no image, or timed out. For GPT, check
  that `codex features list` shows `image_generation` enabled. A headless `agy`
  run that hits a tool needing approval still exits 0, so the scripts judge
  success by a real file, never by the exit code. Re-run once; if it persists,
  report the stderr the script printed.

Don't silently fall back to the *other* backend or to a billed image API — the
user chose a backend (or you asked them to), and switching it without saying so
hides what actually happened. If the chosen backend genuinely can't produce an
image, surface the failure and let the user decide whether to try the other one.
