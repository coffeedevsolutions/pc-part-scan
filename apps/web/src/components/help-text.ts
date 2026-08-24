/**
 * Every explanatory string in the app, in one place.
 *
 * Terms like "headroom" and "confidence" mean something specific here and
 * appear on several pages; keeping the wording in one registry stops the
 * same concept being explained three slightly different ways.
 */
export const HELP = {
  grade: "Overall verdict, from headroom discounted by how much we trust the estimate. A lot priced only from comps for its kind is capped at C; a lot whose contents we cannot read at all gets no grade — see \u201Cunrated\u201D.",
  itemClass: "What we think the lot holds, read from its title. A lot read as computers is priced from the parts inside it; a lot read as chargers, docks or monitors is priced from what sold lots of the same kind fetched. \u201Cunread\u201D means the title named several things at once, or nothing we recognise.",
  classComps: "Per-unit prices for kinds of thing the machine model has no features for. Both numbers come from sold GovDeals lots of that kind and nothing else: the pallet price is what a lot of them clears, the parts-out price is what one is worth sold alone, capped so the two cannot disagree by more than the bulk discount.",
  unrated: "Fewer than half this lot's units have a component we recognise, so its value would come from a generic per-unit rate — a number driven by how many things are on the pallet, not by what they are. Rather than publish that as a max bid we show nothing and rank the lot last.",
  confidence: "0-1. How much of this lot we can actually price: does it have a readable spec sheet, and do we recognise the parts inside? Low confidence means the value below is a guess from unit count alone.",
  maxBid: "The most you can pay and still clear your target return, after buyer premium, tax, pickup and per-unit handling. Not a prediction of the closing price.",
  headroom: "Max bid minus the current bid. What is left on the table right now. It shrinks as people bid.",
  currentBid: "The bid as of the last scan. Between scans this is stale, so treat it as a floor, not the live number.",
  units: "How many machines the lot contains, from the title or the spec sheet.",
  closes: "When the auction ends. Most lots take their real bids in the final hour.",
  floor: "What a pallet like this tends to clear at auction if you resold it whole, from the bulk-discount fit.",
  ceiling: "The lot's units priced one at a time, from what comparable single units fetched at GovDeals auction. Despite the name it is a wholesale number, not a retail parts-out one \u2014 across 2,351 closed pallets it predicted the whole lot's hammer price at a median of 0.77\u00d7.",
  expectedRevenue: "What we actually underwrite against: the parts-out value after dead units and your recovery rate.",
  roi: "Return you would clear if you won at the current bid, against your all-in cost.",
  targetRoi: "The return you require. Higher target means lower max bid.",
  recovery: "What you get per unit through your own channel, as a multiple of what that unit fetches at GovDeals auction \u2014 which is what the ceiling above measures. 100% means you resell at GovDeals rates; 200% means you get double, roughly what parting out on eBay is for. The default of 55% predates that reading and would have been outbid on 92% of closed pallets; see Models \u2192 Backtest.",
  deadRate: "Share of units you assume arrive non-functional.",
  buyerPremium: "The seller's buyer premium, added on top of the hammer price.",
  salesTax: "Sales tax, if you are not tax-exempt.",
  handling: "Your cost to test, wipe, photograph and pack each unit.",
  pickup: "Flat travel or freight cost for the whole lot.",
  singleR2: "How well the per-machine price model fits sold single-unit lots. 1.0 is perfect; below about 0.5 the estimate is weak.",
  bulkK: "The share of parts-out value a whole pallet actually clears at auction. Drives the floor.",
  bulkN: "How many sold lots with a readable spec sheet the bulk fit is based on. Small numbers mean an unreliable floor.",
  cpuBaseValue: "What the model thinks one machine with this CPU is worth, before RAM and drive adjustments. Pin a value to override it.",
  ranking: "Lots are ordered by headroom multiplied by confidence, so a large number we do not believe does not outrank a smaller one we do. Click any column header to sort by that column instead.",
  backtest: "Every closed lot re-graded as if it were live, with its own outcome held out of the models that priced it. It is the only number here that can tell you a max bid was wrong \u2014 everything else describes the data it was fitted on.",
  jobRuns: "Every scheduled scan, burst and archive, with what it wrote. The pipeline's heartbeat.",
  floorCeiling: "The range this lot's value sits in: flipping the whole pallet at auction on the left, selling every unit individually on the right. What you actually underwrite against is somewhere between them.",
  identifiedUnits: "How many of the lot's units have a component we recognise. Below half, we do not publish a price for the lot at all.",
  bidHistory: "Every bid we have observed, from the hourly scan plus a tighter burst in the final hours. Flat stretches are real: most lots take their bids at the very end.",
  machineMix: "What we believe is in the lot, from the seller's spec sheet if it has a readable one and from the title if it does not. This is what the parts-out value is computed from, so a wrong row here is a wrong price.",
  hammer: "What the lot actually closed at, excluding buyer premium. This is the number the models are fitted on.",
  soldClosed: "When the auction ended. Recent comps are better comps — hardware prices drift.",
  datasetCounts: "How much the pipeline has accumulated. The models get better as sold lots and readable spec sheets pile up.",
} as const;

export type HelpKey = keyof typeof HELP;
