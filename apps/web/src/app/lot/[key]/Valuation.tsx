import Link from "next/link";

import { maxHammer, type Config } from "@pcps/valuation";

import { HelpIcon } from "@/components/Tooltip";
import type { SnapshotLot } from "@/lib/data";
import { usd } from "@/lib/format";

/**
 * How a pile of machines becomes a number you can bid.
 *
 * This used to be five labelled totals in a table — "ceiling (blend,
 * parts-out)", "expected revenue (underwritten)" — which told you what the
 * grader had computed but not why, and left the two numbers that actually
 * decide the bid (your target return, your recovery rate) invisible. It is
 * now the chain itself: every step names what it takes out and what is
 * left, so a max bid you disagree with can be traced to the assumption you
 * disagree with.
 *
 * The arithmetic mirrors regrade() in @pcps/valuation, which mirrors
 * grade.py. The subtotals here are recomputed rather than read off the
 * snapshot so a step can never silently stop adding up.
 */

interface Step {
  label: string;
  why?: React.ReactNode;
  amount: number | null;
  /** a running total, not a movement */
  total?: boolean;
  /** shown but not applied */
  ignored?: boolean;
  sign?: "minus";
  help?: "ceiling" | "floor" | "expectedRevenue" | "maxBid" | "headroom";
}

export function ValuationWaterfall({
  lot,
  cfg,
  bid,
  muted = false,
}: {
  lot: SnapshotLot;
  cfg: Config;
  bid: number;
  /** an unrated lot: show the chain for diagnosis, but never in the
   *  colours that say "this is money on the table" */
  muted?: boolean;
}) {
  const pct = (x: number) => `${Math.round(x * 1000) / 10}%`;

  const afterDead = lot.ceiling * (1 - cfg.dead_rate);
  const partsOut = afterDead * cfg.recovery;
  const floorCounts = lot.floor_trusted !== false && lot.floor > partsOut;
  const revenue = floorCounts ? lot.floor : partsOut;

  const budget = revenue / (1 + cfg.target_roi);
  const fixed = cfg.pickup_cost + cfg.per_unit_handling * lot.units;
  const maxBid = maxHammer(cfg, revenue, lot.units);
  // whatever the premium and tax divisor takes out, as a movement
  const onTop = Math.max(0, budget - fixed) - maxBid;
  const headroom = maxBid - bid;

  const sourceCount = Object.keys(lot.ceiling_sources ?? {}).length;

  const steps: Step[] = [
    {
      label: "What the parts are worth",
      why: (
        <>
          {lot.units.toLocaleString()}{" "}
          {lot.units === 1 ? "machine" : "machines"} priced one at a time,
          from what comparable single units have actually sold for
          {sourceCount > 1 ? ", averaged across sources" : ""}.
        </>
      ),
      amount: lot.ceiling,
      total: true,
      help: "ceiling",
    },
    {
      label: `Less dead units (${pct(cfg.dead_rate)})`,
      why: "The share you assume arrives non-functional.",
      amount: lot.ceiling - afterDead,
      sign: "minus",
    },
    {
      label: `Less what you never recover (${pct(1 - cfg.recovery)})`,
      why: "Listing fees, returns, price drops, and your time. You keep the rest.",
      amount: afterDead - partsOut,
      sign: "minus",
    },
    {
      label: "Parting it out would make",
      amount: partsOut,
      total: true,
    },
    {
      label: "Flipping the whole pallet would make",
      why: floorCounts ? (
        "Higher than parting it out, so this is what you underwrite against — you would take the easier route."
      ) : lot.floor_trusted === false ? (
        <>
          Ignored: the bulk-resale fit behind it is too weak to bid on. See{" "}
          <Link href="/models">Models</Link>.
        </>
      ) : (
        "Lower than parting it out, so it does not set the price."
      ),
      amount: lot.floor,
      ignored: !floorCounts,
      help: "floor",
    },
    {
      label: "What you expect to make",
      amount: revenue,
      total: true,
      help: "expectedRevenue",
    },
    {
      label: `Less your required return (${pct(cfg.target_roi)})`,
      why: `You will not do this for less, so ${usd(revenue - budget)} of that has to be profit.`,
      amount: revenue - budget,
      sign: "minus",
    },
    {
      label: `Less handling (${lot.units.toLocaleString()} × ${usd(cfg.per_unit_handling, 2)}${cfg.pickup_cost ? ` + ${usd(cfg.pickup_cost)} pickup` : ""})`,
      why: "Testing, wiping, photographing and packing every unit, plus getting the lot home.",
      amount: fixed,
      sign: "minus",
    },
  ];

  if (onTop > 0.005) {
    steps.push({
      label: `Less room for buyer premium and tax (${pct(cfg.buyer_premium)} + ${pct(cfg.sales_tax)})`,
      why: "Charged on top of the hammer price, so the hammer price has to be lower.",
      amount: onTop,
      sign: "minus",
    });
  }

  steps.push(
    {
      label: "The most you can pay",
      amount: maxBid,
      total: true,
      help: "maxBid",
    },
    {
      label: "Current bid",
      amount: bid,
      sign: "minus",
    },
    {
      label: "Headroom left",
      amount: headroom,
      total: true,
      help: "headroom",
    },
  );

  return (
    <>
      <table className={`data waterfall${muted ? " wf-muted" : ""}`}>
        <tbody>
          {steps.map((s, i) => (
            <tr
              key={i}
              className={`${s.total ? "wf-total" : ""} ${s.ignored ? "wf-ignored" : ""}`}
            >
              <td>
                <span className="wf-label">
                  {s.label}
                  {s.help && <HelpIcon k={s.help} label={s.label.toLowerCase()} />}
                </span>
                {s.why && <div className="muted small">{s.why}</div>}
              </td>
              <td
                className={`num ${
                  !muted && s.label === "Headroom left"
                    ? headroom >= 0
                      ? "pos"
                      : "neg"
                    : ""
                }`}
              >
                {s.amount == null
                  ? "—"
                  : `${s.sign === "minus" ? "−" : ""}${usd(s.amount)}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sourceCount > 1 && (
        <p className="muted small">
          Parts-out sources:{" "}
          {Object.entries(lot.ceiling_sources)
            .map(([src, val]) => `${src.replace(/_/g, " ")} ${usd(val)}`)
            .join(" · ")}
        </p>
      )}
    </>
  );
}
