# pc-part-scan

Harvest, cache and analyse GovDeals bulk-computer auctions, and grade live lots
on whether they are worth bidding on.

The upstream site is a JS app behind Akamai Bot Manager, but the JSON API
underneath it is not bot-protected — so this runs headless with no browser and
no scraping of rendered HTML. See [docs/API.md](docs/API.md) for the endpoints
and the three non-obvious headers you need.

The plan for evolving this into a scheduled, MongoDB-backed system with a web
workbench is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The pipeline
lives in `pipeline/` (`pcps` CLI, scheduled by GitHub Actions, writing to
MongoDB), the web workbench in `apps/web/` (Next.js, deployed on Vercel), and
the shared grading math in `packages/valuation/` (kept in lockstep with the
Python grader by a golden parity test).

## What it does

1. **Harvest** the sold archive (all sellers) and currently open lots.
2. **Download and parse** seller spec-sheet PDFs to learn the exact CPU/RAM mix
   inside a bulk lot.
3. **Fit** a per-machine price model on sold single-unit lots, plus a bulk
   discount on sold pallets with reconcilable manifests.
4. **Grade** open lots on a max-bid basis and write everything into a
   structured, append-only dataset under `data/`.

## Quick start

```bash
pip install -r requirements.txt
python scan.py --full
```

Then:

```bash
python scan.py --no-refresh --states IA,IL,MO --top 20
```

| Flag | Meaning |
|---|---|
| `--no-refresh` | Grade from the cached corpus, no network |
| `--full` | Deep refresh: more sold pages, more manifest fetches |
| `--backfill` | Import a legacy `cache/` directory into `data/` |
| `--target-roi` | Required return over all-in cost (default 0.60) |
| `--recovery` | Share of parts-out value you expect to realize (default 0.55) |
| `--buyer-premium` | Your seller's buyer premium (default 0.00) |
| `--states` | Comma-separated state filter |

## The dataset

`data/` is the durable artifact — see [docs/SCHEMA.md](docs/SCHEMA.md).

| File | What it holds |
|---|---|
| `index.json` | Manifest: schema version, counts, last run |
| `lots.json` | Every lot ever seen |
| `bid_history.jsonl` | **Append-only** bid observations over time |
| `sold.json` | Closed lots with realized prices |
| `components.json` | Fitted component prices, one entry per run |
| `manifests/` | Machine mix parsed from spec-sheet PDFs |
| `snapshots/` | Full graded output of each run |

`bid_history.jsonl` is the file that matters most: the API exposes only a lot's
*current* bid, so history cannot be reconstructed after the fact. Run on a
schedule and the bid curve accumulates.

## How grading works

The output is **max bid**, not "is the current bid cheap". Lots close with a
late surge, so a mid-auction snapshot flatters everything. Max bid is the most
you can pay and still clear your target return, and it stays valid as the
auction runs. **Headroom** = max bid − current bid.

- **Floor** — resale-as-lot value, from the fitted bulk discount.
- **Ceiling** — parts-out value, from the sold single-unit model, blended with
  the static table and eBay when those are available.

### Confidence, and why it gates the grade

Without a spec sheet, the CPU mix in a lot is unknown, so every machine falls
back to a generic bucket value and the ceiling becomes a function of unit count
alone — a 253-unit lot of unknown junk scores like a 253-unit lot of 11th-gen
i7s. Lots below `CONFIDENCE_GATE` (0.50) therefore cannot grade above **C**, no
matter how much nominal headroom they show, and ranking is by
confidence-weighted headroom. Treat sub-gate rows as leads to check by hand,
not as recommendations.

## Model quality, honestly

Current fit on the harvested corpus:

| Model | n | R² | Notes |
|---|---|---|---|
| Single-unit price | 416 | 0.895 | Solid. Drives the ceiling. |
| Bulk discount `k` | 41 | 0.291 | `k ≈ 0.57`, wide dispersion. Weak leg. |

The bulk discount rests on only 41 lots, because just 43 of ~625 bulk lots
checked had a parseable spec sheet. Treat the floor as indicative. It improves
as `data/manifests/` grows.

## Layout

```
scan.py                    entry point
src/pcpartscan/
  api.py                   GovDeals JSON API client
  specs.py                 CPU / RAM / form-factor / unit-count parsing
  harvest.py               sweeps and manifest fetching
  pricing.py               the four valuation sources
  grade.py                 max-bid and grading
  dataset.py               structured append-only storage
docs/API.md                endpoint reference
docs/SCHEMA.md             dataset schema
```

## Notes

- Requests are paced at ~0.35 s. Keep it polite.
- The API key is a public client key embedded in the site's own JavaScript.
- Anonymous read only — nothing here bids, authenticates, or transacts.
