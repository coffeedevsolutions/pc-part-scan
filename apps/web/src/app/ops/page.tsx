import { Stat } from "@/components/Stat";
import { HelpIcon } from "@/components/Tooltip";
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
        {Object.entries(counts).map(([k, v], i) => (
          <Stat
            key={k}
            label={k.replace(/_/g, " ")}
            // one explanation for the row, on the first card: repeating it
            // on all seven would be noise, and omitting it entirely leaves
            // "bid observations" unexplained
            help={i === 0 ? "datasetCounts" : undefined}
            helpLabel="these counts"
          >
            {v.toLocaleString()}
          </Stat>
        ))}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>
                Job
                <HelpIcon k="jobRuns" label="the job log" />
              </th>
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
