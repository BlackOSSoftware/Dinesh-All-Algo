/** Simple English help for settings (hover the i icon). */
export const SETTINGS_HELP: Record<string, string> = {
  market: "Which MCX commodity to trade: Crude Oil, Natural Gas, or Silver Micro.",
  startTime: "Time of the 1-minute candle used as reference price each day.",
  endTime: "Algo stops taking new trades after this time.",
  lotSize: "How many lots per trade.",
  breakoutDistance: "Points above or below reference price to trigger buy or sell.",
  takeProfit: "Exit when price moves this many points in your profit direction.",
  stopLoss: "Exit when price moves this many points against you.",
};
