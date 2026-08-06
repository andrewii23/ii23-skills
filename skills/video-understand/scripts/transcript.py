#!/usr/bin/env python3
"""Get a timestamped transcript for a video -- the half of understanding that
frames cannot supply.

Grids show what is on screen; they never show what was SAID. On a 24-minute
episode the grid alone yields the arc (someone is accused, a gadget appears, a
shadow chases them) while every fact that matters -- what was stolen, the
gadget's name and rule, how it resolves -- lives entirely in the audio. Pair the
two or the read is a guess.

Sources, in priority order:

  elevenlabs  Scribe v2, word-level timestamps. Default, and the most accurate
              option for Thai. Needs ELEVENLABS_API_KEY.
  captions    Native subtitles pulled by yt-dlp. Free and instant, but only for
              URLs that publish them.
  whisper     Local faster-whisper. Free, offline, no key, slower and weaker on
              Thai.

Usage:
  python3 transcript.py VIDEO_OR_URL --out transcript.json
                        [--source auto|elevenlabs|captions|whisper] [--lang th]

Output JSON:
  {source, language, duration_s, segments:[{t_ms, end_ms, t_label, text}], words:[...]}
  prints the path on the last line as `TRANSCRIPT: <abs-path>`

Exit codes:
  0  transcript written
  1  bad args / missing input
  2  no usable source (no key, no captions, no whisper)
  3  the source ran but returned nothing

Requires: ffmpeg on PATH. Python stdlib only (yt-dlp / faster-whisper optional).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL = "scribe_v2"

# ElevenLabs speaks ISO 639-3; accept the 2-letter codes people actually type.
ISO3 = {"th": "tha", "en": "eng", "ja": "jpn", "zh": "zho", "ko": "kor",
        "es": "spa", "fr": "fra", "de": "deu", "id": "ind", "vi": "vie"}


def fmt_ts(ms: int) -> str:
    s, ms_r = divmod(int(ms), 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}.{ms_r // 100}"
    return f"{m:02d}:{sec:02d}.{ms_r // 100}"


def load_env_file() -> None:
    """Walk up from cwd for a .env and load it WITHOUT overriding real env vars.

    Shell-exported keys must win: a stale .env silently shadowing the key the
    user just exported is a maddening failure to debug.
    """
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        f = d / ".env"
        if not f.exists():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            pass
        return


def is_url(v: str) -> bool:
    return v.startswith("http://") or v.startswith("https://")


def extract_audio(video: str, dest: Path) -> bool:
    """Mono 16kHz m4a -- small enough to upload, plenty for ASR."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video,
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def multipart_post(url: str, headers: dict, fields: dict, file_path: Path) -> bytes:
    """Minimal multipart/form-data POST so this stays stdlib-only."""
    boundary = f"----vu{uuid.uuid4().hex}"
    pre = bytearray()
    for k, v in fields.items():
        pre += (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    pre += (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n").encode()
    body = bytes(pre) + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=900) as resp:
        return resp.read()


def group_words(words: list[dict], max_gap_ms: int = 700,
                max_chars: int = 90) -> list[dict]:
    """Group word timings into readable lines.

    Splits on a real pause or on length. Thai has no spaces, so never join on
    whitespace -- concatenate and let the gap decide the boundary.
    """
    out: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if not cur:
            return
        text = "".join(w["text"] for w in cur).strip()
        if text:
            out.append({"t_ms": cur[0]["t_ms"], "end_ms": cur[-1]["end_ms"],
                        "t_label": fmt_ts(cur[0]["t_ms"]), "text": text})
        cur.clear()

    for w in words:
        if cur:
            gap = w["t_ms"] - cur[-1]["end_ms"]
            wide = sum(len(x["text"]) for x in cur) >= max_chars
            if gap > max_gap_ms or wide:
                flush()
        cur.append(w)
    flush()
    return out


def via_elevenlabs(audio: Path, lang: str | None) -> dict:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    fields = {"model_id": ELEVENLABS_MODEL, "timestamps_granularity": "word"}
    code = ISO3.get(lang, lang) if lang else None
    if code:
        fields["language_code"] = code
    try:
        raw = multipart_post(ELEVENLABS_URL, {"xi-api-key": key}, fields, audio)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {detail}") from e
    data = json.loads(raw)

    words = []
    for w in data.get("words", []) or []:
        # `audio_event` entries are sounds like [laughter], not speech. Keeping
        # them corrupts both the text and the timing of real words.
        if w.get("type") == "audio_event":
            continue
        t = w.get("text", "")
        if not t:
            continue
        words.append({"text": t,
                      "t_ms": int(round(float(w.get("start", 0)) * 1000)),
                      "end_ms": int(round(float(w.get("end", 0)) * 1000))})
    return {"language": data.get("language_code") or lang,
            "words": words,
            "segments": group_words(words)}


def via_captions(url: str, lang: str | None) -> dict:
    """Native subtitles via yt-dlp. Free, but only when the platform has them."""
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp not installed")
    tmp = Path(tempfile.mkdtemp(prefix="vu_subs_"))
    try:
        langs = lang or "th,en"
        r = subprocess.run(
            ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", langs, "--sub-format", "vtt/srt",
             "--convert-subs", "srt", "-o", str(tmp / "s.%(ext)s"),
             "--no-warnings", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        files = sorted(tmp.glob("*.srt"))
        if not files:
            raise RuntimeError(f"no captions available: {(r.stderr or '')[-200:]}")
        return {"language": lang, "words": [],
                "segments": parse_srt(files[0].read_text(encoding="utf-8", errors="replace"))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_srt(text: str) -> list[dict]:
    def to_ms(s: str) -> int:
        s = s.replace(",", ".").strip()
        h, m, rest = s.split(":")
        return int((int(h) * 3600 + int(m) * 60 + float(rest)) * 1000)

    segs: list[dict] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        stamp = next((ln for ln in lines if "-->" in ln), None)
        if not stamp:
            continue
        body = " ".join(lines[lines.index(stamp) + 1:]).strip()
        if not body:
            continue
        try:
            a, b = stamp.split("-->")
            t0, t1 = to_ms(a), to_ms(b)
        except (ValueError, IndexError):
            continue
        if segs and segs[-1]["text"] == body:  # auto-subs repeat rolling lines
            segs[-1]["end_ms"] = t1
            continue
        segs.append({"t_ms": t0, "end_ms": t1, "t_label": fmt_ts(t0), "text": body})
    return segs


def via_whisper(audio: Path, lang: str | None) -> dict:
    """Local faster-whisper. Free and offline; weaker on Thai than Scribe."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper not installed (pip install faster-whisper)") from e
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "base"),
                         device="auto", compute_type="int8")
    segments, info = model.transcribe(str(audio), language=lang, word_timestamps=True)
    words: list[dict] = []
    segs: list[dict] = []
    for s in segments:
        text = (s.text or "").strip()
        if text:
            segs.append({"t_ms": int(s.start * 1000), "end_ms": int(s.end * 1000),
                         "t_label": fmt_ts(int(s.start * 1000)), "text": text})
        for w in (getattr(s, "words", None) or []):
            words.append({"text": w.word, "t_ms": int(w.start * 1000),
                          "end_ms": int(w.end * 1000)})
    return {"language": getattr(info, "language", lang), "words": words,
            "segments": segs}


def main() -> None:
    ap = argparse.ArgumentParser(description="Timestamped transcript for a video.")
    ap.add_argument("video", help="Local path or URL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="auto",
                    choices=["auto", "elevenlabs", "captions", "whisper"])
    ap.add_argument("--lang", default=None, help="e.g. th, en (auto-detect if unset)")
    args = ap.parse_args()

    load_env_file()
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH.")

    src, video = args.source, args.video
    local = not is_url(video)
    if local and not Path(video).expanduser().exists():
        sys.exit(f"no such file: {video}")

    order = ([src] if src != "auto"
             else (["captions", "elevenlabs", "whisper"] if not local
                   else ["elevenlabs", "whisper"]))

    tmp = Path(tempfile.mkdtemp(prefix="vu_audio_"))
    audio: Path | None = None
    result: dict | None = None
    errors: list[str] = []

    try:
        for cand in order:
            try:
                if cand == "captions":
                    if local:
                        raise RuntimeError("captions only apply to URLs")
                    result = via_captions(video, args.lang)
                else:
                    if audio is None:
                        if not local:
                            raise RuntimeError(
                                "download the video first, then pass the local path")
                        audio = tmp / "a.m4a"
                        if not extract_audio(str(Path(video).expanduser()), audio):
                            raise RuntimeError("audio extraction failed")
                    result = (via_elevenlabs(audio, args.lang) if cand == "elevenlabs"
                              else via_whisper(audio, args.lang))
                if result and result.get("segments"):
                    result["source"] = cand
                    break
                errors.append(f"{cand}: returned nothing")
                result = None
            except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as e:
                errors.append(f"{cand}: {e}")
                print(f"[transcript] {cand} failed: {e}", file=sys.stderr)
                result = None

        if not result:
            for line in errors:
                print(f"  - {line}", file=sys.stderr)
            sys.exit(2 if not errors else 3)

        segs = result["segments"]
        payload = {
            "video": video if not local else str(Path(video).expanduser().resolve()),
            "source": result["source"],
            "language": result.get("language"),
            "duration_s": round(segs[-1]["end_ms"] / 1000, 2) if segs else 0,
            "segment_count": len(segs),
            "segments": segs,
            "words": result.get("words", []),
        }
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[transcript] {result['source']}: {len(segs)} segments", file=sys.stderr)
        print(f"TRANSCRIPT: {out.resolve()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
