#!/usr/bin/env python3
"""Generate an image with the Codex CLI's built-in image generation (GPT backend).

Runs `codex exec` under your ChatGPT login, the same as typing the prompt into
Codex yourself: no API key, no per-image API bill. It counts toward your Codex
plan's usage limits (OpenAI: image turns use them 3-5x faster than plain turns).

Usage:
  python3 gen_gpt.py "a cozy reading nook, warm light, watercolor"
  python3 gen_gpt.py "isometric server room, flat vector" --out ~/Desktop/server.png
  python3 gen_gpt.py --prompt-file prompt.txt --out out.png

How it follows the Codex docs:
  - `$imagegen` in the prompt invokes the built-in image skill explicitly
    (learn.chatgpt.com/docs/image-generation).
  - `--sandbox read-only` (the documented default, set explicitly so a
    danger-full-access config changes nothing): Codex is never asked to copy
    the file. It saves every image under
    $CODEX_HOME/generated_images/<thread_id>/; this script reads the thread id
    from `--json` and copies the image from that folder itself.
  - `--ephemeral` keeps the run out of ~/.codex/sessions (the image is still saved).
  - `-c model_reasoning_effort=low`: the prompt needs no deep reasoning, and
    xhigh configs were seen to time out.

Output:
  - With --out: the image is copied there and that absolute path is printed.
  - Without --out: Codex's own file is left in $CODEX_HOME/generated_images/
    and its absolute path is printed.

Exit codes:
  0  image generated, path printed on the last line as `IMAGE: <abs-path>`
  1  bad args / missing input
  2  codex CLI missing or not authenticated
  3  codex ran but produced no image

Requires `codex` on PATH and logged in (`codex login status`), with image
generation enabled (`codex features list` shows `image_generation ... true`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
GEN_DIR = CODEX_HOME / "generated_images"
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def newest_image(root: Path, since_ts: float) -> Path | None:
    """Newest image under `root` written at/after `since_ts`."""
    if not root.exists():
        return None
    newest = None
    for p in root.rglob("*"):
        if p.suffix.lower() not in IMG_EXTS:
            continue
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt >= since_ts and (newest is None or mt > newest[1]):
            newest = (p, mt)
    return newest[0] if newest else None


def thread_id(jsonl: str) -> str | None:
    for line in jsonl.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            return ev.get("thread_id")
    return None


def run_codex(prompt: str, dest: Path | None, timeout: int) -> Path:
    if not shutil.which("codex"):
        print(
            "codex CLI not found on PATH.\n"
            "Install + login: https://github.com/openai/codex",
            file=sys.stderr,
        )
        sys.exit(2)

    instruction = (
        "$imagegen Generate exactly one image with the EXACT prompt below. "
        "Do not write, copy or move any files; leave the image where Codex "
        "saves it.\n\nPROMPT:\n" + prompt
    )

    started = time.time() - 1  # 1s slack for clock skew
    print(f"-> codex exec (ChatGPT login, no API key) — {len(prompt)} char prompt",
          file=sys.stderr)
    try:
        result = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--json",
             "--sandbox", "read-only", "-c", "model_reasoning_effort=low", instruction],
            stdin=subprocess.DEVNULL,   # an open stdin makes the CLI wait for more prompt text
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

    tid = thread_id(result.stdout)
    # only this run's thread folder; the newest fresh image anywhere only when no thread id came back
    src = newest_image(GEN_DIR / tid, started) if tid else newest_image(GEN_DIR, started)
    if src is None:
        sys.stderr.write(result.stdout + "\n")
        print(
            f"codex finished but no image appeared in {GEN_DIR}/.\n"
            "Check `codex login status` and that `codex features list` shows "
            "image_generation enabled.",
            file=sys.stderr,
        )
        sys.exit(3)

    if dest is None:
        return src

    return save_as(src, dest)


def save_as(src: Path, dest: Path) -> Path:
    """Copy src to dest; convert when the extensions differ and macOS `sips` is available."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    norm = lambda s: {".jpeg": ".jpg"}.get(s.lower(), s.lower())
    if not dest.suffix or norm(dest.suffix) == norm(src.suffix):
        target = dest if dest.suffix else dest.with_suffix(src.suffix)
        shutil.copyfile(src, target)
        return target
    fmt = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(dest.suffix.lower())
    if fmt and shutil.which("sips"):
        r = subprocess.run(["sips", "-s", "format", fmt, str(src), "--out", str(dest)], capture_output=True, text=True)
        if r.returncode == 0 and dest.exists():
            return dest
    target = dest.with_suffix(src.suffix)
    print(f"note: codex wrote {src.suffix}; saved as {target.name} (no converter for {dest.suffix})", file=sys.stderr)
    shutil.copyfile(src, target)
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an image via Codex built-in image generation (GPT).")
    ap.add_argument("prompt", nargs="?", help="The image prompt (or use --prompt-file).")
    ap.add_argument("--prompt-file", help="Read the prompt from this file instead.")
    ap.add_argument("--out", help="Destination path (.png/.jpg). Omit to keep codex's default location.")
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
