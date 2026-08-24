"use server";

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { getDb } from "./mongo";

async function requireUser(): Promise<void> {
  if (process.env.AUTH_DISABLED === "1") return;
  const session = await auth();
  if (!session?.user) throw new Error("not signed in");
}

function now(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

const KEY_RE = /^\d+-\d+$/;

export async function setWatch(key: string, want: boolean): Promise<boolean> {
  await requireUser();
  if (!KEY_RE.test(key)) throw new Error("bad key");
  const c = getDb().collection<{ _id: string }>("watchlist");
  if (want) {
    // atomic and idempotent: concurrent clicks can't duplicate-key crash
    await c.updateOne(
      { _id: key },
      { $setOnInsert: { added_at: now() } },
      { upsert: true },
    );
  } else {
    await c.deleteOne({ _id: key });
  }
  revalidatePath("/");
  revalidatePath(`/lot/${key}`);
  return want;
}

export async function saveNote(key: string, text: string): Promise<void> {
  await requireUser();
  if (!KEY_RE.test(key)) throw new Error("bad key");
  const c = getDb().collection<{ _id: string }>("notes");
  const trimmed = text.slice(0, 20_000);
  if (trimmed.trim() === "") {
    await c.deleteOne({ _id: key });
  } else {
    await c.replaceOne(
      { _id: key },
      { _id: key, text: trimmed, updated_at: now() } as never,
      { upsert: true },
    );
  }
  revalidatePath(`/lot/${key}`);
}

const ACTIONS = new Set(["watching", "bid", "won", "lost", "passed"]);

const MAX_MONEY = 1_000_000;

function cleanMoney(value: number | null): number | null {
  if (value == null) return null;
  if (!Number.isFinite(value) || value < 0 || value > MAX_MONEY) {
    throw new Error("bad amount");
  }
  return Math.round(value * 100) / 100;
}

export async function setLotAction(
  key: string,
  action: string,
  amount: number | null,
): Promise<void> {
  await requireUser();
  if (!KEY_RE.test(key)) throw new Error("bad key");
  const c = getDb().collection<{ _id: string }>("lot_actions");
  if (action === "none") {
    await c.deleteOne({ _id: key });
  } else {
    if (!ACTIONS.has(action)) throw new Error("bad action");
    await c.replaceOne(
      { _id: key },
      { _id: key, action, amount: cleanMoney(amount), at: now() } as never,
      { upsert: true },
    );
  }
  revalidatePath(`/lot/${key}`);
  revalidatePath("/");
}

export async function saveComponentPrice(
  cpu: string,
  value: number | null,
): Promise<void> {
  await requireUser();
  const id = cpu.trim().toLowerCase();
  if (!/^[a-z0-9_][a-z0-9._-]{0,39}$/.test(id)) throw new Error("bad cpu key");
  const c = getDb().collection<{ _id: string }>("component_prices");
  if (value == null) {
    await c.deleteOne({ _id: id });
  } else {
    if (!Number.isFinite(value) || value < 0 || value > MAX_MONEY) {
      throw new Error("bad price");
    }
    await c.replaceOne(
      { _id: id },
      {
        _id: id,
        value_usd: value,
        source: "user",
        note: "pinned from workbench",
        updated_at: now(),
      } as never,
      { upsert: true },
    );
  }
  revalidatePath("/models");
}

export async function saveAssumptions(
  cfg: Record<string, number>,
): Promise<void> {
  await requireUser();
  const clean: Record<string, number> = {};
  for (const k of [
    "buyer_premium",
    "sales_tax",
    "pickup_cost",
    "per_unit_handling",
    "recovery",
    "dead_rate",
    "target_roi",
  ]) {
    const v = cfg[k];
    if (typeof v === "number" && Number.isFinite(v) && v >= 0) clean[k] = v;
  }
  await getDb()
    .collection<{ _id: string }>("settings")
    .replaceOne(
      { _id: "assumptions" },
      { _id: "assumptions", ...clean, updated_at: now() } as never,
      { upsert: true },
    );
}
