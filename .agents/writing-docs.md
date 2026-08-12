# Writing docs pages

Every skill has a human-facing page at `docs/<skill-name>.md`. It is not the
skill and not a copy of `SKILL.md`. `SKILL.md` tells an agent what to run; the
docs page orients a human deciding whether to reach for it at all.

Create or re-sync the page whenever a skill is added, renamed, or changes
behaviour. A rename moves the file, because the page is addressed by skill name.

## Page structure

Fill the template below, keeping its order. `## What it does`, `## When to reach
for it`, and `## Where it fits` appear on every page. The rest carry only what
this skill needs — delete the ones that would be padding.

```markdown
## What it does

One or two plain paragraphs. Lead with the skill's one-sentence job, then state
the **defining constraint** — the single fact that makes it behave differently
from the obvious default. Write it as a plain declarative sentence, never a
labelled aside like "The key thing is:" — the formula reads as filler. This is
the most valuable line on the page.

## When to reach for it

Two beats:
- **Invocation mode** — do you type it, or does the agent fire it?
- **Trigger boundary** — "reach for this when …", and where it is confusable
  with a sibling, the other half: "for X instead, use <sibling>".

## Prerequisites

Optional. Include only where something must be in place — a key, a CLI, a
workspace it writes into. A skill that runs anywhere drops this section.

## <free-form middle>

One to three short sections in the skill's own vocabulary that make it click.
No prescribed heading. The non-negotiable: surface the skill's **leading word**
(grid, budget, distinctness) — the reader learns what it is and the word they
will later think with to reach for it.

## Common questions

Real questions, each in bold with the answer beneath. No sub-headings.

## It's working if

Bullets naming what the reader sees when it is working. Each must be checkable
without opening `SKILL.md`.

## Where it fits

A sentence or two placing the skill among its neighbours.
```

## Conventions

- **Explain the why, not the process.** The page never reproduces `SKILL.md`'s
  steps. Someone choosing a tool does not need the runbook.
- **An observed question beats an invented one.** Hunt before writing: the
  repo's issues, the changelog, what people actually asked. A well-discussed
  skill earns six questions; an obscure one earns one or two, or none. Padding a
  thin skill to match a rich one fills the section with questions nobody asked,
  and an invented question teaches nothing.
- **Branches go in a table or a list, never a paragraph.** Where the page
  presents a choice, the reader is scanning for the row that matches their
  situation. A paragraph makes them read all of it first.
- **Name no author.** "X says", a quoted reply, an attributed position — all of
  it goes. State the substance as a plain claim. An opinion carries the same
  weight either way, and an attributed one dates the moment the position moves.
  Quoting a *user* is fine and stays anonymous: "one user hit …" is evidence.
- **Every number is measured.** Cite what it was measured on (duration, codec,
  resolution). A performance claim with no source is a guess wearing a number.
- **Say the unflattering thing where it is true.** The limits section is worth
  more than the feature list — a reader who trusts the limits trusts the rest.

## Done when

- [ ] `## What it does` states the defining constraint as plain prose
- [ ] `## When to reach for it` gives invocation mode and trigger boundary
- [ ] Every multi-way branch is a table or list
- [ ] Questions come from real ones, and the count is honest to what was found
- [ ] Every `## It's working if` bullet is checkable without `SKILL.md`
- [ ] No author is named
- [ ] Every number says what it was measured on
- [ ] Every link resolves
