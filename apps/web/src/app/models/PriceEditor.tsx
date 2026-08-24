"use client";

import { useCallback, useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { saveComponentPrice } from "@/lib/actions";
import { usd } from "@/lib/format";

interface Row {
  cpu: string;
  fitted: number | null;
  pinned: number | null;
  note: string;
  /** just added by hand, so it has nothing to sort on yet */
  isNew?: boolean;
}

/**
 * The model's per-CPU values, with an override column.
 *
 * A pin replaces the fitted number in the next scan's valuations — it is
 * how you tell the system about a price you know better than it does.
 */
export function PriceEditor({ rows: initial }: { rows: Row[] }) {
  const [rows, setRows] = useState(initial);
  const [newCpu, setNewCpu] = useState("");
  const [status, setStatus] = useState("");

  const save = useCallback(async function save(cpu: string, raw: string) {
    const value = raw.trim() === "" ? null : Number(raw);
    if (value != null && (!Number.isFinite(value) || value < 0)) return;
    setStatus("saving…");
    try {
      await saveComponentPrice(cpu, value);
      setRows((rs) => rs.map((r) => (r.cpu === cpu ? { ...r, pinned: value } : r)));
      setStatus(value == null ? `unpinned ${cpu}` : `pinned ${cpu}`);
    } catch (e) {
      setStatus(`could not save ${cpu}: ${e instanceof Error ? e.message : "error"}`);
    }
  }, []);

  function addRow() {
    const cpu = newCpu.trim().toLowerCase();
    if (!cpu || rows.some((r) => r.cpu === cpu)) return;
    setRows((rs) => [{ cpu, fitted: null, pinned: null, note: "", isNew: true }, ...rs]);
    setNewCpu("");
    setStatus(`added ${cpu} — enter a price to pin it`);
  }

  const columns: Column<Row>[] = useMemo(() => [
    {
      id: "cpu",
      header: "CPU",
      sortValue: (r) => r.cpu,
      cell: (r) => r.cpu,
    },
    {
      id: "fitted",
      header: "Model says",
      numeric: true,
      sortValue: (r) => r.fitted,
      cell: (r) => (
        <span className="muted">{r.fitted != null ? usd(r.fitted) : "—"}</span>
      ),
    },
    {
      id: "pinned",
      header: "Your override",
      numeric: true,
      sortValue: (r) => r.pinned,
      cell: (r) => (
        <input
          className="priceedit"
          type="number"
          min={0}
          step={1}
          defaultValue={r.pinned ?? ""}
          placeholder="—"
          aria-label={`Override price for ${r.cpu}`}
          onBlur={(e) => {
            const raw = e.target.value;
            const prev = r.pinned == null ? "" : String(r.pinned);
            if (raw !== prev) save(r.cpu, raw);
          }}
        />
      ),
    },
    {
      id: "effective",
      header: "Used in valuations",
      numeric: true,
      sortValue: (r) => r.pinned ?? r.fitted,
      cell: (r) => {
        const eff = r.pinned ?? r.fitted;
        return (
          <span style={{ fontWeight: r.pinned != null ? 650 : 400 }}>
            {eff != null ? usd(eff) : "—"}
          </span>
        );
      },
    },
  ], [save]);

  return (
    <>
      <div className="controls" style={{ marginBottom: 12 }}>
        <label className="field">
          <span className="fieldlabel">Pin a CPU the fit does not know</span>
          <input
            className="select"
            type="text"
            placeholder="i5-8500t"
            value={newCpu}
            onChange={(e) => setNewCpu(e.target.value)}
            style={{ width: 140 }}
          />
        </label>
        <button type="button" className="btn" onClick={addRow}>
          Add
        </button>
        <span className="spacer" />
        <span className="muted small" style={{ height: 30, lineHeight: "30px" }}>
          {status}
        </span>
      </div>
      <div style={{ maxHeight: 460, overflowY: "auto" }}>
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(r) => r.cpu}
          initialSort="effective"
          initialDir="desc"
          pinFirst={(r) => r.isNew === true}
        />
      </div>
      <p className="muted small">
        Leave the override blank to use the model&apos;s own number. Clearing a
        pinned value unpins it.
      </p>
    </>
  );
}
