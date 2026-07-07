# Strategy 3 — Indian Algo

Next.js frontend + Python FastAPI (auth only). Strategy logic not included yet.

## Run

**Terminal 1 — Backend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-3"
npm run worker
```

**Terminal 2 — Frontend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-3"
npm run dev
```

Open **http://localhost:3002**

**Login:** `admin` / `admin`

Or double-click `Start Trader.cmd`.

## Ports

| Service | Port |
|---------|------|
| Next.js | 3002 |
| FastAPI | 8002 |

## Pages

- Dashboard (`/`)
- Strategy Settings (`/strategy-settings`)
- Backtest (`/backtest`)

UI matches Strategy 2 design. Trading/backtest logic will be added later.
