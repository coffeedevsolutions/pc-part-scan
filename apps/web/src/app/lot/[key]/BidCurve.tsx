"use client";

import { LineChart } from "@/components/LineChart";
import { usd } from "@/lib/format";

export function BidCurve({
  data,
}: {
  data: { at: string; bid: number; source: string }[];
}) {
  const points = data
    .map((d) => ({
      x: new Date(d.at).getTime(),
      y: d.bid,
      note: d.source === "burst" ? "burst" : undefined,
    }))
    .filter((p) => !Number.isNaN(p.x));
  return (
    <LineChart
      points={points}
      step
      markerNotes={points.length <= 120}
      yFormat={(v) => usd(v)}
    />
  );
}
