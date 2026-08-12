# Splitting audio into chunks and transcribing them in parallel

`video-understand` sends the whole audio track to the transcription API in one
request. Splitting it into chunks and uploading them concurrently is out of
scope.

## Why this is out of scope

It is slower. Measured on a 24-minute episode (11.7MB mono 16kHz m4a), same key,
same model:

| Approach | Wall-clock |
| --- | --- |
| One request, whole file | **65s** |
| Same file again (variance check) | 64s |
| 4 chunks of 6 minutes, uploaded in parallel | **142s** |

Chunking is 2.2x slower because ElevenLabs rate-limits per API key. Four
concurrent uploads queue against each other instead of overlapping, so you pay
four round-trips of overhead and get none of the concurrency you split for.

Longer files make the single request look *better*, not worse. The API cost is
mostly fixed overhead rather than a function of duration:

| Duration | Transcribe time | Ratio |
| --- | --- | --- |
| 24 min | 65s | 1:22 |
| 67 min | 80s | 1:50 |

2.8x the runtime for 23% more time. Splitting a 67-minute file into 11 chunks
would pay that fixed overhead eleven times over.

## What to do instead

Run the transcript and the frame extraction concurrently — they share nothing.
That takes a 67-minute film from 168s sequential to **95s**, and the grids
effectively become free. `SKILL.md` documents this as the intended flow.

## If you want to revisit this

The finding is specific to a rate-limited key. An account with a higher
concurrency allowance could plausibly win from chunking. Re-run the measurement
above before changing anything — and if chunking does win, the transcript
assembly also has to re-base each chunk's timestamps onto the full timeline,
which the current single-request path never has to do.
