"use client";

import { useEffect, useState } from "react";

import { formatAgo, formatRemaining } from "@/lib/format";

/**
 * Readings that go stale while you look at them.
 *
 * A lot page is left open — that is the whole point of a page with a bid
 * chart on it — and both of these numbers are only true at the instant they
 * were rendered. A static "closes in 41m" is wrong a minute later and
 * dangerously wrong an hour later, which on a lot that takes its real bids
 * in the final minutes is exactly when it matters.
 *
 * The server's own rendering comes in as `initial`, so the first client
 * render reproduces it and hydration stays quiet; the interval takes over
 * from there.
 */
function useNow(periodMs: number): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), periodMs);
    return () => clearInterval(id);
  }, [periodMs]);
  return now;
}

/** Milliseconds until `iso`, or null if it is unusable. */
function msUntil(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : t - now;
}

function exact(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/**
 * A live countdown to a close time.
 *
 * Under an hour it counts seconds and turns red; under six it turns amber.
 * Those thresholds are the burst-sampling windows, so the colour on screen
 * matches how closely the pipeline is actually watching the lot.
 */
export function Countdown({
  endUtc,
  initial,
}: {
  endUtc: string | null | undefined;
  initial: string;
}) {
  // one tick a second inside the final hour, otherwise every half minute:
  // no point re-rendering 60 times to move a number that changes hourly
  const [period, setPeriod] = useState(30_000);
  const now = useNow(period);
  const ms = now == null ? null : msUntil(endUtc, now);

  useEffect(() => {
    if (ms == null) return;
    const want = ms > 0 && ms < 3_600_000 ? 1_000 : 30_000;
    setPeriod((p) => (p === want ? p : want));
  }, [ms]);

  if (!endUtc) return <span className="muted">—</span>;
  if (ms == null) return <span suppressHydrationWarning>{initial}</span>;

  const urgency = ms <= 0 ? "" : ms < 3_600_000 ? "neg" : ms < 21_600_000 ? "warn" : "";
  return (
    <time
      dateTime={endUtc}
      title={`Closes ${exact(endUtc)}`}
      className={urgency}
      suppressHydrationWarning
    >
      {formatRemaining(ms)}
    </time>
  );
}

/** How long ago something was observed, ticking as it ages. */
export function Ago({
  at,
  initial,
}: {
  at: string | null | undefined;
  initial: string;
}) {
  const now = useNow(30_000);
  if (!at) return <span className="muted">—</span>;
  const until = now == null ? null : msUntil(at, now);
  return (
    <time dateTime={at} title={exact(at)} suppressHydrationWarning>
      {until == null ? initial : formatAgo(Math.max(0, -until))}
    </time>
  );
}
