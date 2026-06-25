# DDT Server

Backend for DOMO DPS Tracker — replaces Google Drive leaderboard sync.

## Deploy to Railway

1. Go to [railway.app](https://railway.app) and create an account
2. Click **New Project → Deploy from GitHub repo** (push this folder to a GitHub repo first)
   - Or use **New Project → Deploy from local** with the Railway CLI
3. Add a **Volume** in Railway dashboard:
   - Mount path: `/data`
   - This stores all player records and screenshots persistently
4. Set environment variables in Railway dashboard:
   - `DDT_GUILD_KEY` = your secret guild password (share with guildmates, not publicly)
   - `DDT_DATA_DIR` = `/data`
5. Deploy — Railway gives you a URL like `https://ddt-server-production.up.railway.app`

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | None | Health check |
| GET | `/version` | None | Latest DDT version info (auto-updater) |
| GET | `/leaderboard` | None | All player records |
| POST | `/upload` | Guild key | Upload your records |
| DELETE | `/player/{name}` | Guild key | Admin: remove a player |
| POST | `/screenshot/{player}/{boss}/{rank}` | Guild key | Upload PB screenshot |
| GET | `/screenshot/{player}/{boss}/{rank}` | None | Fetch a screenshot |
| GET | `/admin/players` | Guild key | List all players |

## Auth

Protected endpoints require the `X-Guild-Key` header:
```
X-Guild-Key: your_guild_key_here
```

## Local Testing

```bash
pip install -r requirements.txt
DDT_GUILD_KEY=testkey DDT_DATA_DIR=./data uvicorn ddt_server:app --reload
```

Then visit `http://localhost:8000/docs` for interactive API docs.
