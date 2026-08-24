"use client";

import { useState } from "react";

import { saveComponentPrice } from "@/lib/actions";
import { usd } from "@/lib/format";

interface Row {
  cpu: string;
  fitted: number | null;
  pinned: number | null;
  note: string;
}

/**
 * Pinned prices override the fitted estimate in the pipeline's valuation
 * blend. Editing a cell saves on blur; clearing it removes the pin.
 */
export function PriceEditor({ rows: initial }: { rows: Row[] }) {
  const [rows, setRows] = useState(initial);
  const [newCpu, setNewCpu] = useState("");
  const [status, setStatus] = useState("");

  async function save(cpu: string, raw: string) {
    const value = raw.trim() === "" ? null : Number(raw);
    if (value != null && (!Number.isFinite(value) || value < 0)) return;
    setStatus("saving…");
    try {
      await saveComponentPrice(cpu, value);
      setRows((rs) =>
        rs.map((r) => (r.cpu === cpu ? { ...r, pinned: value } : r)),
      );
      setStatus(`saved ${cpu}`);
    } catch (e) {
      setStatus(`failed to save ${cpu}: ${e instanceof Error ? e.message : "error"}`);
    }
  }

  function addRow() {
    const cpu = newCpu.trim().toLowerCase();
    if (!cpu || rows.some((r) => r.cpu === cpu)) return;
    setRows((rs) => [{ cpu, fitted: null, pinned: null, note: "" }, ...rs]);
    setNewCpu("");
  }

  return (
    <>
      <div className="filters">
        <label>
          Pin a CPU not in the fit
          <input
            type="text"
            placeholder="i5-8500t"
            value={newCpu}
            onChange={(e) => setNewCpu(e.target.value)}
            style={{ width: 120 }}
          />
        </label>
        <button type="button" onClick={addRow}>
          Add
        </button>
        <span className="muted small">{status}</span>
      </div>
      <div style={{ maxHeight: 460, overflowY: "auto" }}>
        <table className="data" style={{ maxWidth: 640 }}>
          <thead>
            <tr>
              <th>CPU</th>
              <th className="num">Fitted</th>
              <th className="num">Pinned override</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cpu}>
                <td>{r.cpu}</td>
                <td className="num muted">{r.fitted != null ? usd(r.fitted) : "—"}</td>
                <td className="num">
                  <input
                    className="priceedit"
                    type="number"
                    min={0}
                    step={1}
                    defaultValue={r.pinned ?? ""}
                    placeholder="—"
                    onBlur={(e) => {
                      const raw = e.target.value;
                      const prev = r.pinned == null ? "" : String(r.pinned);
                      if (raw !== prev) save(r.cpu, raw);
                    }}
                  />
                </td>
                <td className="muted small">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        A pinned value replaces the fitted estimate in the next scan&apos;s
        valuation blend. Clear a cell to unpin.
      </p>
    </>
  );
}
