import "server-only";

import { getDb } from "./mongo";

/** A distribution of one ratio across a bucket of backtested lots. */
export interface Spread {
  n: number;
  p10: number;
  p25: number;
  median: number;
  p75: number;
  p90: number;
}

export interface BacktestBucket {
  name: string;
  n: number;
  n_priced: number;
  vs_max_bid: Spread | Record<string, never>;
  vs_floor: Spread | Record<string, never>;
  vs_ceiling: Spread | Record<string, never>;
  win_rate?: number;
  floor_within_2x?: number;
}

/** How the grader did against lots that already closed (backtest.py). */
export interface Backtest {
  run_id: string;
  generated_at: string;
  folds: number;
  n_lots: number;
  config: Record<string, number>;
  overall: BacktestBucket;
  pallets: BacktestBucket;
  by_size: Record<string, BacktestBucket>;
  by_confidence: Record<string, BacktestBucket>;
  by_path: Record<string, BacktestBucket>;
  by_class: Record<string, BacktestBucket>;
  win_curves: {
    n_pallets: number;
    by_target_roi: { target_roi: number; n: number; win_rate: number; median_ratio: number }[];
    by_recovery: { recovery: number; n: number; win_rate: number; median_ratio: number }[];
    grid: { target_roi: number; recovery: number; win_rate: number }[];
  };
}

/** One graded lot from a scan snapshot (grade.py Valuation, serialized). */
export interface SnapshotLot {
  lot_key: string;
  title: string;
  account_id: number;
  asset_id: number;
  units: number;
  current_bid: number;
  end_date: string;
  state: string | null;
  exact_manifest: boolean;
  mix: MachineLine[];
  /**
   * false when too few of the lot's units have an identified component to
   * price it — the lot is UNRATED and the numbers below are diagnostics,
   * not a bid ceiling. Absent on snapshots written before abstention.
   */
  contents_known?: boolean;
  /** units whose CPU the mix actually names */
  identified_units?: number;
  /** false when the title never said how many things are in the lot */
  count_known?: boolean;
  /** what kind of thing we think the lot holds (classify.py) */
  item_class?: string | null;
  item_family?: "computer" | "part" | null;
  /** plain-language account of how we read the title, shown as-is */
  class_reason?: string;
  class_confidence?: number;
  /**
   * "machines" when the CPU feature model priced it, "class" when it fell
   * back to sold comps for this kind of thing, absent when neither could.
   */
  priced_by?: "machines" | "class" | null;
  class_quote?: ClassQuote | null;
  floor: number;
  /** false when the bulk fit behind `floor` is too weak to underwrite against */
  floor_trusted?: boolean;
  ceiling: number;
  ceiling_sources: Record<string, number>;
  expected_revenue: number;
  max_bid: number;
  headroom: number;
  roi_at_current: number;
  confidence: number;
  grade: string;
}

/** What sold comps say one unit of an item class is worth (classprice.py). */
export interface ClassQuote {
  item_class: string;
  family: string;
  single_n: number;
  single_p25: number;
  single_p50: number;
  single_p75: number;
  bulk_n: number;
  bulk_p25: number;
  bulk_p50: number;
  bulk_p75: number;
  usable: boolean;
  has_floor: boolean;
  has_ceiling: boolean;
  ceiling_per_unit: number;
  floor_per_unit: number;
}

export interface MachineLine {
  cpu: string | null;
  generation: number | null;
  ram_gb: number | null;
  form_factor: string | null;
  chassis: string | null;
  has_drive: boolean | null;
  qty: number;
  /**
   * What the model says one machine on this line is worth (grade.py writes
   * it onto the mix). Present only on lots priced by the machine model or
   * by class comps, and absent on snapshots written before it existed — so
   * the mix table shows the price columns only when every row has one.
   */
  unit_value?: number;
}

export interface Snapshot {
  run_id: string;
  generated_at: string;
  config: Record<string, number>;
  model_fit: {
    single_r2: number;
    single_n: number;
    bulk_k: number | null;
    bulk_r2: number | null;
    bulk_n: number;
  };
  confidence_gate: number;
  class_prices?: Record<string, ClassQuote>;
  lots: SnapshotLot[];
}

export interface LotDoc {
  key: string;
  account_id: number;
  asset_id: number;
  title: string | null;
  seller: string | null;
  category: string | null;
  location: { city?: string; state?: string; zip?: string } | null;
  auction_start: string | null;
  auction_end: string | null;
  auction_end_utc: string | null;
  status: "open" | "sold";
  final_price: number | null;
  url: string;
  photo: string | null;
  first_seen: string;
  last_seen: string;
  last_obs?: { at: string; bid: number; bid_count: number | null };
  latest_grade?: {
    run_id: string;
    grade: string;
    max_bid: number;
    headroom: number;
    confidence: number;
  };
}

export interface BidObservation {
  key: string;
  observed_at: string;
  run_id: string;
  bid: number;
  bid_count: number | null;
  auction_end_utc?: string | null;
  is_sold: boolean;
  source: string;
}

export interface ManifestDoc {
  key: string;
  parsed_at: string;
  parsed_by?: string;
  source_files: string[];
  unit_total: number;
  machines: MachineLine[];
}

export interface ModelRunDoc {
  run_id: string;
  fitted_at: string;
  n_observations: number;
  r2: number;
  ram_per_8gb: number;
  drive_adder: number;
  bulk_discount_k: number | null;
  bulk_n: number;
  bulk_r2: number | null;
  cpu_base_value_usd: Record<string, number>;
}

export interface JobRunDoc {
  job: string;
  run_id: string;
  started_at: string;
  finished_at?: string;
  status: string;
  counts?: Record<string, number>;
  error?: string | null;
}

/** Pipeline collections use string _ids (lot keys, run ids), not ObjectIds. */
interface StringIdDoc {
  _id: string;
  [key: string]: unknown;
}

function coll(name: string) {
  return getDb().collection<StringIdDoc>(name);
}

function clean<T>(doc: unknown): T {
  // strip Mongo's _id (an ObjectId is not serializable across the RSC boundary)
  const { _id, ...rest } = doc as { _id?: unknown } & Record<string, unknown>;
  return rest as T;
}

export async function latestSnapshot(): Promise<Snapshot | null> {
  const doc = await coll("snapshots")
    .find({})
    .sort({ _id: -1 })
    .limit(1)
    .next();
  return doc ? clean<Snapshot>(doc) : null;
}

/** A lot we published a number for, now closed, with what it fetched. */
export interface ClosedOutcome {
  key: string;
  title: string | null;
  url: string | null;
  auction_end_utc: string | null;
  final_price: number;
  grade: string;
  max_bid: number;
  confidence: number;
  run_id: string;
}

/**
 * How our published max bids actually turned out.
 *
 * This is the backtest made personal: not "lots like this" but the exact
 * lots the board showed, scored against the price they really fetched. It
 * only fills in as `pcps resolve` learns outcomes, so it starts empty and
 * grows with every scan.
 */
export async function recentlyClosed(limit = 12): Promise<ClosedOutcome[]> {
  const docs = await coll("lots")
    .find({
      status: "sold",
      final_price: { $gt: 0 },
      latest_grade: { $ne: null },
    })
    .sort({ auction_end_utc: -1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => {
    const g = (d.latest_grade ?? {}) as Record<string, number | string>;
    return {
      key: String(d._id),
      title: (d.title as string) ?? null,
      url: (d.url as string) ?? null,
      auction_end_utc: (d.auction_end_utc as string) ?? null,
      final_price: Number(d.final_price),
      grade: String(g.grade ?? "?"),
      max_bid: Number(g.max_bid ?? 0),
      confidence: Number(g.confidence ?? 0),
      run_id: String(g.run_id ?? ""),
    };
  });
}

/** The most recent backtest, or null before one has ever been run. */
export async function latestBacktest(): Promise<Backtest | null> {
  const doc = await coll("backtests")
    .find({})
    .sort({ _id: -1 })
    .limit(1)
    .next();
  return doc ? clean<Backtest>(doc) : null;
}

/** Fresher bids than the snapshot: last_obs per key from the lots collection. */
export async function freshBids(
  keys: string[],
): Promise<Record<string, { bid: number; at: string; end_utc: string | null }>> {
  const out: Record<string, { bid: number; at: string; end_utc: string | null }> = {};
  const docs = await coll("lots")
    .find({ _id: { $in: keys } })
    .project<StringIdDoc>({ last_obs: 1, auction_end_utc: 1, status: 1 })
    .toArray();
  for (const d of docs) {
    const obs = d.last_obs as { bid: number; at: string } | undefined;
    if (obs) {
      out[d._id] = {
        bid: obs.bid,
        at: obs.at,
        end_utc: (d.auction_end_utc as string | null) ?? null,
      };
    }
  }
  return out;
}

export async function getLot(key: string): Promise<LotDoc | null> {
  const doc = await coll("lots").findOne({ _id: key });
  return doc ? clean<LotDoc>(doc) : null;
}

export async function bidSeries(key: string): Promise<BidObservation[]> {
  const docs = await coll("bid_observations")
    .find({ key })
    .sort({ observed_at: 1 })
    .limit(2000)
    .toArray();
  return docs.map((d) => clean<BidObservation>(d));
}

export async function getManifest(key: string): Promise<ManifestDoc | null> {
  const doc = await coll("manifests").findOne({ _id: key });
  return doc ? clean<ManifestDoc>(doc) : null;
}

export async function snapshotEntry(key: string): Promise<{
  run_id: string;
  lot: SnapshotLot;
} | null> {
  const snap = await latestSnapshot();
  const lot = snap?.lots.find((l) => l.lot_key === key);
  return snap && lot ? { run_id: snap.run_id, lot } : null;
}

export async function searchSold(
  q: string,
  state: string,
  limit = 100,
): Promise<LotDoc[]> {
  const filter: Record<string, unknown> = {};
  if (q) filter.title = { $regex: q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
  if (state) filter["location.state"] = state.toUpperCase();
  const docs = await coll("sold")
    .find(filter as never)
    .sort({ auction_end_utc: -1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => clean<LotDoc>(d));
}

/** States present in the sold corpus, for the explorer's filter. */
export async function soldStates(): Promise<string[]> {
  const vals = await coll("sold").distinct("location.state");
  return (vals as (string | null)[])
    .filter((v): v is string => typeof v === "string" && v.length > 0)
    .sort();
}

export async function modelRuns(limit = 60): Promise<ModelRunDoc[]> {
  const docs = await coll("model_runs")
    .find({})
    .sort({ run_id: 1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => clean<ModelRunDoc>(d));
}

export async function jobRuns(limit = 60): Promise<JobRunDoc[]> {
  const docs = await coll("job_runs")
    .find({})
    .sort({ started_at: -1 })
    .limit(limit)
    .toArray();
  return docs.map((d) => clean<JobRunDoc>(d));
}

export async function datasetCounts(): Promise<Record<string, number>> {
  const doc = await coll("meta").findOne({ _id: "index" });
  return (doc?.counts as Record<string, number>) ?? {};
}

export async function watchedKeys(): Promise<Set<string>> {
  const docs = await coll("watchlist").find({}).project({ _id: 1 }).toArray();
  return new Set(docs.map((d) => String(d._id)));
}

export async function isWatched(key: string): Promise<boolean> {
  return (await coll("watchlist").findOne({ _id: key })) != null;
}

export async function getNote(key: string): Promise<string> {
  const doc = await coll("notes").findOne({ _id: key });
  return (doc?.text as string) ?? "";
}

export async function getLotAction(
  key: string,
): Promise<{ action: string; amount: number | null } | null> {
  const doc = await coll("lot_actions").findOne({ _id: key });
  return doc
    ? {
        action: doc.action as string,
        amount: (doc.amount as number | null) ?? null,
      }
    : null;
}

/** Pins a human set. Anything not explicitly seeded counts, so pins made
 *  before provenance existed are not orphaned. */
export async function componentPrices(): Promise<
  { cpu: string; value_usd: number; note: string }[]
> {
  const docs = await coll("component_prices")
    .find({ source: { $ne: "seed" } })
    .sort({ _id: 1 })
    .toArray();
  return docs.map((d) => ({
    cpu: d._id,
    value_usd: d.value_usd as number,
    note: (d.note as string) ?? "",
  }));
}

export async function savedAssumptions(): Promise<Record<string, number>> {
  const doc = await coll("settings").findOne({ _id: "assumptions" });
  if (!doc) return {};
  const { _id, updated_at, ...rest } = doc as Record<string, unknown>;
  void _id;
  void updated_at;
  return rest as Record<string, number>;
}
