"use client";

import { useEffect, useState } from "react";

import { HelpIcon } from "./Tooltip";
import type { HelpKey } from "./help-text";

/**
 * A rate shown the way people say it (60%) while the model keeps the
 * fraction it actually computes with (0.60). Typing "60" must never be
 * read as 6000%.
 */
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
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  help?: HelpKey;
  step?: number;
  max?: number;
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
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  help?: HelpKey;
  step?: number;
}) {
  return (
    <label className="field">
      <span className="fieldlabel">
        {label}
        {help && <HelpIcon k={help} label={label} />}
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

export function Grade({ grade }: { grade: string }) {
  return (
    <span className={`grade grade-${grade}`} title={`Grade ${grade}`}>
      {grade}
    </span>
  );
}
