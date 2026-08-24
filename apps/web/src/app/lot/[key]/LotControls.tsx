"use client";

import { useRef, useState } from "react";

import { saveNote, setLotAction, setWatch } from "@/lib/actions";

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

  const noteRef = useRef(note);
  noteRef.current = note;

  async function onWatch() {
    const want = !watched;
    setWatched(want);
    try {
      await setWatch(lotKey, want);
    } catch {
      setWatched(!want);
    }
  }

  async function onSaveNote() {
    const sending = noteRef.current;
    setNoteState("saving");
    try {
      await saveNote(lotKey, sending);
      // edits made while the save was in flight must stay saveable
      setNoteState(noteRef.current === sending ? "saved" : "dirty");
    } catch {
      setNoteState("dirty");
    }
  }

  async function persistAction(value: string, amt: string) {
    try {
      await setLotAction(lotKey, value, amt.trim() === "" ? null : Number(amt));
      return true;
    } catch {
      return false;
    }
  }

  /** Toggle a button: clicking the active action clears it. */
  async function onAction(next: string) {
    const prev = action;
    const value = next === prev ? "none" : next;
    setAction(value);
    if (!(await persistAction(value, amount))) setAction(prev);
  }

  /** Re-save the current action with the amount — never toggles. */
  async function onAmountBlur() {
    if (action !== "none") await persistAction(action, amount);
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
          min={0}
          placeholder="amount $"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onBlur={onAmountBlur}
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
