import { componentPrices, modelRuns } from "@/lib/data";
import { usd } from "@/lib/format";

import { HelpIcon } from "@/components/Tooltip";

import { ModelTrends } from "./ModelTrends";
import { PriceEditor } from "./PriceEditor";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const [runs, pinned] = await Promise.all([modelRuns(), componentPrices()]);
  const latest = runs[runs.length - 1];
  const pinnedMap = new Map(pinned.map((p) => [p.cpu, p]));
  const fitted = latest ? Object.entries(latest.cpu_base_value_usd) : [];
  const editorRows = [
    ...fitted.map(([cpu, v]) => ({
      cpu,
      fitted: v,
      pinned: pinnedMap.get(cpu)?.value_usd ?? null,
      note: pinnedMap.get(cpu)?.note ?? "",
    })),
    ...pinned
      .filter((p) => !p.cpu.startsWith("_") && !fitted.some(([c]) => c === p.cpu))
      .map((p) => ({ cpu: p.cpu, fitted: null, pinned: p.value_usd, note: p.note })),
  ].sort((a, b) => (b.fitted ?? b.pinned ?? 0) - (a.fitted ?? a.pinned ?? 0));

  return (
    <main>
      <h1>Models</h1>
      <p className="sub">
        Every scan refits two price models on sold auctions: what one machine
        is worth (drives the parts-out ceiling) and what a whole pallet
        clears (drives the resale floor). This page is where you check
        whether those fits are healthy enough to trust a grade — and where
        you correct a CPU price the model has wrong.
      </p>

      {latest && (
        <div className="statrow">
          <div className="stat">
            <div className="label">
              Single-unit R²
              <HelpIcon k="singleR2" label="single-unit R squared" />
            </div>
            <div className="value">{latest.r2.toFixed(3)}</div>
          </div>
          <div className="stat">
            <div className="label">Observations</div>
            <div className="value">{latest.n_observations}</div>
          </div>
          <div className="stat">
            <div className="label">
              Bulk discount k
              <HelpIcon k="bulkK" label="the bulk discount" />
            </div>
            <div className="value">
              {latest.bulk_discount_k?.toFixed(2) ?? "—"}
            </div>
          </div>
          <div className="stat">
            <div className="label">
              Bulk n
              <HelpIcon k="bulkN" label="the bulk sample size" />
            </div>
            <div className="value">{latest.bulk_n}</div>
          </div>
        </div>
      )}

      <ModelTrends
        runs={runs.map((r) => ({
          fitted_at: r.fitted_at,
          r2: r.r2,
          k: r.bulk_discount_k,
          bulk_n: r.bulk_n,
        }))}
      />

      {latest && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>
            CPU base values
            <HelpIcon k="cpuBaseValue" label="CPU base values" />
          </h2>
          <p className="muted small" style={{ marginTop: 0 }}>
            What one machine with each CPU is worth before adjustments, fitted
            in run {latest.run_id}. On top of these the model adds{" "}
            {usd(latest.ram_per_8gb)} per 8GB of RAM and{" "}
            {usd(latest.drive_adder)} for a drive.
          </p>
          <PriceEditor rows={editorRows} />
        </div>
      )}
    </main>
  );
}
