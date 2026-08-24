import { datasetCounts, jobRuns } from "@/lib/data";
import { shortDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OpsPage() {
  const [counts, runs] = await Promise.all([datasetCounts(), jobRuns()]);

  return (
    <main>
      <h1>Ops</h1>
      <p className="sub">
        Pipeline heartbeat: what ran, what it wrote, and how big the dataset
        is.
      </p>

      <div className="statrow">
        {Object.entries(counts).map(([k, v]) => (
          <div className="stat" key={k}>
            <div className="label">{k.replace(/_/g, " ")}</div>
            <div className="value">{v.toLocaleString()}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Job</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Status</th>
              <th>Counts</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={`${r.job}-${r.run_id}`}>
                <td>{r.job}</td>
                <td style={{ whiteSpace: "nowrap" }}>{shortDate(r.started_at)}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {r.finished_at ? shortDate(r.finished_at) : "…"}
                </td>
                <td>
                  {r.status === "ok" ? (
                    <span className="pos">✓ ok</span>
                  ) : r.status === "running" ? (
                    <span className="muted">⏳ running</span>
                  ) : (
                    <span className="neg" title={r.error ?? undefined}>
                      ✕ {r.status}
                    </span>
                  )}
                </td>
                <td className="muted small">
                  {r.counts
                    ? Object.entries(r.counts)
                        .map(([k, v]) => `${k} ${v.toLocaleString()}`)
                        .join(" · ")
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
