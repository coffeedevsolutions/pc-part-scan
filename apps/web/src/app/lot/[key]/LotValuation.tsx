"use client";

import { createContext, useContext, useState } from "react";

import { UNRATED, regrade, type Config } from "@pcps/valuation";

import { AssumptionFields } from "@/components/AssumptionFields";
import { Grade } from "@/components/Fields";
import { Stat } from "@/components/Stat";
import { HelpIcon } from "@/components/Tooltip";
import { useAssumptions } from "@/lib/assumptions";
import type { SnapshotLot } from "@/lib/data";
import { usd } from "@/lib/format";

import { ValuationWaterfall } from "./Valuation";

/**
 * The parts of the lot page that move when an assumption moves.
 *
 * The hero cards and the waterfall are far apart on the page but are the
 * same arithmetic, so they have to share one config: if the sliders only
 * fed the waterfall, moving one would leave the max bid in the header
 * disagreeing with the max bid in the chain that derives it. Hence a
 * context rather than two independent hooks — one state, two readers.
 *
 * Everything else on the page stays server-rendered and is passed through
 * as children.
 */

const Ctx = createContext<{
  cfg: Config;
  updateCfg: (patch: Partial<Config>) => void;
  isDefault: (key: keyof Config) => boolean;
} | null>(null);

function useCfg() {
  const v = useContext(Ctx);
  if (!v) throw new Error("lot valuation components need AssumptionsScope");
  return v;
}

export function AssumptionsScope({
  saved,
  hasServerSaved,
  children,
}: {
  saved: Record<string, number>;
  hasServerSaved: boolean;
  children: React.ReactNode;
}) {
  const { cfg, updateCfg, isDefault } = useAssumptions(saved, hasServerSaved);
  return (
    <Ctx.Provider value={{ cfg, updateCfg, isDefault }}>{children}</Ctx.Provider>
  );
}

/** The three hero cards whose values depend on the assumptions. */
export function LotStats({
  lot,
  bid,
  unrated,
}: {
  lot: SnapshotLot;
  bid: number;
  unrated: boolean;
}) {
  const { cfg } = useCfg();
  const re = regrade({ ...lot, current_bid: bid }, cfg);

  return (
    <>
      <Stat label="Grade · confidence" help="grade" helpLabel="the grade">
        <Grade grade={unrated ? UNRATED : re.grade} />{" "}
        <span className="muted" style={{ fontSize: 15 }}>
          {lot.confidence.toFixed(2)}
        </span>
      </Stat>
      <Stat
        label="Max bid"
        help="maxBid"
        helpLabel="max bid"
        sub="at your assumptions"
      >
        {unrated ? <span className="muted">—</span> : usd(re.max_bid)}
      </Stat>
      <Stat
        label="Headroom vs current"
        help="headroom"
        helpLabel="headroom"
        sub="against the bid above"
        valueClass={unrated ? "" : re.headroom >= 0 ? "pos" : "neg"}
      >
        {unrated ? <span className="muted">—</span> : usd(re.headroom)}
      </Stat>
    </>
  );
}

/**
 * The derivation, with the assumptions that drive it attached to it.
 *
 * The editor lives inside this card rather than on the Board alone, because
 * this is the page where you are being told a number and the obvious next
 * question is "what if I disagree with that". Making you navigate away to
 * ask it, and back to see the answer, is how an assumption becomes
 * invisible.
 */
export function ValuationCard({
  lot,
  bid,
  muted = false,
}: {
  lot: SnapshotLot;
  bid: number;
  muted?: boolean;
}) {
  const { cfg, updateCfg, isDefault } = useCfg();
  const anyDefault = (
    [
      "target_roi",
      "recovery",
      "dead_rate",
      "per_unit_handling",
    ] as (keyof Config)[]
  ).some(isDefault);
  // Decided once, on mount. As a live value it is a controlled `open`, so
  // changing the last still-default field flips it false and React shuts
  // the panel — pulling the slider out from under the user mid-drag. The
  // panel should open itself because defaults were showing when you
  // arrived, not police whether they still are.
  const [startedOpen] = useState(anyDefault);

  return (
    <>
      <p className="sub" style={{ marginTop: 0 }}>
        Every step below comes off the one above it. Change an assumption and
        the chain moves with it — the same settings the Board uses.
      </p>

      <details className="card assumptions" open={startedOpen}>
        <summary>
          <strong>Assumptions</strong>{" "}
          <span className="muted">
            {anyDefault
              ? "— some of these are still shipped defaults, not your numbers"
              : "— all set by you"}
          </span>
        </summary>
        <div className="controls" style={{ marginTop: 10 }}>
          <AssumptionFields
            cfg={cfg}
            updateCfg={updateCfg}
            isDefault={isDefault}
          />
        </div>
        {isDefault("recovery") && (
          <p className="muted small" style={{ marginBottom: 0 }}>
            <strong>Recovery is the one to look at.</strong> It moves the
            outcome more than every other setting combined, and 55% is a
            default nobody chose — it predates our knowing the ceiling is a
            wholesale figure, so read literally it says you resell for about
            half what the wholesale market already pays. Across closed
            pallets it would have been outbid on 92% of them. The panel on{" "}
            <a href="/models">Models</a> measures it from eBay rather than
            asking you to guess.
          </p>
        )}
      </details>

      <ValuationWaterfall lot={lot} cfg={cfg} bid={bid} muted={muted} editable />
    </>
  );
}

/** A heading with the help icon, kept next to the card it belongs to. */
export function ValuationHeading() {
  return (
    <h2 style={{ marginTop: 0 }}>
      How this number is built
      <HelpIcon k="expectedRevenue" label="the valuation" />
    </h2>
  );
}
