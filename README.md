# Senzo Netflix Bot

Telegram bot for account stock, cookie checking, user reports, and admin tools.

## Deploy on Railway

1. Push this folder to a GitHub repo (or use **Railway → New Project → Deploy from GitHub**).
2. In Railway, open your service → **Variables** and set at minimum:
   - `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `ADMIN_IDS` — your Telegram numeric user ID(s), comma-separated
3. Optional but recommended:
   - `REPORT_CHANNEL_ID` — channel ID for working/not-working screenshots
   - `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` — [Turso](https://turso.tech) for persistent users/reports across redeploys
   - Mount a **Volume** at `/data` and set `DATA_DIR=/data` so account stock survives redeploys
4. Railway uses `Procfile` (`web: python main.py`) and `requirements.txt` via Nixpacks.
5. After deploy, open the service URL — you should see JSON `{"status":"online",...}` from the health server on the same port as the bot process.

## Local run

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your BOT_TOKEN and ADMIN_IDS
python main.py
```

## Notes

- Without Turso, user/report data is stored in SQLite alongside accounts (`accounts.db` under `DATA_DIR`).
- The bot runs long polling plus a small Flask health check on `PORT` (required for Railway web services).
