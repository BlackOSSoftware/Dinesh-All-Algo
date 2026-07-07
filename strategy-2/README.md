# Strategy 2 — Indian Algo

Next.js frontend at repo root + Python FastAPI in `backend/`.

## Run

**Terminal 1 — Backend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-2"
npm run worker
```

**Terminal 2 — Frontend**
```powershell
cd "d:\BlackOS\dinesh algo\strategy-2"
npm run dev
```

Open **http://localhost:3001**

**Login:** `admin` / `admin`

Or double-click `Start Trader.cmd`.

## Ports

| Service | Port |
|---------|------|
| Next.js | 3001 |
| FastAPI | 8001 |

> Strategy 1 uses 3000 / 8000. Run both strategies side-by-side without port conflicts.

## Environment

- `backend/.env` — Angel One + JWT (same as Strategy 1)
- `.env.local` — `BACKEND_PROXY_URL=http://127.0.0.1:8001`

Admin user is created/updated on every API startup with password `admin`.
