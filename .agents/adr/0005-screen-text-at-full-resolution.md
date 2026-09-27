# Screen for burned-in text at full resolution, with a measured threshold

Finding reusable footage means sorting many downloads into "someone typed over
this" and "clean". Grids are the wrong tool for that: they answer what happens
in one video, and building them for fifty clips just to spot subtitles wastes
the tokens the grid exists to save. So `text_check.py` samples a few frames per
clip and runs OCR, with no model in the loop.

The first version downscaled frames to 720px wide and discarded OCR reads under
0.5 confidence. On 54 RedNote clips it called one clip clean even though it had
small burned-in subtitles. Looking at the frames by eye caught the miss. Sampling
at the source resolution with a 0.3 confidence floor now reports 100 characters
on that clip.

Lowering the floor also picks up noise, so "any text at all" is too strict a
cut. On the same 54 clips, noise on footage verified clean by eye topped out at
4 characters. The smallest real overlay, a phone screenshot's status bar,
measured 18. Subtitles ran 30 to 1,122. The default `--max-chars 8` sits in the
gap between the two.

| Choice | Measured on 54 RedNote clips |
| --- | --- |
| 720px, confidence ≥ 0.5 (rejected) | 9 marked clean; 2 carried text (subtitles, a screenshot overlay) |
| Full-res, confidence ≥ 0.3, 0 chars | 5 marked clean; 2 visually clean clips rejected over 2- and 4-char noise |
| Full-res, confidence ≥ 0.3, ≤ 8 chars (chosen) | 7 marked clean, all visually clean |

Vision is the default backend on macOS because the machine already has it and
it reads Chinese, Japanese, Korean and Thai with no packs to install. Python
cannot call it from the standard library, so a small Swift helper is compiled on
first use and cached in `~/.cache/video-understand/`. `tesseract` is the portable
fallback.

Vision needs full language codes (`th-TH`, `ja-JP`, `ko-KR`) and silently
ignores ones it does not know. The first helper passed `th`, `ja` and `ko`, so
it only ever read Chinese and English: on a Thai film with burned-in subtitles
it returned no Thai at all. Languages are now a flag (`--lang` /
`--ocr-lang`, short codes mapped to Vision's), default `zh,en`. Re-running the
54-clip measurement with the new default reproduced every number above.
