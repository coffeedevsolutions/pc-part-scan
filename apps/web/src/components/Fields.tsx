"use client";

import { HelpIcon } from "./Tooltip";
import type { HelpKey } from "./help-text";

/**
 * A rate shown the way people say it (60%) while the model keeps the
 * fraction it actually computes with (0.60). Typing "60" must never be
 * read as 6000%.
 */
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
          value={Math.round(value * 1000) / 10}
          onChange={(e) => {
            const pct = Number(e.target.value);
            onChange(Number.isFinite(pct) ? Math.max(0, pct) / 100 : 0);
          }}
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
