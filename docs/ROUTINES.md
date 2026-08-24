# Claude Routines — the judgment layer

Three scheduled Claude sessions (architecture §8). Each fires as a fresh
session in the repo's Claude Code environment, uses the `pcps` commands for
all mechanical data access, and does only the work that needs judgment. The
pipeline is fully functional with all three off.

**Prerequisite:** `MONGODB_URI` must be set in the Claude Code environment's
variables (claude.ai/code → environment settings). Every prompt begins with a
guard that ends the session quietly when it is missing.

Shared preamble (every routine):

> Install the pipeline first: `pip install ./pipeline`. If `MONGODB_URI` is
> not set in the environment, print one line noting it and end — do not
> improvise another data path. Never commit or push anything to the
> repository. Never place bids or authenticate to any auction site.

## 1. Manifest triage — daily

The bulk-discount model's bottleneck is exact manifests: most bulk lots have
a spec-sheet PDF the regex parser cannot read. This routine reads them.

Prompt sketch:

1. `pcps triage-queue --limit 8` — bulk lots whose parse attempt came up
   empty.
2. For each: `pcps triage-fetch --key <key> --out attachments/` and READ the
   downloaded PDFs. Extract the machine mix — one entry per line item:
   `{cpu, generation, ram_gb, form_factor, chassis, has_drive, qty}`. Use
   lowercase CPU model strings like `i5-8500`; leave unknown fields null.
   Skip a sheet that genuinely lists no per-machine specs.
3. Write the JSON and store it:
   `pcps save-manifest --key <key> --file m.json`. The command validates
   quantities against the title's stated unit count; only pass
   `--allow-mismatch` when the sheet itself contradicts the title and the
   sheet is clearly right.
4. Finish with a one-paragraph summary: how many sheets read, how many
   manifests stored, and anything systematic the regex parser could learn
   (leave that observation in the summary — do not edit parser code).

## 2. Daily digest — weekday mornings

1. `pcps digest` — top actionable lots, watched lots closing within 24h,
   sold-price surprises (model badly wrong in either direction), job health.
2. Write a short human digest: the 3 most actionable lots with one line of
   reasoning each (headroom, confidence, close time, location), any watched
   lot closing today, any surprise worth a look, and a one-line "pipeline
   ok/not ok". No tables, no fluff. This summary is the deliverable — it
   reaches the owner through the routine's completion notification.

## 3. Weekly health review — Mondays

1. `pcps health` — recent model fits, the close-hour histogram, `raw_extra`
   key frequencies, job failures, manifest coverage.
2. Judge: is R² drifting down? Is the bulk-n growing week over week (it
   should, while triage runs)? Does the close-hour histogram still support
   the burst window in `.github/workflows/burst.yml` (22:40 UTC weekdays)?
   Any new `raw_extra` keys that suggest upstream API changes? Repeated job
   failures?
3. For each real finding, open ONE GitHub issue on this repository titled
   `health: <finding>` with the evidence and a proposed change — do not push
   code. Skip issues for anything already reported and still open. End with
   a one-paragraph summary either way.

## Operational notes

- The routines were created by the Claude session that built this system and
  can be updated or deleted by any later Claude session (`list_triggers`,
  `update_trigger`) or from claude.ai → Routines.
- Schedules (UTC): triage `30 9 * * *` · digest `30 11 * * 1-5` · health
  `0 13 * * 1`.
- Cost control: triage caps at 8 sheets/run; all three end quietly when
  there is nothing to do.
