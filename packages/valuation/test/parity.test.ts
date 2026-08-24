import { describe, expect, it } from "vitest";

import { CONFIDENCE_GATE, regrade, type Config, type LotFacts } from "../src/index";
import golden from "./fixtures/valuation-golden.json";

interface GoldenCase {
  config: Config;
  expected: Record<
    string,
    {
      expected_revenue: number;
      max_bid: number;
      headroom: number;
      roi_at_current: number;
      grade: string;
      handling_applied: number;
      handling_breakeven: number;
    }
  >;
}

interface GoldenLot extends LotFacts {
  lot_key: string;
}

const lots = golden.lots as GoldenLot[];
const cases = golden.cases as GoldenCase[];

// The fixture stores Python-rounded values (2dp money, 6dp ratios); compare
// the unrounded TS output within half a rounding step plus float slack.
const MONEY_TOL = 0.005 + 1e-6;
const RATIO_TOL = 5e-7 + 1e-9;

describe("parity with the Python grader", () => {
  it("uses the same confidence gate", () => {
    expect(golden.confidence_gate).toBe(CONFIDENCE_GATE);
  });

  for (const [i, c] of cases.entries()) {
    it(`case ${i}: ${JSON.stringify(c.config)}`, () => {
      for (const lot of lots) {
        const want = c.expected[lot.lot_key];
        expect(want, lot.lot_key).toBeDefined();
        const got = regrade(lot, c.config);
        expect(
          Math.abs(got.expected_revenue - want!.expected_revenue),
          `${lot.lot_key} expected_revenue`,
        ).toBeLessThanOrEqual(MONEY_TOL);
        expect(
          Math.abs(got.max_bid - want!.max_bid),
          `${lot.lot_key} max_bid`,
        ).toBeLessThanOrEqual(MONEY_TOL);
        expect(
          Math.abs(got.headroom - want!.headroom),
          `${lot.lot_key} headroom`,
        ).toBeLessThanOrEqual(MONEY_TOL);
        expect(
          Math.abs(got.roi_at_current - want!.roi_at_current),
          `${lot.lot_key} roi_at_current`,
        ).toBeLessThanOrEqual(RATIO_TOL);
        expect(got.grade, `${lot.lot_key} grade`).toBe(want!.grade);
        expect(
          Math.abs(got.handling_applied - want!.handling_applied),
          `${lot.lot_key} handling_applied`,
        ).toBeLessThanOrEqual(MONEY_TOL);
        expect(
          Math.abs(got.handling_breakeven - want!.handling_breakeven),
          `${lot.lot_key} handling_breakeven`,
        ).toBeLessThanOrEqual(MONEY_TOL);
      }
    });
  }
});
