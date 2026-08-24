import type { ReactNode } from "react";

import { HelpIcon } from "./Tooltip";
import type { HelpKey } from "./help-text";

/**
 * One number in a hero row.
 *
 * The hero cards were the only place in the app where a term appeared with
 * nothing to explain it — "Headroom vs current" is the number people act
 * on, and it was the one number with no way to ask what it meant. Routing
 * them through a component makes the help icon part of the card rather than
 * something each page has to remember.
 */
export function Stat({
  label,
  help,
  helpLabel,
  sub,
  valueClass,
  small,
  children,
}: {
  label: ReactNode;
  help?: HelpKey;
  /** what the tooltip's screen-reader label calls this, if not `label` */
  helpLabel?: string;
  /** a caption under the value: provenance, freshness, a caveat */
  sub?: ReactNode;
  valueClass?: string;
  /** for values that are text rather than one figure */
  small?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="label">
        {label}
        {help && (
          <HelpIcon
            k={help}
            label={helpLabel ?? (typeof label === "string" ? label : undefined)}
          />
        )}
      </div>
      <div
        className={`value${valueClass ? ` ${valueClass}` : ""}`}
        style={small ? { fontSize: 17 } : undefined}
      >
        {children}
      </div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}
