import { componentPrices, modelRuns } from "@/lib/data";
import { usd } from "@/lib/format";

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
        Fit quality over time, and what each CPU is currently worth to the
        single-unit model.
      </p>

      {latest && (
        <div className="statrow">
          <div className="stat">
            <div className="label">Single-unit R²</div>
            <div className="value">{latest.r2.toFixed(3)}</div>
          </div>
          <div className="stat">
            <div className="label">Observations</div>
            <div className="value">{latest.n_observations}</div>
          </div>
          <div className="stat">
            <div className="label">Bulk discount k</div>
            <div className="value">
              {latest.bulk_discount_k?.toFixed(2) ?? "—"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Bulk n (weak leg)</div>
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
            CPU base values{" "}
            <span className="muted small">
              fitted in run {latest.run_id} · + {usd(latest.ram_per_8gb)} per
              8GB RAM · + {usd(latest.drive_adder)} with drive
            </span>
          </h2>
          <PriceEditor rows={editorRows} />
        </div>
      )}
    </main>
  );
}
