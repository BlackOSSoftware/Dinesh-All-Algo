/** Simple English help for settings (hover the i icon). */
export const SETTINGS_HELP: Record<string, string> = {
  startTime: "Time when the first 10-minute trade window starts (e.g. 14:35).",
  windowCount: "How many trade chances in one day. Each window uses one 10-minute candle.",
  windowGapMinutes: "Minutes between windows. Usually 10 (next window starts 10 min later).",
  candleTimeframeMinutes: "Candle size is fixed at 10 minutes for this strategy.",
  targetPercent: "Take profit in %. Example: 20 means exit when option price rises 20%.",
  stopLossPercent: "Stop loss in %. Example: 10 means exit when option price falls 10%.",
  quantity: "How many lots to buy in each trade.",
  productType: "MIS = close same day. NRML = can carry to next day.",
  expiryDayOnly: "If ON, algo runs only on SENSEX weekly expiry day.",
  premiumTier: "If option premium is in this range, entry % tells how much above premium close to place buy order.",
  entryPercent: "Buy order is placed at premium close plus this percent. Example: 5% on ₹100 = buy at ₹105.",
};
