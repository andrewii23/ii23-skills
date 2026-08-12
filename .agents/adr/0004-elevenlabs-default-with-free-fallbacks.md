# Default to ElevenLabs for transcripts, but never require it

Transcripts carry the half of a video that frames cannot show, so their accuracy
decides whether a summary is right. ElevenLabs Scribe v2 is the default because
it gives word-level timing and handles Thai better than the alternatives — on
Thai dubbed anime it returned proper nouns intact where cheaper models garble
them.

Requiring it would be the wrong call for a public repo. The skill's other job is
to work at all for someone who just cloned it, so two free paths sit behind the
default:

| Source | Cost | When it applies |
| --- | --- | --- |
| `elevenlabs` | paid key | Default. Best accuracy, especially Thai. |
| `captions` | free | URLs whose platform publishes subtitles. Instant — no ASR at all. |
| `whisper` | free | Local `faster-whisper`. Offline, weaker on Thai. |

They are tried in order and each is selectable with `--source`. A missing key
degrades the skill rather than breaking it.

The tiers are not equivalent, so the skill says which one produced a transcript
rather than presenting them as interchangeable. Where every source fails it
exits non-zero and the agent is told to say so plainly and continue with frames
only — an invented line of dialogue is worse than an admitted gap.
