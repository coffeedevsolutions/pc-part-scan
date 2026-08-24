/**
 * Every explanatory string in the app, in one place.
 *
 * Terms like "headroom" and "confidence" mean something specific here and
 * appear on several pages; keeping the wording in one registry stops the
 * same concept being explained three slightly different ways.
 */
export const HELP = {
  grade: "Overall verdict, from headroom discounted by how much we trust the estimate. A lot we cannot identify is capped at C no matter how good the numbers look.",
  confidence: "0-1. How much of this lot we can actually price: does it have a readable spec sheet, and do we recognise the parts inside? Low confidence means the value below is a guess from unit count alone.",
  maxBid: "The most you can pay and still clear your target return, after buyer premium, tax, pickup and per-unit handling. Not a prediction of the closing price.",
  headroom: "Max bid minus the current bid. What is left on the table right now. It shrinks as people bid.",
  currentBid: "The bid as of the last scan. Between scans this is stale, so treat it as a floor, not the live number.",
  units: "How many machines the lot contains, from the title or the spec sheet.",
  closes: "When the auction ends. Most lots take their real bids in the final hour.",
  floor: "What a pallet like this tends to clear at auction if you resold it whole, from the bulk-discount fit.",
  ceiling: "What the parts inside are worth sold individually, before any allowance for dead units, fees or your time.",
  expectedRevenue: "What we actually underwrite against: the parts-out value after dead units and your recovery rate.",
  roi: "Return you would clear if you won at the current bid, against your all-in cost.",
  targetRoi: "The return you require. Higher target means lower max bid.",
  recovery: "The share of parts-out value you expect to actually realise after listing fees, returns and your time.",
  deadRate: "Share of units you assume arrive non-functional.",
  buyerPremium: "The seller's buyer premium, added on top of the hammer price.",
  salesTax: "Sales tax, if you are not tax-exempt.",
  handling: "Your cost to test, wipe, photograph and pack each unit.",
  pickup: "Flat travel or freight cost for the whole lot.",
  singleR2: "How well the per-machine price model fits sold single-unit lots. 1.0 is perfect; below about 0.5 the estimate is weak.",
  bulkK: "The share of parts-out value a whole pallet actually clears at auction. Drives the floor.",
  bulkN: "How many sold lots with a readable spec sheet the bulk fit is based on. Small numbers mean an unreliable floor.",
  cpuBaseValue: "What the model thinks one machine with this CPU is worth, before RAM and drive adjustments. Pin a value to override it.",
  jobRuns: "Every scheduled scan, burst and archive, with what it wrote. The pipeline's heartbeat.",
} as const;

export type HelpKey = keyof typeof HELP;
