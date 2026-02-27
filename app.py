# app.py
import os
import json
import secrets
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# =========================
# Config
# =========================
PORT = int(os.environ.get("PORT", "8000"))


def db_conn():
    """
    Render: mets DATABASE_URL dans Environment.
    On force sslmode=require (Render Postgres).
    On normalise postgres:// -> postgresql:// (compat psycopg2).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL manquant (Render > Web Service > Environment)."
        )

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(url, sslmode="require")


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


# =========================
# DB init (safe migrations)
# =========================
INIT_SQL = """
-- 1) Online tables (créées si absentes)
CREATE TABLE IF NOT EXISTS online_games (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  rows INT NOT NULL DEFAULT 8,
  cols INT NOT NULL DEFAULT 9,
  starting_color CHAR(1) NOT NULL DEFAULT 'R',
  current_turn CHAR(1) NOT NULL DEFAULT 'R',
  status TEXT NOT NULL DEFAULT 'waiting', -- waiting/playing/finished
  winner CHAR(1), -- R/Y/D
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS online_players (
  id SERIAL PRIMARY KEY,
  game_id INT NOT NULL REFERENCES online_games(id) ON DELETE CASCADE,
  player_name TEXT NOT NULL,
  token CHAR(1) NOT NULL,  -- R/Y/S (spectateur)
  secret TEXT NOT NULL,    -- "player_secret" côté client
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(game_id, token) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE IF NOT EXISTS online_moves (
  id SERIAL PRIMARY KEY,
  game_id INT NOT NULL REFERENCES online_games(id) ON DELETE CASCADE,
  move_index INT NOT NULL,
  token CHAR(1) NOT NULL,     -- R/Y
  col INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(game_id, move_index)
);

-- 2) saved_games (compat game.js) : crée si absent
CREATE TABLE IF NOT EXISTS saved_games (
  game_id SERIAL PRIMARY KEY,
  user_id INT,
  save_name TEXT,
  game_index INT,
  rows_count INT,
  cols_count INT,
  starting_color CHAR(1),
  ai_mode TEXT,
  ai_depth INT,
  game_mode INT,
  status TEXT,
  winner CHAR(1),
  view_index INT,
  moves JSONB NOT NULL DEFAULT '[]'::jsonb,
  player_red TEXT,
  player_yellow TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3) Migrations douces si saved_games existe déjà avec un schéma différent
ALTER TABLE saved_games
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE saved_games
  ADD COLUMN IF NOT EXISTS moves JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE saved_games
  ADD COLUMN IF NOT EXISTS player_red TEXT;

ALTER TABLE saved_games
  ADD COLUMN IF NOT EXISTS player_yellow TEXT;

-- 4) Index: seulement si la colonne existe (elle existe après l'ALTER ci-dessus)
CREATE INDEX IF NOT EXISTS idx_saved_games_created_at ON saved_games(created_at DESC);
"""


def init_db():
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(INIT_SQL)
        conn.commit()


# =========================
# Game logic (connect4)
# =========================
EMPTY = "."
R = "R"
Y = "Y"
CONNECT_N = 4


def new_board(rows, cols):
    return [[EMPTY for _ in range(cols)] for _ in range(rows)]


def apply_move(board, col, token):
    rows = len(board)
    cols = len(board[0])
    if col < 0 or col >= cols:
        raise ValueError("col out of range")

    for r in range(rows - 1, -1, -1):
        if board[r][col] == EMPTY:
            board[r][col] = token
            return r
    raise ValueError("column full")


def check_winner(board):
    rows = len(board)
    cols = len(board[0])

    def inb(r, c):
        return 0 <= r < rows and 0 <= c < cols

    for r0 in range(rows):
        for c0 in range(cols):
            t = board[r0][c0]
            if t not in (R, Y):
                continue
            for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
                ok = True
                for k in range(1, CONNECT_N):
                    r = r0 + dr * k
                    c = c0 + dc * k
                    if not inb(r, c) or board[r][c] != t:
                        ok = False
                        break
                if ok:
                    return t

    if all(board[0][c] != EMPTY for c in range(cols)):
        return "D"
    return None


def rebuild_board(rows, cols, moves):
    b = new_board(rows, cols)
    for mv in moves:
        apply_move(b, mv["col"], mv["token"])
    return b


# =========================
# FastAPI
# =========================
app = FastAPI(title="Connect4 Online")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # OK pour demo; restreins ensuite
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir le frontend (index.html, game.js, style.css dans ./public)
if os.path.isdir("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="public")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True, "time": now_utc_iso()}


# =========================
# Models
# =========================
class CreateOnlineReq(BaseModel):
    player_name: str = Field(min_length=1, max_length=40)
    rows: int = 8
    cols: int = 9
    starting_color: str = "R"


class JoinOnlineReq(BaseModel):
    code: str = Field(min_length=4, max_length=16)
    player_name: str = Field(min_length=1, max_length=40)


class MoveReq(BaseModel):
    player_secret: str = Field(min_length=10, max_length=200)
    col: int


# =========================
# Online endpoints
# =========================
def gen_code():
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()


@app.post("/api/online/create")
def online_create(req: CreateOnlineReq):
    code = gen_code()
    secret = secrets.token_urlsafe(24)

    rows = max(4, min(20, int(req.rows)))
    cols = max(4, min(20, int(req.cols)))
    starting = req.starting_color if req.starting_color in ("R", "Y") else "R"

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO online_games(code, rows, cols, starting_color, current_turn, status)
                VALUES (%s,%s,%s,%s,%s,'waiting')
                RETURNING id, code, rows, cols, starting_color, current_turn, status
                """,
                (code, rows, cols, starting, starting),
            )
            game = cur.fetchone()

            cur.execute(
                """
                INSERT INTO online_players(game_id, player_name, token, secret)
                VALUES (%s,%s,%s,%s)
                RETURNING id, token
                """,
                (game["id"], req.player_name.strip(), game["starting_color"], secret),
            )
            pl = cur.fetchone()

        conn.commit()

    return {
        "code": game["code"],
        "rows": game["rows"],
        "cols": game["cols"],
        "starting_color": game["starting_color"],
        "your_token": pl["token"],
        "player_secret": secret,
        "share_url": f"/?join={game['code']}",
    }


@app.post("/api/online/join")
def online_join(req: JoinOnlineReq):
    code = req.code.strip().upper()
    secret = secrets.token_urlsafe(24)

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM online_games WHERE code=%s", (code,))
            game = cur.fetchone()
            if not game:
                raise HTTPException(404, "Code de partie introuvable.")

            cur.execute(
                "SELECT token FROM online_players WHERE game_id=%s", (game["id"],)
            )
            tokens = {row["token"] for row in cur.fetchall()}

            if "R" not in tokens:
                token = "R"
            elif "Y" not in tokens:
                token = "Y"
            else:
                token = "S"  # spectateur

            cur.execute(
                """
                INSERT INTO online_players(game_id, player_name, token, secret)
                VALUES (%s,%s,%s,%s)
                RETURNING id, token
                """,
                (game["id"], req.player_name.strip(), token, secret),
            )
            pl = cur.fetchone()

            if token in ("R", "Y"):
                cur.execute(
                    "SELECT COUNT(*) AS c FROM online_players WHERE game_id=%s AND token IN ('R','Y')",
                    (game["id"],),
                )
                c = cur.fetchone()["c"]
                if c == 2 and game["status"] == "waiting":
                    cur.execute(
                        "UPDATE online_games SET status='playing' WHERE id=%s",
                        (game["id"],),
                    )

        conn.commit()

    return {
        "code": code,
        "rows": game["rows"],
        "cols": game["cols"],
        "starting_color": game["starting_color"],
        "your_token": pl["token"],
        "player_secret": secret,
        "status": "playing" if pl["token"] in ("R", "Y") else "spectator",
    }


@app.get("/api/online/{code}/state")
def online_state(code: str):
    code = code.strip().upper()
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM online_games WHERE code=%s", (code,))
            game = cur.fetchone()
            if not game:
                raise HTTPException(404, "Partie introuvable.")

            cur.execute(
                """
                SELECT move_index, token, col, created_at
                FROM online_moves
                WHERE game_id=%s
                ORDER BY move_index ASC
                """,
                (game["id"],),
            )
            moves = cur.fetchall()

            cur.execute(
                """
                SELECT token, player_name
                FROM online_players
                WHERE game_id=%s
                ORDER BY id ASC
                """,
                (game["id"],),
            )
            players = cur.fetchall()

    return {
        "code": code,
        "rows": game["rows"],
        "cols": game["cols"],
        "starting_color": game["starting_color"],
        "current_turn": game["current_turn"],
        "status": game["status"],
        "winner": game["winner"],
        "moves": [
            {"move_index": m["move_index"], "token": m["token"], "col": m["col"]}
            for m in moves
        ],
        "players": players,
    }


@app.post("/api/online/{code}/move")
def online_move(code: str, req: MoveReq):
    code = code.strip().upper()

    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM online_games WHERE code=%s FOR UPDATE", (code,))
            game = cur.fetchone()
            if not game:
                raise HTTPException(404, "Partie introuvable.")
            if game["status"] not in ("playing", "waiting"):
                raise HTTPException(409, "Partie terminée.")
            if game["winner"] is not None:
                raise HTTPException(409, "Partie terminée.")

            cur.execute(
                "SELECT * FROM online_players WHERE game_id=%s AND secret=%s",
                (game["id"], req.player_secret),
            )
            player = cur.fetchone()
            if not player:
                raise HTTPException(401, "Joueur non reconnu (secret invalide).")

            token = player["token"]
            if token not in ("R", "Y"):
                raise HTTPException(403, "Spectateur: pas le droit de jouer.")

            if token != game["current_turn"]:
                raise HTTPException(409, "Pas ton tour.")

            cur.execute(
                "SELECT move_index, token, col FROM online_moves WHERE game_id=%s ORDER BY move_index ASC",
                (game["id"],),
            )
            moves = cur.fetchall()

            rows = int(game["rows"])
            cols = int(game["cols"])

            board = rebuild_board(rows, cols, moves)
            try:
                apply_move(board, int(req.col), token)
            except ValueError as e:
                raise HTTPException(409, str(e))

            move_index = len(moves)
            cur.execute(
                """
                INSERT INTO online_moves(game_id, move_index, token, col)
                VALUES (%s,%s,%s,%s)
                """,
                (game["id"], move_index, token, int(req.col)),
            )

            w = check_winner(board)
            if w in ("R", "Y", "D"):
                cur.execute(
                    "UPDATE online_games SET status='finished', winner=%s WHERE id=%s",
                    (w, game["id"]),
                )
                next_turn = game["current_turn"]
            else:
                next_turn = "Y" if token == "R" else "R"
                cur.execute(
                    "UPDATE online_games SET current_turn=%s, status='playing' WHERE id=%s",
                    (next_turn, game["id"]),
                )

        conn.commit()

    return {"ok": True, "next_turn": next_turn}


# =========================
# Save/Load endpoints (compat game.js)
# =========================
class SaveReq(BaseModel):
    user_id: int | None = 1
    save_name: str | None = None
    game_index: int | None = None
    rows_count: int
    cols_count: int
    starting_color: str
    ai_mode: str | None = "random"
    ai_depth: int | None = 4
    game_mode: int | None = 0
    status: str | None = "in_progress"
    winner: str | None = None
    view_index: int | None = 0
    moves: list[int] = []
    player_red: str | None = None
    player_yellow: str | None = None


@app.post("/api/games")
def save_game(req: SaveReq):
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO saved_games(
                  user_id, save_name, game_index, rows_count, cols_count, starting_color,
                  ai_mode, ai_depth, game_mode, status, winner, view_index, moves, player_red, player_yellow
                ) VALUES (
                  %s,%s,%s,%s,%s,%s,
                  %s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                RETURNING game_id
                """,
                (
                    req.user_id,
                    req.save_name,
                    req.game_index,
                    req.rows_count,
                    req.cols_count,
                    req.starting_color,
                    req.ai_mode,
                    req.ai_depth,
                    req.game_mode,
                    req.status,
                    req.winner,
                    req.view_index,
                    json.dumps(req.moves),
                    req.player_red,
                    req.player_yellow,
                ),
            )
            gid = cur.fetchone()["game_id"]
        conn.commit()
    return {"game_id": gid}


@app.get("/api/games")
def list_games():
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # created_at existe après migration
            cur.execute(
                """
                SELECT game_id, save_name, rows_count, cols_count, game_mode, ai_mode, ai_depth,
                       jsonb_array_length(moves) AS total_moves, created_at
                FROM saved_games
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()
    return rows


@app.get("/api/games/{game_id}")
def get_game(game_id: int):
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM saved_games WHERE game_id=%s", (game_id,))
            g = cur.fetchone()
            if not g:
                raise HTTPException(404, "Partie introuvable.")
    return g
