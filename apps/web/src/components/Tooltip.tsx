"use client";

import { useCallback, useId, useLayoutEffect, useRef, useState } from "react";

import { HELP, type HelpKey } from "./help-text";

const WIDTH = 280;
const MARGIN = 8;

/**
 * Accessible explanation bubble. Opens on hover and on keyboard focus, and
 * the trigger is a real button so it is reachable without a mouse.
 *
 * The bubble is positioned fixed from the trigger's measured rect rather
 * than absolutely inside it: these icons sit in table headers, and a
 * horizontally scrollable table clips anything positioned within it, which
 * silently cut off the explanation on the rightmost columns.
 */
export function HelpIcon({ k, label }: { k: HelpKey; label?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const id = useId();

  const place = useCallback(() => {
    const el = btn.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const half = WIDTH / 2;
    // keep the bubble inside the viewport on both sides
    const left = Math.min(
      Math.max(r.left + r.width / 2 - half, MARGIN),
      window.innerWidth - WIDTH - MARGIN,
    );
    setPos({ top: r.bottom + 8, left });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const close = () => setOpen(false);
    // any scroll would detach a fixed bubble from its trigger
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open, place]);

  return (
    <span className="helpwrap">
      <button
        ref={btn}
        type="button"
        className="helpicon"
        aria-label={label ? `What is ${label}?` : "Explain this"}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          e.preventDefault();
          setOpen((v) => !v);
        }}
      >
        ?
      </button>
      {open && pos && (
        <span
          role="tooltip"
          id={id}
          className="helpbubble"
          style={{ top: pos.top, left: pos.left, width: WIDTH }}
        >
          {HELP[k]}
        </span>
      )}
    </span>
  );
}
