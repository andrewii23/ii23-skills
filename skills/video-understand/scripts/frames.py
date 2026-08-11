#!/usr/bin/env python3
"""Extract the frames worth looking at, then pack them into grid images.

Two extractors, auto-selected by probing how many keyframes are actually
DISTINCT (see KEYFRAME_MIN_DISTINCT -- density alone picks exactly backwards):

  keyframe  -- `-skip_frame nokey` decodes I-frames only. Encoders emit those at
               scene cuts, so on cut-heavy footage they ARE the distinct moments.
               Near-instant: 404 frames out of a 24-min episode in ~1.2s.
  uniform   -- fixed-fps sampling for low-cut footage (screen recordings, talking
               heads, vlogs) whose I-frames follow encoder cadence, not content.

Then dedup, then tile. Dedup is not an optimization here, it is what makes the
grid worth reading: measured on a screen recording, 88% of frames at 12fps and
54% at 4fps were near-identical to their predecessor, while real events scored a
10-40x higher delta. Raising fps mostly buys duplicates; dropping them is what
buys coverage.

Grids are read left-to-right, top-to-bottom. ALWAYS pass the emitted manifest to
the model alongside the images -- the grid carries order and content, the
manifest carries real timestamps. Never ask a model to guess a timestamp off a
grid cell.

Usage:
  python3 frames.py VIDEO --out-dir DIR [--cells 64] [--fps 4]
                          [--start T] [--end T] [--max-grids N] [--no-dedup]

Output:
  DIR/grid_000.png ...        the tiled images
  DIR/manifest.json           {grids:[{path, cells:[{index,t_ms,t_label}]}], ...}
  prints the manifest path on the last line as `MANIFEST: <abs-path>`

Exit codes:
  0  ok
  1  bad args / missing input
  2  ffmpeg or ffprobe missing
  3  extraction produced no frames

Requires: ffmpeg + ffprobe on PATH. Python stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Keyframe DENSITY does not tell you whether keyframes are useful: a 120fps
# screen recording emits ~1.0 I-frames/s (encoder cadence) while a 24-min anime
# emits ~0.28/s (real scene cuts). Density would pick exactly backwards.
#
# What separates them is how many keyframes SURVIVE dedup. Measured: anime kept
# 402/403 (0% waste -- every keyframe is a distinct shot), the screen recording
# kept 32/45 and those 32 still missed the action, because its keyframes track
# the encoder rather than the content. So probe a sample, and fall back to
# uniform sampling when too few keyframes are distinct or the clip is simply
# keyframe-poor.
KEYFRAME_MIN_PER_S = 0.15      # below this, too sparse to cover the clip at all
KEYFRAME_MIN_DISTINCT = 0.80   # fraction surviving dedup for keyframes to be trusted

# Cap total frames for the WHOLE run, because a fixed fps does not survive long videos:
# a 67-minute file at 4fps produced 16227 frames -> 12306 kept -> ~193 grids
# (~359k tokens), versus 7 grids for a 24-minute episode. Coverage per minute is
# what should shrink on a long video, not the token bill. 512 frames = 8 grids at
# --cells 64, which is a readable amount and still spans the entire runtime.
DEFAULT_BUDGET = 512

# How many keyframes to write while deciding which extractor to use. Enough to
# judge distinctness, small enough that a pathological encode costs ~1s.
PROBE_LIMIT = 400

# 16x16 grayscale thumbnails, mean absolute per-pixel difference (0-255).
# Measured idle frames land at 0.1-1.4, real cuts/events at 15-43, so anything
# at or under this is the same shot continuing.
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0

# Claude downscales any image to a 1568px long edge before tokenizing, so a grid
# wider than this costs the same ~1.85k tokens no matter how many cells it holds.
# Cells past that point are free in tokens and paid for in per-cell resolution.
TOKEN_CAP_LONG_EDGE = 1568

SHOWINFO_TS = re.compile(r"pts_time:([0-9.]+)")


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"{tool} not found on PATH. Install ffmpeg (brew install ffmpeg).")


def probe(video: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(Path(video).resolve())],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        sys.exit(f"ffprobe failed on {video}")
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    if not v:
        sys.exit(f"no video stream in {video}")
    dur = float(d.get("format", {}).get("duration") or v.get("duration") or 0)
    return {
        "duration_s": dur,
        "width": v.get("width"),
        "height": v.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", [])),
    }


def fmt_ts(ms: int) -> str:
    s, ms_r = divmod(int(ms), 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}.{ms_r // 100}"
    return f"{m:02d}:{sec:02d}.{ms_r // 100}"


def parse_time(v: str | None) -> float | None:
    """SS, MM:SS or HH:MM:SS (optional .ms) -> seconds."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    sys.exit(f"cannot parse time {v!r} (want SS, MM:SS or HH:MM:SS)")


def _range_args(start: float | None, end: float | None) -> list[str]:
    out: list[str] = []
    if start is not None:
        out += ["-ss", f"{start:.3f}"]
    if end is not None:
        out += ["-to", f"{end:.3f}"]
    return out


def extract_keyframes(video: str, out: Path, width: int,
                      start: float | None, end: float | None,
                      limit: int | None = None) -> list[dict]:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "info", "-skip_frame", "nokey"]
    cmd += _range_args(start, end)
    cmd += ["-i", str(Path(video).resolve()),
            "-vf", f"scale={width}:-2,showinfo", "-vsync", "vfr"]
    if limit:
        # Stops the decode early instead of writing every keyframe first.
        cmd += ["-frames:v", str(limit)]
    cmd += ["-q:v", "4", str(out / "f_%05d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    times = [float(m.group(1)) for m in SHOWINFO_TS.finditer(r.stderr or "")]
    files = sorted(out.glob("f_*.jpg"))
    off = start or 0.0
    return [{"path": str(p),
             "t_ms": int(round(((times[i] if i < len(times) else 0.0) + off) * 1000))}
            for i, p in enumerate(files)]


def extract_uniform(video: str, out: Path, width: int, fps: float,
                    start: float | None, end: float | None) -> list[dict]:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    cmd += _range_args(start, end)
    cmd += ["-i", str(Path(video).resolve()),
            "-vf", f"fps={fps},scale={width}:-2", "-q:v", "4",
            str(out / "f_%05d.jpg")]
    subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    off = start or 0.0
    files = sorted(out.glob("f_*.jpg"))
    return [{"path": str(p), "t_ms": int(round((off + i / fps) * 1000))}
            for i, p in enumerate(files)]


def thumbs(paths: list[Path]) -> list[bytes]:
    """Decode every frame to a tiny gray thumbnail in ONE ffmpeg pass.

    Fail-open: any mismatch returns [] so the caller simply skips dedup rather
    than dropping frames it cannot verify.
    """
    if not paths:
        return []
    m = re.match(r"(.*?)(\d+)(\.[A-Za-z0-9]+)$", paths[0].name)
    if not m:
        return []
    prefix, digits, ext = m.group(1), m.group(2), m.group(3)
    pattern = str(paths[0].parent / f"{prefix}%0{len(digits)}d{ext}")
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-start_number", str(int(digits)), "-i", pattern,
         "-vf", f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if r.returncode != 0:
        return []
    chunk = DEDUP_THUMB * DEDUP_THUMB
    data = r.stdout
    if len(data) != chunk * len(paths):
        return []
    return [data[i * chunk:(i + 1) * chunk] for i in range(len(paths))]


def dedupe(frames: list[dict], threshold: float = DEDUP_THRESHOLD) -> tuple[list[dict], int]:
    if len(frames) <= 1:
        return frames, 0
    th = thumbs([Path(f["path"]) for f in frames])
    if len(th) != len(frames):
        return frames, 0
    kept = [frames[0]]
    last = th[0]
    dropped = 0
    for f, t in zip(frames[1:], th[1:]):
        delta = sum(abs(a - b) for a, b in zip(t, last)) / len(t)
        if delta <= threshold:
            dropped += 1
        else:
            kept.append(f)
            last = t
    return kept, dropped


def even_sample(items: list[dict], n: int) -> list[dict]:
    """n evenly spaced items, always keeping first and last."""
    if n >= len(items):
        return items
    if n <= 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def grid_shape(cells: int) -> tuple[int, int]:
    """Near-square, never taller than wide (matches reading order)."""
    cols = int(cells ** 0.5)
    if cols * cols < cells:
        cols += 1
    rows = (cells + cols - 1) // cols
    return cols, rows


def build_grid(frames: list[dict], cols: int, rows: int, cell_w: int,
               out_png: Path, tmp: Path) -> bool:
    stage = tmp / f"stage_{out_png.stem}"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    for i, f in enumerate(frames):
        shutil.copy(f["path"], stage / f"g_{i:03d}.jpg")
    cell_h = int(round(cell_w * 9 / 16 / 2)) * 2
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(stage / "g_%03d.jpg"),
         "-vf", f"scale={cell_w}:{cell_h},"
                f"tile={cols}x{rows}:margin=6:padding=4:color=white",
         "-frames:v", "1", str(out_png)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    shutil.rmtree(stage, ignore_errors=True)
    return r.returncode == 0 and out_png.exists()


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract + dedup + grid-pack video frames.")
    ap.add_argument("video")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cells", type=int, default=64,
                    help="Cells per grid. 16 to read on-screen text, 36 for faces "
                         "and fine action, 64 for plot/scene (default).")
    ap.add_argument("--fps", type=float, default=0.0,
                    help="Force a sampling rate for the uniform extractor. Default 0 "
                         "= derive it from --budget so long videos stay affordable.")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                    help=f"Max frames to keep for the whole run (default {DEFAULT_BUDGET} "
                         "= a readable number of grids). Frames are thinned evenly "
                         "across the full range, never truncated at the tail. "
                         "0 disables the cap.")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--max-grids", type=int, default=0,
                    help="Cap total grids (0 = no cap). Frames are thinned evenly "
                         "across the whole range, never truncated at the tail.")
    ap.add_argument("--cell-width", type=int, default=480)
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--force", choices=["keyframe", "uniform"],
                    help="Override the auto-selected extractor.")
    args = ap.parse_args()

    need("ffmpeg")
    need("ffprobe")

    video = str(Path(args.video).expanduser())
    if not Path(video).exists():
        sys.exit(f"no such file: {video}")
    if args.cells < 1:
        sys.exit("--cells must be >= 1")

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = probe(video)
    start = parse_time(args.start)
    end = parse_time(args.end)
    span = (end if end is not None else meta["duration_s"]) - (start or 0.0)
    if span <= 0:
        sys.exit("empty time range")

    tmp = Path(tempfile.mkdtemp(prefix="vu_frames_"))
    raw = tmp / "raw"
    raw.mkdir()

    try:
        engine = args.force
        frames: list[dict] = []
        dropped = 0

        if engine is None:
            # Actually run the keyframe pass and measure how much of it is
            # distinct -- cheap (~1s even on a 24-min file) and far more
            # reliable than inferring intent from I-frame cadence.
            #
            # Bounded, because "every frame is a keyframe" is a real encode: a
            # 67-minute VP9 file reported 121701 keyframes at 30/s, and writing
            # all of them just to reject the engine costs minutes and gigabytes.
            # Probing a prefix answers the only question here (are keyframes
            # distinct enough to trust?) at a fixed cost.
            probe_frames = extract_keyframes(video, raw, args.cell_width, start, end,
                                             limit=PROBE_LIMIT)
            probe_span = span
            if len(probe_frames) >= PROBE_LIMIT and probe_frames:
                # Only covered up to the last probed frame, so rate must use that
                # span, not the whole clip, or a dense encode reads as sparse.
                probe_span = max(0.001, probe_frames[-1]["t_ms"] / 1000.0 - (start or 0.0))
            per_s = len(probe_frames) / probe_span
            kept, drop = (probe_frames, 0) if args.no_dedup else dedupe(probe_frames)
            distinct = (len(kept) / len(probe_frames)) if probe_frames else 0.0
            partial = len(probe_frames) >= PROBE_LIMIT
            if per_s >= KEYFRAME_MIN_PER_S and distinct >= KEYFRAME_MIN_DISTINCT:
                engine = "keyframe"
                if not partial:
                    frames, dropped = kept, drop
            else:
                engine = "uniform"
            why = (f"{len(probe_frames)}{'+' if partial else ''} keyframes over "
                   f"{probe_span:.1f}s ({per_s:.2f}/s), {distinct:.0%} distinct")
            print(f"[frames] {why} -> {engine}", file=sys.stderr)
            if engine == "uniform" or partial:
                shutil.rmtree(raw, ignore_errors=True)
                raw.mkdir()

        # Derive fps from the budget so a long video thins itself instead of
        # extracting tens of thousands of frames and discarding most of them.
        fps = args.fps
        if engine == "uniform" and fps <= 0:
            fps = min(4.0, args.budget / span) if args.budget > 0 else 4.0
            fps = max(fps, 0.05)

        if engine == "uniform" and not frames:
            frames = extract_uniform(video, raw, args.cell_width, fps, start, end)
            if frames and not args.no_dedup:
                frames, dropped = dedupe(frames)
        elif engine == "keyframe" and not frames:
            frames = extract_keyframes(video, raw, args.cell_width, start, end)
            if frames and not args.no_dedup:
                frames, dropped = dedupe(frames)

        if not frames:
            sys.exit(3)
        extracted = len(frames) + dropped

        # Budget applies to BOTH engines: a cut-heavy 3-hour film blows the same
        # hole through keyframes that a fixed fps blows through uniform sampling.
        budgeted = 0
        if args.budget > 0 and len(frames) > args.budget:
            budgeted = len(frames) - args.budget
            frames = even_sample(frames, args.budget)

        if args.max_grids > 0:
            frames = even_sample(frames, args.max_grids * args.cells)

        cols, rows = grid_shape(args.cells)
        # Report the resolution each cell actually survives at once Claude
        # downscales the grid -- this, not the cell count, is the real limit.
        eff_w = TOKEN_CAP_LONG_EDGE / cols
        thinned = (f", {budgeted} thinned to fit --budget {args.budget}"
                   if budgeted else "")
        print(f"[frames] {extracted} extracted, {dropped} near-duplicates dropped"
              f"{thinned}, {len(frames)} kept -> {cols}x{rows} grids "
              f"(~{eff_w:.0f}px per cell after downscale)", file=sys.stderr)

        grids = []
        for gi in range(0, len(frames), args.cells):
            chunk = frames[gi:gi + args.cells]
            png = out_dir / f"grid_{gi // args.cells:03d}.png"
            # A partly-filled grid (the last one, usually) is tiled to its own
            # shape so it carries no blank cells -- empty space costs tokens and
            # reads as missing content.
            c, r = (cols, rows) if len(chunk) == args.cells else grid_shape(len(chunk))
            if not build_grid(chunk, c, r, args.cell_width, png, tmp):
                continue
            grids.append({
                "path": str(png),
                "cols": c,
                "rows": r,
                "cells": [{"index": i, "t_ms": f["t_ms"], "t_label": fmt_ts(f["t_ms"])}
                          for i, f in enumerate(chunk)],
            })

        if not grids:
            sys.exit(3)

        manifest = {
            "video": str(Path(video).resolve()),
            "duration_s": round(meta["duration_s"], 2),
            "has_audio": meta["has_audio"],
            "engine": engine,
            "cells_per_grid": args.cells,
            "grid_cols": cols,   # nominal shape; a short final grid has its own
            "grid_rows": rows,   # cols/rows -- always read those per grid
            "frames_extracted": extracted,
            "frames_deduped": dropped,
            "frames_thinned_for_budget": budgeted,
            "budget": args.budget,
            "sampling_fps": round(fps, 3) if engine == "uniform" else None,
            "frames_used": len(frames),
            "range": {"start_s": start, "end_s": end},
            "reading_order": "left-to-right, top-to-bottom",
            "grids": grids,
        }
        mpath = out_dir / "manifest.json"
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"MANIFEST: {mpath.resolve()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
