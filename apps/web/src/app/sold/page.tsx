import { searchSold } from "@/lib/data";
import { shortDate, usd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function SoldPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; state?: string }>;
}) {
  const { q = "", state = "" } = await searchParams;
  const results = await searchSold(q, state);

  return (
    <main>
      <h1>Sold explorer</h1>
      <p className="sub">
        Realized prices from the harvested sold archive — the comps behind the
        models.
      </p>
      <form className="filters" method="get">
        <label>
          Title contains
          <input type="text" name="q" defaultValue={q} placeholder="optiplex 7050" />
        </label>
        <label>
          State
          <input
            type="text"
            name="state"
            defaultValue={state}
            placeholder="IA"
            style={{ width: 60 }}
            maxLength={2}
          />
        </label>
        <button type="submit">Search</button>
      </form>
      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Closed</th>
              <th>Lot</th>
              <th>Seller</th>
              <th>State</th>
              <th className="num">Hammer</th>
            </tr>
          </thead>
          <tbody>
            {results.map((l) => (
              <tr key={l.key}>
                <td style={{ whiteSpace: "nowrap" }}>
                  {shortDate(l.auction_end_utc ?? l.auction_end)}
                </td>
                <td>
                  <a href={l.url}>{l.key}</a>
                  <div className="muted small">{(l.title ?? "").slice(0, 96)}</div>
                </td>
                <td>{l.seller ?? "—"}</td>
                <td>{l.location?.state ?? "—"}</td>
                <td className="num">{usd(l.final_price)}</td>
              </tr>
            ))}
            {results.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}
