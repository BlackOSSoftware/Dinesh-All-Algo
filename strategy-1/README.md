# Indian Algo

Layout aligned with [BlackOSSoftware/Abhisek-Algo](https://github.com/BlackOSSoftware/Abhisek-Algo): **Next.js at repo root**, `src/`, `public/`, `scripts/`, `data/`, and two npm entrypoints from the root folder.

| Path | Role |
|------|------|
| `src/app/` | Pages: `/`, `/strategy`, `/settings`, `/risk` + `api/*` routes |
| `src/components/trader/` | Dashboard UI shell, auth gate, cards |
| `src/server/` | Next.js server helpers + API proxy to FastAPI |
| `src/worker/live-runner.ts` | `npm run worker` → Python FastAPI engine |
| `public/` | Static assets |
| `scripts/` | `start-local.ps1`, `maintenance.ts`, helpers |
| `data/` | `trader.sql` reference schema |
| `backend/` | Python FastAPI + trading engine (unchanged logic) |
| `mysql/init/` | Docker-first MySQL init scripts |

## Login (default)

After the API has started once, sign in with:

- **Username:** `admin`  
- **Password:** `admin`  

The first startup creates this user (password stored as a bcrypt hash). New users: `POST http://127.0.0.1:8000/auth/register` with JSON `{"username","password"}`.

## Database

By default the API uses **SQLite** at `backend/instance/app.db` (no Docker). Omit `DATABASE_URL` in `backend/.env`, or copy `backend/.env.example` as-is. For **MySQL**, uncomment `DATABASE_URL` there, set the `mysql+pymysql://...` line, and run `docker compose up -d`.

Tables `strategy_settings`, `trade_positions`, and `trading_logs` are created automatically on API startup. See `backend/TRADING_ENGINE.md` for the execution layer, LIVE BFO mapping, and persistence details.

## Prerequisites

- Node.js 20+
- Python 3.11+
- Docker Desktop (optional — only if you use MySQL)

## Root commands (two terminals)

**1) Frontend**

```powershell
cd "d:\BlackOS\dinesh algo"
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000` — login gate, then dashboard at `/`.

**2) Engine (Python API)**

```powershell
cd "d:\BlackOS\dinesh algo\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

From **repo root** (second terminal):

```powershell
cd "d:\BlackOS\dinesh algo"
npm run worker
```

`npm run worker` runs `tsx src/worker/live-runner.ts` → `uvicorn` on port **8000**.

**One-click (Windows):** double-click `Start Trader.cmd` to launch dev + worker together.

## MySQL (optional)

If `backend/.env` sets `DATABASE_URL` to MySQL, start the DB first:

```powershell
docker compose up -d
```

Defaults: host `127.0.0.1`, port `3306`, DB `indian_algo`, user `root`, password `rootsecret` (see `backend/.env.example`).

## API quick reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | `{ "username", "password" }` |
| `POST` | `/auth/login` | `{ "username", "password" }` → JWT |
| `GET` | `/users/me` | `Authorization: Bearer <token>` |
| `POST` | `/users/me/change-password` | JSON `{ "old_password", "new_password" }` (Bearer required) |
| `GET` | `/trading/settings` | Load persisted dashboard + `algo_running` + `trading_mode` |
| `PUT` | `/trading/settings` | Body `{ "config", "algo_running", "trading_mode" }` (partial OK) |
| `GET` | `/trading/logs` | Trading log rows (newest first) |
| `GET` | `/trading/positions/active` | Open positions + live PnL proxy |
| `GET` | `/trading/positions/completed` | Closed trades |
| `POST` | `/trading/legs/{leg_id}/close` | Manual close (leg id `SOB` for the SENSEX option-buy strategy) |
| `POST` | `/trading/order/cancel` | Angel cancel (Bearer) |
| `POST` | `/trading/order/modify` | Angel modify |
| `GET` | `/trading/order/status` | Query `order_id` in order book |
| `GET` | `/angel/live-quote` | Angel One live quote (LTP/OHLC/FULL); Bearer + `ANGEL_*` in `backend/.env` |
| `GET` | `/angel/start-bar-close?start=09:15` | First 1m candle at `start` (IST today) for primary `ANGEL_EXCHANGE_TOKENS` instrument |
| `POST` | `/angel/refresh-session` | **Admin only.** Runs `scripts/angel_smartapi_login.py` with the backend venv, updates `ANGEL_JWT_TOKEN` in `.env` and in-memory settings. |

**Automatic Angel login:** the API schedules `angel_smartapi_login.py` daily at **00:30** server time (see `backend/docs/ANGEL_AUTO_LOGIN.md`).

Refresh **`ANGEL_JWT_TOKEN`** manually: from `backend/` run `python scripts/angel_smartapi_login.py` (uses `ANGEL_API_KEY`, `ANGEL_CLIENT_ID`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`), or use **`POST /angel/refresh-session`** as admin from the dashboard button when the session has expired.

For **SENSEX** live LTP/OHLC set `ANGEL_EXCHANGE_TOKENS={"BSE":["99919000"]}` (BSE index; `99919000` is not an NSE token). SBIN example: `{"NSE":["3045"]}`.

Interactive docs: `http://127.0.0.1:8000/docs`

## Ports

| Service | Port |
|---------|------|
| Next.js (`npm run dev`) | 3000 |
| FastAPI (`npm run worker`) | 8000 |
| MySQL | 3306 |

## Troubleshooting login (“Cannot reach API” / “Failed to fetch”)

1. **Start the API:** from repo root, `npm run worker` (FastAPI on **port 8000**).
2. **Frontend API calls** go through **`/api/backend/...`** (Next.js route proxy). Set `BACKEND_PROXY_URL` if FastAPI is not on `127.0.0.1:8000`.
3. **Login:** `admin` / `admin` after first worker start.

## Security

Defaults are for **local development** only. Rotate `JWT_SECRET` and DB passwords before production.
