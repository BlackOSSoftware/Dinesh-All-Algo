import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../..");
const backend = path.join(root, "backend");

const win = process.platform === "win32";
const venvPython = win
  ? path.join(backend, ".venv", "Scripts", "python.exe")
  : path.join(backend, ".venv", "bin", "python");

const python = fs.existsSync(venvPython) ? venvPython : win ? "python" : "python3";

console.log("[worker] Starting Python FastAPI engine from", backend);

const child = spawn(
  python,
  // --no-access-log: per-request lines otherwise flood the CMD window (frontend
  // polls every second) and slowly hang the VPS console. Details still go to
  // backend/instance/logs/backend.log (rotating).
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
  {
    cwd: backend,
    stdio: "inherit",
    env: { ...process.env },
    shell: false,
  },
);

child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code ?? 0);
});
