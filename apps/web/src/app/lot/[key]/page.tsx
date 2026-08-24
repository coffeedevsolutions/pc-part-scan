import { notFound } from "next/navigation";

import {
  bidSeries,
  getLot,
  getManifest,
  snapshotEntry,
} from "@/lib/data";
import { closesIn, shortDate, usd } from "@/lib/format";

import { BidCurve } from "./BidCurve";

export const dynamic = "force-dynamic";

export default async function LotPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  if (!/^\d+-\d+$/.test(key)) notFound();

  const [lot, series, manifest, snap] = await Promise.all([
    getLot(key),
    bidSeries(key),
    getManifest(key),
    snapshotEntry(key),
  ]);
  if (!lot) notFound();
  const v = snap?.lot;

  return (
    <main>
      <h1>{lot.title ?? key}</h1>
      <p className="sub">
        {key} · {lot.seller ?? "unknown seller"} ·{" "}
        {lot.location?.city ? `${lot.location.city}, ` : ""}
        {lot.location?.state ?? "—"} ·{" "}
        {lot.status === "sold" ? (
          <>sold {usd(lot.final_price)}</>
        ) : (
          <>closes in {closesIn(lot.auction_end_utc)}</>
        )}{" "}
        · <a href={lot.url}>view on GovDeals ↗</a>
      </p>

      {v && (
        <div className="statrow">
          <div className="stat">
            <div className="label">Grade · confidence</div>
            <div className="value">
              <span className={`grade grade-${v.grade}`}>{v.grade}</span>{" "}
              <span className="muted" style={{ fontSize: 15 }}>
                {v.confidence.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="stat">
            <div className="label">Max bid (run {snap.run_id})</div>
            <div className="value">{usd(v.max_bid)}</div>
          </div>
          <div className="stat">
            <div className="label">Headroom vs current</div>
            <div className={`value ${v.headroom >= 0 ? "pos" : "neg"}`}>
              {usd(v.headroom)}
            </div>
          </div>
          <div className="stat">
            <div className="label">Floor → ceiling</div>
            <div className="value" style={{ fontSize: 17 }}>
              {usd(v.floor)} → {usd(v.ceiling)}
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Bid history</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {series.length} observations · dots mark burst samples
        </p>
        <BidCurve
          data={series.map((o) => ({
            at: o.observed_at,
            bid: o.bid,
            source: o.source,
          }))}
        />
        <details>
          <summary className="muted small">Observation table</summary>
          <table className="data">
            <thead>
              <tr>
                <th>Observed</th>
                <th className="num">Bid</th>
                <th className="num">Bid count</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {series.slice(-200).map((o, i) => (
                <tr key={i}>
                  <td>{shortDate(o.observed_at)}</td>
                  <td className="num">{usd(o.bid, 2)}</td>
                  <td className="num">{o.bid_count ?? "—"}</td>
                  <td>{o.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>

      {v && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Valuation</h2>
          <table className="data" style={{ maxWidth: 560 }}>
            <tbody>
              {Object.entries(v.ceiling_sources).map(([src, val]) => (
                <tr key={src}>
                  <td>ceiling · {src.replace(/_/g, " ")}</td>
                  <td className="num">{usd(val)}</td>
                </tr>
              ))}
              <tr>
                <td>ceiling (blend, parts-out)</td>
                <td className="num">{usd(v.ceiling)}</td>
              </tr>
              <tr>
                <td>floor (resale as lot)</td>
                <td className="num">{usd(v.floor)}</td>
              </tr>
              <tr>
                <td>expected revenue (underwritten)</td>
                <td className="num">{usd(v.expected_revenue)}</td>
              </tr>
              <tr>
                <td>ROI at current bid</td>
                <td className="num">
                  {(v.roi_at_current * 100).toFixed(0)}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>
          Machine mix{" "}
          <span className="muted small">
            {manifest
              ? manifest.machines.length
                ? `from spec sheet (${manifest.parsed_by ?? "regex"}, ${manifest.unit_total} units)`
                : "spec sheet attempted — unparseable"
              : v?.exact_manifest
                ? "exact manifest"
                : "inferred from title"}
          </span>
        </h2>
        <MixTable
          mix={manifest?.machines.length ? manifest.machines : (v?.mix ?? [])}
        />
        {manifest?.source_files.length ? (
          <p className="muted small">
            Source: {manifest.source_files.join(", ")}
          </p>
        ) : null}
      </div>
    </main>
  );
}

function MixTable({
  mix,
}: {
  mix: {
    cpu: string | null;
    ram_gb: number | null;
    form_factor: string | null;
    chassis: string | null;
    has_drive: boolean | null;
    qty: number;
  }[];
}) {
  if (!mix.length) return <p className="muted small">Unknown.</p>;
  return (
    <table className="data" style={{ maxWidth: 640 }}>
      <thead>
        <tr>
          <th>CPU</th>
          <th>Chassis</th>
          <th>Form</th>
          <th className="num">RAM</th>
          <th>Drive</th>
          <th className="num">Qty</th>
        </tr>
      </thead>
      <tbody>
        {mix.map((m, i) => (
          <tr key={i}>
            <td>{m.cpu ?? "unknown"}</td>
            <td>{m.chassis ?? "—"}</td>
            <td>{m.form_factor ?? "—"}</td>
            <td className="num">{m.ram_gb ? `${m.ram_gb}GB` : "—"}</td>
            <td>{m.has_drive == null ? "—" : m.has_drive ? "yes" : "no"}</td>
            <td className="num">{m.qty}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
