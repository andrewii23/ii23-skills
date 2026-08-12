# Shrinking the audio upload to speed up transcription

`video-understand` extracts mono 16kHz AAC at 64kbps before uploading. Making
that file smaller — a lower bitrate, Opus instead of AAC — to speed up the
transcription request is out of scope.

## Why this is out of scope

Upload size is not the bottleneck. Measured on the same 24-minute episode:

| File | Size | Wall-clock |
| --- | --- | --- |
| AAC 64k mono 16kHz (current) | 11.7 MB | **65s** |
| Opus 24k mono 16kHz | 4.3 MB | **182s** |
| Stream-copy, no re-encode (`-c:a copy`) | 22.1 MB | 73s |

Opus was 2.7x smaller and 3x slower. The transcripts were equivalent — 10,574
vs 10,799 characters of the same dialogue — so nothing was gained for the wait.

Stream-copy is the interesting near-miss. It skips re-encoding entirely, so
extraction drops from 3.4s to 0.13s (25x faster), but the resulting 22MB upload
adds about 8s to the request. Net loss, and it also makes the pipeline depend on
the source's codec and channel count rather than normalising them.

## What this means

The current extraction settings are already the right trade: small enough to
upload quickly, cheap enough to produce, and normalised to what ASR wants
regardless of what the source video contains.

## If you want to revisit this

A slow uplink changes the arithmetic — these numbers came from a connection
where 11.7MB uploads in a few seconds. On a constrained link, a 4.3MB file could
plausibly win. Measure both on the actual network before switching, and check
transcript equivalence (character count and a spot-check of proper nouns), not
just wall-clock.
