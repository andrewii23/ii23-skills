#!/usr/bin/env python3
"""Generate an image via the Codex CLI's built-in `imagegen` tool (GPT backend).

Runs under your logged-in ChatGPT account, so it never touches the OpenAI
Images API, OpenRouter, or any API key — no per-image billing.

Usage:
  python3 gen_gpt.py "a cozy reading nook, warm light, watercolor"
  python3 gen_gpt.py "isometric server room, flat vector" --out ~/Desktop/server.png
  python3 gen_gpt.py --prompt-file prompt.txt --out out.png

Output:
  - With --out: the PNG is copied there and that absolute path is printed.
  - Without --out: Codex's own file is left in ~/.codex/generated_images/ and
    its absolute path is printed.

Exit codes:
  0  image generated, path printed on the last line as `IMAGE: <abs-path>`
  1  bad args / missing input
  2  codex CLI missing or not authenticated
  3  codex ran but produced no image

Requires:
  - `codex` CLI on PATH and logged in (`codex login status`).
  - ~/.codex/config.toml default model supports imagegen (e.g. gpt-5.5).
    Do NOT force gpt-5 / gpt-5-codex — ChatGPT-account auth rejects them.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

GEN_DIR = Path.home() / ".codex" / "generated_images"


def find_codex_image(since_ts: float) -> Path | None:
    """Newest codex-generated PNG created at/after `since_ts`."""
    if not GEN_DIR.exists():
        return None
    newest = None
    for p in GEN_DIR.rglob("ig_*.png"):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt >= since_ts and (newest is None or mt > newest[1]):
            newest = (p, mt)
    return newest[0] if newest else None


def run_codex(prompt: str, dest: Path | None, timeout: int) -> Path:
    if not shutil.which("codex"):
        print(
            "codex CLI not found on PATH.\n"
            "Install + login: https://github.com/openai/codex",
            file=sys.stderr,
        )
        sys.exit(2)

    if dest is not None:
        instruction = (
            f"Generate one image using the imagegen tool with the EXACT prompt "
            f"below. After it is generated, copy the resulting PNG to {dest} and "
            f"run 'ls -la {dest}' to confirm it exists.\n\nPROMPT:\n{prompt}"
        )
    else:
        instruction = (
            "Generate one image using the imagegen tool with the EXACT prompt "
            "below. After it is generated, print the absolute path of the saved "
            "PNG.\n\nPROMPT:\n" + prompt
        )

    started = time.time() - 1  # 1s slack for clock skew
    print(f"-> codex headless (ChatGPT login, no API key) — {len(prompt)} char prompt",
          file=sys.stderr)
    try:
        result = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", instruction],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"codex exec timed out after {timeout}s", file=sys.stderr)
        sys.exit(3)

    if result.returncode != 0:
        sys.stderr.write(result.stdout + "\n")
        sys.stderr.write(result.stderr + "\n")
        if "login" in (result.stdout + result.stderr).lower():
            print("Looks like an auth problem — run `codex login status`.",
                  file=sys.stderr)
            sys.exit(2)
        print(f"codex exec failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(3)

    if dest is not None and dest.exists() and dest.stat().st_mtime >= started:
        return dest

    src = find_codex_image(started)
    if src is None:
        sys.stderr.write(result.stdout + "\n")
        print(
            "codex finished but no PNG appeared in ~/.codex/generated_images/.\n"
            "Check `codex login status` and that the model in "
            "~/.codex/config.toml supports imagegen.",
            file=sys.stderr,
        )
        sys.exit(3)

    if dest is None:
        return src

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an image via Codex imagegen (GPT).")
    ap.add_argument("prompt", nargs="?", help="The image prompt (or use --prompt-file).")
    ap.add_argument("--prompt-file", help="Read the prompt from this file instead.")
    ap.add_argument("--out", help="Destination PNG path. Omit to keep codex's default location.")
    ap.add_argument("--timeout", type=int, default=600, help="Seconds before giving up (default 600).")
    args = ap.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
    elif args.prompt:
        prompt = args.prompt.strip()
    else:
        print("error: provide a prompt (positional) or --prompt-file", file=sys.stderr)
        sys.exit(1)

    if not prompt:
        print("error: prompt is empty", file=sys.stderr)
        sys.exit(1)

    dest = Path(args.out).expanduser().resolve() if args.out else None
    out = run_codex(prompt, dest, args.timeout)

    print(f"\nIMAGE: {out.resolve()}")


if __name__ == "__main__":
    main()
