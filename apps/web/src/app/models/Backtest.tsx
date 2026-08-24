import { HelpIcon } from "@/components/Tooltip";
import { Stat } from "@/components/Stat";
import type { Backtest, BacktestBucket, Spread } from "@/lib/data";
import { shortDate } from "@/lib/format";

/**
 * How the grader did against lots that have already closed.
 *
 * Everything else on this page is a model describing the data it was fitted
 * on. This is the only section that says whether any of it works, and it is
 * the only one that can tell you a max bid was wrong.
 *
 * Two rules govern how it reads. Every figure is out of sample — a lot never
 * helped fit the model that priced it. And the headline is always pallets,
 * never the pooled corpus: 87% of machine-priced sold lots are single units,
 * which are exactly what the single-unit model is fitted to predict, so
 * pooling them makes the ceiling look flawless when it is only reciting its
 * own training target.
 */

function pct(x: number | undefined) {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

function has(s: Spread | Record<string, never>): s is Spread {
  return "median" in s;
}

function Row({
  bucket,
  which,
  label,
}: {
  bucket: BacktestBucket;
  which: "vs_ceiling" | "vs_floor" | "vs_max_bid";
  label?: string;
}) {
  const s = bucket[which];
  return (
    <tr>
      <td>{label ?? bucket.name}</td>
      <td className="num">{bucket.n.toLocaleString()}</td>
      {has(s) ? (
        <>
          <td className="num">{s.p25.toFixed(2)}</td>
          <td className="num" style={{ fontWeight: 650 }}>
            {s.median.toFixed(2)}
          </td>
          <td className="num">{s.p75.toFixed(2)}</td>
        </>
      ) : (
        <>
          <td className="num muted">—</td>
          <td className="num muted">too few</td>
          <td className="num muted">—</td>
        </>
      )}
    </tr>
  );
}

function Table({
  bt,
  which,
  caption,
}: {
  bt: Backtest;
  which: "vs_ceiling" | "vs_floor" | "vs_max_bid";
  caption: string;
}) {
  const sizes = ["5-49", "50+"].filter((k) => bt.by_size[k]);
  return (
    <>
      <p className="muted small" style={{ margin: "14px 0 4px" }}>
        {caption}
      </p>
      <table className="data" style={{ maxWidth: 560 }}>
        <thead>
          <tr>
            <th>Bucket</th>
            <th className="num">Lots</th>
            <th className="num">p25</th>
            <th className="num">Median</th>
            <th className="num">p75</th>
          </tr>
        </thead>
        <tbody>
          <Row bucket={bt.pallets} which={which} label="All pallets (5+)" />
          {sizes.map((k) => (
            <Row key={k} bucket={bt.by_size[k]} which={which} />
          ))}
          {/* Only ever the real bucket. Falling back to bt.overall put the
              pooled corpus under a "single units" label -- precisely the
              confusion the caption above warns against. */}
          {bt.by_size["1 unit"] && (
            <Row
              bucket={bt.by_size["1 unit"]}
              which={which}
              label="Single units (not comparable)"
            />
          )}
        </tbody>
      </table>
    </>
  );
}

export function BacktestPanel({ bt }: { bt: Backtest }) {
  const rec = bt.win_curves.by_recovery;
  const atDefault = rec.find(
    (r) => Math.abs(r.recovery - (bt.config.recovery ?? 0.55)) < 1e-6,
  );
  const pal = bt.pallets.vs_ceiling;
  const roi = bt.win_curves.by_target_roi;
  const at = (v: number) => roi.find((r) => Math.abs(r.target_roi - v) < 1e-6);
  const roiHigh = at(bt.config.target_roi ?? 0.6) ?? roi.at(-1);
  const roiLow = roi[0];

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>
        Backtest
        <HelpIcon k="backtest" label="the backtest" />
      </h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Every closed lot re-graded without its own outcome in the training
        data, {bt.folds} folds. Run {bt.run_id} on{" "}
        {shortDate(bt.generated_at)}. Pallets are reported separately
        throughout, because a sold lot of one machine is what the single-unit
        model is fitted to predict and pooling them flatters everything.
      </p>

      <div className="statrow" style={{ marginTop: 14 }}>
        <Stat label="Closed lots replayed">{bt.n_lots.toLocaleString()}</Stat>
        <Stat label="Pallets of 5+" sub="the only ones the board shows">
          {bt.pallets.n.toLocaleString()}
        </Stat>
        <Stat
          label="Would have won"
          sub={`at ${pct(bt.config.recovery)} recovery, ${pct(bt.config.target_roi)} ROI`}
          valueClass={
            atDefault && atDefault.win_rate < 0.15 ? "neg" : undefined
          }
        >
          {pct(atDefault?.win_rate)}
        </Stat>
        <Stat label="Pallet clears at" sub="× the summed per-unit value" small>
          {has(pal) ? `${pal.median.toFixed(2)}×` : "—"}
        </Stat>
      </div>

      <Table
        bt={bt}
        which="vs_ceiling"
        caption="Hammer ÷ ceiling — what the lot fetched against its units priced one at a time. On pallets this lands near the bulk discount, which says the ceiling measures the same wholesale market the lot sold into, not a retail parts-out value."
      />
      <Table
        bt={bt}
        which="vs_floor"
        caption="Hammer ÷ floor — the floor claims to be what a pallet like this clears, so 1.00 would be right. Above it the floor is too low."
      />

      <p className="muted small" style={{ margin: "18px 0 4px" }}>
        What recovery buys you. Recovery is what you realise per unit as a
        multiple of GovDeals rates, so 100% means reselling at wholesale and
        200% means doubling it. Every row is the same predictions, re-scored.
      </p>
      <table className="data" style={{ maxWidth: 460 }}>
        <thead>
          <tr>
            <th className="num">Recovery</th>
            <th className="num">Pallets you win</th>
            <th className="num">Median hammer ÷ max bid</th>
          </tr>
        </thead>
        <tbody>
          {rec.map((r) => (
            <tr
              key={r.recovery}
              style={{
                fontWeight:
                  Math.abs(r.recovery - (bt.config.recovery ?? 0.55)) < 1e-6
                    ? 650
                    : 400,
              }}
            >
              <td className="num">{pct(r.recovery)}</td>
              <td className="num">{pct(r.win_rate)}</td>
              <td className="num">{r.median_ratio.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {roiLow && roiHigh && (
        <p className="muted small">
          The target return barely moves this by comparison — dropping it from{" "}
          {pct(roiHigh.target_roi)} to {pct(roiLow.target_roi)} only takes the
          win rate from {pct(roiHigh.win_rate)} to {pct(roiLow.win_rate)}.
          Recovery is the lever that matters, and it is the one nobody has
          measured yet.
        </p>
      )}
    </div>
  );
}
