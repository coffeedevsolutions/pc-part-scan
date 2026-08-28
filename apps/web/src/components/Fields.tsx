"use client";

import { useEffect, useState } from "react";

import { UNRATED } from "@pcps/valuation";

import { HelpIcon } from "./Tooltip";
import type { HelpKey } from "./help-text";

/**
 * A rate shown the way people say it (60%) while the model keeps the
 * fraction it actually computes with (0.60). Typing "60" must never be
 * read as 6000%.
 */
/**
 * Marks a field still sitting on its shipped default.
 *
 * Without it the panel presents an inherited guess and a considered choice
 * in identical type. That is not a cosmetic problem here: `recovery`
 * defaults to 55%, a figure the backtest says would have been outbid on
 * 92% of closed pallets, and it drives the largest number on every page.
 */
function DefaultTag() {
  return (
    <span className="defaulttag" title="Still the shipped default — not a value you chose">
      default
    </span>
  );
}

/** 0.1275 -> "12.75", trimming trailing zeros. */
function fromFraction(v: number): string {
  return String(Math.round(v * 10000) / 100);
}

export function PercentField({
  label,
  value,
  onChange,
  help,
  step = 1,
  max = 500,
  isDefault = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  help?: HelpKey;
  step?: number;
  max?: number;
  isDefault?: boolean;
}) {
  const [text, setText] = useState(() => fromFraction(value));
  // follow the value when it changes from elsewhere (Reset, a server load)
  useEffect(() => {
    setText((t) => (Number(t) / 100 === value ? t : fromFraction(value)));
  }, [value]);
  return (
    <label className="field">
      <span className="fieldlabel">
        {label}
        {help && <HelpIcon k={help} label={label} />}
        {isDefault && <DefaultTag />}
      </span>
      <span className="inputwrap">
        <input
          type="number"
          inputMode="decimal"
          min={0}
          max={max}
          step={step}
          value={text}
          onChange={(e) => {
            // keep exactly what was typed on screen -- re-deriving it from
            // the rounded fraction snapped the text under the cursor -- and
            // store at the same precision the field displays, so the value
            // shown is the value the grades are computed from
            const raw = e.target.value;
            setText(raw);
            const pct = Number(raw);
            onChange(
              Number.isFinite(pct) ? Math.round(Math.max(0, pct) * 100) / 10000 : 0,
            );
          }}
          onBlur={() => setText(fromFraction(value))}
        />
        <span className="suffix">%</span>
      </span>
    </label>
  );
}

export function MoneyField({
  label,
  value,
  onChange,
  help,
  step = 1,
  isDefault = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  help?: HelpKey;
  step?: number;
  isDefault?: boolean;
}) {
  return (
    <label className="field">
      <span className="fieldlabel">
        {label}
        {help && <HelpIcon k={help} label={label} />}
        {isDefault && <DefaultTag />}
      </span>
      <span className="inputwrap">
        <span className="prefix">$</span>
        <input
          type="number"
          inputMode="decimal"
          min={0}
          step={step}
          value={value}
          onChange={(e) => {
            const v = Number(e.target.value);
            onChange(Number.isFinite(v) ? Math.max(0, v) : 0);
          }}
        />
      </span>
    </label>
  );
}

/**
 * The grade chip. "U" is not a letter grade but an abstention, so it says
 * so in words — a chip reading "U" next to four blank money columns looks
 * like a bug rather than a deliberate refusal to guess.
 */
export function Grade({ grade }: { grade: string }) {
  const unrated = grade === UNRATED;
  return (
    <span
      className={`grade grade-${grade}`}
      title={unrated ? "Unrated — we cannot tell what is in this lot" : `Grade ${grade}`}
    >
      {unrated ? "unrated" : grade}
    </span>
  );
}
