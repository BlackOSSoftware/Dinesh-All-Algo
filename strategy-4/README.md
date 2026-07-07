# Strategy 4 — Indian Algo

Next.js frontend at repo root + Python FastAPI in `backend/`.

## Run

**Terminal 1 — Backend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-4"
npm run worker
```

**Terminal 2 — Frontend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-4"
npm run dev
```

Open **http://localhost:3003**

**Login:** `admin` / `admin`

Or double-click `Start Trader.cmd`.

## Ports

| Service | Port |
|---------|------|
| Next.js | 3003 |
| FastAPI | 8003 |

> Strategy 1: 3000/8000 · Strategy 2: 3001/8001 · Strategy 3: 3002/8002 · Strategy 4: 3003/8003

## Environment

- `backend/.env` — Angel One + JWT (copied from Strategy 2; CORS uses port 3003)
- `.env.local` — `BACKEND_PROXY_URL=http://127.0.0.1:8003`

Admin user is created/updated on every API startup with password `admin`.
