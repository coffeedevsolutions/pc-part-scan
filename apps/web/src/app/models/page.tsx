import { modelRuns } from "@/lib/data";
import { usd } from "@/lib/format";

import { ModelTrends } from "./ModelTrends";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const runs = await modelRuns();
  const latest = runs[runs.length - 1];

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
            Fitted CPU base values{" "}
            <span className="muted small">run {latest.run_id}</span>
          </h2>
          <div style={{ maxHeight: 420, overflowY: "auto" }}>
            <table className="data" style={{ maxWidth: 480 }}>
              <thead>
                <tr>
                  <th>CPU</th>
                  <th className="num">Base value</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(latest.cpu_base_value_usd)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cpu, v]) => (
                    <tr key={cpu}>
                      <td>{cpu}</td>
                      <td className="num">{usd(v)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            + {usd(latest.ram_per_8gb)} per 8GB RAM · +{" "}
            {usd(latest.drive_adder)} with drive
          </p>
        </div>
      )}
    </main>
  );
}
