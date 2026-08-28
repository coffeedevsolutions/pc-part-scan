"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_CONFIG,
  UNRATED,
  rankKey,
  regrade,
  type Config,
  type Regrade,
} from "@pcps/valuation";

import { saveAssumptions, setWatch } from "@/lib/actions";
import { DataTable, type Column } from "@/components/DataTable";
import { Grade, MoneyField, PercentField } from "@/components/Fields";
import { HelpIcon } from "@/components/Tooltip";
import type { SnapshotLot } from "@/lib/data";
import { Countdown } from "@/components/Live";
import { remainingFrom, usd } from "@/lib/format";

type BoardLot = SnapshotLot & { end_utc: string | null };
type Row = { lot: BoardLot; v: Regrade };

/**
 * Bumped from v1 when part_handling's default changed from $3 to $0.
 *
 * A v1 blob holds a full config snapshot written by a build where $3 was
 * the default, so it says `part_handling: 3` for everyone who ever touched
 * any slider — indistinguishably from someone who chose $3 on purpose.
 * Replaying one would push $3 back to the server as a deliberate setting
 * and return every charger pallet to a max bid of zero, with nothing on
 * screen to explain it. There is no way to tell the two apart after the
 * fact, so v1 blobs are simply not read: the cost is one device falling
 * back to current defaults, against silently undoing the change.
 *
 * Bump this again whenever a default changes meaning, for the same reason.
 */
const STORAGE_KEY = "pcps.assumptions.v2";

export function BoardClient({
  lots,
  defaults,
  hasServerSaved,
  watched: watchedInit,
}: {
  lots: BoardLot[];
  defaults: Record<string, number>;
  hasServerSaved: boolean;
  watched: string[];
}) {
  const base: Config = { ...DEFAULT_CONFIG, ...defaults };
  const [cfg, setCfg] = useState<Config>(base);
  const [gradeMin, setGradeMin] = useState("all");
  const [state, setState] = useState("all");
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [hideUnrated, setHideUnrated] = useState(false);
  const [watched, setWatched] = useState<Set<string>>(new Set(watchedInit));
  const touched = useRef(false); // only the user's own edits reach the server
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // the server copy is the durable cross-device one and wins; localStorage
    // only fills in when the server has nothing yet
    if (hasServerSaved) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw);
      setCfg((c) => ({ ...c, ...stored }));
      // ...and then send it on, because every other page reads the server
      // copy and nothing else. Without this the Board would grade a lot at
      // the rates on screen while its own detail page graded the same lot
      // at the defaults, with no visible reason for the two to disagree.
      //
      // Safe to treat as user-chosen only because STORAGE_KEY is versioned:
      // anything under this key was written by a build whose defaults match
      // the ones running now, so a value that differs from a default is a
      // value somebody set.
      saveAssumptions({ ...base, ...stored } as unknown as Record<string, number>)
        .catch(() => {});
    } catch {
      /* first visit / blocked storage: keep defaults */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!touched.current) return; // hydration must never clobber the server
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
    } catch {
      /* storage unavailable: the sliders still work for this visit */
    }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveAssumptions(cfg as unknown as Record<string, number>).catch(() => {});
    }, 800);
  }, [cfg]);

  function updateCfg(patch: Partial<Config>) {
    touched.current = true;
    setCfg((c) => ({ ...c, ...patch }));
  }

  async function onToggleWatch(key: string) {
    const want = !watched.has(key);
    setWatched((prev) => {
      const next = new Set(prev);
      if (want) next.add(key);
      else next.delete(key);
      return next;
    });
    try {
      await setWatch(key, want);
    } catch {
      setWatched((prev) => {
        const next = new Set(prev);
        if (want) next.delete(key);
        else next.add(key);
        return next;
      });
    }
  }

  const states = useMemo(
    () =>
      Array.from(
        new Set(lots.map((l) => l.state).filter(Boolean)),
      ).sort() as string[],
    [lots],
  );

  const rows: Row[] = useMemo(() => {
    return lots
      .map((lot) => ({ lot, v: regrade(lot, cfg) }))
      .filter(({ lot, v }) => {
        if (hideUnrated && v.grade === UNRATED) return false;
        if (watchedOnly && !watched.has(lot.lot_key)) return false;
        if (state !== "all" && lot.state !== state) return false;
        if (gradeMin !== "all" && v.grade > gradeMin) return false;
        return true;
      })
      // Default order is confidence-weighted headroom, matching the
      // pipeline: a big number we do not believe should not outrank a
      // smaller one we do. Sorting the table by raw headroom instead put
      // huge low-confidence unknowns on top. Clicking a header overrides.
      .sort((a, b) => rankKey(a.v, a.lot.confidence) - rankKey(b.v, b.lot.confidence));
  }, [lots, cfg, gradeMin, state, watchedOnly, hideUnrated, watched]);

  const unratedCount = useMemo(
    () => rows.filter(({ v }) => v.grade === UNRATED).length,
    [rows],
  );

  const columns: Column<Row>[] = useMemo(() => [
    {
      id: "watch",
      header: "",
      width: "34px",
      cell: ({ lot }) => (
        <button
          type="button"
          className="watchstar"
          aria-pressed={watched.has(lot.lot_key)}
          title={watched.has(lot.lot_key) ? "Unwatch" : "Watch"}
          onClick={() => onToggleWatch(lot.lot_key)}
        >
          {watched.has(lot.lot_key) ? "★" : "☆"}
        </button>
      ),
    },
    {
      id: "grade",
      header: "Grade",
      help: "grade",
      helpLabel: "grade",
      width: "96px",
      // A is best, so ascending letters are descending quality
      sortValue: ({ v }) => v.grade,
      cell: ({ v }) => <Grade grade={v.grade} />,
    },
    {
      id: "lot",
      header: "Lot",
      sortValue: ({ lot }) => lot.title.toLowerCase(),
      cell: ({ lot }) => (
        <>
          <Link href={`/lot/${lot.lot_key}`} className="lottitle">
            {lot.title}
          </Link>
          <div className="muted small">
            {lot.lot_key}
            {lot.state ? ` · ${lot.state}` : ""}
          </div>
        </>
      ),
    },
    {
      id: "kind",
      header: "Kind",
      help: "itemClass",
      helpLabel: "the kind",
      width: "104px",
      sortValue: ({ lot }) => lot.item_class ?? null,
      cell: ({ lot }) =>
        lot.item_class ? (
          <span
            className={`kind kind-${lot.item_family ?? "unknown"}`}
            title={lot.class_reason}
          >
            {lot.item_class}
          </span>
        ) : (
          <span className="muted small" title={lot.class_reason}>
            unread
          </span>
        ),
    },
    {
      id: "units",
      header: "Units",
      help: "units",
      helpLabel: "units",
      numeric: true,
      sortValue: ({ lot }) => lot.units,
      cell: ({ lot }) => lot.units.toLocaleString(),
    },
    {
      id: "bid",
      header: "Bid",
      help: "currentBid",
      helpLabel: "the current bid",
      numeric: true,
      sortValue: ({ lot }) => lot.current_bid,
      cell: ({ lot }) => usd(lot.current_bid),
    },
    {
      id: "maxbid",
      header: "Max bid",
      help: "maxBid",
      helpLabel: "max bid",
      numeric: true,
      // An abstention has no max bid. Sorting it as null keeps it out of the
      // top of a "highest max bid" sort instead of letting a number we do
      // not stand behind win the column.
      sortValue: ({ v }) => (v.grade === UNRATED ? null : v.max_bid),
      cell: ({ v }) =>
        v.grade === UNRATED ? <span className="muted">—</span> : usd(v.max_bid),
    },
    {
      id: "headroom",
      header: "Headroom",
      help: "headroom",
      helpLabel: "headroom",
      numeric: true,
      sortValue: ({ v }) => (v.grade === UNRATED ? null : v.headroom),
      cell: ({ v }) =>
        v.grade === UNRATED ? (
          <span className="muted">—</span>
        ) : (
          <span className={v.headroom >= 0 ? "pos" : "neg"}>{usd(v.headroom)}</span>
        ),
    },
    {
      id: "closes",
      header: "Closes",
      help: "closes",
      helpLabel: "the closing time",
      sortValue: ({ lot }) =>
        lot.end_utc ? new Date(lot.end_utc).getTime() : null,
      // live, because the board's whole job is telling you what is about to
      // close and a server-rendered string starts aging the moment it lands
      cell: ({ lot }) =>
        lot.end_utc ? (
          <Countdown endUtc={lot.end_utc} initial={remainingFrom(lot.end_utc)} />
        ) : (
          lot.end_date
        ),
    },
    {
      id: "confidence",
      header: "Conf",
      help: "confidence",
      helpLabel: "confidence",
      numeric: true,
      sortValue: ({ lot }) => lot.confidence,
      cell: ({ lot }) => lot.confidence.toFixed(2),
    },
  ], [watched]);

  return (
    <>
      <div className="card">
        <div className="controls">
          <PercentField
            label="Target ROI"
            help="targetRoi"
            value={cfg.target_roi}
            onChange={(v) => updateCfg({ target_roi: v })}
            step={5}
          />
          <PercentField
            label="Recovery"
            help="recovery"
            value={cfg.recovery}
            onChange={(v) => updateCfg({ recovery: v })}
            step={5}
            max={100}
          />
          <PercentField
            label="Dead rate"
            help="deadRate"
            value={cfg.dead_rate}
            onChange={(v) => updateCfg({ dead_rate: v })}
            step={5}
            max={100}
          />
          <PercentField
            label="Buyer premium"
            help="buyerPremium"
            value={cfg.buyer_premium}
            onChange={(v) => updateCfg({ buyer_premium: v })}
            step={0.5}
          />
          <PercentField
            label="Sales tax"
            help="salesTax"
            value={cfg.sales_tax}
            onChange={(v) => updateCfg({ sales_tax: v })}
            step={0.5}
          />
          <MoneyField
            label="Handling / machine"
            help="handling"
            value={cfg.per_unit_handling}
            onChange={(v) => updateCfg({ per_unit_handling: v })}
            step={0.5}
          />
          <MoneyField
            label="Handling / part"
            help="partHandling"
            value={cfg.part_handling ?? cfg.per_unit_handling}
            onChange={(v) => updateCfg({ part_handling: v })}
            step={0.5}
          />
          <MoneyField
            label="Pickup"
            help="pickup"
            value={cfg.pickup_cost}
            onChange={(v) => updateCfg({ pickup_cost: v })}
            step={25}
          />
          <span className="spacer" />
          <button
            type="button"
            className="btn"
            onClick={() => {
              touched.current = true;
              setCfg(base);
            }}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="card">
        <div className="controls">
          <label className="field">
            <span className="fieldlabel">Grade at least</span>
            <select
              className="select"
              value={gradeMin}
              onChange={(e) => setGradeMin(e.target.value)}
            >
              <option value="all">any</option>
              {["A", "B", "C", "D"].map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="fieldlabel">State</span>
            <select
              className="select"
              value={state}
              onChange={(e) => setState(e.target.value)}
            >
              <option value="all">all</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="checkfield">
            <input
              type="checkbox"
              checked={watchedOnly}
              onChange={(e) => setWatchedOnly(e.target.checked)}
            />
            Watched only
          </label>
          <label className="checkfield">
            <input
              type="checkbox"
              checked={hideUnrated}
              onChange={(e) => setHideUnrated(e.target.checked)}
            />
            Hide unrated
            <HelpIcon k="unrated" label="unrated lots" />
          </label>
          <span className="spacer" />
          <span className="muted small" style={{ height: 30, lineHeight: "30px" }}>
            {rows.length} lots · ranked by confidence-weighted headroom
            <HelpIcon k="ranking" label="the default ranking" />
            {unratedCount > 0 && ` · ${unratedCount} unrated`}
          </span>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={({ lot }) => lot.lot_key}
          empty="No lots match these filters."
        />
      </div>
    </>
  );
}
