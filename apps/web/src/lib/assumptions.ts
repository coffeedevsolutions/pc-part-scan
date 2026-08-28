"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_CONFIG, type Config } from "@pcps/valuation";

import { saveAssumptions } from "@/lib/actions";

/**
 * The assumptions every page grades with, and how they persist.
 *
 * There is one set of these and it has to be the same everywhere: a max bid
 * that changes when you click from the board into the lot it belongs to is
 * not a number anyone can act on. That used to be exactly what happened —
 * the Board held the live copy in React state and the lot page read the
 * server copy, and a key the save action silently dropped could make the two
 * disagree with nothing on screen to explain it.
 *
 * So the state, the hydration and the write-back live here once, and both
 * pages call this. Adding a page that grades is now a matter of calling the
 * hook, not of reimplementing the storage rules.
 */

/**
 * Bumped from v1 when part_handling's default changed from $3 to $0.
 *
 * A v1 blob holds a full config snapshot written by a build where $3 was
 * the default, so it says `part_handling: 3` for everyone who ever touched
 * any slider — indistinguishably from someone who chose $3 on purpose.
 * Replaying one would push $3 back to the server as a deliberate setting
 * and return every charger pallet to a max bid of zero, with nothing on
 * screen to explain it. There is no way to tell the two apart after the
 * fact, so v1 blobs are simply not read: the cost is one device falling
 * back to current defaults, against silently undoing the change.
 *
 * Bump this again whenever a default changes meaning, for the same reason.
 */
export const STORAGE_KEY = "pcps.assumptions.v2";

const SAVE_DEBOUNCE_MS = 800;

export interface Assumptions {
  cfg: Config;
  updateCfg: (patch: Partial<Config>) => void;
  /**
   * Whether this setting is still the shipped default rather than something
   * the user chose. Compared by value, not by tracking edits: what a reader
   * needs to know is whether the number is inherited or decided, and a
   * setting deliberately left at the default is inherited either way.
   */
  isDefault: (key: keyof Config) => boolean;
  /** true once the user has moved anything in this session */
  touched: boolean;
  /** back to the shipped defaults, and persist that as a deliberate choice */
  reset: () => void;
}

export function useAssumptions(
  saved: Record<string, number>,
  hasServerSaved: boolean,
): Assumptions {
  const base: Config = { ...DEFAULT_CONFIG, ...saved };
  const [cfg, setCfg] = useState<Config>(base);
  const [touched, setTouched] = useState(false);
  const dirty = useRef(false); // only the user's own edits reach the server
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // the server copy is the durable cross-device one and wins; localStorage
    // only fills in when the server has nothing yet
    if (hasServerSaved) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw);
      setCfg((c) => ({ ...c, ...stored }));
      // ...and then send it on, because every other page reads the server
      // copy and nothing else. Without this the Board would grade a lot at
      // the rates on screen while its own detail page graded the same lot
      // at the defaults, with no visible reason for the two to disagree.
      //
      // Safe to treat as user-chosen only because STORAGE_KEY is versioned:
      // anything under this key was written by a build whose defaults match
      // the ones running now, so a value that differs from a default is a
      // value somebody set.
      saveAssumptions({ ...base, ...stored } as unknown as Record<string, number>)
        .catch(() => {});
    } catch {
      /* first visit / blocked storage: keep defaults */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!dirty.current) return; // hydration must never clobber the server
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
    } catch {
      /* storage unavailable: the sliders still work for this visit */
    }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveAssumptions(cfg as unknown as Record<string, number>).catch(() => {});
    }, SAVE_DEBOUNCE_MS);
  }, [cfg]);

  // Flush a pending save when the page is being left. The debounce exists so
  // dragging a slider does not write on every frame, but clicking through to
  // a lot within that window would otherwise land on a page still reading
  // the previous value.
  useEffect(() => {
    const flush = () => {
      if (!dirty.current || !saveTimer.current) return;
      clearTimeout(saveTimer.current);
      saveTimer.current = null;
      saveAssumptions(cfg as unknown as Record<string, number>).catch(() => {});
    };
    document.addEventListener("visibilitychange", flush);
    return () => document.removeEventListener("visibilitychange", flush);
  }, [cfg]);

  const updateCfg = useCallback((patch: Partial<Config>) => {
    dirty.current = true;
    setTouched(true);
    setCfg((c) => ({ ...c, ...patch }));
  }, []);

  const isDefault = useCallback(
    (key: keyof Config) => cfg[key] === DEFAULT_CONFIG[key],
    [cfg],
  );

  const reset = useCallback(() => {
    dirty.current = true;
    setTouched(true);
    setCfg({ ...DEFAULT_CONFIG });
  }, []);

  return { cfg, updateCfg, isDefault, touched, reset };
}
