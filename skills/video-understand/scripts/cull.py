#!/usr/bin/env python3
"""Rank a pile of clips for reuse: sharp, well exposed, steady, text-free.

For choosing footage, not understanding it. Every clip gets one low-res pass
(the same one index.py runs) and a score built from things ffmpeg can measure:

  sharpness  blurdetect, lower blur is better. Compared WITHIN the batch --
             absolute blur values do not transfer between cameras.
  exposure   mean luma far from mid-grey, or crushed/blown, costs points.
  jitter     how much frame-to-frame motion itself jumps around. A steady pan
             has high motion and low jitter; handheld shake has both. Rough --
             it is a ranking signal, not a stabilisation measurement.
  text       burned-in text from text_check.py (optional, --text).
  length     usable seconds; very short clips rank down.

Output: a ranked table and ONE contact sheet -- the sharpest frame of every
clip, labelled with its rank -- so the whole batch is judged from one image.

Usage:
  python3 cull.py CLIP [CLIP ...] --out-dir DIR [--text] [--top N]

Output:
  DIR/cull.json, DIR/cull.md, DIR/sheet_000.png ...
  prints `CULL: <abs-path-to-cull.md>` on the last line

Requires: ffmpeg + ffprobe. Python stdlib only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frames as fr  # noqa: E402
import index as ix  # noqa: E402

MIN_USEFUL_S = 2.0


def measure(video: str, tmp: Path) -> dict:
    meta = ix.probe(video)
    work = tmp / Path(video).stem
    work.mkdir(parents=True, exist_ok=True)
    scene, stats, _, _ = ix.run_passes(video, None, None, False, work)
    cuts = ix.detect_cuts(scene)
    rows = [r for r in stats if "blur" in r and "signalstats.YAVG" in r]
    if not rows:
        return {"video": video, "error": "no samples"}
    # blurdetect scores a near-black frame (a fade, a night sky) as razor
    # sharp because it has no edges to be soft, and so does a murky low-contrast
    # one -- on the first b-roll batch two night clips ranked 4th and 5th on the
    # strength of near-black frames. Sharpness only counts where there is
    # picture to judge: mid luma AND a real spread between shadows and highlights.
    lit = [r for r in rows if 25 <= r["signalstats.YAVG"] <= 235
           and r.get("signalstats.YHIGH", 255) - r.get("signalstats.YLOW", 0) >= 60] or rows
    blur_lit = [r["blur"] for r in lit]
    blur = [r["blur"] for r in rows]
    ydif = [r.get("signalstats.YDIF", 0.0) for r in rows]
    yavg = [r.get("signalstats.YAVG", 0.0) for r in rows]
    ylow = [r.get("signalstats.YLOW", 0.0) for r in rows]
    yhigh = [r.get("signalstats.YHIGH", 255.0) for r in rows]
    n = len(rows)
    motion = sum(ydif) / n
    jitter = (sum(abs(ydif[i] - ydif[i - 1]) for i in range(1, n)) / max(1, n - 1)) / (motion + 1.0)
    best = min(lit, key=lambda r: r["blur"])
    return {
        "video": video, "duration_s": round(meta["duration_s"], 2),
        "width": meta["width"], "height": meta["height"],
        "shots": len(cuts) + 1,
        "blur": round(sum(blur_lit) / len(blur_lit), 3),
        "lit": round(len(lit) / n, 3),
        "luma": round(sum(yavg) / n, 1),
        "crushed": round(sum(1 for v in yhigh if v < 60) / n, 3),
        "blown": round(sum(1 for v in ylow if v > 200) / n, 3),
        "motion": round(motion, 2),
        "jitter": round(jitter, 3),
        "sharpest_s": round(best["t"], 2),
    }


def zscores(vals: list[float]) -> list[float]:
    if len(vals) < 2:
        return [0.0] * len(vals)
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
    return [(v - m) / sd for v in vals]


def main() -> None:
    ap = argparse.ArgumentParser(description="Rank clips for reuse.")
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--text", action="store_true",
                    help="Also run text_check.py and rank burned-in text down.")
    ap.add_argument("--top", type=int, default=0, help="Only list the best N.")
    ap.add_argument("--cells", type=int, default=24, help="Clips per contact sheet.")
    args = ap.parse_args()
    fr.need("ffmpeg")
    fr.need("ffprobe")
    clips = [str(Path(c).expanduser().absolute()) for c in args.clips]
    for c in clips:
        if not Path(c).exists():
            sys.exit(f"no such file: {c}")
    out = Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="vu_cull_"))

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            res = list(pool.map(lambda c: measure(c, tmp), clips))
        res = [r for r in res if "error" not in r]
        if not res:
            sys.exit(3)

        text_chars: dict[str, int] = {}
        if args.text:
            rp = out / "text_check.json"
            subprocess.run([sys.executable, str(Path(__file__).parent / "text_check.py"),
                            *[r["video"] for r in res], "--out", str(rp)],
                           capture_output=True, text=True)
            if rp.exists():
                for v in json.loads(rp.read_text(encoding="utf-8"))["videos"]:
                    text_chars[str(Path(v["video"]).resolve())] = v["chars"]

        zb = zscores([r["blur"] for r in res])
        zj = zscores([r["jitter"] for r in res])
        for r, b, j in zip(res, zb, zj):
            expo = (abs(r["luma"] - 115) / 40 + 3 * (r["crushed"] + r["blown"])
                    + 2 * (1 - r["lit"]))
            short = 1.0 if r["duration_s"] < MIN_USEFUL_S else 0.0
            txt = text_chars.get(str(Path(r["video"]).resolve()))
            r["text_chars"] = txt
            tpen = 0.0 if txt is None else min(2.0, txt / 40)
            r["score"] = round(-b - 0.7 * j - expo - short - tpen, 2)
            notes = []
            if b > 1:
                notes.append("soft")
            if j > 1:
                notes.append("shaky")
            if r["crushed"] > 0.3:
                notes.append("dark")
            if r["blown"] > 0.3:
                notes.append("blown")
            if txt and txt > 8:
                notes.append(f"text {txt}ch")
            if short:
                notes.append("too short")
            r["notes"] = notes
        res.sort(key=lambda r: -r["score"])
        for i, r in enumerate(res, 1):
            r["rank"] = i

        stills = tmp / "stills"
        stills.mkdir()
        items = []
        for r in res:
            p = stills / f"f_{r['rank']:05d}.jpg"
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                            "-ss", str(r["sharpest_s"]), "-i", r["video"], "-frames:v", "1",
                            "-vf", "scale=480:480:force_original_aspect_ratio=decrease,"
                                   "pad=480:480:(ow-iw)/2:(oh-ih)/2",
                            "-q:v", "4", str(p)], capture_output=True)
            if p.exists():
                items.append({"path": str(p), "t_ms": 0, "label": str(r["rank"])})
        sheets = []
        for gi in range(0, len(items), args.cells):
            chunk = items[gi:gi + args.cells]
            c, rr = fr.grid_shape(len(chunk), 1.0)
            png = out / f"sheet_{gi // args.cells:03d}.png"
            if fr.build_grid(chunk, c, rr, 480, 480, png, tmp):
                sheets.append(str(png))

        shown = res[:args.top] if args.top else res
        lines = ["# Cull ranking", "",
                 f"{len(res)} clips. Each sheet cell is one clip's sharpest frame, "
                 "labelled with its rank.", "",
                 "| rank | clip | len | score | blur | jitter | luma | notes |",
                 "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in shown:
            lines.append(f"| {r['rank']} | {Path(r['video']).name} | {r['duration_s']:.0f}s | "
                         f"{r['score']} | {r['blur']} | {r['jitter']} | {r['luma']} | "
                         f"{', '.join(r['notes'])} |")
        lines += ["", "Sheets: " + ", ".join(sheets)]
        (out / "cull.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        md = out / "cull.md"
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[cull] {len(res)} clips ranked, {len(sheets)} sheet(s)", file=sys.stderr)
        print(f"CULL: {md.resolve()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
