/** English explanations for each strategy setting (shown via info icon). */
export const SETTINGS_HELP: Record<string, string> = {
  startTime:
    "Session open time (IST). The 09:15 candle close becomes the base price for calculating entry triggers.",
  endTime:
    "Session close time (IST). No new entries after this; open positions are squared off at auto square-off time.",
  entryGap:
    "Index points above/below base to trigger the first Call or Put entry. Larger value = fewer but stronger signals.",
  strikeOffset:
    "How far OTM the option strike is selected from current SENSEX level when placing orders.",
  stopDistance:
    "Index stop-loss distance from entry. If SENSEX moves against the position by this many points, the trade exits.",
  numEntries:
    "Maximum averaging entries allowed in one direction (initial + adds). Controls how many times the algo can scale in.",
  entryLots:
    "Lot size for each entry step. Entry 1 is the initial size; later entries use their own lot counts for averaging.",
  addGap:
    "Index points between averaging entries. Each add is placed when price moves this much further in your favour.",
  firstEntryTp1:
    "Take-profit 1 distance (index points) for the first/core entry. Partial exit happens when this level is hit.",
  target1Pts:
    "Take-profit 1 distance for averaging adds only. Averaging legs exit fully at this smaller target.",
  tp2Trail:
    "After core TP1, remaining lots trail the session extreme by this many index points for TP2 exit.",
  reEntryGap:
    "Pullback required (index points) after TP2 before the algo can re-enter in the same direction.",
  autoSquareOff:
    "Time (IST) to force-close all open positions before market end, regardless of targets.",
  tradeDirection:
    "Restrict which side the algo trades: both Call & Put, Call only, or Put only.",
  callEnabled: "Allow Call (bullish) entries when index breaks above the upper trigger.",
  putEnabled: "Allow Put (bearish) entries when index breaks below the lower trigger.",
  reEntryEnabled: "Allow a new cycle after TP2 trail exit when price pulls back by the re-entry gap.",
  firstEntryEnabled:
    "Enable the first entry of the day. Turn off to skip initial trigger and only allow re-entries.",
  maxReEntries: "Cap how many re-entry cycles per day. Set 0 for unlimited re-entries.",
};
