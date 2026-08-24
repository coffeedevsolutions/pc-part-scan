"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  DEFAULT_CONFIG,
  regrade,
  type Config,
  type Grade,
} from "@pcps/valuation";

import type { SnapshotLot } from "@/lib/data";
import { closesIn, usd } from "@/lib/format";

type BoardLot = SnapshotLot & { end_utc: string | null };

const STORAGE_KEY = "pcps.assumptions.v1";

const FIELDS: {
  key: keyof Config;
  label: string;
  step: number;
  pct?: boolean;
}[] = [
  { key: "target_roi", label: "Target ROI", step: 0.05, pct: true },
  { key: "recovery", label: "Recovery", step: 0.05, pct: true },
  { key: "dead_rate", label: "Dead rate", step: 0.05, pct: true },
  { key: "buyer_premium", label: "Buyer premium", step: 0.005, pct: true },
  { key: "sales_tax", label: "Sales tax", step: 0.005, pct: true },
  { key: "per_unit_handling", label: "$/unit handling", step: 0.5 },
  { key: "pickup_cost", label: "Pickup $", step: 25 },
];

export function BoardClient({
  lots,
  defaults,
}: {
  lots: BoardLot[];
  defaults: Record<string, number>;
}) {
  const base: Config = { ...DEFAULT_CONFIG, ...defaults };
  const [cfg, setCfg] = useState<Config>(base);
  const [gradeMin, setGradeMin] = useState<string>("all");
  const [state, setState] = useState<string>("all");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setCfg({ ...base, ...JSON.parse(raw) });
    } catch {
      /* first visit / blocked storage: keep defaults */
    }
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
    } catch {
      /* storage unavailable: sliders still work for this visit */
    }
  }, [cfg, loaded]);

  const states = useMemo(
    () =>
      Array.from(new Set(lots.map((l) => l.state).filter(Boolean))).sort() as string[],
    [lots],
  );

  const rows = useMemo(() => {
    const graded = lots.map((l) => ({ lot: l, v: regrade(l, cfg) }));
    graded.sort(
      (a, b) =>
        b.v.headroom * b.lot.confidence - a.v.headroom * a.lot.confidence,
    );
    return graded.filter(({ lot, v }) => {
      if (state !== "all" && lot.state !== state) return false;
      if (gradeMin !== "all" && v.grade > gradeMin) return false; // 'A' < 'B' < ...
      return true;
    });
  }, [lots, cfg, gradeMin, state]);

  return (
    <>
      <div className="card">
        <div className="filters" role="group" aria-label="Assumptions">
          {FIELDS.map((f) => (
            <label key={f.key}>
              {f.label}
              <input
                type="number"
                step={f.step}
                min={0}
                value={f.pct ? round4(cfg[f.key]) : cfg[f.key]}
                onChange={(e) =>
                  setCfg({ ...cfg, [f.key]: Number(e.target.value) || 0 })
                }
              />
            </label>
          ))}
          <button type="button" onClick={() => setCfg(base)}>
            Reset
          </button>
        </div>
        <div className="filters">
          <label>
            Grade at least
            <select
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
          <label>
            State
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="all">all</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <span className="muted small">
            {rows.length} lots · regraded live in your browser
          </span>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Grade</th>
              <th className="num">Conf</th>
              <th>Lot</th>
              <th className="num">Units</th>
              <th className="num">Bid</th>
              <th className="num">Max bid</th>
              <th className="num">Headroom</th>
              <th>Closes</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ lot, v }) => (
              <tr key={lot.lot_key} className="rowlink">
                <td>
                  <GradeBadge grade={v.grade} />
                </td>
                <td className="num">{lot.confidence.toFixed(2)}</td>
                <td>
                  <Link href={`/lot/${lot.lot_key}`}>{lot.lot_key}</Link>
                  <div className="muted small">{lot.title.slice(0, 88)}</div>
                </td>
                <td className="num">{lot.units.toLocaleString()}</td>
                <td className="num">{usd(lot.current_bid)}</td>
                <td className="num">{usd(v.max_bid)}</td>
                <td className={`num ${v.headroom >= 0 ? "pos" : "neg"}`}>
                  {usd(v.headroom)}
                </td>
                <td>{closesIn(lot.end_utc) || lot.end_date}</td>
                <td>{lot.state ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function GradeBadge({ grade }: { grade: Grade | string }) {
  return <span className={`grade grade-${grade}`}>{grade}</span>;
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000;
}
