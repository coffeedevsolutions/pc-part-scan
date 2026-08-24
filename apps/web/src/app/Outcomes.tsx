import Link from "next/link";

import { Grade } from "@/components/Fields";
import { HelpIcon } from "@/components/Tooltip";
import type { ClosedOutcome } from "@/lib/data";
import { shortDate, usd } from "@/lib/format";

/**
 * What the lots we priced actually went for.
 *
 * The board used to keep showing lots whose auction had already ended,
 * because a lot only stopped being "open" if the keyword sweep happened to
 * surface it again — so a lot we published a max bid for could sit there
 * forever reading "closed", and we would never learn the one number that
 * says whether that max bid was any good. `pcps resolve` now asks each
 * seller directly, and this is where the answers land.
 *
 * It is the backtest made personal: not "lots like this" but these lots,
 * against the price they really fetched.
 */
export function Outcomes({ rows }: { rows: ClosedOutcome[] }) {
  if (!rows.length) return null;
  const scored = rows.filter((r) => r.max_bid > 0);
  const ratios = scored.map((r) => r.final_price / r.max_bid).sort((a, b) => a - b);
  const median = ratios.length ? ratios[Math.floor(ratios.length / 2)] : null;
  const won = scored.filter((r) => r.final_price <= r.max_bid).length;

  return (
    <details className="card">
      <summary className="outcomes-summary">
        <strong>Recently closed</strong>{" "}
        <span className="muted">
          — {rows.length} {rows.length === 1 ? "lot" : "lots"} we priced have
          finished
          {median != null && (
            <>
              , clearing at a median of {median.toFixed(1)}× our max bid; we
              would have won {won} of {scored.length}
            </>
          )}
        </span>
        <HelpIcon k="outcomes" label="recently closed lots" />
      </summary>

      <table className="data" style={{ marginTop: 10 }}>
        <thead>
          <tr>
            <th>Grade</th>
            <th>Lot</th>
            <th className="num">We said max</th>
            <th className="num">Sold for</th>
            <th className="num">Ratio</th>
            <th>Closed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ratio = r.max_bid > 0 ? r.final_price / r.max_bid : null;
            return (
              <tr key={r.key}>
                <td>
                  <Grade grade={r.grade} />
                </td>
                <td>
                  <Link href={`/lot/${r.key}`} className="lottitle">
                    {r.title ?? r.key}
                  </Link>
                  <div className="muted small">{r.key}</div>
                </td>
                <td className="num">
                  {r.max_bid > 0 ? usd(r.max_bid) : <span className="muted">—</span>}
                </td>
                <td className="num">{usd(r.final_price)}</td>
                <td className={`num ${ratio != null && ratio <= 1 ? "pos" : ""}`}>
                  {ratio != null ? `${ratio.toFixed(2)}×` : "—"}
                </td>
                <td className="muted small">{shortDate(r.auction_end_utc)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small">
        A ratio at or below 1.00 is a lot you could have bought at your own
        ceiling. Consistently high ratios mean the assumptions are pricing you
        out rather than the lots being bad — see the win curve on{" "}
        <Link href="/models">Models</Link>.
      </p>
    </details>
  );
}
