import { searchSold, soldStates } from "@/lib/data";

import { SoldTable } from "./SoldTable";

export const dynamic = "force-dynamic";

export default async function SoldPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; state?: string }>;
}) {
  const { q = "", state = "" } = await searchParams;
  const [results, states] = await Promise.all([
    searchSold(q, state),
    soldStates(),
  ]);

  return (
    <main>
      <h1>Sold explorer</h1>
      <p className="sub">
        What lots actually closed at. These realized prices are the comps the
        valuation models are fitted on — search here to sanity-check a grade
        against real outcomes.
      </p>

      <div className="card">
        <form className="controls" method="get">
          <label className="field">
            <span className="fieldlabel">Title contains</span>
            <input
              className="select"
              type="text"
              name="q"
              defaultValue={q}
              placeholder="optiplex 7050"
              style={{ width: 240 }}
            />
          </label>
          <label className="field">
            <span className="fieldlabel">State</span>
            <select className="select" name="state" defaultValue={state}>
              <option value="">all states</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary">
            Search
          </button>
          <span className="spacer" />
          <span className="muted small" style={{ height: 30, lineHeight: "30px" }}>
            {results.length} results
          </span>
        </form>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <SoldTable rows={results} />
      </div>
    </main>
  );
}
