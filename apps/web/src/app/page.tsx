import { freshBids, latestSnapshot } from "@/lib/data";

import { BoardClient } from "./BoardClient";

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
  const bids = await freshBids(snap.lots.map((l) => l.lot_key));
  const lots = snap.lots.map((l) => {
    const fresh = bids[l.lot_key];
    return {
      ...l,
      current_bid:
        fresh && fresh.bid > l.current_bid ? fresh.bid : l.current_bid,
      end_utc: fresh?.end_utc ?? null,
    };
  });
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
      </p>
      <BoardClient lots={lots} defaults={snap.config} />
    </main>
  );
}
