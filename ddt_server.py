"""
DDT Server — DOMO DPS Tracker backend
Replaces Google Drive leaderboard sync.
Hosts: player records, leaderboard, screenshots (future), version info.
Deploy on Railway.
"""

import os
import json
import shutil
import hashlib
import hmac
import time
import random
import string
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GUILD_KEY   = os.environ.get("DDT_GUILD_KEY", "incognito2024")  # set in Railway env vars
DATA_DIR    = Path(os.environ.get("DDT_DATA_DIR", "/data"))           # Railway persistent volume
RECORDS_DIR = DATA_DIR / "records"
SHOTS_DIR   = DATA_DIR / "screenshots"
VERSION_FILE = DATA_DIR / "version.json"

RECORDS_DIR.mkdir(parents=True, exist_ok=True)
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Write default version file if missing
if not VERSION_FILE.exists():
    VERSION_FILE.write_text(json.dumps({
        "version": "1.0.0",
        "download_url": "",
        "notes": "Initial release"
    }))

app = FastAPI(title="DDT Server", version="1.0.0")

# Allow DDT client and future website to hit the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory party sessions
# { room_code: { "members": { player_name: { dps, boss, timestamp } }, "buffs": [...] } }
# ---------------------------------------------------------------------------
PARTY_ROOMS = {}
PARTY_TIMEOUT = 10  # seconds before a member is considered offline

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def verify_key(x_guild_key: Optional[str]) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if not x_guild_key:
        return False
    return hmac.compare_digest(x_guild_key.strip(), GUILD_KEY)

def clean_rooms():
    """Remove stale members and empty rooms."""
    now = time.time()
    for code in list(PARTY_ROOMS.keys()):
        members = PARTY_ROOMS[code]["members"]
        stale = [p for p, d in members.items() if now - d.get("timestamp", 0) > PARTY_TIMEOUT]
        for p in stale:
            del members[p]
        if not members:
            del PARTY_ROOMS[code]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UploadPayload(BaseModel):
    player: str
    records: dict  # same format DDT already saves locally

class PartyJoinPayload(BaseModel):
    player: str
    room_code: str

class PartyDPSPayload(BaseModel):
    player: str
    room_code: str
    dps: int
    boss: str = ""

class PartyLeavePayload(BaseModel):
    player: str
    room_code: str

class PartyBuffPayload(BaseModel):
    room_code: str
    caster: str
    buff_name: str
    timestamp: float

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "DDT Server online", "guild": "Incognito"}


@app.get("/version")
def get_version():
    """Auto-updater endpoint — DDT checks this on launch."""
    try:
        return json.loads(VERSION_FILE.read_text())
    except Exception:
        return {"version": "1.0.0", "download_url": "", "notes": ""}


@app.get("/leaderboard")
def get_leaderboard():
    """
    Return all player records.
    Same structure as GDriveLeaderboard.download_all():
    { "PlayerName": { boss_name: { top_runs: [...] } } }
    """
    all_data = {}
    for f in RECORDS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            player  = data.get("player", f.stem)
            records = data.get("records", {})
            all_data[player] = records
        except Exception:
            continue
    return all_data


@app.post("/upload")
def upload_records(
    payload: UploadPayload,
    x_guild_key: Optional[str] = Header(None)
):
    """
    Upload a player's full records.
    Requires X-Guild-Key header matching the server's DDT_GUILD_KEY env var.
    Same data DDT sends to Google Drive: { player, records }
    """
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    player = payload.player.strip()
    if not player:
        raise HTTPException(status_code=400, detail="Player name required")

    # Sanitize filename
    safe_name = "".join(c for c in player if c.isalnum() or c in (" ", "_", "-")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid player name")

    out_path = RECORDS_DIR / f"{safe_name}.json"
    out_path.write_text(
        json.dumps({"player": player, "records": payload.records}, ensure_ascii=False),
        encoding="utf-8"
    )
    return {"status": "ok", "player": player}


@app.delete("/player/{player_name}")
def delete_player(
    player_name: str,
    x_guild_key: Optional[str] = Header(None)
):
    """Admin: remove a player's records (cheated entry, name change, etc.)"""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    safe_name = "".join(c for c in player_name if c.isalnum() or c in (" ", "_", "-")).strip()
    record_file = RECORDS_DIR / f"{safe_name}.json"
    shot_files  = list(SHOTS_DIR.glob(f"{safe_name}_*.png"))

    deleted = []
    if record_file.exists():
        record_file.unlink()
        deleted.append(str(record_file.name))
    for sf in shot_files:
        sf.unlink()
        deleted.append(sf.name)

    if not deleted:
        raise HTTPException(status_code=404, detail="Player not found")

    return {"status": "deleted", "files": deleted}


# ---------------------------------------------------------------------------
# Screenshots (ready for when feature is built in DDT)
# ---------------------------------------------------------------------------

@app.post("/screenshot/{player_name}/{boss_name}/{rank}")
def upload_screenshot(
    player_name: str,
    boss_name: str,
    rank: int,
    file: UploadFile = File(...),
    x_guild_key: Optional[str] = Header(None)
):
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")
    if rank not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Rank must be 1, 2, or 3")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    safe_player = "".join(c for c in player_name if c.isalnum() or c in (" ", "_", "-")).strip()
    safe_boss   = "".join(c for c in boss_name   if c.isalnum() or c in (" ", "_", "-")).strip()
    filename    = f"{safe_player}_{safe_boss}_{rank}.png"
    out_path    = SHOTS_DIR / filename

    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"status": "ok", "file": filename}


@app.get("/screenshot/{player_name}/{boss_name}/{rank}")
def get_screenshot(player_name: str, boss_name: str, rank: int):
    safe_player = "".join(c for c in player_name if c.isalnum() or c in (" ", "_", "-")).strip()
    safe_boss   = "".join(c for c in boss_name   if c.isalnum() or c in (" ", "_", "-")).strip()
    filename    = f"{safe_player}_{safe_boss}_{rank}.png"
    path        = SHOTS_DIR / filename

    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(path, media_type="image/png")


# ---------------------------------------------------------------------------
# Admin: list all players
# ---------------------------------------------------------------------------

@app.get("/admin/players")
def list_players(x_guild_key: Optional[str] = Header(None)):
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    players = []
    for f in RECORDS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            players.append({
                "name": data.get("player", f.stem),
                "bosses": list(data.get("records", {}).keys()),
                "file": f.name
            })
        except Exception:
            continue

    return {"players": players, "count": len(players)}


# ---------------------------------------------------------------------------
# Party System
# ---------------------------------------------------------------------------

@app.post("/party/create")
def party_create(
    payload: PartyLeavePayload,
    x_guild_key: Optional[str] = Header(None)
):
    """Create a new party room. Returns a 6-character room code."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    clean_rooms()

    # Generate unique 6-char room code
    for _ in range(10):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in PARTY_ROOMS:
            break

    PARTY_ROOMS[code] = {
        "members": {
            payload.player: {"dps": 0, "boss": "", "timestamp": time.time()}
        },
        "buffs": []
    }
    return {"status": "ok", "room_code": code}


@app.post("/party/join")
def party_join(
    payload: PartyJoinPayload,
    x_guild_key: Optional[str] = Header(None)
):
    """Join an existing party room by code."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    clean_rooms()

    code = payload.room_code.upper().strip()
    if code not in PARTY_ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")

    PARTY_ROOMS[code]["members"][payload.player] = {
        "dps": 0, "boss": "", "timestamp": time.time()
    }
    return {"status": "ok", "room_code": code, "members": list(PARTY_ROOMS[code]["members"].keys())}


@app.post("/party/dps")
def party_dps(
    payload: PartyDPSPayload,
    x_guild_key: Optional[str] = Header(None)
):
    """Push live DPS update for a player in a room."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    code = payload.room_code.upper().strip()
    if code not in PARTY_ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")

    PARTY_ROOMS[code]["members"][payload.player] = {
        "dps": payload.dps,
        "boss": payload.boss,
        "timestamp": time.time()
    }
    return {"status": "ok"}


@app.get("/party/live/{room_code}")
def party_live(
    room_code: str,
    x_guild_key: Optional[str] = Header(None)
):
    """Get live DPS for all members in a room."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    clean_rooms()

    code = room_code.upper().strip()
    if code not in PARTY_ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")

    members = PARTY_ROOMS[code]["members"]
    return {
        "room_code": code,
        "members": [
            {"player": p, "dps": d["dps"], "boss": d["boss"]}
            for p, d in sorted(members.items(), key=lambda x: x[1]["dps"], reverse=True)
        ]
    }


@app.post("/party/buff")
def party_buff(
    payload: PartyBuffPayload,
    x_guild_key: Optional[str] = Header(None)
):
    """Report a buff received — used to relay buff back to the caster (support)."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    code = payload.room_code.upper().strip()
    if code not in PARTY_ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")

    # Keep only last 50 buff events, drop old ones
    buffs = PARTY_ROOMS[code]["buffs"]
    buffs.append({
        "caster": payload.caster,
        "buff_name": payload.buff_name,
        "timestamp": payload.timestamp
    })
    PARTY_ROOMS[code]["buffs"] = buffs[-50:]
    return {"status": "ok"}


@app.get("/party/buffs/{room_code}/{player_name}")
def party_buffs(
    room_code: str,
    player_name: str,
    since: float = 0,
    x_guild_key: Optional[str] = Header(None)
):
    """Get buff events cast by a specific player since a given timestamp."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    code = room_code.upper().strip()
    if code not in PARTY_ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")

    buffs = [
        b for b in PARTY_ROOMS[code]["buffs"]
        if b["caster"] == player_name and b["timestamp"] > since
    ]
    return {"buffs": buffs}


@app.post("/party/leave")
def party_leave(
    payload: PartyLeavePayload,
    x_guild_key: Optional[str] = Header(None)
):
    """Remove a player from a party room."""
    if not verify_key(x_guild_key):
        raise HTTPException(status_code=401, detail="Invalid guild key")

    code = payload.room_code.upper().strip()
    if code in PARTY_ROOMS:
        PARTY_ROOMS[code]["members"].pop(payload.player, None)
        if not PARTY_ROOMS[code]["members"]:
            del PARTY_ROOMS[code]

    return {"status": "ok"}
