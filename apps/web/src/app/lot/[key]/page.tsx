import Link from "next/link";
import { notFound } from "next/navigation";

import { DEFAULT_CONFIG, UNRATED, regrade, type Config } from "@pcps/valuation";

import { Grade } from "@/components/Fields";
import { Ago, Countdown } from "@/components/Live";
import { Stat } from "@/components/Stat";
import { HelpIcon } from "@/components/Tooltip";

import {
  bidSeries,
  getLot,
  getLotAction,
  getManifest,
  getNote,
  isWatched,
  savedAssumptions,
  snapshotEntry,
  type MachineLine,
  type ManifestDoc,
  type SnapshotLot,
} from "@/lib/data";
import { agoFrom, remainingFrom, shortDate, usd } from "@/lib/format";

import { BidCurve } from "./BidCurve";
import { LotControls } from "./LotControls";
import { ValuationWaterfall } from "./Valuation";

export const dynamic = "force-dynamic";

export default async function LotPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  if (!/^\d+-\d+$/.test(key)) notFound();

  const [lot, series, manifest, snap, note, action, watched, saved] =
    await Promise.all([
      getLot(key),
      bidSeries(key),
      getManifest(key),
      snapshotEntry(key),
      getNote(key),
      getLotAction(key),
      isWatched(key),
      savedAssumptions(),
    ]);
  // the same assumptions the board is using, so a max bid does not change
  // when you click through to the lot it belongs to
  const cfg: Config = { ...DEFAULT_CONFIG, ...saved };
  if (!lot) notFound();
  const v = snap?.lot;
  // An abstention: too little of the lot is identifiable to price it. The
  // numbers are still on the record below, labelled as the diagnostics they
  // are, but nothing here may present them as a bid ceiling.
  const unrated = v?.contents_known === false;
  const open = lot.status !== "sold";
  // The freshest bid we have. The snapshot's copy is as old as the last
  // scan, and on a lot closing in twenty minutes that is the difference
  // between headroom and a lost deposit.
  const bid = lot.last_obs?.bid ?? v?.current_bid ?? null;
  const bidAt = lot.last_obs?.at ?? null;
  const re = v ? regrade({ ...v, current_bid: bid ?? v.current_bid }, cfg) : null;
  const headroom = re ? re.headroom : null;

  return (
    <main>
      <h1>{lot.title ?? key}</h1>
      <p className="sub">
        {key} · {lot.seller ?? "unknown seller"} ·{" "}
        {lot.location?.city ? `${lot.location.city}, ` : ""}
        {lot.location?.state ?? "—"}
        {lot.status === "sold" ? <> · sold {usd(lot.final_price)}</> : null} ·{" "}
        <a href={lot.url}>view on GovDeals ↗</a>
      </p>

      <div className="statrow">
        <Stat
          label={open ? "Closes in" : "Closed"}
          help="closes"
          helpLabel="the closing time"
          small={!open}
        >
          {open ? (
            <Countdown
              endUtc={lot.auction_end_utc}
              initial={remainingFrom(lot.auction_end_utc)}
            />
          ) : (
            <span className="muted">{shortDate(lot.auction_end_utc)}</span>
          )}
        </Stat>
        <Stat
          label="Current bid"
          help="currentBid"
          helpLabel="the current bid"
          sub={
            bidAt ? (
              <>
                as of <Ago at={bidAt} initial={agoFrom(bidAt)} />
                {lot.last_obs?.bid_count != null
                  ? ` · ${lot.last_obs.bid_count} bids`
                  : ""}
              </>
            ) : (
              "no observation yet"
            )
          }
        >
          {usd(bid)}
        </Stat>
        {v && (
          <>
            <Stat label="Grade · confidence" help="grade" helpLabel="the grade">
              <Grade grade={unrated ? UNRATED : v.grade} />{" "}
              <span className="muted" style={{ fontSize: 15 }}>
                {v.confidence.toFixed(2)}
              </span>
            </Stat>
            <Stat
              label="Max bid"
              help="maxBid"
              helpLabel="max bid"
              sub="at your assumptions"
            >
              {unrated ? <span className="muted">—</span> : usd(re!.max_bid)}
            </Stat>
            <Stat
              label="Headroom vs current"
              help="headroom"
              helpLabel="headroom"
              sub="against the bid above"
              valueClass={
                unrated || headroom == null ? "" : headroom >= 0 ? "pos" : "neg"
              }
            >
              {unrated || headroom == null ? (
                <span className="muted">—</span>
              ) : (
                usd(headroom)
              )}
            </Stat>
            <Stat
              label={
                v.count_known === false
                  ? "Units"
                  : unrated
                    ? "Units identified"
                    : "Floor → ceiling"
              }
              help={unrated ? "identifiedUnits" : "floorCeiling"}
              helpLabel={unrated ? "units identified" : "floor and ceiling"}
              small
            >
              {v.count_known === false ? (
                <span className="muted">not stated</span>
              ) : unrated ? (
                `${(v.identified_units ?? 0).toLocaleString()} of ${v.units.toLocaleString()}`
              ) : (
                `${usd(v.floor)} → ${usd(v.ceiling)}`
              )}
            </Stat>
          </>
        )}
      </div>

      {unrated && (
        <div className="card notice">
          <strong>Not priced.</strong>{" "}
          {v!.count_known === false
            ? `The title never says how many things are in this lot, and no spec sheet settled it. Every number here is per unit, so without a count there is nothing to multiply.`
            : v!.item_class
              ? `We read this as ${v!.item_class}s, but too few ${v!.item_class} lots have sold for us to put a number on one.`
              : `We cannot tell what this lot holds — ${v!.class_reason || "the title does not name it"}.`}{" "}
          Anything we produced would come from a generic per-unit rate — a
          number that says how many things are on the pallet, not what they
          are. A pallet of laptop chargers and a pallet of i7 desktops come
          out within a few dollars a unit of each other that way, so we show
          nothing rather than a figure you might bid against.
          <div className="muted small" style={{ marginTop: 6 }}>
            To price it: check what is in the lot below, then pin the parts
            you recognise on the <Link href="/models">Models</Link> page.
          </div>
        </div>
      )}

      <LotControls
        lotKey={key}
        watched={watched}
        note={note}
        action={action}
      />

      <div className="card">
        <h2 style={{ marginTop: 0 }}>
          Bid history
          <HelpIcon k="bidHistory" label="the bid history" />
        </h2>
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

      {v && !unrated && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>How this number is built</h2>
          <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
            Every step below comes off the one above it. Change an assumption
            on the <Link href="/">Board</Link> and this chain moves with it.
          </p>
          <ValuationWaterfall lot={v} cfg={cfg} bid={bid ?? v.current_bid} />
        </div>
      )}

      {v && unrated && v.count_known !== false && (
        <details className="card">
          {/* folded away on purpose: a green headroom figure is exactly the
              thing this lot is not entitled to show */}
          <summary className="muted small">
            Show what a generic per-unit rate would have produced — diagnosis
            only, none of it underwritten
          </summary>
          <ValuationWaterfall
            lot={v}
            cfg={cfg}
            bid={bid ?? v.current_bid}
            muted
          />
        </details>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>
          What is in this lot
          <HelpIcon k="machineMix" label="the contents" />
        </h2>
        <Contents lot={v} manifest={manifest} />
        {manifest?.source_files.length ? (
          <p className="muted small">
            Source: {manifest.source_files.join(", ")}
          </p>
        ) : null}
      </div>
    </main>
  );
}

/**
 * What we believe the lot holds and how that belief was reached.
 *
 * Two very different readings end up here. Either the spec sheet or the
 * title named the machines and the CPU model priced them one by one, or it
 * did not and the lot was priced from sold lots of the same kind of thing.
 * The second is a much cruder answer and has to say so on the page, not
 * only in the code.
 */
function Contents({
  lot,
  manifest,
}: {
  lot: SnapshotLot | undefined;
  manifest: ManifestDoc | null;
}) {
  // Which list of machines to show, and whether it carries prices.
  //
  // The graded mix is the one with prices on it, so it is preferred — but
  // only when it is actually the manifest's machines. It is not always:
  // grade.py reads the manifest only when the count is unknown or the lot
  // has 5+ units (grade.py `if unknown_count or units >= 5`), and otherwise
  // synthesizes a single row from the title. Preferring the priced copy
  // unconditionally therefore replaced a genuine 3-machine spec sheet with
  // one generic row — fewer facts, dressed up as more, because it had a
  // price column. The same happened whenever a manifest was parsed after
  // the last scan: the fresh spec sheet hid behind the stale synthesized
  // row until the next snapshot.
  //
  // So: take the graded mix when it is at least as detailed as the
  // manifest, and the manifest otherwise. Losing the price columns is the
  // cheaper loss — the per-unit price is one derived number, and the
  // manifest rows are what the lot actually contains.
  const gradedRows = lot?.mix?.length ?? 0;
  const manifestRows = manifest?.machines.length ?? 0;
  const gradedIsRicher = gradedRows > 0 && gradedRows >= manifestRows;
  const mix = gradedIsRicher
    ? lot!.mix
    : manifestRows
      ? manifest!.machines
      : (lot?.mix ?? []);
  const priced = mix.length > 0 && mix.every((m) => m.unit_value != null);
  const q = lot?.class_quote;
  const kind = lot?.item_class;
  // A synthesized one-row "mix" with no CPU is not a machine list, it is the
  // absence of one wearing a table. On a pallet of chargers it read as one
  // unknown laptop x 300, which is worse than showing nothing.
  //
  // That rule was right when the row carried no price, and wrong once it
  // did. Priced, the same row says "300 adapters at $4.17 each = $1,250" --
  // the arithmetic the ceiling is built from, on the one line there is. It
  // was hiding the breakdown on 59 of 60 board lots, because most lots are
  // exactly this shape: one kind of thing, N of them.
  const realMix =
    priced || mix.length > 1 || mix.some((m) => m.cpu) ||
    !!manifest?.machines.length;
  return (
    <>
      <table className="data waterfall" style={{ marginBottom: 10 }}>
        <tbody>
          <tr>
            <td style={{ width: 150 }}>Read as</td>
            <td>
              {kind ? (
                <>
                  <strong>{kind}s</strong>{" "}
                  <span className="muted">— {lot?.class_reason}</span>
                </>
              ) : (
                <span className="muted">
                  {lot?.class_reason || "not identified"}
                </span>
              )}
            </td>
          </tr>
          <tr>
            <td>Count</td>
            <td>
              {lot?.count_known === false ? (
                <span className="muted">
                  not stated anywhere — the lot cannot be priced per unit
                </span>
              ) : (
                <>
                  {lot?.units.toLocaleString()} units
                  {lot?.exact_manifest ? " (from the spec sheet)" : " (from the title)"}
                </>
              )}
            </td>
          </tr>
          <tr>
            <td>Spec sheet</td>
            <td>
              {manifest
                ? manifest.machines.length
                  ? `read (${manifest.parsed_by ?? "regex"}, ${manifest.unit_total} units)`
                  : "attached but unreadable — the triage routine will retry it"
                : "none attached"}
            </td>
          </tr>
          <tr>
            <td>Priced from</td>
            <td>
              {lot?.priced_by === "machines" ? (
                <>
                  the machine model —{" "}
                  {(lot.identified_units ?? 0).toLocaleString()} of{" "}
                  {lot.units.toLocaleString()} units have a component we
                  recognise
                </>
              ) : lot?.priced_by === "class" && q ? (
                <>
                  sold lots of the same kind — {q.bulk_n} pallets and{" "}
                  {q.single_n} single sales of {kind}s. Not from what is
                  actually inside this one, which is why it caps at grade C.
                </>
              ) : (
                <span className="muted">nothing — this lot is unrated</span>
              )}
            </td>
          </tr>
        </tbody>
      </table>
      {realMix ? (
        <MixTable mix={mix} lot={lot} />
      ) : (
        <p className="muted small" style={{ margin: 0 }}>
          No per-unit breakdown: nothing named a component we recognise, so
          there is nothing to list beyond the count above.
        </p>
      )}
    </>
  );
}

/**
 * The spec-sheet lines, each with what one of them is worth and what the
 * line comes to.
 *
 * The table used to stop at Qty, which meant the page could tell you a
 * pallet held 40 i5-8500s and separately that the whole lot was worth
 * $3,240, with no way to see which lines carried that and which were
 * making up the numbers. The per-unit price is the model's actual output;
 * the extended column is just it times Qty, and the total is what the
 * ceiling is built from — so a ceiling you doubt can be traced to the line
 * you doubt.
 */
/** How to name a row that has no CPU: the lot's item class, else "units". */
function kindLabel(lot: SnapshotLot | undefined, qty: number): string {
  const kind = lot?.item_class;
  if (!kind) return "unidentified units";
  return qty === 1 ? kind : `${kind}s`;
}

function MixTable({
  mix,
  lot,
}: {
  mix: MachineLine[];
  lot: SnapshotLot | undefined;
}) {
  if (!mix.length) return <p className="muted small">Unknown.</p>;
  const priced = mix.every((m) => m.unit_value != null);
  // A lot of chargers has no CPU, chassis or RAM to show, and five columns of
  // em-dashes is not a machine list — it is a machine list's absence. When
  // nothing names a component, the same rows are the item and its count.
  const machines = mix.some((m) => m.cpu);
  const units = mix.reduce((a, m) => a + m.qty, 0);
  const total = mix.reduce((a, m) => a + (m.unit_value ?? 0) * m.qty, 0);
  // The ceiling blends sources; this column is one of them. Say so rather
  // than showing a total that silently disagrees with the number above.
  // Tolerance scales with the lot: each unit price is rounded to the cent
  // before being multiplied out, so the column can drift by up to half a
  // cent a unit without anything being wrong.
  const blended = priced && lot
    ? Math.abs(lot.ceiling - total) > Math.max(1, lot.units * 0.01)
    : false;
  const byClass = lot?.priced_by === "class";

  return (
    <>
      <table
        className="data"
        style={{ maxWidth: machines ? (priced ? 820 : 640) : 520 }}
      >
        <thead>
          <tr>
            {machines ? (
              <>
                <th>CPU</th>
                <th>Chassis</th>
                <th>Form</th>
                <th className="num">RAM</th>
                <th>Drive</th>
              </>
            ) : (
              <th>Item</th>
            )}
            <th className="num">Qty</th>
            {priced && <th className="num">$/unit</th>}
            {priced && <th className="num">Value</th>}
          </tr>
        </thead>
        <tbody>
          {mix.map((m, i) => (
            <tr key={i}>
              {machines ? (
                <>
                  <td>{m.cpu ?? "unknown"}</td>
                  <td>{m.chassis ?? "—"}</td>
                  <td>{m.form_factor ?? "—"}</td>
                  <td className="num">{m.ram_gb ? `${m.ram_gb}GB` : "—"}</td>
                  <td>
                    {m.has_drive == null ? "—" : m.has_drive ? "yes" : "no"}
                  </td>
                </>
              ) : (
                <td>
                  {kindLabel(lot, m.qty)}
                  {m.chassis && <span className="muted"> · {m.chassis}</span>}
                </td>
              )}
              <td className="num">{m.qty.toLocaleString()}</td>
              {priced && <td className="num">{usd(m.unit_value!, 2)}</td>}
              {priced && (
                <td className="num">{usd(m.unit_value! * m.qty)}</td>
              )}
            </tr>
          ))}
        </tbody>
        {priced && mix.length > 1 && (
          <tfoot>
            <tr className="wf-total">
              <td colSpan={machines ? 5 : 1}>Total</td>
              <td className="num">{units.toLocaleString()}</td>
              <td className="num muted">{usd(total / (units || 1), 2)}</td>
              <td className="num">{usd(total)}</td>
            </tr>
          </tfoot>
        )}
      </table>
      {priced && byClass && (
        <p className="muted small">
          {mix.length > 1 ? (
            <>
              Every line carries the same price because nothing on this lot
              was priced on its own merits — it is {units.toLocaleString()} ×{" "}
              {usd(mix[0].unit_value!, 2)}, the going rate for{" "}
              {lot?.item_class}s, whatever each line happens to say.
            </>
          ) : (
            <>
              One line because that is all we know: the lot is{" "}
              {units.toLocaleString()} {lot?.item_class}
              {units === 1 ? "" : "s"} at the going rate for the kind, not{" "}
              {units.toLocaleString()} things we have looked at individually.
              A spec sheet we could read would break this into real rows.
            </>
          )}
        </p>
      )}
      {priced && !byClass && (
        <p className="muted small">
          {blended ? (
            <>
              {usd(total)} is what the GovDeals single-unit model makes of
              these lines. The ceiling used above is {usd(lot!.ceiling)},
              because it also blends in eBay asks.
            </>
          ) : (
            <>This total is the ceiling the valuation above starts from.</>
          )}
        </p>
      )}
    </>
  );
}
