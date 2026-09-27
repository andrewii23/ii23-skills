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

A third mode, `--at`, skips both: it grabs one frame at each named moment. Use
it after reading the transcript, when the speaker points at something ("look
here", "notice this") -- the grid's sampling may have landed either side of it.

Usage:
  python3 frames.py VIDEO --out-dir DIR [--cells 64] [--fps 4]
                          [--start T] [--end T] [--max-grids N] [--no-dedup]
  python3 frames.py VIDEO --out-dir DIR --at 4:32,7:10 [--cells 16]

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
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import index as shot_index  # noqa: E402

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

# Ceiling for the shot-driven budget: past this, frames thin evenly again.
# 2048 frames = 32 grids at --cells 64.
SHOT_BUDGET_CAP = 2048

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


def extract_at(video: str, out: Path, width: int, times: list[float]) -> list[dict]:
    """One frame at each requested moment -- cues the transcript pointed at.

    Input-side seek per cue, so a cue near the end of a long file costs the same
    as one near the start. Cues are never deduped: the caller asked for exactly
    these moments, and two cues on a static shot are still two answers.
    """
    src = str(Path(video).resolve())

    def grab(item: tuple[int, float]) -> dict | None:
        i, t = item
        dest = out / f"f_{i:05d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{t:.3f}", "-i", src,
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(dest)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if dest.exists():
            return {"path": str(dest), "t_ms": int(round(t * 1000))}
        print(f"[frames] no frame at {fmt_ts(int(t * 1000))} (past the end?)",
              file=sys.stderr)
        return None

    # Each seek is its own short ffmpeg; running several at once is what makes
    # a thousand-shot film take seconds instead of minutes.
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4))) as pool:
        got = list(pool.map(grab, enumerate(times)))
    return [f for f in got if f]


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
    """Drop frames near-identical to the last kept one. Frames marked `anchor`
    (one per shot) are never dropped: they are the coverage guarantee."""
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
        if delta <= threshold and not f.get("anchor"):
            dropped += 1
        else:
            kept.append(f)
            last = t
    return kept, dropped


def shot_times(shots: list[dict], budget: int, start: float, end: float,
               fill_fps_cap: float = 4.0) -> list[dict]:
    """One anchor per shot (its sharpest sampled moment), then spend what is left
    of the budget evenly across the range so long takes -- a walkthrough, a pan,
    a talking head -- get more than one frame."""
    anchors = [{"t": s["sharpest_s"], "anchor": True, "shot": s["index"]} for s in shots]
    if len(anchors) > budget:
        anchors = even_sample([{**a, "t_ms": 0} for a in anchors], budget)
    span = end - start
    left = budget - len(anchors)
    fill: list[dict] = []
    if left > 0 and span > 0:
        rate = min(fill_fps_cap, left / span)
        n = int(span * rate)
        taken = sorted(a["t"] for a in anchors)
        import bisect
        for k in range(n):
            t = start + (k + 0.5) / rate
            i = bisect.bisect_left(taken, t)
            near = min([abs(taken[j] - t) for j in (i - 1, i) if 0 <= j < len(taken)] or [9])
            if near >= 0.3:
                fill.append({"t": t, "anchor": False})
    return sorted(anchors + fill, key=lambda x: x["t"])


def even_sample(items: list[dict], n: int) -> list[dict]:
    """n evenly spaced items, always keeping first and last."""
    if n >= len(items):
        return items
    if n <= 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def grid_shape(cells: int, aspect: float = 16 / 9) -> tuple[int, int]:
    """Columns x rows that make the whole GRID near-square.

    `aspect` is one cell's width/height. Landscape cells keep the old near-square
    count layout; portrait cells (phone video) get more columns, so a 9:16 grid
    is not a tall strip that the long-edge downscale crushes.
    """
    if aspect >= 1:
        cols = int(cells ** 0.5)
        if cols * cols < cells:
            cols += 1
    else:
        cols = min(cells, max(1, round((cells / aspect) ** 0.5)))
    rows = (cells + cols - 1) // cols
    return cols, rows


# 5x7 bitmap glyphs for timestamp labels. ffmpeg's drawtext needs a freetype
# build that many installs (Homebrew's included) do not have, and the label is
# only ever digits, ':' and '.'.
GLYPHS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00110", "00110"],
    " ": ["00000"] * 7,
}


def write_label(text: str, scale: int, dest: Path) -> None:
    """White-on-black timestamp as a binary PGM -- stdlib only."""
    pad = scale
    glyph_w = 6 * scale
    w = len(text) * glyph_w + 2 * pad
    h = 7 * scale + 2 * pad
    rows = [bytearray(w) for _ in range(h)]
    for ci, ch in enumerate(text):
        g = GLYPHS.get(ch, GLYPHS[" "])
        for gy, line in enumerate(g):
            for gx, bit in enumerate(line):
                if bit == "1":
                    for dy in range(scale):
                        y = pad + gy * scale + dy
                        x0 = pad + ci * glyph_w + gx * scale
                        rows[y][x0:x0 + scale] = b"\xff" * scale
    dest.write_bytes(f"P5 {w} {h} 255\n".encode() + b"".join(bytes(r) for r in rows))


def build_grid(frames: list[dict], cols: int, rows: int, cell_w: int, cell_h: int,
               out_png: Path, tmp: Path, labels: bool = True) -> bool:
    stage = tmp / f"stage_{out_png.stem}"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    # Fit the label to the narrower side: a 9:16 cell is tall but thin, and a
    # label sized off its height runs past the edge.
    longest = max((len(f.get("label") or fmt_ts(f["t_ms"])) for f in frames), default=7)
    scale = max(1, min(cell_h // 60, int(cell_w * 0.55) // (6 * longest)))
    for i, f in enumerate(frames):
        shutil.copy(f["path"], stage / f"g_{i:03d}.jpg")
        if labels:
            # Every label in one grid must be the same size: ffmpeg re-inits the
            # overlay when a frame's dimensions change, and the tile restarts --
            # a grid mixing "9" and "10", or "59:59.9" and "1:00:00.0", lost
            # its first half that way.
            write_label((f.get("label") or fmt_ts(f["t_ms"])).ljust(longest), scale,
                        stage / f"l_{i:03d}.pgm")
    tile = f"tile={cols}x{rows}:margin=6:padding=4:color=white"
    if labels:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(stage / "g_%03d.jpg"), "-i", str(stage / "l_%03d.pgm"),
               "-filter_complex",
               f"[0:v]scale={cell_w}:{cell_h},setsar=1[c];[c][1:v]overlay=0:0,{tile}",
               "-frames:v", "1", str(out_png)]
    else:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(stage / "g_%03d.jpg"),
               "-vf", f"scale={cell_w}:{cell_h},setsar=1,{tile}",
               "-frames:v", "1", str(out_png)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    shutil.rmtree(stage, ignore_errors=True)
    return r.returncode == 0 and out_png.exists()


def frame_aspect(path: str) -> float:
    """Width/height of an extracted frame -- after ffmpeg applied any rotation
    metadata, so a phone clip stored landscape-with-rotate reads as portrait."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return w / h if h else 16 / 9
    except ValueError:
        return 16 / 9


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
    ap.add_argument("--budget", type=int, default=None,
                    help=f"Max frames for the whole run. Default: {DEFAULT_BUDGET}, "
                         f"raised to one frame per shot (up to {SHOT_BUDGET_CAP}) so "
                         "no shot goes unseen. Frames are thinned evenly across the "
                         "full range, never truncated at the tail. 0 disables the cap.")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--max-grids", type=int, default=0,
                    help="Cap total grids (0 = no cap). Frames are thinned evenly "
                         "across the whole range, never truncated at the tail.")
    ap.add_argument("--cell-width", type=int, default=480)
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--no-labels", action="store_true",
                    help="Do not burn each cell's timestamp into its corner.")
    ap.add_argument("--force", choices=["shots", "keyframe", "uniform"],
                    help="Override the extractor. Default is shots.")
    ap.add_argument("--index",
                    help="index.json from index.py -- reuses its shot list instead "
                         "of decoding the video again.")
    ap.add_argument("--at",
                    help="Comma-separated moments (SS, MM:SS or HH:MM:SS) to grab "
                         "exactly one frame each -- e.g. the times the transcript "
                         "says 'look at this'. Replaces the extractor; no dedup.")
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
    lo = start or 0.0
    hi = end if end is not None else meta["duration_s"]
    span = hi - lo
    if span <= 0:
        sys.exit("empty time range")

    tmp = Path(tempfile.mkdtemp(prefix="vu_frames_"))
    raw = tmp / "raw"
    raw.mkdir()
    budget = DEFAULT_BUDGET if args.budget is None else args.budget
    shots_seen = 0

    try:
        engine = args.force or "shots"
        frames: list[dict] = []
        dropped = 0

        if args.at:
            cues = sorted(parse_time(t) for t in args.at.split(",") if t.strip())
            engine = "cues"
            frames = extract_at(video, raw, args.cell_width, cues)
            print(f"[frames] {len(frames)}/{len(cues)} cue frames", file=sys.stderr)

        elif engine == "shots":
            if args.index:
                idx = json.loads(Path(args.index).expanduser().read_text(encoding="utf-8"))
                shots = [s for s in idx["shots"] if s["end_s"] > lo and s["start_s"] < hi]
            else:
                itmp = tmp / "idx"
                itmp.mkdir()
                scene, stats, _, _ = shot_index.run_passes(
                    str(Path(video).resolve()), start, end, False, itmp)
                shots = shot_index.build_shots(shot_index.detect_cuts(scene), span, stats, [])
                for s in shots:
                    for k in ("start_s", "end_s", "sharpest_s"):
                        s[k] = round(s[k] + lo, 3)
            shots_seen = len(shots)
            # One frame per shot is the floor, so the default budget rises to
            # meet the shot count -- a film with 1700 shots gets 1700 frames,
            # not 512 that silently skip two shots in three.
            if args.budget is None:
                budget = min(max(DEFAULT_BUDGET, len(shots)), SHOT_BUDGET_CAP)
            # Fill density falls with length: a 30s clip can afford 4 frames a
            # second of fine action, a 5-minute walkthrough does not need them --
            # shots and the index already mark where things change.
            cap = 4.0 if span <= 60 else (2.0 if span <= 300 else 1.0)
            plan = shot_times(shots, budget if budget > 0 else max(len(shots), 1) * 4,
                              lo, hi, fill_fps_cap=cap)
            got = extract_at(video, raw, args.cell_width, [p["t"] for p in plan])
            by_t = {int(round(p["t"] * 1000)): p for p in plan}
            for f in got:
                p = by_t.get(f["t_ms"], {})
                f["anchor"] = p.get("anchor", False)
                if "shot" in p:
                    f["shot"] = p["shot"]
            frames = got
            if frames and not args.no_dedup:
                frames, dropped = dedupe(frames)
            print(f"[frames] {len(shots)} shots -> "
                  f"{sum(1 for f in frames if f.get('anchor'))} shot anchors + "
                  f"{sum(1 for f in frames if not f.get('anchor'))} fill frames",
                  file=sys.stderr)

        if engine in ("keyframe", "uniform"):
            fps = args.fps
            if engine == "uniform" and fps <= 0:
                fps = min(4.0, budget / span) if budget > 0 else 4.0
                fps = max(fps, 0.05)
            if engine == "uniform":
                frames = extract_uniform(video, raw, args.cell_width, fps, start, end)
            else:
                frames = extract_keyframes(video, raw, args.cell_width, start, end)
            if frames and not args.no_dedup:
                frames, dropped = dedupe(frames)
        else:
            fps = 0.0

        if not frames:
            sys.exit(3)
        extracted = len(frames) + dropped

        budgeted = 0
        if budget > 0 and len(frames) > budget:
            budgeted = len(frames) - budget
            frames = even_sample(frames, budget)

        if args.max_grids > 0:
            frames = even_sample(frames, args.max_grids * args.cells)

        aspect = frame_aspect(frames[0]["path"])
        cell_w = args.cell_width if aspect >= 1 else int(round(args.cell_width * aspect / 2)) * 2
        cell_h = int(round(cell_w / aspect / 2)) * 2
        cols, rows = grid_shape(args.cells, cell_w / cell_h)
        long_edge = max(cols * cell_w, rows * cell_h)
        eff = min(cell_w, cell_w * TOKEN_CAP_LONG_EDGE / long_edge)
        thinned = (f", {budgeted} thinned to fit --budget {budget}" if budgeted else "")
        print(f"[frames] {extracted} extracted, {dropped} near-duplicates dropped"
              f"{thinned}, {len(frames)} kept -> {cols}x{rows} grids "
              f"(~{eff:.0f}px wide per cell after downscale)", file=sys.stderr)

        grids = []
        for gi in range(0, len(frames), args.cells):
            chunk = frames[gi:gi + args.cells]
            png = out_dir / f"grid_{gi // args.cells:03d}.png"
            c, r = ((cols, rows) if len(chunk) == args.cells
                    else grid_shape(len(chunk), cell_w / cell_h))
            if not build_grid(chunk, c, r, cell_w, cell_h, png, tmp,
                              labels=not args.no_labels):
                continue
            grids.append({
                "path": str(png),
                "cols": c,
                "rows": r,
                "cells": [{"index": i, "t_ms": f["t_ms"], "t_label": fmt_ts(f["t_ms"]),
                           **({"shot": f["shot"]} if "shot" in f else {})}
                          for i, f in enumerate(chunk)],
            })

        if not grids:
            sys.exit(3)

        manifest = {
            "video": str(Path(video).resolve()),
            "duration_s": round(meta["duration_s"], 2),
            "has_audio": meta["has_audio"],
            "engine": engine,
            "shots": shots_seen or None,
            "cells_per_grid": args.cells,
            "grid_cols": cols,   # nominal shape; a short final grid has its own
            "grid_rows": rows,   # cols/rows -- always read those per grid
            "labels": not args.no_labels,
            "frames_extracted": extracted,
            "frames_deduped": dropped,
            "frames_thinned_for_budget": budgeted,
            "budget": budget,
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
