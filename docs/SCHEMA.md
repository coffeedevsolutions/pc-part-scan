# Dataset schema

Schema version: **2**. Everything lives under `data/`.

`data/index.json` is the manifest — read it first. It carries the schema
version, the last run id, record counts, and the config used for that run.

## Files

| File | Format | Write mode | Contents |
|---|---|---|---|
| `index.json` | JSON | rewrite | Manifest: version, counts, last run, last config |
| `lots.json` | JSON object | rewrite (merge) | Every lot ever seen, keyed `<accountId>-<assetId>` |
| `bid_history.jsonl` | JSON Lines | **append only** | One line per observation of a lot's bid |
| `sold.json` | JSON object | rewrite (merge) | Closed lots with realized hammer price |
| `components.json` | JSON | rewrite (append run) | Fitted component prices, one entry per fit run |
| `models.json` | JSON | rewrite | Full model coefficients for the latest run |
| `manifests/<key>.json` | JSON | rewrite | Machine mix parsed from a lot's spec-sheet PDF |
| `snapshots/<run_id>.json` | JSON | write once | Full graded output of one scan run |

Writes are atomic (temp file + `os.replace`), so an interrupted run leaves the
previous file intact.

## Why bid_history is append-only

The API exposes only a lot's *current* bid. Bid history cannot be recovered
after the fact, so every run appends its observations and nothing ever rewrites
that file. It is JSON Lines specifically so appends can never corrupt earlier
records.

```jsonc
{"key": "7484-44150", "observed_at": "2026-08-23T01:47:17Z",
 "run_id": "20260823T014717Z", "current_bid": 400.0, "bid_count": null,
 "time_remaining": "1:20:14:32", "auction_end_utc": "2026-08-24T21:45:00Z",
 "is_sold": false, "reserve_not_met": false}
```

Run often enough and you get the bid curve for each lot, which is what makes
late-surge behaviour analysable instead of guessed at.

## Lot record

```jsonc
{
  "key": "7484-44150",
  "account_id": 7484, "asset_id": 44150,
  "title": "Lot of 48 Various Models of Dell OptiPlex Towers/SFF Computers",
  "category": "Computers: Desktops and All-In-Ones", "category_code": "217",
  "make": "Dell", "model": "OptiPlex",
  "seller": "University of Iowa Surplus",
  "location": {"city": "Iowa City", "state": "IA", "zip": "52242", "country": "USA"},
  "currency": "USD",
  "auction_start": "2026-08-18T14:00:00",
  "auction_end": "2026-08-24T17:45:00",
  "auction_end_utc": "2026-08-24T21:45:00Z",
  "status": "open",              // "open" | "sold"; never downgraded from sold
  "is_sold_auction": false,
  "final_price": null,           // set once the lot is observed sold
  "url": "https://www.govdeals.com/asset/44150/7484",
  "first_seen": "...", "last_seen": "...",
  "raw_extra": { }               // unmodelled API fields, kept verbatim
}
```

`raw_extra` exists because the upstream API adds and renames fields without
notice. Modelled fields stay stable; anything new lands there rather than
being dropped.

## Manifest record

Parsed from the seller's attached spec sheet — the only way to know the actual
CPU mix inside a bulk lot.

```jsonc
{
  "key": "7484-44150", "parsed_at": "...",
  "source_files": ["48 DELL OPTIPLEX COMPUTER SPECS.pdf"],
  "unit_total": 48,
  "machines": [
    {"cpu": "i7-4790", "generation": 4, "ram_gb": 8, "form_factor": "tower",
     "chassis": "9020", "has_drive": false, "qty": 4}
  ]
}
```

## Components record

One entry per fit run, so a CPU's fitted value can be charted over time.

```jsonc
{
  "latest": {
    "run_id": "20260823T014726Z", "fitted_at": "...",
    "n_observations": 416, "r2": 0.895,
    "ram_per_8gb": 0.0, "drive_adder": 0.0,
    "bulk_discount_k": 0.569, "bulk_n": 41, "bulk_r2": 0.291,
    "cpu_base_value_usd": {"i7-11700": 213.65, "i5-9500": 44.03}
  },
  "runs": [ /* every prior fit, same shape */ ]
}
```

`pcpartscan.dataset.component_price_series("i7-11700")` returns that CPU's
value across all runs.
