Each skill lives at `skills/<name>/` with a `SKILL.md` and, where it needs them,
a `scripts/` folder. Scripts are stdlib-only Python so a skill installs by
copying a folder.

Adding, renaming, or removing a skill means updating **three** places, or the
repo starts lying about itself:

1. `README.md` — a problem-and-fix section under "Why these exist", plus a row
   in the Skills table. Every mention links to the skill's `SKILL.md`.
2. `skills.sh.json` — the skill's name in a grouping's `skills` array.
3. `docs/<name>.md` — the human-facing page. Follow
   [.agents/writing-docs.md](./.agents/writing-docs.md); a rename moves the file.

`SKILL.md` is the agent contract: what to run, in what order, and the traps to
avoid while doing it. It is not the place for the reasoning behind a decision.
That goes in `.agents/adr/`, and a rejected approach goes in `.out-of-scope/`
with the measurement that killed it — so nobody re-proposes it and no agent
burns a session rediscovering it.

Numbers in any document are measured, never estimated. Every performance claim
in this repo came from a real run on a real file; if you change a claim, re-run
the measurement first and say what you ran it on.

Validate a skill after editing it:

```bash
python3 ~/.agents/skills/skill-creator/scripts/quick_validate.py skills/<name>
```

Frontmatter limits it enforces: `name` <= 64 chars, `description` <= 1024. The
`description` is what makes a skill trigger, so it carries the trigger phrases
(including Thai ones) and an explicit "do NOT use for ..." boundary.
