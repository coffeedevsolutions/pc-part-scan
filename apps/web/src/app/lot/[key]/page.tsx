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
              label={unrated ? "Units identified" : "Floor → ceiling"}
              help={unrated ? "identifiedUnits" : "floorCeiling"}
              helpLabel={unrated ? "units identified" : "floor and ceiling"}
              small
            >
              {unrated
                ? `${(v.identified_units ?? 0).toLocaleString()} of ${v.units.toLocaleString()}`
                : `${usd(v.floor)} → ${usd(v.ceiling)}`}
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

      {v && unrated && (
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
  const mix = manifest?.machines.length ? manifest.machines : (lot?.mix ?? []);
  const q = lot?.class_quote;
  const kind = lot?.item_class;
  // A synthesized one-row "mix" with no CPU is not a machine list, it is the
  // absence of one wearing a table. On a pallet of chargers it read as one
  // unknown laptop x 300, which is worse than showing nothing.
  const realMix =
    mix.length > 1 || mix.some((m) => m.cpu) || !!manifest?.machines.length;
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
        <MixTable mix={mix} />
      ) : (
        <p className="muted small" style={{ margin: 0 }}>
          No per-unit breakdown: nothing named a component we recognise, so
          there is nothing to list beyond the count above.
        </p>
      )}
    </>
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
