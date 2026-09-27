#!/usr/bin/env python3
"""Index a video: every shot, what moves, how it looks, how it sounds.

The transcript tells you what was said. This tells you everything else, as
text, from one cheap pass -- which is what a silent clip (a room tour, a sight
gag, b-roll) has instead of dialogue, and what a two-hour film needs before any
frame is worth looking at.

Two ffmpeg processes run side by side:

  video  one decode at 160px. Scene score on EVERY frame (cuts are one frame
         wide, so sampling would miss them); motion, exposure and sharpness on
         a few samples per second.
  audio  momentary loudness every 100ms, plus silence spans.

From that:

  shots   every cut, found with a fixed floor plus an adaptive test (a score
          several times its neighbours') so dark scenes and fast pans neither
          hide cuts nor invent them.
  per shot: duration, motion, brightness, sharpest moment, loudness.
  events  loudness jumps (a slam, a laugh track, a music hit) and silences.

Usage:
  python3 index.py VIDEO --out-dir DIR [--start T] [--end T]

Output:
  DIR/index.json   machine-readable: shots, samples, audio
  DIR/index.md     one line per shot -- read this, then zoom with frames.py
  prints `INDEX: <abs-path-to-index.md>` on the last line

Requires: ffmpeg + ffprobe on PATH. Python stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# A cut is certain above this scene score (the value claude-real-video and
# most ffmpeg recipes settle on)...
CUT_HARD = 0.30
# ...and likely when a score clears this floor AND stands this many times above
# the mean of its neighbours -- PySceneDetect's AdaptiveDetector idea, which is
# what catches cuts inside dark scenes whose scores never reach CUT_HARD.
CUT_FLOOR = 0.12
CUT_RATIO = 3.0
CUT_WINDOW = 4          # neighbours on each side for the adaptive mean
MIN_SHOT_S = 0.4        # cuts closer than this are flicker or a flash frame

SAMPLE_FPS = 4.0        # motion/exposure/sharpness samples per second
PTS = re.compile(r"pts_time:([0-9.]+)")
KV = re.compile(r"^lavfi\.([\w.]+)=(.+)$")
SILENCE = re.compile(r"silence_(start|end): (-?[0-9.]+)")


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"{tool} not found on PATH. Install ffmpeg (brew install ffmpeg).")


def probe(video: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
         "-show_streams", video],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    d = json.loads(r.stdout or "{}")
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    if not v:
        sys.exit(f"no video stream in {video}")
    return {"duration_s": float(d.get("format", {}).get("duration") or v.get("duration") or 0),
            "width": v.get("width"), "height": v.get("height"),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    s, ms_r = divmod(ms, 1000)
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}.{ms_r // 100}" if h else f"{m:02d}:{x:02d}.{ms_r // 100}"


def parse_time(v: str | None) -> float | None:
    if not v:
        return None
    p = v.strip().split(":")
    try:
        if len(p) == 1:
            return float(p[0])
        if len(p) == 2:
            return int(p[0]) * 60 + float(p[1])
        return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
    except ValueError:
        sys.exit(f"cannot parse time {v!r}")


def read_metadata(path: Path) -> list[dict]:
    """ffmpeg `metadata=print:file=` output -> [{t, key: value, ...}]."""
    rows: list[dict] = []
    cur: dict | None = None
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("frame:"):
            m = PTS.search(line)
            cur = {"t": float(m.group(1)) if m else 0.0}
            rows.append(cur)
            continue
        m = KV.match(line.strip())
        if m and cur is not None:
            try:
                v = float(m.group(2))
            except ValueError:
                continue
            # blurdetect reports nan on flat frames (black, fades); a nan
            # poisons every mean it touches, so treat it as "not measured".
            if v == v and v not in (float("inf"), float("-inf")):
                cur[m.group(1)] = v
    return rows


def run_passes(video: str, start: float | None, end: float | None,
               has_audio: bool, tmp: Path) -> tuple[list[dict], list[dict], list[dict], list[tuple]]:
    rng: list[str] = []
    if start is not None:
        rng += ["-ss", f"{start:.3f}"]
    if end is not None:
        rng += ["-to", f"{end:.3f}"]
    scene_f, stats_f, loud_f = tmp / "scene.txt", tmp / "stats.txt", tmp / "loud.txt"
    graph = (
        "[0:v]scale=160:-2,split[a][b];"
        f"[a]select='gte(scene,0)',metadata=print:key=lavfi.scene_score:file={scene_f}[sa];"
        f"[b]fps={SAMPLE_FPS},signalstats,blurdetect=block_width=16:block_height=16,"
        f"metadata=print:file={stats_f}[sb]"
    )
    vcmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *rng, "-i", video,
            "-filter_complex", graph, "-map", "[sa]", "-f", "null", "-",
            "-map", "[sb]", "-f", "null", "-"]
    procs = [subprocess.Popen(vcmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, errors="replace")]
    if has_audio:
        acmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", *rng, "-i", video, "-vn",
                "-af", "silencedetect=noise=-35dB:d=0.6,"
                       f"ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file={loud_f}",
                "-f", "null", "-"]
        procs.append(subprocess.Popen(acmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      text=True, errors="replace"))
    errs = [p.communicate()[1] or "" for p in procs]
    if procs[0].returncode != 0:
        sys.exit(f"ffmpeg video pass failed: {errs[0][-400:]}")

    scene = read_metadata(scene_f)
    stats = read_metadata(stats_f)
    loud = read_metadata(loud_f) if has_audio else []
    silences: list[tuple] = []
    if has_audio:
        s0 = None
        for kind, val in SILENCE.findall(errs[1]):
            if kind == "start":
                s0 = float(val)
            elif s0 is not None:
                silences.append((s0, float(val)))
                s0 = None
    return scene, stats, loud, silences


def detect_cuts(scene: list[dict]) -> list[float]:
    scores = [r.get("scene_score", 0.0) for r in scene]
    times = [r["t"] for r in scene]
    cuts: list[float] = []
    n = len(scores)
    for i in range(1, n):
        s = scores[i]
        if s < CUT_FLOOR:
            continue
        lo, hi = max(0, i - CUT_WINDOW), min(n, i + CUT_WINDOW + 1)
        nb = [scores[j] for j in range(lo, hi) if j != i]
        mean = (sum(nb) / len(nb)) if nb else 0.0
        if s >= CUT_HARD or s >= CUT_RATIO * max(mean, 0.01):
            prev = cuts[-1] if cuts else times[0]
            if times[i] - prev < MIN_SHOT_S:
                continue
            cuts.append(times[i])
    return cuts


def level(v: float, bands: list[tuple[float, str]]) -> str:
    for th, name in bands:
        if v < th:
            return name
    return bands[-1][1]


def build_shots(cuts: list[float], span: float, stats: list[dict], loud: list[dict]) -> list[dict]:
    bounds = [0.0] + [c for c in cuts if 0 < c < span] + [span]
    shots = []
    si = li = 0
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        if b - a <= 0:
            continue
        samp = []
        while si < len(stats) and stats[si]["t"] < b:
            if stats[si]["t"] >= a:
                samp.append(stats[si])
            si += 1
        lv = []
        while li < len(loud) and loud[li]["t"] < b:
            if loud[li]["t"] >= a:
                lv.append(loud[li].get("r128.M", -70.0))
            li += 1
        shot = {"index": len(shots), "start_s": round(a, 3), "end_s": round(b, 3),
                "dur_s": round(b - a, 3)}
        if samp:
            ydif = sum(r.get("signalstats.YDIF", 0) for r in samp) / len(samp)
            yavg = sum(r.get("signalstats.YAVG", 0) for r in samp) / len(samp)
            blur = [r.get("blur", 0.0) for r in samp]
            # A black or blown frame has no edges and so reads as "sharpest";
            # never pick it as the shot's representative.
            lit = [i for i, r in enumerate(samp)
                   if 25 <= r.get("signalstats.YAVG", 128) <= 235
                   and r.get("signalstats.YHIGH", 255) - r.get("signalstats.YLOW", 0) >= 60]
            lit = lit or list(range(len(samp)))
            sharp = min(lit, key=lambda i: blur[i])
            shot.update({
                "motion": round(ydif, 2),
                "luma": round(yavg, 1),
                "blur": round(sum(blur) / len(blur), 2),
                "sharpest_s": round(samp[sharp]["t"], 3),
            })
        else:
            shot["sharpest_s"] = round((a + b) / 2, 3)
        if lv:
            lv = [x for x in lv if x > -120]
            if lv:
                shot["loud_lufs"] = round(sum(lv) / len(lv), 1)
                shot["loud_peak"] = round(max(lv), 1)
        shots.append(shot)
    return shots


def audio_events(loud: list[dict], min_jump: float = 12.0) -> list[dict]:
    """Sudden loudness jumps: onsets of a hit, a laugh, a music sting."""
    ev: list[dict] = []
    vals = [(r["t"], r.get("r128.M", -70.0)) for r in loud]
    for i in range(5, len(vals)):
        t, v = vals[i]
        base = sum(x for _, x in vals[i - 5:i - 1]) / 4
        if v - base >= min_jump and v > -30:
            if ev and t - ev[-1]["t_s"] < 1.0:
                continue
            ev.append({"t_s": round(t, 2), "lufs": round(v, 1), "jump": round(v - base, 1)})
    return ev


def ocr_track(video: str, start: float | None, end: float | None, span: float,
              tmp: Path) -> tuple[str | None, list[dict]]:
    """On-screen text over time: burned-in captions, signs, title cards.

    For a muted clip or one whose words are typed on screen instead of spoken,
    this IS the transcript. One decode writes a frame every `step` seconds;
    OCR runs in parallel batches; identical consecutive reads merge into spans.
    """
    import text_check  # sibling script; only needed when --ocr is asked for
    binary = text_check.vision_binary()
    backend = "vision" if binary else ("tesseract" if shutil.which("tesseract") else None)
    if backend is None:
        print("[index] --ocr skipped: needs macOS + swiftc, or tesseract", file=sys.stderr)
        return None, []
    step = 1.0 if span <= 300 else (2.0 if span <= 1800 else 3.0)
    d = tmp / "ocr"
    d.mkdir()
    rng: list[str] = []
    if start is not None:
        rng += ["-ss", f"{start:.3f}"]
    if end is not None:
        rng += ["-to", f"{end:.3f}"]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *rng, "-i", video,
                    "-vf", f"fps=1/{step},scale='min(1280,iw)':-2", "-q:v", "3",
                    str(d / "o_%06d.jpg")], capture_output=True)
    files = sorted(d.glob("o_*.jpg"))
    batches = [files[i:i + 40] for i in range(0, len(files), 40)]

    def run(batch: list[Path]) -> dict:
        return (text_check.ocr_vision(binary, batch) if backend == "vision"
                else text_check.ocr_tesseract(batch, "eng+chi_sim+tha"))
    rows: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for part in pool.map(run, batches):
            rows.update(part)
    spans: list[dict] = []
    off = start or 0.0
    for i, f in enumerate(files):
        t = off + (i + 0.5) * step
        text = (rows.get(str(f), {}).get("text") or "").strip()
        if len(text.replace(" ", "").replace("|", "")) < 2:
            continue
        # OCR flickers a character between reads of the same caption (字幕 /
        # 字慕), so "same text" means near-identical, not byte-identical.
        same = bool(spans) and difflib.SequenceMatcher(
            None, spans[-1]["text"], text).ratio() >= 0.8
        if same and t - spans[-1]["end_s"] <= step * 1.5:
            spans[-1]["end_s"] = round(t + step / 2, 2)
        else:
            spans.append({"start_s": round(t - step / 2, 2), "end_s": round(t + step / 2, 2),
                          "text": text})
    return backend, spans


def describe(shot: dict, motion_bands, luma_bands) -> str:
    bits = []
    if "motion" in shot:
        bits.append(level(shot["motion"], motion_bands))
        lum = level(shot["luma"], luma_bands)
        if lum != "normal":
            bits.append(lum)
    if "loud_lufs" in shot:
        l = shot["loud_lufs"]
        bits.append("quiet" if l < -40 else ("loud" if l > -18 else "sound"))
    return ", ".join(bits)


def main() -> None:
    ap = argparse.ArgumentParser(description="One-pass shot/motion/audio index.")
    ap.add_argument("video")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--ocr", action="store_true",
                    help="Also read on-screen text over time (captions, signs). The "
                         "transcript of a muted or captioned-only video.")
    args = ap.parse_args()
    need("ffmpeg")
    need("ffprobe")
    video = str(Path(args.video).expanduser().absolute())
    if not Path(video).exists():
        sys.exit(f"no such file: {video}")
    out = Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    meta = probe(video)
    start, end = parse_time(args.start), parse_time(args.end)
    off = start or 0.0
    span = (end if end is not None else meta["duration_s"]) - off
    if span <= 0:
        sys.exit("empty time range")

    tmp = Path(tempfile.mkdtemp(prefix="vu_index_"))
    ocr_backend, onscreen = None, []
    try:
        scene, stats, loud, silences = run_passes(video, start, end, meta["has_audio"], tmp)
        if args.ocr:
            ocr_backend, onscreen = ocr_track(video, start, end, span, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    cuts = detect_cuts(scene)
    shots = build_shots(cuts, span, stats, loud)
    for s in shots:
        for k in ("start_s", "end_s", "sharpest_s"):
            s[k] = round(s[k] + off, 3)
    events = [{**e, "t_s": round(e["t_s"] + off, 2)} for e in audio_events(loud)]
    silences = [(round(a + off, 2), round(b + off, 2)) for a, b in silences]

    # Bands are relative to THIS video, so "high motion" means high for this
    # footage -- a handheld vlog and a locked-off tripod shot both get a spread.
    motions = sorted(s["motion"] for s in shots if "motion" in s)

    def pct(p: float) -> float:
        return motions[min(len(motions) - 1, int(p * len(motions)))] if motions else 0.0
    motion_bands = [(max(0.5, pct(0.25)), "still"), (pct(0.75), "moving"), (1e9, "high motion")]
    luma_bands = [(45, "dark"), (200, "normal"), (1e9, "bright")]

    speech_free = sum(b - a for a, b in silences)
    index = {
        "video": video, "duration_s": round(meta["duration_s"], 2),
        "range": {"start_s": start, "end_s": end},
        "width": meta["width"], "height": meta["height"], "has_audio": meta["has_audio"],
        "shot_count": len(shots),
        "median_shot_s": round(sorted(s["dur_s"] for s in shots)[len(shots) // 2], 2) if shots else 0,
        "silence_s": round(speech_free, 1),
        "shots": shots, "audio_events": events,
        "silences": [{"start_s": a, "end_s": b} for a, b in silences],
        "ocr_backend": ocr_backend,
        "onscreen_text": onscreen,
        "thresholds": {"cut_hard": CUT_HARD, "cut_floor": CUT_FLOOR, "cut_ratio": CUT_RATIO,
                       "min_shot_s": MIN_SHOT_S, "sample_fps": SAMPLE_FPS},
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# Index: {Path(video).name}", "",
             f"{fmt_ts(meta['duration_s'])} long, {len(shots)} shots "
             f"(median {index['median_shot_s']}s), "
             f"{'audio' if meta['has_audio'] else 'NO audio'}, "
             f"{index['silence_s']}s silent.", "",
             "Shot lines: `#n start-end (dur) | motion, light, sound`. "
             "Zoom any span with `frames.py --start --end`.", ""]
    ev_i = 0
    for s in shots:
        tag = describe(s, motion_bands, luma_bands)
        hits = []
        while ev_i < len(events) and events[ev_i]["t_s"] < s["end_s"]:
            if events[ev_i]["t_s"] >= s["start_s"]:
                hits.append(f"sound hit {fmt_ts(events[ev_i]['t_s'])}")
            ev_i += 1
        extra = ("; " + ", ".join(hits)) if hits else ""
        lines.append(f"#{s['index']} {fmt_ts(s['start_s'])}-{fmt_ts(s['end_s'])} "
                     f"({s['dur_s']:.1f}s) | {tag}{extra}")
    if onscreen:
        lines += ["", f"## On-screen text ({ocr_backend} OCR)", ""]
        lines += [f"- {fmt_ts(o['start_s'])}-{fmt_ts(o['end_s'])} {o['text']}" for o in onscreen]
    if silences:
        lines += ["", "## Silences (>= 0.6s)", ""]
        lines += [f"- {fmt_ts(a)}-{fmt_ts(b)} ({b - a:.1f}s)" for a, b in silences[:400]]
    md = out / "index.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[index] {len(shots)} shots, {len(events)} sound hits, "
          f"{len(silences)} silences"
          + (f", {len(onscreen)} on-screen text spans" if args.ocr else ""), file=sys.stderr)
    print(f"INDEX: {md.resolve()}")


if __name__ == "__main__":
    main()
