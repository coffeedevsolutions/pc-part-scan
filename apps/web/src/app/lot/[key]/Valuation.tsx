import Link from "next/link";

import { forFamily, maxHammer, type Config } from "@pcps/valuation";

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
  cfg: baseCfg,
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
  // A lot of chargers is not handled like a lot of PCs, so the rate is
  // chosen once here and every step below just uses it.
  const cfg = forFamily(baseCfg, lot.item_family);
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
  // the per-unit handling at which max bid would reach zero
  const breakeven =
    lot.units > 0 ? (revenue / (1 + cfg.target_roi) - cfg.pickup_cost) / lot.units : -1;

  const sourceCount = Object.keys(lot.ceiling_sources ?? {}).length;
  const byClass = lot.priced_by === "class";
  const q = lot.class_quote;
  const kind = lot.item_class ?? "item";

  const steps: Step[] = [
    {
      label: "The units priced one at a time",
      why: byClass ? (
        <>
          We could not read what is inside, so this is {lot.units.toLocaleString()}{" "}
          {lot.units === 1 ? kind : `${kind}s`} at{" "}
          {usd(q?.ceiling_per_unit ?? 0, 2)} each — what sold lots of the same
          kind imply one is worth. It cannot tell a new one from a ten-year-old
          one, which is why this lot can never grade above C.
        </>
      ) : (
        <>
          {lot.units.toLocaleString()}{" "}
          {lot.units === 1 ? "machine" : "machines"} at what comparable single
          units fetched at GovDeals auction
          {sourceCount > 1 ? ", averaged across sources" : ""}. A wholesale
          number, not a retail one — closed pallets clear at a median of
          0.77× it.
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
      label:
        cfg.recovery <= 1
          ? `Less what you never recover (${pct(1 - cfg.recovery)})`
          : `Plus what you make above GovDeals rates (${pct(cfg.recovery - 1)})`,
      why: `Recovery says you realise ${pct(cfg.recovery)} of what a unit fetches at GovDeals auction. Below 100% you are assuming you resell for less than the wholesale market already pays.`,
      amount: Math.abs(afterDead - partsOut),
      sign: partsOut < afterDead ? "minus" : undefined,
    },
    {
      label: "Selling the units separately would make",
      amount: partsOut,
      total: true,
    },
    {
      label: "Flipping the whole pallet would make",
      why: floorCounts ? (
        byClass && q ? (
          <>
            {q.bulk_n} sold pallets of {kind}s cleared{" "}
            {usd(q.floor_per_unit, 2)} a unit or better. Higher than parting it
            out, so this is what you underwrite against.
          </>
        ) : (
          "Higher than parting it out, so this is what you underwrite against — you would take the easier route."
        )
      ) : lot.floor_trusted === false ? (
        byClass ? (
          `Too few sold pallets of ${kind}s to put a number on it.`
        ) : (
          <>
            Ignored: the bulk-resale fit behind it is too weak to bid on. See{" "}
            <Link href="/models">Models</Link>.
          </>
        )
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
      label:
        fixed <= 0
          ? "Less handling (nothing)"
          : cfg.per_unit_handling > 0
            ? `Less handling (${lot.units.toLocaleString()} × ${usd(cfg.per_unit_handling, 2)}${cfg.pickup_cost ? ` + ${usd(cfg.pickup_cost)} pickup` : ""})`
            : `Less pickup (${usd(cfg.pickup_cost)})`,
      why:
        lot.item_family === "part"
          ? cfg.per_unit_handling > 0
            ? `Your handling rate for parts, plus getting the lot home. Sorting ${lot.item_class}s is not the same work as testing and wiping a PC, so the two rates are set apart above.`
            : cfg.pickup_cost > 0
              ? // The per-unit rate is zero but the pickup is not, so this
                // step still takes money out. Saying "nothing comes out
                // here" would contradict the figure beside it.
                `Getting the lot home. Sorting ${lot.item_class}s itself costs you nothing, so the whole ${usd(fixed)} is pickup — machines are charged ${usd(baseCfg.per_unit_handling, 2)} a unit on top of it.`
              : `Sorting ${lot.item_class}s costs you nothing, so nothing comes out here. Machines are charged at ${usd(baseCfg.per_unit_handling, 2)} a unit — either rate is editable above.`
          : "Testing, wiping, photographing and packing every unit, plus getting the lot home.",
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
      {fixed > 0 && maxBid <= 0 && breakeven >= 0 && (
        <p className="muted small">
          <strong>Handling is what stops this lot.</strong> At{" "}
          {usd(cfg.per_unit_handling, 2)} a unit it costs {usd(fixed)}. Of the{" "}
          {usd(revenue)} this lot is expected to make, your {pct(cfg.target_roi)}{" "}
          required return reserves all but {usd(budget)} — so handling has
          nothing left to come out of. It would need to be under{" "}
          <strong>{usd(breakeven, 2)}</strong> a unit for any bid to clear that
          return.
        </p>
      )}
      {byClass && q && (
        <p className="muted small">
          Comps behind this: {q.bulk_n} sold pallets of {kind}s (
          {usd(q.bulk_p25, 2)}–{usd(q.bulk_p75, 2)} a unit) and {q.single_n}{" "}
          sold on their own ({usd(q.single_p25, 2)}–{usd(q.single_p75, 2)}).
        </p>
      )}
      {!byClass && sourceCount > 1 && (
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
