import {
  freshBids,
  latestSnapshot,
  recentlyClosed,
  savedAssumptions,
  watchedKeys,
} from "@/lib/data";

import { BoardClient } from "./BoardClient";
import { Outcomes } from "./Outcomes";

export const dynamic = "force-dynamic";

export default async function BoardPage() {
  const snap = await latestSnapshot();
  if (!snap) {
    return (
      <main>
        <h1>Board</h1>
        <p className="sub">
          No scan snapshot yet — the board fills in after the first scheduled
          scan writes to MongoDB.
        </p>
      </main>
    );
  }
  const [bids, watched, saved, closed] = await Promise.all([
    freshBids(snap.lots.map((l) => l.lot_key)),
    watchedKeys(),
    savedAssumptions(),
    recentlyClosed(),
  ]);
  // A finished auction is not a lot you can bid on. The snapshot is a
  // moment in time and lots close between scans, so filter on the clock
  // rather than trusting the snapshot to have been written after the fact.
  const now = Date.now();
  const lots = snap.lots
    .map((l) => {
      const fresh = bids[l.lot_key];
      return {
        ...l,
        current_bid:
          fresh && fresh.bid > l.current_bid ? fresh.bid : l.current_bid,
        end_utc: fresh?.end_utc ?? null,
      };
    })
    .filter((l) => !l.end_utc || new Date(l.end_utc).getTime() > now);
  const closedSinceScan = snap.lots.length - lots.length;
  return (
    <main>
      <h1>Board</h1>
      <p className="sub">
        {lots.length} screened lots from run {snap.run_id} · single-unit model
        R² {snap.model_fit.single_r2.toFixed(3)} on {snap.model_fit.single_n}{" "}
        sold machines
        {snap.model_fit.bulk_k != null && (
          <>
            {" "}
            · bulk discount k {snap.model_fit.bulk_k.toFixed(2)} (n{" "}
            {snap.model_fit.bulk_n})
          </>
        )}
        {closedSinceScan > 0 && (
          <> · {closedSinceScan} closed since the scan and dropped</>
        )}
      </p>

      <Outcomes rows={closed} />

      <BoardClient
        lots={lots}
        defaults={{ ...snap.config, ...saved }}
        hasServerSaved={Object.keys(saved).length > 0}
        watched={[...watched]}
      />
    </main>
  );
}
