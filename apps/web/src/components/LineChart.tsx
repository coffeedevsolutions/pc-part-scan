"use client";

import { useMemo, useRef, useState } from "react";

export interface ChartPoint {
  x: number; // epoch ms
  y: number;
  note?: string; // e.g. "burst" — shown in the tooltip
}

/**
 * Single-series line/step chart with the standard hover layer: a vertical
 * crosshair snaps to the nearest point and one tooltip shows time + value.
 * Single series ⇒ no legend; the surrounding card's title names the data.
 */
export function LineChart({
  points,
  step = false,
  height = 220,
  yFormat = (v) => v.toLocaleString(),
  xFormat = (ms) =>
    new Date(ms).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }),
  markerNotes = false,
}: {
  points: ChartPoint[];
  step?: boolean;
  height?: number;
  yFormat?: (v: number) => string;
  xFormat?: (ms: number) => string;
  markerNotes?: boolean; // draw dots on points that carry a note
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const W = 760;
  const H = height;
  const PAD = { l: 56, r: 16, t: 12, b: 26 };

  const { path, ticks, xTicks, sx, sy } = useMemo(() => {
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const x0 = Math.min(...xs);
    const x1 = Math.max(...xs);
    const yMax = Math.max(...ys, 1);
    const sx = (x: number) =>
      PAD.l + ((x - x0) / Math.max(1, x1 - x0)) * (W - PAD.l - PAD.r);
    const sy = (y: number) => H - PAD.b - (y / yMax) * (H - PAD.t - PAD.b);

    const stepTick = niceStep(yMax / 4);
    const ticks: number[] = [];
    for (let v = 0; v <= yMax + 1e-9; v += stepTick) ticks.push(v);

    const xTicks =
      x1 > x0 ? [x0, x0 + (x1 - x0) / 2, x1] : [x0];

    let d = "";
    points.forEach((p, i) => {
      const X = sx(p.x);
      const Y = sy(p.y);
      if (i === 0) d = `M ${X} ${Y}`;
      else if (step) d += ` H ${X} V ${Y}`;
      else d += ` L ${X} ${Y}`;
    });
    return { path: d, ticks, xTicks, sx, sy };
  }, [points, step, H, PAD.l, PAD.r, PAD.t, PAD.b]);

  if (points.length === 0) {
    return <p className="muted small">No observations yet.</p>;
  }

  const hovered = hover != null ? points[hover] : null;
  const last = points[points.length - 1]!;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestD = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(sx(p.x) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setHover(best);
  }

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label="Line chart"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={sy(v)}
              y2={sy(v)}
              stroke="var(--grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.l - 8}
              y={sy(v) + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {yFormat(v)}
            </text>
          </g>
        ))}
        {xTicks.map((ms) => (
          <text
            key={ms}
            x={sx(ms)}
            y={H - 8}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-muted)"
          >
            {new Date(ms).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
            })}
          </text>
        ))}
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={sy(0)}
          y2={sy(0)}
          stroke="var(--baseline)"
          strokeWidth={1}
        />
        <path
          d={path}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {markerNotes &&
          points.map(
            (p, i) =>
              p.note && (
                <circle
                  key={i}
                  cx={sx(p.x)}
                  cy={sy(p.y)}
                  r={4}
                  fill="var(--series-1)"
                  stroke="var(--surface-1)"
                  strokeWidth={2}
                />
              ),
          )}
        {/* end marker with surface ring */}
        <circle
          cx={sx(last.x)}
          cy={sy(last.y)}
          r={4.5}
          fill="var(--series-1)"
          stroke="var(--surface-1)"
          strokeWidth={2}
        />
        {hovered && (
          <>
            <line
              x1={sx(hovered.x)}
              x2={sx(hovered.x)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="var(--baseline)"
              strokeWidth={1}
            />
            <circle
              cx={sx(hovered.x)}
              cy={sy(hovered.y)}
              r={4.5}
              fill="var(--series-1)"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
          </>
        )}
      </svg>
      {hovered && (
        <div
          className="chart-tip"
          style={{
            left: `${(sx(hovered.x) / W) * 100}%`,
            top: 0,
            transform:
              sx(hovered.x) > W * 0.7
                ? "translateX(-105%)"
                : "translateX(12px)",
          }}
        >
          <div className="v">{yFormat(hovered.y)}</div>
          <div className="muted">
            {xFormat(hovered.x)}
            {hovered.note ? ` · ${hovered.note}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

function niceStep(raw: number): number {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const n = raw / mag;
  if (n <= 1) return mag;
  if (n <= 2) return 2 * mag;
  if (n <= 5) return 5 * mag;
  return 10 * mag;
}
