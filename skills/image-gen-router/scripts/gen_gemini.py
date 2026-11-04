#!/usr/bin/env python3
"""Generate an image with the Antigravity CLI `agy` in headless mode (Gemini backend).

Runs `agy -p` under your Google login, the same as typing the prompt into
Antigravity yourself: no API key, no per-image API bill. It uses your plan's
Antigravity quota (and AI credits only if you turned that on).

Usage:
  python3 gen_gemini.py "a cozy reading nook, warm light, watercolor"
  python3 gen_gemini.py "isometric server room, flat vector" --out ~/Desktop/server.png
  python3 gen_gemini.py --prompt-file prompt.txt --out out.png

How it follows the Antigravity headless docs (antigravity.google/docs/cli/headless):
  - `-p` runs one prompt and exits; `--output-format json` returns one envelope
    with `conversation_id`, `status` and `response`.
  - No `--dangerously-skip-permissions`: image generation needs no approval,
    and the agent is never asked to write a file. agy saves each image itself
    under ~/.gemini/antigravity-cli/brain/<conversation_id>/ (measured on
    agy 1.5.0); this script copies it from there.
  - A tool that would need approval is soft-denied in headless mode (exit 0 plus
    a stderr notice), so success is judged by a real file, not the exit code.
  - agy runs inside ~/.cache/agy-imagegen/workspace so it never treats your
    project folder as its workspace.

Output:
  - With --out: the image is copied there and that absolute path is printed.
    agy writes JPEG; when --out asks for another format, macOS `sips` converts
    it, and without `sips` the file keeps agy's extension.
  - Without --out: agy's own file is left in its brain folder and its absolute
    path is printed.

Exit codes:
  0  image generated, path printed on the last line as `IMAGE: <abs-path>`
  1  bad args / missing input
  2  agy CLI missing or not signed in
  3  agy ran but produced no image / timed out

Requires `agy` on PATH, signed in once through an interactive `agy` session
(headless reuses those cached credentials).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
WORKSPACE = Path.home() / ".cache" / "agy-imagegen" / "workspace"
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


def printed_image(text: str, since_ts: float) -> Path | None:
    """An existing, fresh image path the agent printed (it usually states the path last)."""
    for cand in reversed(re.findall(r"(/[^\s'\"`)\]]+\.(?:png|jpe?g|webp))", text, re.IGNORECASE)):
        p = Path(cand)
        if p.exists() and p.stat().st_mtime >= since_ts:
            return p
    return None


def save_as(src: Path, dest: Path) -> Path:
    """Copy src to dest; convert when the extensions differ and `sips` is available."""
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
    print(f"note: agy wrote {src.suffix}; saved as {target.name} (no converter for {dest.suffix})", file=sys.stderr)
    shutil.copyfile(src, target)
    return target


def run_agy(prompt: str, dest: Path | None, timeout: int) -> Path:
    if not shutil.which("agy"):
        print(
            "agy CLI not found on PATH.\n"
            "Antigravity CLI is required for the Gemini backend: https://antigravity.google/",
            file=sys.stderr,
        )
        sys.exit(2)

    instruction = (
        "Generate exactly one image with your built-in image generation tool, "
        "using the EXACT prompt below. Do not write, copy or move any files "
        "yourself. When it is done, state the absolute path of the generated "
        "image on its own line.\n\nPROMPT:\n" + prompt
    )

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    started = time.time() - 1  # clock-skew slack
    print(f"-> agy headless (Google login, no API key) — {len(prompt)} char prompt", file=sys.stderr)
    try:
        result = subprocess.run(
            ["agy", "-p", instruction, "--output-format", "json",
             "--print-timeout", f"{max(1, timeout - 15)}s"],
            stdin=subprocess.DEVNULL,   # an open stdin makes the CLI wait for more prompt text
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE,
        )
    except subprocess.TimeoutExpired:
        print(f"agy timed out after {timeout}s", file=sys.stderr)
        sys.exit(3)

    out_text = (result.stdout or "") + "\n" + (result.stderr or "")
    if "authentication required" in out_text.lower():
        sys.stderr.write(out_text + "\n")
        print("agy is not signed in — run `agy` once interactively and sign in.", file=sys.stderr)
        sys.exit(2)

    try:
        env = json.loads(result.stdout)
    except ValueError:
        env = {}
    conv = env.get("conversation_id")

    if conv:  # only this run's conversation folder, so a soft-denied run never picks up another run's image
        src = newest_image(BRAIN_DIR / conv, started)
    else:     # no envelope: the path the agent printed, else the newest fresh image agy saved
        src = printed_image(out_text, started) or newest_image(BRAIN_DIR, started)
    if src is None:
        sys.stderr.write(out_text + "\n")
        print(
            f"agy finished (status {env.get('status', 'unknown')}, exit {result.returncode}) "
            "but no fresh image was found.\n"
            "Check `agy --version` and that your account can generate images. "
            "Re-running once often clears a transient backend hiccup.",
            file=sys.stderr,
        )
        sys.exit(3)

    return save_as(src, dest) if dest is not None else src


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an image via agy headless (Gemini).")
    ap.add_argument("prompt", nargs="?", help="The image prompt (or use --prompt-file).")
    ap.add_argument("--prompt-file", help="Read the prompt from this file instead.")
    ap.add_argument("--out", help="Destination path (.png/.jpg). Omit to keep agy's own file.")
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
    out = run_agy(prompt, dest, args.timeout)
    print(f"\nIMAGE: {out.resolve()}")


if __name__ == "__main__":
    main()
