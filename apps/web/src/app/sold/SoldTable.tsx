"use client";

import { DataTable, type Column } from "@/components/DataTable";
import type { LotDoc } from "@/lib/data";
import { shortDate, usd } from "@/lib/format";

export function SoldTable({ rows }: { rows: LotDoc[] }) {
  const columns: Column<LotDoc>[] = [
    {
      id: "closed",
      header: "Closed",
      sortValue: (l) =>
        l.auction_end_utc ? new Date(l.auction_end_utc).getTime() : null,
      cell: (l) => (
        <span style={{ whiteSpace: "nowrap" }}>
          {shortDate(l.auction_end_utc ?? l.auction_end)}
        </span>
      ),
    },
    {
      id: "lot",
      header: "Lot",
      sortValue: (l) => (l.title ?? "").toLowerCase(),
      cell: (l) => (
        <>
          <a href={l.url} className="lottitle">
            {l.title ?? l.key}
          </a>
          <div className="muted small">
            {l.key} · {l.seller ?? "unknown seller"}
          </div>
        </>
      ),
    },
    {
      id: "state",
      header: "State",
      sortValue: (l) => l.location?.state ?? null,
      cell: (l) => l.location?.state ?? "—",
    },
    {
      id: "hammer",
      header: "Hammer",
      numeric: true,
      sortValue: (l) => l.final_price,
      cell: (l) => usd(l.final_price),
    },
  ];
  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(l) => l.key}
      initialSort="closed"
      initialDir="desc"
      empty="No sold lots match that search."
    />
  );
}
