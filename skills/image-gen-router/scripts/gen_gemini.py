#!/usr/bin/env python3
"""Generate an image via the Antigravity CLI `agy` headless (Gemini backend).

`agy -p` runs a single prompt non-interactively. We tell its agent to use the
built-in image-gen tool and save the PNG to a path we control, so we always
know where the file landed. Runs under your Google/Antigravity login — no API
key handling here.

Usage:
  python3 gen_gemini.py "a cozy reading nook, warm light, watercolor"
  python3 gen_gemini.py "isometric server room, flat vector" --out ~/Desktop/server.png
  python3 gen_gemini.py --prompt-file prompt.txt --out out.png

Output:
  - With --out: agy is told to save there; that absolute path is printed.
  - Without --out: a temp path under ~/.cache/agy-imagegen/ is used and printed.

Exit codes:
  0  image generated, path printed on the last line as `IMAGE: <abs-path>`
  1  bad args / missing input
  2  agy CLI missing
  3  agy ran but produced no image / timed out

Requires:
  - `agy` CLI on PATH and logged in. Verify with `agy --version`.
  - We pass --dangerously-skip-permissions so the agent's tool calls (image
    gen + file write) run without an interactive approval prompt, which would
    otherwise hang a non-interactive run.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "agy-imagegen"
# A signature agy itself uses for generated artifacts; we scan for these as a
# fallback if the agent saved somewhere other than our requested path.
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def newest_image_under(root: Path, since_ts: float) -> Path | None:
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


def extract_path_from_output(text: str) -> Path | None:
    """Best-effort: pull an absolute image path the agent printed."""
    candidates = re.findall(r"(/[^\s'\"`]+\.(?:png|jpe?g|webp))", text, re.IGNORECASE)
    # Prefer the last mention (agent usually states the final path last).
    for cand in reversed(candidates):
        p = Path(cand)
        if p.exists():
            return p
    return None


def run_agy(prompt: str, dest: Path, timeout: int) -> Path:
    if not shutil.which("agy"):
        print(
            "agy CLI not found on PATH.\n"
            "Antigravity CLI is required for the Gemini backend.",
            file=sys.stderr,
        )
        sys.exit(2)

    dest.parent.mkdir(parents=True, exist_ok=True)

    instruction = (
        "Generate exactly one image using your built-in image generation tool "
        "with the EXACT prompt below. Save the resulting PNG to this absolute "
        f"path: {dest}\n"
        f"Then run 'ls -la {dest}' to confirm the file exists, and state the "
        "final absolute path on its own line.\n\nPROMPT:\n" + prompt
    )

    started = time.time() - 1  # clock-skew slack
    print(f"-> agy headless (Gemini) — {len(prompt)} char prompt", file=sys.stderr)
    try:
        result = subprocess.run(
            [
                "agy",
                "--dangerously-skip-permissions",
                "--print-timeout", f"{max(1, timeout - 15)}s",
                "-p", instruction,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"agy timed out after {timeout}s", file=sys.stderr)
        sys.exit(3)

    out_text = (result.stdout or "") + "\n" + (result.stderr or "")

    if result.returncode != 0:
        sys.stderr.write(out_text + "\n")
        print(f"agy exited non-zero ({result.returncode})", file=sys.stderr)
        # Don't give up yet — the file may still have been written.

    # Path A: agent honored our requested dest (preferred).
    if dest.exists() and dest.stat().st_mtime >= started:
        return dest

    # Path B: agent printed an absolute path that exists.
    printed = extract_path_from_output(out_text)
    if printed is not None and printed.stat().st_mtime >= started:
        shutil.copyfile(printed, dest)
        return dest

    # Path C: scan agy's likely artifact dirs for a fresh image.
    search_roots = [
        Path.home() / ".antigravity",
        Path.home() / ".agy",
        Path.home() / ".cache" / "antigravity",
        Path(os.getcwd()),
    ]
    for root in search_roots:
        found = newest_image_under(root, started)
        if found is not None:
            shutil.copyfile(found, dest)
            return dest

    sys.stderr.write(out_text + "\n")
    print(
        "agy finished but no fresh image was found.\n"
        "Check `agy --version` and that your Antigravity account can generate "
        "images. Re-running once often clears a transient backend hiccup.",
        file=sys.stderr,
    )
    sys.exit(3)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an image via agy headless (Gemini).")
    ap.add_argument("prompt", nargs="?", help="The image prompt (or use --prompt-file).")
    ap.add_argument("--prompt-file", help="Read the prompt from this file instead.")
    ap.add_argument("--out", help="Destination PNG path. Omit for a temp path under ~/.cache.")
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

    if args.out:
        dest = Path(args.out).expanduser().resolve()
    else:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = str(int(time.time()))
        dest = CACHE_DIR / f"agy_{stamp}.png"

    out = run_agy(prompt, dest, args.timeout)
    print(f"\nIMAGE: {out.resolve()}")


if __name__ == "__main__":
    main()
