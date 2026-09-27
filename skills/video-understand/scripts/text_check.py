#!/usr/bin/env python3
"""Flag videos that carry burned-in text -- subtitles, captions, title cards.

For picking raw footage (b-roll, reference clips) out of a pile of downloads:
the clips you can reuse are the ones nobody has already typed over. This does
not describe WHAT is on screen -- that is frames.py's job -- it only answers
"is there text on it, and roughly how much".

Samples a few frames evenly across each video at full resolution (subtitles are
small; downscaling first is how they get missed) and runs OCR on each.

OCR backend, first available wins:
  vision     macOS Vision framework via a tiny Swift helper, compiled once and
             cached. Reads Chinese, Japanese, Korean, Thai and English.
  tesseract  `tesseract` on PATH (any OS). Needs the language packs you care
             about installed, e.g. chi_sim, tha.

Usage:
  python3 text_check.py VIDEO [VIDEO ...] [--samples 6] [--max-chars 8]
                        [--out report.json]

Output:
  a table on stderr, sorted cleanest first
  report JSON: {backend, samples, videos:[{video, duration_s, chars, clean,
                frames:[{t_ms, chars, text}]}]}
  prints `REPORT: <abs-path>` on the last line

Exit codes:
  0  report written
  1  bad args / missing input
  2  no OCR backend available

Requires: ffmpeg + ffprobe on PATH. Python stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path.home() / ".cache" / "video-understand"

# Measured on 54 RedNote clips (6 samples each, Vision backend): OCR noise on
# clean footage topped out at 4 chars (a stray "ーー", a background sign), while
# the smallest real overlay -- a phone screenshot's status bar -- was 18 and
# burned-in subtitles ran 30-1122. 8 sits in that gap.
MAX_CHARS = 8


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"{tool} not found on PATH. Install ffmpeg (brew install ffmpeg).")


def duration(video: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def vision_binary() -> Path | None:
    """Compile ocr.swift once; reuse until the source changes."""
    if platform.system() != "Darwin" or shutil.which("swiftc") is None:
        return None
    src = HERE / "ocr.swift"
    binary = CACHE / "ocr"
    if binary.exists() and binary.stat().st_mtime >= src.stat().st_mtime:
        return binary
    CACHE.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["swiftc", "-O", str(src), "-o", str(binary)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[text_check] swiftc failed: {r.stderr[-300:]}", file=sys.stderr)
        return None
    return binary


# Short codes people type -> the codes Vision accepts.
VISION_LANGS = {"th": "th-TH", "en": "en-US", "zh": "zh-Hans", "zh-tw": "zh-Hant",
                "ja": "ja-JP", "ko": "ko-KR", "vi": "vi-VT", "id": "id-ID",
                "ms": "ms-MY", "ar": "ar-SA", "ru": "ru-RU", "hi": "hi-IN"}
TESS_LANGS = {"th": "tha", "en": "eng", "zh": "chi_sim", "zh-tw": "chi_tra",
              "ja": "jpn", "ko": "kor", "vi": "vie", "id": "ind"}


def vision_langs(langs: str) -> str:
    return ",".join(VISION_LANGS.get(x.strip().lower(), x.strip()) for x in langs.split(","))


def tess_langs(langs: str) -> str:
    return "+".join(TESS_LANGS.get(x.strip().lower(), x.strip()) for x in langs.split(","))


def ocr_vision(binary: Path, images: list[Path], langs: str = "zh,en") -> dict[str, dict]:
    env = {**os.environ, "OCR_LANGS": vision_langs(langs)}
    r = subprocess.run([str(binary), *map(str, images)], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: dict[str, dict] = {}
    for line in r.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[row["path"]] = row
    return out


def ocr_tesseract(images: list[Path], langs: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for img in images:
        r = subprocess.run(["tesseract", str(img), "-", "-l", langs],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        text = " | ".join(ln.strip() for ln in r.stdout.splitlines() if ln.strip())
        chars = sum(1 for ch in text if not ch.isspace() and ch != "|")
        out[str(img)] = {"path": str(img), "chars": chars, "text": text}
    return out


def sample_frames(video: str, dur: float, n: int, dest: Path) -> list[tuple[int, Path]]:
    """n frames at the middle of n equal slices -- never the first frame, which
    is often a black lead-in or a thumbnail-style title card."""
    frames = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        p = dest / f"s_{i:02d}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", str(p)],
            capture_output=True,
        )
        if p.exists():
            frames.append((int(round(t * 1000)), p))
    return frames


def main() -> None:
    ap = argparse.ArgumentParser(description="Flag videos with burned-in text.")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--samples", type=int, default=6,
                    help="Frames checked per video (default 6).")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS,
                    help="A video is 'clean' at or under this many characters "
                         f"across all samples (default {MAX_CHARS}).")
    ap.add_argument("--backend", choices=["auto", "vision", "tesseract"], default="auto")
    ap.add_argument("--lang", default="zh,en",
                    help="Languages to read, comma-separated: th, en, zh, ja, ko ... "
                         "(default zh,en). Name the language of the text you expect -- "
                         "Vision reads only the scripts it is told to.")
    ap.add_argument("--out", default="text_check.json")
    args = ap.parse_args()

    need("ffmpeg")
    need("ffprobe")
    videos = [str(Path(v).expanduser()) for v in args.videos]
    missing = [v for v in videos if not Path(v).exists()]
    if missing:
        sys.exit(f"no such file: {missing[0]}")

    backend, binary = None, None
    if args.backend in ("auto", "vision"):
        binary = vision_binary()
        if binary:
            backend = "vision"
    if backend is None and args.backend in ("auto", "tesseract") and shutil.which("tesseract"):
        backend = "tesseract"
    if backend is None:
        print("[text_check] no OCR backend: needs macOS + swiftc, or tesseract on PATH",
              file=sys.stderr)
        sys.exit(2)

    tmp = Path(tempfile.mkdtemp(prefix="vu_text_"))
    report = []
    try:
        for vi, video in enumerate(videos):
            dur = duration(video)
            work = tmp / f"v{vi:04d}"
            work.mkdir()
            frames = sample_frames(video, dur, args.samples, work) if dur > 0 else []
            paths = [p for _, p in frames]
            rows = (ocr_vision(binary, paths, args.lang) if backend == "vision"
                    else ocr_tesseract(paths, tess_langs(args.lang))) if paths else {}
            per = [{"t_ms": t, "chars": rows.get(str(p), {}).get("chars", 0),
                    "text": rows.get(str(p), {}).get("text", "")} for t, p in frames]
            total = sum(f["chars"] for f in per)
            report.append({"video": str(Path(video).resolve()),
                           "duration_s": round(dur, 2), "chars": total,
                           "clean": bool(frames) and total <= args.max_chars,
                           "frames": per})
            shutil.rmtree(work, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    report.sort(key=lambda r: (not r["clean"], r["chars"]))
    for r in report:
        mark = "clean" if r["clean"] else "TEXT "
        print(f"[text_check] {mark} {r['chars']:>5} chars  {r['duration_s']:>7.1f}s  "
              f"{Path(r['video']).name}", file=sys.stderr)
    clean = sum(r["clean"] for r in report)
    print(f"[text_check] {backend}: {clean}/{len(report)} clean", file=sys.stderr)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"backend": backend, "samples": args.samples,
                               "max_chars": args.max_chars, "videos": report},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT: {out.resolve()}")


if __name__ == "__main__":
    main()
