"use client";

import { useMemo, useState, type ReactNode } from "react";

import { HelpIcon } from "./Tooltip";
import type { HelpKey } from "./help-text";

export interface Column<T> {
  /** stable id, also the default sort key */
  id: string;
  header: ReactNode;
  /** right-align and use tabular figures */
  numeric?: boolean;
  /** the value to sort on; omit to make the column unsortable */
  sortValue?: (row: T) => number | string | null | undefined;
  /** what to render; defaults to the sort value */
  cell: (row: T) => ReactNode;
  help?: HelpKey;
  helpLabel?: string;
  width?: string;
}

export type SortDir = "asc" | "desc";

/**
 * Sortable table shared by every list in the app.
 *
 * Sorting lives here rather than in each page so the Board, Sold explorer
 * and Models table cannot drift into three different behaviours. Headers
 * are real buttons, so sorting works from the keyboard and screen readers
 * announce the current direction.
 */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  initialSort,
  initialDir = "desc",
  empty = "Nothing to show.",
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  initialSort?: string;
  initialDir?: SortDir;
  empty?: ReactNode;
}) {
  const [sortId, setSortId] = useState<string | undefined>(initialSort);
  const [dir, setDir] = useState<SortDir>(initialDir);

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.id === sortId);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    const mul = dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      // missing values sort last in both directions rather than pretending
      // to be zero, which would rank an unknown above a genuine low value
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * mul;
      return String(x).localeCompare(String(y)) * mul;
    });
  }, [rows, columns, sortId, dir]);

  function toggle(col: Column<T>) {
    if (!col.sortValue) return;
    if (col.id === sortId) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortId(col.id);
      setDir(col.numeric ? "desc" : "asc");
    }
  }

  return (
    <div className="tablewrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((c) => {
              const active = c.id === sortId;
              return (
                <th
                  key={c.id}
                  className={c.numeric ? "num" : undefined}
                  style={c.width ? { width: c.width } : undefined}
                  aria-sort={
                    active
                      ? dir === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                >
                  <span className="thinner">
                    {c.sortValue ? (
                      <button
                        type="button"
                        className={`sortbtn${active ? " active" : ""}`}
                        onClick={() => toggle(c)}
                      >
                        {c.header}
                        <span className="sortcaret" aria-hidden="true">
                          {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </button>
                    ) : (
                      <span>{c.header}</span>
                    )}
                    {c.help && <HelpIcon k={c.help} label={c.helpLabel} />}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.id} className={c.numeric ? "num" : undefined}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="muted">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
