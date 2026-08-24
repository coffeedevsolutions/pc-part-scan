"use client";

import { LineChart } from "@/components/LineChart";

/**
 * Two measures on different scales -> two charts, never a dual axis.
 */
export function ModelTrends({
  runs,
}: {
  runs: { fitted_at: string; r2: number; k: number | null; bulk_n: number }[];
}) {
  const r2Points = runs
    .map((r) => ({ x: new Date(r.fitted_at).getTime(), y: r.r2 }))
    .filter((p) => !Number.isNaN(p.x));
  const kPoints = runs
    .filter((r) => r.k != null)
    .map((r) => ({
      x: new Date(r.fitted_at).getTime(),
      y: r.k as number,
      note: `bulk n ${r.bulk_n}`,
    }))
    .filter((p) => !Number.isNaN(p.x));

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
        gap: 16,
      }}
    >
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Single-unit R² by fit run</h2>
        <LineChart
          points={r2Points}
          height={170}
          yFormat={(v) => v.toFixed(2)}
        />
      </div>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Bulk discount k by fit run</h2>
        <LineChart
          points={kPoints}
          height={170}
          yFormat={(v) => v.toFixed(2)}
        />
      </div>
    </div>
  );
}
