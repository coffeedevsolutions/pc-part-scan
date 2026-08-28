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

## 2. Daily digest — retired 2026-08-28

Ran weekday mornings and summarised the top actionable lots, watched lots
closing within 24h, and sold-price surprises. Deleted because the Board does
all of that live, sorted and clickable, for anyone who opens it — a routine
whose output is a worse copy of a page you already visit is a cost with no
reader. Nothing replaced it.

## 3. Weekly health review — Mondays

**Rewritten 2026-08-28**, after five of nine scheduled scans silently failed
to fire and the board served an eight-hour-old snapshot with nothing
anywhere saying so. It was found by hand, because it was nobody's job.

The Ops page shows the runs that *happened*. This routine is the only thing
that asks about the runs that *should* have happened and did not, which is
now its headline question. It reports, in order:

1. **Scheduled delivery** — runs fired vs. runs the cron asked for, over
   seven days, per workflow. Anything under ~70% is flagged. It also reports
   how often `pcps scan` promoted itself to a deep sweep
   (`job_runs.counts.caught_up`, see ARCHITECTURE §5a): a high rate means
   the data recovered but the schedule is still unreliable.
2. **Data freshness** — age of the newest snapshot and bid observation.
3. **The eBay resale panel** — has `ebay-watch` run every day? A missed day
   is a batch of departures nothing can recover (§11d). Plus panel size and
   whether `pcps recovery` yet has a measured figure or only an ask-derived
   one.
4. **Model health** — single-unit R², bulk k and its trust flag, class-table
   coverage, week over week. An R² drop over 0.05 is flagged.
5. **Anything failing** — failed `job_runs`, red workflows, manifest-triage
   backlog.

The final message is the deliverable and reaches the owner through the
routine's completion notification. Routine-fired sessions carry no GitHub
tooling, so findings are reported, not filed as issues.

## Operational notes

- Created 2026-08-24 by the session that built this system:
  `pcps manifest triage` (trig_01MS9dQjrBrMD7MHsaPCmkeY),
  `pcps daily digest` (trig_01R6Exun9y5AZjsswN87jDpU, push+email
  notifications), `pcps weekly health review`
  (trig_01DqEtRWa6qVh18kQC2FM8mP, push+email). Manageable by any later
  Claude session (`list_triggers` / `update_trigger`) or from
  claude.ai → Routines.
- Schedules (UTC): triage `30 9 * * *` · digest `30 11 * * 1-5` · health
  `0 13 * * 1`.
- Cost control: triage caps at 8 sheets/run; all three end quietly when
  there is nothing to do.
