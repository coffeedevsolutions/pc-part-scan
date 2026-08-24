"use client";

import { useState } from "react";

import { saveNote, setLotAction, toggleWatch } from "@/lib/actions";

export function LotControls({
  lotKey,
  watched: watchedInit,
  note: noteInit,
  action: actionInit,
}: {
  lotKey: string;
  watched: boolean;
  note: string;
  action: { action: string; amount: number | null } | null;
}) {
  const [watched, setWatched] = useState(watchedInit);
  const [note, setNote] = useState(noteInit);
  const [noteState, setNoteState] = useState<"saved" | "dirty" | "saving">(
    "saved",
  );
  const [action, setAction] = useState(actionInit?.action ?? "none");
  const [amount, setAmount] = useState<string>(
    actionInit?.amount != null ? String(actionInit.amount) : "",
  );

  async function onWatch() {
    setWatched(!watched);
    try {
      await toggleWatch(lotKey);
    } catch {
      setWatched(watched);
    }
  }

  async function onSaveNote() {
    setNoteState("saving");
    try {
      await saveNote(lotKey, note);
      setNoteState("saved");
    } catch {
      setNoteState("dirty");
    }
  }

  async function onAction(next: string) {
    const value = next === action ? "none" : next;
    setAction(value);
    try {
      await setLotAction(
        lotKey,
        value,
        amount.trim() === "" ? null : Number(amount),
      );
    } catch {
      setAction(action);
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>
        Your workbench{" "}
        <button
          type="button"
          className="watchstar"
          aria-pressed={watched}
          onClick={onWatch}
          title={watched ? "Unwatch" : "Watch"}
        >
          {watched ? "★ watching" : "☆ watch"}
        </button>
      </h2>
      <div className="actionbtns" style={{ marginBottom: 10 }}>
        {["bid", "won", "lost", "passed"].map((a) => (
          <button
            key={a}
            type="button"
            aria-pressed={action === a}
            onClick={() => onAction(a)}
          >
            {a}
          </button>
        ))}
        <input
          className="priceedit"
          type="number"
          placeholder="amount $"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onBlur={() => action !== "none" && onAction(action)}
        />
      </div>
      <textarea
        className="notes"
        placeholder="Notes — pickup logistics, spec-sheet oddities, comps you checked…"
        value={note}
        onChange={(e) => {
          setNote(e.target.value);
          setNoteState("dirty");
        }}
      />
      <div className="filters" style={{ marginTop: 8 }}>
        <button type="button" onClick={onSaveNote} disabled={noteState !== "dirty"}>
          {noteState === "saving" ? "Saving…" : "Save note"}
        </button>
        <span className="muted small">
          {noteState === "saved" ? "saved" : noteState === "dirty" ? "unsaved changes" : ""}
        </span>
      </div>
    </div>
  );
}
