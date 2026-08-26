import { HelpIcon } from "@/components/Tooltip";
import type { RecoveryBand, RecoveryReport } from "@/lib/data";
import { usd } from "@/lib/format";

/**
 * What we actually get for a machine, measured rather than assumed.
 *
 * `recovery` moves the outcome more than every other setting combined —
 * sweeping it 0.55 → 2.00 takes the backtest win rate from 14% to 64% — and
 * it was the one input the system asked a human to supply. eBay can answer
 * it, but not in one call: Browse serves active listings, and sold prices
 * sit behind an API we do not have. So `pcps ebay-watch` polls daily and
 * treats a fixed-price listing that stops appearing as a sale at its last
 * ask, and this is where those departures turn back into a number.
 *
 * The panel needs weeks to fill. Until it does, the honest thing to show is
 * the ask-derived figure clearly labelled as reading high, and how far off
 * the measured one still is — never a default dressed up as evidence.
 */

function Band({
  label,
  band,
  note,
  strong = false,
}: {
  label: string;
  band: RecoveryBand | undefined;
  note?: string;
  strong?: boolean;
}) {
  if (!band) return null;
  const value = band.recovery ?? band.upper_bound ?? null;
  const n = band.n_sales ?? band.n_listings ?? 0;
  return (
    <tr className={strong ? "wf-total" : ""}>
      <td>
        {label}
        {note && <div className="muted small">{note}</div>}
      </td>
      <td className="num">
        {value == null ? (
          <span className="muted">—</span>
        ) : (
          `${value.toFixed(2)}×`
        )}
      </td>
      <td className="num muted small">
        {value == null
          ? `${band.n_cpus}/${band.min_cpus} CPUs`
          : `${band.n_cpus} CPUs · ${n.toLocaleString()}`}
      </td>
    </tr>
  );
}

export function RecoveryPanel({
  report,
  current,
}: {
  report: RecoveryReport | null;
  /** the recovery the grader is running on right now */
  current: number;
}) {
  if (!report) {
    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>
          What you get for a machine
          <HelpIcon k="recovery" label="recovery" />
        </h2>
        <p className="muted">
          Nothing measured yet. <code>pcps ebay-watch</code> polls eBay daily
          and records which listings have stopped appearing — a fixed-price
          listing that vanishes has almost certainly sold, at the price it was
          last asking. Those departures are the only route to a realised eBay
          price without the Marketplace Insights API, and they take a few
          weeks to accumulate. Until then the grader is running on{" "}
          <strong>{current.toFixed(2)}×</strong>, which is an assumption, not
          a measurement.
        </p>
      </div>
    );
  }

  const best =
    report.strict?.recovery != null ? report.strict : report.loose;
  const measured = best?.recovery ?? null;
  const days = best?.median_days_to_sell ?? null;
  const rows = measured != null ? best.per_cpu : (report.bound?.per_cpu ?? []);
  const bySales = measured != null;

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>
        What you get for a machine
        <HelpIcon k="recovery" label="recovery" />
      </h2>
      <p className="muted small">
        Every figure is what one machine fetched on eBay, net of{" "}
        {((report.strict?.fee_rate ?? 0.1325) * 100).toFixed(2)}% fees and{" "}
        {usd(report.shipping ?? 0, 2)} shipping, over what the same CPU
        fetches sold on its own at a GovDeals auction. That ratio is exactly
        the <code>recovery</code> setting on the Board.
      </p>

      <table className="data waterfall" style={{ maxWidth: 560 }}>
        <tbody>
          <Band
            label="From live asking prices"
            band={report.bound}
            note="Available at once, but reads high: nothing sells above its own ask, and the listings still up are the ones that have failed to sell."
          />
          <Band
            label="Measured — confirmed ended"
            band={report.strict}
            note="Listings eBay confirmed had ended. The number to trust."
            strong
          />
          <Band
            label="Measured — all departures"
            band={report.loose}
            note="Also counts listings that merely stopped appearing in search."
          />
          <Band
            label="Measured — incl. best-offer at ask"
            band={report.with_offers}
            note="Best-offer listings sold below their ask by an unknown amount, so this is biased up."
          />
          <tr>
            <td>Currently set to</td>
            <td className="num">{current.toFixed(2)}×</td>
            <td className="num muted small">on the Board</td>
          </tr>
        </tbody>
      </table>

      {measured != null && (
        <p className="muted small">
          {measured > current * 1.15 ? (
            <>
              <strong>The grader is underwriting well below what you get.</strong>{" "}
              At {current.toFixed(2)}× it assumes you realise less than the
              wholesale market already pays; the panel says {measured.toFixed(2)}×.
              Every lot on the board is priced as though it were worth{" "}
              {Math.round((1 - current / measured) * 100)}% less than measured.
            </>
          ) : measured < current * 0.85 ? (
            <>
              <strong>The grader is more optimistic than the evidence.</strong>{" "}
              It is set to {current.toFixed(2)}× against a measured{" "}
              {measured.toFixed(2)}×, so max bids are running high.
            </>
          ) : (
            <>The setting and the measurement agree to within 15%.</>
          )}
          {days != null && (
            <>
              {" "}
              Half of these sold within{" "}
              <strong>{days < 1 ? "under a day" : `${days} days`}</strong> of
              first being listed — that is how long your money is tied up,
              which no price on its own can tell you. Read it as a floor while
              the panel is young: a listing cannot be observed taking longer
              to sell than the panel has been running.
            </>
          )}
        </p>
      )}

      {rows.length > 0 && (
        <>
          <table className="data" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>CPU</th>
                <th className="num">{bySales ? "eBay net" : "Ask net"}</th>
                <th className="num">GovDeals</th>
                <th className="num">Ratio</th>
                <th className="num">Comps</th>
                {bySales && <th className="num">Days</th>}
              </tr>
            </thead>
            <tbody>
              {[...rows]
                .sort((a, b) => b.ratio - a.ratio)
                .slice(0, 20)
                .map((c) => (
                  <tr key={c.cpu}>
                    <td>{c.cpu}</td>
                    <td className="num">
                      {usd(c.ebay_net_median ?? c.ask_net_median ?? 0)}
                    </td>
                    <td className="num">{usd(c.govdeals_median)}</td>
                    <td className={`num ${c.ratio >= 1 ? "pos" : "neg"}`}>
                      {c.ratio.toFixed(2)}×
                    </td>
                    <td className="num muted">
                      {(c.n_ebay ?? c.n_asks ?? 0).toLocaleString()} /{" "}
                      {c.n_govdeals.toLocaleString()}
                    </td>
                    {bySales && (
                      <td className="num muted">
                        {c.median_days_listed != null
                          ? Math.round(c.median_days_listed)
                          : "—"}
                      </td>
                    )}
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="muted small">
            A ratio below 1.00 means you would lose money reselling that
            machine one at a time — the wholesale auction already pays more
            than eBay does, net of fees. Comps are eBay / GovDeals.
          </p>
        </>
      )}

      <p className="muted small">
        <strong>One caveat this cannot measure.</strong> eBay listings are for
        machines with a drive, an operating system and often a warranty.
        GovDeals pallets frequently have none of those — a manifest reading{" "}
        <em>Drive: no</em> on every line is normal. The gap between the two is
        refurb work, which is the handling rate, so a high recovery here and a
        low handling rate on the Board cannot both be right.
      </p>
    </div>
  );
}
