## What it does

`image-gen-router` generates an image from a text prompt using one of two local,
headless backends: GPT through the Codex CLI, or Gemini through the Antigravity
`agy` CLI. Both run under an account you are already logged into, so there is no
API key and no per-image billing — the same as typing the prompt into that tool
yourself.

The model choice is the whole point of the skill. If you name a backend it uses
it; if you do not, it asks which one *before* generating rather than picking for
you and presenting a result you did not ask for.

## When to reach for it

Type `/image-gen-router`, or the agent reaches for it when a request fits — it
is model-invoked and fires on any free-form "generate / draw / make me an image"
that does not already name a different tool.

| Your situation | Where to go |
| --- | --- |
| "Generate an image of …" with no tool named | This skill — it will ask which backend |
| "Use gemini to draw …" / "with gpt, make …" | This skill — it uses what you named, no question |
| Editing an existing image file | Not this skill |
| Removing a background | Not this skill |
| A graphic that is really HTML/CSS | Not this skill |
| You want Midjourney, Stable Diffusion, or the OpenAI Images API | Not this skill — it only drives the two local CLIs |

## Prerequisites

Install whichever backend you plan to use, and be logged in. You only need the
one you will actually call.

| Backend | Needs |
| --- | --- |
| GPT | [`codex` CLI](https://github.com/openai/codex) on PATH, logged in (`codex login status`), with an imagegen-capable default model in `~/.codex/config.toml` |
| Gemini | [Antigravity `agy` CLI](https://antigravity.google/) on PATH and logged in (`agy --version`) |

## The routing decision

Everything else in the skill — subject, style, aspect, palette, mood — flows
straight from your prompt into the chosen backend. The only branch is which one
runs:

| What you said | What happens |
| --- | --- |
| GPT, OpenAI, ChatGPT, codex, "the gpt one" | Runs the GPT backend |
| Gemini, Google, agy, Antigravity, "nano banana" | Runs the Gemini backend |
| Nothing about a model | Asks, with the two presented as equals — neither marked recommended |

Once the backend is known it is never re-asked within the same request.

## Common questions

**Why does it ask instead of just picking one?**
Because the two produce visibly different images, and a default would quietly
make an aesthetic decision on your behalf. Naming a backend in your prompt skips
the question entirely.

**Does this use my API credits?**
No. Both paths run under an existing login — the Codex CLI under your ChatGPT
account, `agy` under your Google account. No API key is read and no per-image
charge is incurred.

**Where does the file end up?**
Pass `--out` for a specific path. Without it, the backend saves wherever it
normally would and the script prints the absolute path on its last line as
`IMAGE: <path>`.

## It's working if

- You named a backend and it generated without asking anything.
- You did not name one and it asked before generating, not after.
- The final line of output is an absolute path, and a real image is at it.

## Where it fits

A reach-for-it-anytime standalone — one prompt in, one image out, no
prerequisites beyond a logged-in CLI. It shares this repo with
[`video-understand`](./video-understand.md), which reads video rather than
generating pictures.
