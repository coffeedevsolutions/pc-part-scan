# Self-sufficient system architecture

Target: a system that harvests, values and grades GovDeals bulk-computer lots
**continuously and unattended**, serves an interactive web workbench for
analysing them, and improves its own weakest data (spec-sheet manifests) over
time — all on free-tier infrastructure.

Decisions locked in with the owner (2026-08-23):

| Decision | Choice |
|---|---|
| Hosting budget | Free tier only: GitHub Actions, MongoDB Atlas M0, Vercel Hobby |
| Web UI depth | Single-user interactive workbench (watchlist, notes, live assumptions) |
| Scan cadence | Close-time-weighted baseline + one targeted burst window per weekday, sized to fit private-repo Actions minutes (2,000/month) |
| Repo visibility | Stays private; schedules fit the free-minute cap (§5) |
| eBay | Yes — official Browse/Insights API via a free developer account |

## 1. What exists today (baseline)

- ~2,000 lines of Python: API client, PDF spec parsing, harvest sweeps, two
  fitted price models (single-unit R²≈0.90 on 416 obs; bulk discount k≈0.57 on
  41 obs), max-bid grading.
- Durable dataset is **flat JSON files committed to git** (`data/`): 8,645
  lots, 44k bid observations, 47 manifests, 6 snapshots.
- Runs are manual (`python scan.py`). No web interface. eBay adapter exists
  but is inert without credentials.

Two structural problems drive most of this plan:

1. **Git is the database.** Every scan commits ~10–15k bid observations of
   JSON into the repo. That bloats history unboundedly, can't be queried by a
   web app, and makes concurrent writers (scheduled scan + burst scan + web app)
   impossible.
2. **Nothing runs on a schedule**, but the whole value of `bid_history.jsonl`
   is temporal density — especially the final-hour surge, which is currently
   never captured.

## 2. Target architecture

```
                 ┌───────────────────────────── GitHub repo (monorepo) ─────┐
                 │  pipeline/ (Python)   apps/web/ (Next.js)   packages/    │
                 └──────────────┬───────────────────┬──────────────────────┘
                                │ deploys via        │ deploys via
        GitHub Actions (cron)   │ Actions            │ Vercel git integration
   ┌────────────────────────────▼─────────┐   ┌──────▼──────────────────────┐
   │ scan.yml      9×/day, close-weighted │   │ Vercel (Hobby)              │
   │ burst.yml     peak-window 2-min poll │   │  Next.js workbench          │
   │ fit.yml       daily refit + eBay     │   │  Auth.js (email allowlist)  │
   │ archive.yml   weekly dump + prune    │   │  TS valuation (live regrade)│
   └──────┬───────────────────────────────┘   └──────┬──────────────────────┘
          │ writes                                   │ reads lots/models,
          ▼                                          ▼ writes watchlist/notes
   ┌──────────────────────── MongoDB Atlas M0 (system of record) ───────────┐
   │ lots · bid_observations · manifests · model_runs · ebay_comps ·        │
   │ component_prices · watchlist · lot_actions · settings · job_runs       │
   └──────┬─────────────────────────────────────────────────────────────────┘
          │ weekly JSONL.gz dump                    ▲
          ▼                                         │ parsed manifests,
   GitHub Releases (free durable backup)            │ parser fixes, digests
                                                    │
   ┌────────────────────────────────────────────────┴───────────────────────┐
   │ Claude Routines (judgment layer, not pipeline backbone)                │
   │  daily: parse spec-sheet PDFs the regex parser failed on (LLM extract) │
   │  daily: digest of top graded lots + anomalies → owner                  │
   │  weekly: model-health review (R² drift, schema drift in raw_extra)     │
   └────────────────────────────────────────────────────────────────────────┘

   External: maestro.lqdt1.com (GovDeals JSON API) · api.ebay.com (Browse /
   Marketplace Insights) · files.lqdt1.com (spec-sheet PDFs)
```

Division of labour, stated once:

- **GitHub Actions** runs everything deterministic on a schedule. It is the
  backbone.
- **MongoDB Atlas** is the single system of record and the serving store for
  the web app. Git stops being a database.
- **Vercel + Next.js** serves the workbench and owns user state.
- **Claude Routines** do only what needs judgment: reading messy PDFs the
  regex parser can't, writing digests, and reviewing model health. They are
  additive — the pipeline is fully functional if every routine is off.

## 3. Monorepo layout

pnpm workspaces for the JS side; plain `pyproject.toml` for Python. No
Turborepo/Nx — one app and one Python package don't need build orchestration.

```
pc-part-scan/
  pipeline/                    # the existing Python code, promoted to a package
    pyproject.toml             # deps, [project.scripts] pcps = pcpartscan.cli:main
    src/pcpartscan/
      api.py specs.py harvest.py pricing.py grade.py
      store/
        mongo.py               # NEW: Mongo read/write layer
        files.py               # legacy data/ reader, kept for backfill only
      cli.py                   # scan / burst / fit / backfill / archive subcommands
    tests/                     # spec-parsing + grading golden tests
  apps/
    web/                       # Next.js App Router, deployed to Vercel
  packages/
    valuation/                 # TS port of grade.py math + zod schemas
  .github/workflows/           # scan.yml burst.yml fit.yml archive.yml ci.yml
  docs/                        # this file, API.md, SCHEMA.md
  data/                        # frozen legacy dataset; used once for backfill,
                               # then removed from the working tree
```

`packages/valuation` exists so the web app can regrade lots live as the user
moves the ROI/recovery sliders, without a Python service. It is kept honest by
**golden-file parity tests**: CI runs the Python grader and the TS grader over
the same fixture snapshot and asserts identical max-bid output to the cent.

## 4. Data layer — MongoDB Atlas M0

One free M0 cluster (512 MB), one database `pcps`. Connection string lives in
GitHub Actions secrets and Vercel env as `MONGODB_URI`.

### Collections

| Collection | Keyed by | Write pattern | Notes |
|---|---|---|---|
| `lots` | `_id = "<accountId>-<assetId>"` | upsert per scan | Same shape as today's lot record incl. `raw_extra`; adds `latest_bid`, `latest_grade` denormalised for cheap board queries |
| `bid_observations` | auto `_id` | **insert-only** | `{key, observed_at, run_id, bid, bid_count, source: "scan"\|"burst"}` — written **only when the bid or bid_count changed** since the last observation for that key (plus one heartbeat obs/day per open lot) |
| `sold` | lot key | upsert once | realized price, close date |
| `manifests` | lot key | upsert | machine mix + `parsed_by: "regex"\|"llm"` + confidence |
| `model_runs` | `run_id` | insert per fit | full coefficients, R², n, k — today's `models.json`/`components.json` merged |
| `component_prices` | cpu key | upsert | the hand-editable static table, moved out of CSV; UI-editable |
| `ebay_comps` | `{cpu, ram_gb}` | upsert daily | median comp, n, `fetched_at`; the blend reads only this cache, never eBay directly |
| `watchlist`, `lot_actions`, `notes`, `settings` | — | web app | user state: watch/pass/bid/won, per-lot notes, assumption overrides |
| `job_runs` | run_id | insert | started/finished/counts/errors per scheduled job — the ops heartbeat the UI and routines read |

Indexes: `lots {status, auction_end_utc}`, `lots {location.state}`,
`bid_observations {key, observed_at}`, `sold {close_date}`,
`ebay_comps {fetched_at}`.

### Fitting 512 MB, honestly

A bid observation is ~180 B in BSON. Naive writes at 9 scans/day for ~1,500
open lots are ~400k docs/month (~75 MB/month) — the M0 would fill within a
year, sooner if the corpus grows. Three mitigations, all in the plan:

1. **Change-only writes** (above). Most lots' bids don't move most hours;
   this is a 5–10× reduction and loses nothing (a flat bid between two
   observations is fully implied).
2. **Downsampling after close.** 30 days after a lot closes, its curve is
   compressed to keypoints (first, last, every bid change ≥ $1 kept — which
   change-only writes already approximate — capped at 500 points/lot).
3. **Archive + prune.** `archive.yml` dumps every collection weekly as
   `jsonl.gz` to a GitHub Release (free, durable, versioned), then prunes
   observations older than 12 months from Mongo. Nothing is ever lost; Mongo
   holds the working set, Releases hold the full history.

### Migration from `data/`

One-time `pcps backfill` reads the committed `data/` tree (8.6k lots, 44k
observations, 47 manifests, all model runs) and loads Mongo. After
verification, `data/` is deleted from the working tree and the scan workflows
stop committing data to git. Git history keeps the old snapshots; the release
archive takes over from there.

## 5. Ingestion & scheduling — GitHub Actions

### The minutes budget

The repo stays **private**, so the hard constraint is the free tier's
**2,000 Actions minutes/month (~66 min/day)**, with each job billed rounded
**up** to the nearest minute — which rules out frequent tiny gate jobs (a
20-second run bills as 1 minute; a `*/15` gate would cost ~2,900 min/month
while idle). The schedule below is therefore shaped by when lots actually
close. From the harvested corpus (n=8,645): ~90% of lots close between
12:00–00:00 UTC, weekdays outnumber weekends ~4:1, and 22:00–23:59 UTC is the
single heaviest band (~21% of all closings).

| Job | Cadence | Est. cost/month |
|---|---|---|
| `scan.yml` | 9×/day, dense in the closing band | ~1,100 min |
| `burst.yml` | 1×/weekday, 20 min, peak window | ~440 min |
| `fit.yml` | daily, ~4 min | ~120 min |
| `archive.yml` | weekly, ~4 min | ~16 min |
| `ci.yml` | on PR/push | ~150 min |
| **Total** | | **~1,830 min** (headroom ~170) |

What this buys vs. an unconstrained schedule: baseline bid curves at 2–3 h
resolution instead of 1 h, and ~2-minute final-surge resolution for lots
closing in one peak window per weekday (watchlist and A/B grades first)
instead of for every interesting lot. Escape hatch if that ever hurts: a
**self-hosted runner** on any spare machine makes minutes unlimited while
keeping the repo private — the workflows only change `runs-on`, nothing else.
Given the nature of this project, a spare desktop is likely on hand; this is
the recommended upgrade path before paying for anything.

### Workflows

**`scan.yml` — 9×/day, close-time-weighted**
Crons: `0 12,14,16,18,20,22 * * *` (every 2 h through the closing band),
plus `0 0,3,8 * * *` (overnight coverage). Each run (~4 min): sweep live lots
across the query list, upsert `lots`, write change-only `bid_observations`,
sweep a few sold pages to catch new closures, mark newly-sold lots, fetch
manifests for new bulk lots (budgeted), grade all open lots with the latest
model and write `latest_grade` onto each lot. The 00:00 UTC run doubles as
last-look coverage for the 600-lot midnight-close cohort. Concurrency group
`scan` with `cancel-in-progress: false` so runs never overlap. Cron jitter
(3–15 min on shared runners) is fine — observations carry their true
`observed_at`.

**`burst.yml` — one targeted window per weekday (`40 22 * * 1-5`)**
Queries Mongo for open lots closing within the horizon (~100 min), groups
them **by seller**, and polls one `accountIds`-scoped search per seller every
~2.5 minutes for up to 20 minutes — the detail endpoint carries no bid
fields (see docs/API.md), so per-seller search is the cheapest way to read
current bids, and one request covers every closing lot that seller has.
Observations land with `source: "burst"`; change-only writes keep volume
proportional to what actually moved, and the accompanying lot upserts
refresh `auction_end_utc`, capturing sniping-driven end-time extensions.
This sits on the empirical peak (the 23:00 UTC close cohort is the largest
of the day), so the budget's one burst lands where the most late-surge data
is. The weekly health routine (§8) re-checks the close-time histogram and
proposes a new window if seller behaviour drifts. Watched lots closing
outside the window rely on the 2-hourly scans — worth knowing when deciding
how long to leave a bid to the last minute.

**`fit.yml` — daily (`30 9 * * *` UTC)**
`pcps fit`: rebuild observations from Mongo, refit the single-unit model and
bulk discount, insert a `model_runs` doc. Then `pcps ebay-refresh`: for every
CPU/config appearing in any open lot's manifest or title, query the eBay
Browse API (Insights once approved), upsert `ebay_comps`. Comp queries are
deduplicated and cached for 24 h, keeping usage far under the 5,000
calls/day free limit. If R² drops more than 0.05 from the previous run, the
job opens a GitHub issue rather than silently shipping a worse model.

**`archive.yml` — weekly (`0 6 * * 1`)**
Dump + prune as described in §4. Also posts collection sizes to `job_runs` so
Atlas usage is visible in the UI before it becomes a problem.

**`ci.yml` — on PR/push**
Python: ruff + pytest (spec-parser fixtures, grading goldens). TS: lint,
typecheck, `packages/valuation` parity test against the Python golden output,
`next build`.

All jobs write a `job_runs` doc on start and finish; a job that fails twice
consecutively opens a GitHub issue (deduped by label). That is the alerting
system — free, and it lands where the owner already looks.

## 6. Valuation upgrades

- **eBay in the blend.** `EbayAdapter` stops calling the network at grade
  time; it reads `ebay_comps` from Mongo (populated by `fit.yml`). Start with
  Browse (active asks, haircut applied as the grader already does for asks);
  apply for Marketplace Insights for true sold prices and flip `EBAY_INSIGHTS`
  when approved.
- **eBay auth model.** Browse and Marketplace Insights use the OAuth
  **client-credentials** flow: the daily job mints an application token from
  `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` (GitHub Actions secrets). No eBay
  user login, no user consent screen, no per-user accounts — nothing
  browser-facing. Only the Actions job ever holds eBay credentials; the web
  app just reads the cached `ebay_comps` collection. If eBay *user*-context
  APIs ever enter scope (Sell/Trading APIs — e.g. listing parts for sale from
  the workbench), that is the point where an eBay OAuth consent flow and a
  stored refresh token get added to the web app; it is an isolated addition,
  not a rework, and stays out of scope for this plan.
- **LLM manifest extraction** (the single highest-leverage improvement — see
  §8). The bulk-discount leg is weak (R² 0.29 on 41 lots) purely because only
  43 of ~625 bulk lots had a *regex-parseable* spec sheet. Most of the rest
  have PDFs a model can read trivially.
- **Static table becomes editable data.** `component_prices` moves to Mongo
  with an edit UI; the owner's pinned prices survive refits and are versioned
  in the release archive.

## 7. Web workbench — `apps/web`

Next.js (App Router) on Vercel Hobby, official Mongo driver from server
components/route handlers (Atlas M0 accepts Vercel egress; allowlist
0.0.0.0/0 with a strong password since Vercel IPs are dynamic).

**Auth:** Auth.js with the GitHub provider, allowlisted to the owner's email.
One user, no roles, ~30 lines. This protects the workbench and its user state
(watchlist, notes, assumptions); it is unrelated to eBay auth, which never
touches the browser (§6) — the app account and the eBay credentials are two
separate concerns, and only the first involves a login screen.

**Pages:**

- **Board** (`/`) — graded open lots ranked by confidence-weighted headroom;
  filters for state, grade, close time, unit count; live countdowns; grade,
  max bid, current bid, headroom, confidence per row. Server-rendered from
  `lots.latest_grade`, so it's fast even if the sliders below aren't touched.
- **Lot detail** (`/lot/[key]`) — bid curve (from `bid_observations`, burst
  points highlighted), valuation waterfall (floor / ceiling with each source's
  contribution: fitted, static, eBay), manifest table with per-machine values,
  photos + spec-sheet links, notes, watch/pass/bid/won buttons, and the
  auction link out to GovDeals.
- **Assumptions** (panel, persisted to `settings`) — target ROI, recovery,
  buyer premium, handling, dead rate. Moving a slider regrades the visible
  lots **in the browser** via `packages/valuation` using the latest
  `model_runs` coefficients — no round trip, and it can never drift from the
  pipeline thanks to the parity tests.
- **Sold explorer** (`/sold`) — searchable comp browser over `sold` +
  `manifests`; the "what did pallets like this actually clear at" question.
- **Models** (`/models`) — fit history: R² and k over time, per-CPU fitted
  price series, eBay comp coverage, and the editable component-price table.
- **Ops** (`/ops`) — `job_runs` feed: last scan, burst coverage, archive
  sizes, Atlas usage estimate.

**Watchlist feeds back into sampling:** watched lots qualify for burst
coverage regardless of grade — the user's attention directly buys data
resolution where it matters.

## 8. Claude Routines — the judgment layer

Three routines, all idempotent, all optional to the pipeline's correctness.
Each runs in a fresh cloud session against this repo with Mongo credentials
available, and each writes a `job_runs` doc like any other job.

1. **Manifest triage (daily).** Query Mongo for bulk lots (open first, then
   sold) that have PDF attachments but no manifest, or a manifest whose unit
   count doesn't reconcile with the title. Download each PDF, extract the
   machine mix (CPU model, RAM, form factor, drive, qty) by reading it,
   validate that quantities sum to the stated unit count, and upsert
   `manifests` with `parsed_by: "llm"`. Where the failure was a systematic
   pattern the regex parser could handle, open a PR against
   `pipeline/src/pcpartscan/specs.py` with the fix and a fixture. This
   routine directly grows the bulk-discount training set — the model's weak
   leg — every day.
2. **Daily digest.** Read the board state and yesterday's closures; send the
   owner a short message: top 3 actionable lots with reasoning (headroom,
   confidence, close time, pickup location), any watched lot closing today,
   and any surprise (a sold price far off prediction — which is also free
   model-error telemetry).
3. **Weekly health review.** Compare `model_runs` over the week (R², k,
   coverage), diff `raw_extra` keys across recent lots to catch upstream API
   schema drift, check `job_runs` for silent degradation (e.g. burst gate
   never firing), and file issues with findings. This is the "self-sufficient"
   guarantee: the system notices its own decay instead of the owner noticing
   stale data a month later.

Routines never bid, never authenticate to GovDeals, and only write
`manifests`, PRs, issues and digests — the deterministic pipeline remains the
sole writer of market data.

## 9. Deliberately left out

- **Turborepo/Nx, Docker, queues, k8s** — one app, one package, cron-shaped
  load. Actions + Vercel git-deploy cover it.
- **A Python API service** — the web app reads Mongo directly; grading math
  is ported to TS instead of hosted.
- **Real-time websockets/SSE** — burst data lands at 2-min resolution;
  polling revalidation in the UI is enough for auction timescales.
- **eBay HTML scraping** — stays out by design (ToS + bot walls); official
  API only.
- **Multi-user anything** — explicitly descoped per owner decision.

## 10. Risks

| Risk | Mitigation |
|---|---|
| GovDeals changes/protects the maestro API | `raw_extra` preserves unknown fields; weekly routine diffs schema; client is one file (`api.py`); polite pacing (0.35 s) and honest UA keep the footprint low |
| Atlas M0 fills | Change-only writes, post-close downsampling, weekly archive+prune, usage on `/ops` and in weekly review |
| Actions cron jitter/skips | Observations timestamped at capture; overlapping scan coverage self-heals gaps; `job_runs` staleness alerting |
| Marketplace Insights application denied | Browse-with-haircut path works from day one; Insights is an upgrade, not a dependency |
| Free Actions minutes exhausted mid-month | Budget in §5 carries ~170 min headroom; `job_runs` tracks spend; if it ever pinches, a self-hosted runner on a spare machine lifts the cap entirely without going public |
| Seller close-time behaviour drifts away from the burst window | Weekly health routine recomputes the close-hour histogram and proposes a new window |
| TS/Python grading drift | Golden parity test in CI blocks merge on any divergence |

## 11. Roadmap

Each phase is independently shippable and leaves the system better than the
last; nothing depends on a later phase.

**Phase 1 — Mongo as system of record (unblocks everything)**
Monorepo restructure (`pipeline/` + pyproject + `pcps` CLI); `store/mongo.py`;
`pcps backfill` from `data/`; scan writes Mongo; stop committing data;
`archive.yml`. *Done when:* a scan run writes only to Mongo, and a release
asset contains the full backfilled history.

**Phase 2 — Scheduled ingestion**
`scan.yml` on the close-weighted schedule, `burst.yml` peak window, `fit.yml`
daily, `ci.yml`, `job_runs` + failure-issue alerting — all inside the §5
minutes budget. *Done when:* 48 h pass with no manual action, a lot closing
in the peak window shows ~2-min final-surge resolution, and projected
month-end Actions spend (from `job_runs`) is under 2,000 min.

**Phase 3 — eBay in the blend**
Developer account, secrets, `pcps ebay-refresh` in `fit.yml`, `ebay_comps`
cache, adapter reads cache; Insights application submitted. *Done when:*
graded lots show an eBay contribution in the valuation breakdown.

**Phase 4 — Workbench MVP (read-only)**
`apps/web` on Vercel, auth, Board + Lot detail with bid curves + Sold explorer
+ Models + Ops. *Done when:* the owner triages a morning's lots without
touching a terminal.

**Phase 5 — Interactive workbench**
`packages/valuation` + parity tests, live assumption sliders, watchlist
(feeding burst coverage), notes, lot actions, editable component prices.
*Done when:* changing target ROI re-ranks the board instantly and a watched
C-grade lot gets burst sampling.

**Phase 6 — Claude Routines**
Manifest triage, daily digest, weekly health review. *Done when:* the
bulk-discount fit's n has grown week-over-week without human PDF-reading, and
the owner gets a useful digest daily.

## 12. Measured and deliberately not built

Two ideas that look obviously right and did not survive contact with the
data. Recorded so they are not re-argued from first principles every time
somebody reads a title with a generation in it.

### A generation multiplier on class-priced computer lots

Titles often name an Intel generation without naming a CPU ("Dell Latitude
Laptops 5th-11th Gen"), and the relationship to price is real: fitting
`log($/unit) ~ generation` over the 64 sold bulk lots that state one gives
**+27.4% per generation, R² 0.396**, monotone from $31/unit at 5th gen to
$133 at 11th.

It is still not worth building yet:

- **It barely predicts.** Leave-one-out median absolute error is 18%,
  against 20% for a flat median of the same lots. A bootstrap over 2,000
  resamples has the regression beating that baseline 94% of the time — real,
  but a 2-point error reduction.
- **It barely applies.** Of 706 live computer lots, 24 state a generation
  far enough from the corpus median for the multiplier to move the number
  at all. Most say "5th-11th Gen", whose midpoint is the median.
- **The path is already capped.** Class-priced lots top out at grade C, so
  a better class price cannot promote a lot into the recommendations.

Revisit after the backtest (Phase 10) can say whether it improves realized
outcomes rather than in-sample fit, or once the corpus carries a few hundred
generation-tagged lots instead of 64.

### Sub-class specifics for parts

Wattage for chargers and screen size for monitors were checked as ways to
split a class quote finer. Neither has the data: 12 of 21 charger pallets
state a wattage and 45W and 65W both clear about $3 a unit, and 3 of 237
monitor lots state a size. There is nothing to fit.
