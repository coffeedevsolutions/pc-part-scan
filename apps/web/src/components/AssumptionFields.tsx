"use client";

import { type Config } from "@pcps/valuation";

import { MoneyField, PercentField } from "@/components/Fields";

/**
 * The assumption controls, in one place so the Board and the lot page
 * cannot offer different ones.
 *
 * They were only on the Board, which meant the page that shows you a max
 * bid was not the page where you could argue with it: you read a chain of
 * reasoning on the lot, then navigated away to change the number it turned
 * on, then navigated back. Worse, nothing said which of those numbers were
 * yours and which were shipped defaults — so `recovery = 55%`, a figure the
 * backtest says would have been outbid on 92% of closed pallets, read like
 * a measurement rather than an inherited guess.
 *
 * `isDefault` is what fixes the second part: every field that is still on
 * its shipped value says so.
 */
export function AssumptionFields({
  cfg,
  updateCfg,
  isDefault,
}: {
  cfg: Config;
  updateCfg: (patch: Partial<Config>) => void;
  isDefault: (key: keyof Config) => boolean;
}) {
  return (
    <>
      <PercentField
        label="Target ROI"
        help="targetRoi"
        value={cfg.target_roi}
        onChange={(v) => updateCfg({ target_roi: v })}
        step={5}
        isDefault={isDefault("target_roi")}
      />
      <PercentField
        label="Recovery"
        help="recovery"
        value={cfg.recovery}
        onChange={(v) => updateCfg({ recovery: v })}
        step={5}
        max={100}
        isDefault={isDefault("recovery")}
      />
      <PercentField
        label="Dead rate"
        help="deadRate"
        value={cfg.dead_rate}
        onChange={(v) => updateCfg({ dead_rate: v })}
        step={5}
        max={100}
        isDefault={isDefault("dead_rate")}
      />
      <PercentField
        label="Buyer premium"
        help="buyerPremium"
        value={cfg.buyer_premium}
        onChange={(v) => updateCfg({ buyer_premium: v })}
        step={0.5}
        isDefault={isDefault("buyer_premium")}
      />
      <PercentField
        label="Sales tax"
        help="salesTax"
        value={cfg.sales_tax}
        onChange={(v) => updateCfg({ sales_tax: v })}
        step={0.5}
        isDefault={isDefault("sales_tax")}
      />
      <MoneyField
        label="Handling / machine"
        help="handling"
        value={cfg.per_unit_handling}
        onChange={(v) => updateCfg({ per_unit_handling: v })}
        step={0.5}
        isDefault={isDefault("per_unit_handling")}
      />
      <MoneyField
        label="Handling / part"
        help="partHandling"
        value={cfg.part_handling ?? cfg.per_unit_handling}
        onChange={(v) => updateCfg({ part_handling: v })}
        step={0.5}
        isDefault={isDefault("part_handling")}
      />
      <MoneyField
        label="Pickup cost"
        help="pickup"
        value={cfg.pickup_cost}
        onChange={(v) => updateCfg({ pickup_cost: v })}
        step={25}
        isDefault={isDefault("pickup_cost")}
      />
    </>
  );
}
