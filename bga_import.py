"""
bga_import.py
============================================================
Import de parties Connect4 scrapées sur BGA vers PostgreSQL
✅ Compatible avec ton projet actuel (table: saved_games)
✅ Crée/patch la table saved_games si besoin (même structure que game.py)
✅ Normalise les coups en colonnes 0-based (0..cols-1)
✅ Calcule distinct_cols
✅ Evite les doublons (même moves JSONB + rows/cols)
============================================================
"""

import json
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import psycopg2


# =======================
# CONFIG DB (comme game.py)
# =======================
DB_CONFIG = {
    "host": "localhost",
    "database": "puissance4_db",
    "user": "postgres",
    "password": "rayane",
    "port": 5432,
}


# =======================
# DB helpers
# =======================
def db_connect():
    return psycopg2.connect(**DB_CONFIG)


def ensure_saved_games_table():
    """
    Table compatible avec game.py + database_viewer.py
    + Ajoute confidence / distinct_cols si manquants.
    """
    create_sql = """
    CREATE TABLE IF NOT EXISTS saved_games (
        id SERIAL PRIMARY KEY,
        save_name VARCHAR(100),
        rows INTEGER NOT NULL,
        cols INTEGER NOT NULL,
        starting_color CHAR(1) NOT NULL CHECK (starting_color IN ('R','Y')),
        mode INTEGER NOT NULL CHECK (mode IN (0,1,2)),
        game_index INTEGER NOT NULL,
        moves JSONB NOT NULL DEFAULT '[]'::jsonb,
        view_index INTEGER NOT NULL DEFAULT 0,
        ai_mode VARCHAR(20) NOT NULL DEFAULT 'random',
        ai_depth INTEGER NOT NULL DEFAULT 4,
        save_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """

    alter_sql = """
    ALTER TABLE saved_games
        ALTER COLUMN rows SET DEFAULT 9;
    ALTER TABLE saved_games
        ALTER COLUMN cols SET DEFAULT 9;

    ALTER TABLE saved_games
        ADD COLUMN IF NOT EXISTS confidence INTEGER NOT NULL DEFAULT 1
        CHECK (confidence BETWEEN 0 AND 5);

    ALTER TABLE saved_games
        ADD COLUMN IF NOT EXISTS distinct_cols INTEGER NOT NULL DEFAULT 0
        CHECK (distinct_cols BETWEEN 0 AND 20);
    """

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(create_sql)
            cur.execute(alter_sql)
        conn.commit()


# =======================
# Normalisation moves
# =======================
def _extract_cols_from_moves(moves: List[Dict[str, Any]]) -> List[int]:
    """
    moves attendu sous forme:
      [{"move_id": 1, "col": 1, "player_id": "123"}, ...]
    ou pour archive:
      [{"move_id": 1, "col": 0, "player_id": "123"}, ...]
    Retourne la liste brute des colonnes (int) dans l'ordre.
    """
    cols = []
    for m in moves or []:
        if isinstance(m, dict) and "col" in m:
            try:
                cols.append(int(m["col"]))
            except Exception:
                pass
    return cols


def _normalize_cols(cols_raw: List[int], cols_count: int) -> List[int]:
    """
    Convertit vers 0-based (0..cols_count-1) si besoin.

    Heuristique:
    - Si on voit un 0 => probablement déjà 0-based
    - Sinon si toutes les valeurs sont dans [1..cols_count] => 1-based => -1
    - Sinon on tente de sécuriser (clip) mais on préfère refuser si incohérent.
    """
    if not cols_raw:
        return []

    mn = min(cols_raw)
    mx = max(cols_raw)

    # Cas déjà 0-based (souvent replay archive)
    if mn == 0 and mx <= cols_count - 1:
        return cols_raw

    # Cas 1-based (gamereview FR "colonne 1..9")
    if mn >= 1 and mx <= cols_count:
        return [c - 1 for c in cols_raw]

    # Cas bizarre: on tente juste si c'est proche
    # (mais si c'est vraiment incohérent, on lève)
    if mn >= 0 and mx <= cols_count - 1:
        return cols_raw

    raise ValueError(
        f"Colonnes incohérentes: min={mn}, max={mx}, cols_count={cols_count}"
    )


def _moves_signature(cols_0_based: List[int]) -> str:
    """
    Hash stable pour identifier une partie (doublons).
    """
    payload = json.dumps(
        cols_0_based, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# =======================
# API principale
# =======================
def import_bga_moves(
    moves: List[Dict[str, Any]],
    rows: int = 9,
    cols: int = 9,
    confiance: int = 3,
    save_name: Optional[str] = None,
    starting_color: str = "R",
) -> int:
    """
    Insère une partie BGA dans saved_games.

    - mode=2 (humain vs humain)
    - ai_mode="bga"
    - ai_depth=4 (valeur neutre)
    - view_index=0
    - game_index=1 (ne sert pas trop dans le viewer)
    - confidence (0..5) -> on passe confiance=3 pour BGA

    Retourne l'id en base (existant si doublon, sinon nouvel id).
    """
    ensure_saved_games_table()

    if starting_color not in ("R", "Y"):
        starting_color = "R"

    cols_raw = _extract_cols_from_moves(moves)
    cols_0 = _normalize_cols(cols_raw, cols_count=cols)
    if not cols_0:
        raise ValueError("Aucun coup valide à importer.")

    distinct_cols = len(set(cols_0))
    signature = _moves_signature(cols_0)

    # Moves stockés dans saved_games: liste simple [0,3,2,...]
    moves_json = json.dumps(cols_0, ensure_ascii=False)

    # Save name par défaut (stable, court)
    if not save_name:
        save_name = f"BGA_{rows}x{cols}_{signature[:12]}"

    # Anti doublon: même rows/cols + moves identiques
    select_dup = """
    SELECT id
    FROM saved_games
    WHERE rows = %s AND cols = %s AND moves = %s::jsonb
    LIMIT 1;
    """

    insert_sql = """
    INSERT INTO saved_games
      (save_name, rows, cols, starting_color, mode, game_index,
       moves, view_index, ai_mode, ai_depth, confidence, distinct_cols, save_date)
    VALUES
      (%s, %s, %s, %s, %s, %s,
       %s::jsonb, %s, %s, %s, %s, %s, NOW())
    RETURNING id;
    """

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(select_dup, (rows, cols, moves_json))
            row = cur.fetchone()
            if row:
                # Déjà en base
                return int(row[0])

            cur.execute(
                insert_sql,
                (
                    save_name,
                    int(rows),
                    int(cols),
                    starting_color,
                    2,  # mode=2 (H vs H)
                    1,  # game_index
                    moves_json,
                    0,  # view_index
                    "bga",
                    4,  # ai_depth (neutre)
                    int(confiance),
                    int(distinct_cols),
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()

    return int(new_id)
