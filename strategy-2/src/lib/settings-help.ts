/** Simple English help for settings (hover the i icon). */
export const SETTINGS_HELP: Record<string, string> = {
  startTime: "What time the algo starts watching the market each day.",
  endTime: "What time the algo stops taking new trades. MCX market close time.",
  market: "Which commodity to trade: Crude Oil, Natural Gas, or Silver Micro.",
  referencePrice: "The middle price where your grid is built. Buy and sell levels are placed above and below this.",
  initialLots: "How many lots you hold when the grid starts.",
  gridGap: "Points between each grid line. Example: gap 2 means levels at +2, +4, +6 points.",
  gridLevelsAbove: "How many sell/buy levels to place above the reference price.",
  gridLevelsBelow: "How many buy/sell levels to place below the reference price.",
  lotsPerGrid: "How many lots to add or remove when price hits each grid level.",
  invertGrid: "Flip buy and sell rules. Use only if you want opposite grid behaviour.",
};
