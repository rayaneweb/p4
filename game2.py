# game.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import random

import psycopg2
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "database": "puissance4_db",
    "user": "postgres",
    "password": "rayane",
    "port": 5432,
}


class Connect4App(tk.Tk):
    EMPTY = "."
    RED = "R"
    YELLOW = "Y"
    CONNECT_N = 4

    CONFIG_PATH = "config.json"

    COLOR_BG = "#00478e"
    COLOR_HOLE = "#e3f2fd"
    COLOR_RED = "#d32f2f"
    COLOR_YELLOW = "#fbc02d"
    COLOR_WIN = "#00c853"

    def __init__(self):
        super().__init__()
        self.title("Puissance 4+ — Random / Minimax (1 fichier)")
        self.minsize(1050, 700)

        cfg = self.load_config()
        self.rows = cfg["rows"]
        self.cols = cfg["cols"]
        self.starting_color = cfg["starting_color"]

        self.board = None
        self.current = self.starting_color
        self.game_over = False
        self.winner = None
        self.winning_cells = []

        self.game_index = 1
        self.moves = []
        self.view_index = 0

        self.robot_thinking = False
        self.pending_after = None

        self.mode_var = tk.StringVar(value="2")
        self.ai_var = tk.StringVar(value="random")
        self.depth_var = tk.StringVar(value="4")
        self.status_var = tk.StringVar(value="")

        self.col_buttons = []
        self.score_labels = []

        # === Timeline ===
        self.timeline_var = tk.IntVar(value=0)
        self._timeline_user_drag = False

        self._build_ui()
        self.reset_game(new_game=False)

    # =======================
    # HELPERS
    # =======================
    def other(self, token):
        return self.YELLOW if token == self.RED else self.RED

    def clamp_int(self, v, lo, hi, default):
        try:
            x = int(v)
            return max(lo, min(hi, x))
        except Exception:
            return default

    def copy_grid(self, g):
        return [row[:] for row in g]

    def is_replay_view(self):
        return self.view_index < len(self.moves)

    # =======================
    # ✅ SYMÉTRIE (miroir gauche↔droite)
    # =======================
    def mirror_col(self, col: int) -> int:
        return (self.cols - 1) - int(col)

    def mirror_moves(self, moves):
        return [self.mirror_col(c) for c in moves]

    def canonical_moves(self, moves):
        """Canonique = min(moves, miroir) en ordre lexicographique."""
        if not moves:
            return []
        m1 = list(moves)
        m2 = self.mirror_moves(m1)
        return m1 if m1 < m2 else m2

    # =======================
    # CONFIG
    # =======================
    def load_config(self, path=None):
        if path is None:
            path = self.CONFIG_PATH

        default = {"rows": 8, "cols": 9, "starting_color": self.RED}

        if not os.path.exists(path):
            return default

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return default

        rows = data.get("rows", default["rows"])
        cols = data.get("cols", default["cols"])
        start = data.get("starting_color", default["starting_color"])

        if not isinstance(rows, int) or not (4 <= rows <= 20):
            rows = default["rows"]
        if not isinstance(cols, int) or not (4 <= cols <= 20):
            cols = default["cols"]
        if start not in (self.RED, self.YELLOW):
            start = default["starting_color"]

        return {"rows": rows, "cols": cols, "starting_color": start}

    # =======================
    # ✅ POSTGRES
    # =======================
    def db_connect(self):
        return psycopg2.connect(**DB_CONFIG)

    def ensure_saved_games_table(self):
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

        with self.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(create_sql)
                cur.execute(alter_sql)
            conn.commit()

    def compute_confidence(self, mode: int, ai_mode: str, ai_depth: int) -> int:
        try:
            mode = int(mode)
        except Exception:
            mode = 2

        ai_mode = (ai_mode or "random").lower()
        ai_depth = self.clamp_int(ai_depth, 1, 8, 4)

        if mode == 2:
            return 5
        if ai_mode == "lose":
            return 0
        if ai_mode == "random":
            return 1
        if ai_mode == "minimax":
            if ai_depth <= 2:
                return 2
            if ai_depth <= 4:
                return 3
            if ai_depth <= 6:
                return 4
            return 5
        return 1

    def find_duplicate_save(self, save_name: str, moves_canon):
        """
        Cherche un doublon si :
        - même save_name
        OU
        - mêmes paramètres + mêmes moves (canonique)
        Retourne (id, reason_str) ou (None, None)
        """
        self.ensure_saved_games_table()

        q = """
        SELECT id,
               CASE
                 WHEN save_name = %s THEN 'name'
                 ELSE 'moves'
               END AS reason
        FROM saved_games
        WHERE save_name = %s
           OR (
                rows=%s AND cols=%s AND starting_color=%s
                AND moves = %s::jsonb
              )
        ORDER BY save_date DESC
        LIMIT 1;
        """
        with self.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    q,
                    (
                        save_name,
                        save_name,
                        self.rows,
                        self.cols,
                        self.starting_color,
                        json.dumps(moves_canon),
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return None, None
                return int(row[0]), str(row[1])

    def upsert_game_to_postgres(self, save_name: str):
        """
        Sauvegarde avec gestion doublons:
        - si doublon (nom OU moves), propose ÉCRASER / ANNULER
        - ÉCRASER = UPDATE de la ligne existante
        - sinon = INSERT
        Retourne (id, action_str) où action_str ∈ {"insert", "update", "cancel"}
        """
        self.ensure_saved_games_table()

        mode = int(self.mode_var.get())
        ai_mode = self.ai_var.get()
        ai_depth = self.clamp_int(self.depth_var.get(), 1, 8, 4)

        confidence = self.compute_confidence(mode, ai_mode, ai_depth)

        moves_to_save = self.canonical_moves(self.moves)
        distinct_cols = len(set(moves_to_save)) if moves_to_save else 0

        dup_id, reason = self.find_duplicate_save(save_name, moves_to_save)

        if dup_id is not None:
            if reason == "name":
                reason_txt = "une partie avec le même NOM existe déjà"
            else:
                reason_txt = (
                    "une partie avec les mêmes COUPS (symétrie incluse) existe déjà"
                )

            ok = messagebox.askyesno(
                "Doublon détecté",
                f"⚠️ Doublon détecté : {reason_txt}.\n\n"
                f"ID existant : {dup_id}\n"
                f"Nom : {save_name}\n\n"
                "Voulez-vous ÉCRASER la sauvegarde existante ?\n\n"
                "➡️ Oui = Écraser\n"
                "➡️ Non = Annuler",
                parent=self,
            )
            if not ok:
                return None, "cancel"

            # UPDATE
            update_sql = """
            UPDATE saved_games
            SET save_name=%s,
                rows=%s,
                cols=%s,
                starting_color=%s,
                mode=%s,
                game_index=%s,
                moves=%s::jsonb,
                view_index=%s,
                ai_mode=%s,
                ai_depth=%s,
                confidence=%s,
                distinct_cols=%s,
                save_date=NOW()
            WHERE id=%s
            RETURNING id;
            """
            with self.db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        update_sql,
                        (
                            save_name,
                            self.rows,
                            self.cols,
                            self.starting_color,
                            mode,
                            int(self.game_index),
                            json.dumps(moves_to_save),
                            int(self.view_index),
                            ai_mode,
                            ai_depth,
                            confidence,
                            distinct_cols,
                            dup_id,
                        ),
                    )
                    gid = cur.fetchone()[0]
                conn.commit()
            return int(gid), "update"

        # INSERT
        insert_sql = """
        INSERT INTO saved_games
          (save_name, rows, cols, starting_color, mode, game_index,
           moves, view_index, ai_mode, ai_depth, confidence, distinct_cols, save_date)
        VALUES
          (%s, %s, %s, %s, %s, %s,
           %s::jsonb, %s, %s, %s, %s, %s, NOW())
        RETURNING id;
        """
        with self.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    insert_sql,
                    (
                        save_name,
                        self.rows,
                        self.cols,
                        self.starting_color,
                        mode,
                        int(self.game_index),
                        json.dumps(moves_to_save),
                        int(self.view_index),
                        ai_mode,
                        ai_depth,
                        confidence,
                        distinct_cols,
                    ),
                )
                gid = cur.fetchone()[0]
            conn.commit()
        return int(gid), "insert"

    def fetch_saved_games_list(self):
        self.ensure_saved_games_table()
        query = """
        SELECT
            id, save_name, rows, cols, mode, ai_mode, ai_depth,
            confidence, distinct_cols,
            jsonb_array_length(moves) as nb_coups,
            save_date
        FROM saved_games
        ORDER BY save_date DESC
        LIMIT 200;
        """
        with self.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

    def fetch_saved_game_by_id(self, game_id: int):
        self.ensure_saved_games_table()
        query = """
        SELECT
            id, save_name, rows, cols, starting_color,
            mode, game_index, moves, view_index, ai_mode, ai_depth,
            confidence, distinct_cols,
            save_date
        FROM saved_games
        WHERE id = %s
        LIMIT 1;
        """
        with self.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (game_id,))
                return cur.fetchone()

    # =======================
    # GAME CORE
    # =======================
    def create_board(self):
        return [[self.EMPTY for _ in range(self.cols)] for _ in range(self.rows)]

    def valid_columns(self, board=None):
        b = board if board is not None else self.board
        return [c for c in range(self.cols) if b[0][c] == self.EMPTY]

    def drop_token(self, board, col, token):
        if col < 0 or col >= self.cols:
            return None
        if board[0][col] != self.EMPTY:
            return None
        for r in range(self.rows - 1, -1, -1):
            if board[r][col] == self.EMPTY:
                board[r][col] = token
                return (r, col)
        return None

    def is_draw(self, board=None):
        b = board if board is not None else self.board
        return all(b[0][c] != self.EMPTY for c in range(self.cols))

    def is_human_turn(self, mode, current):
        mode = int(mode)
        if mode == 2:
            return True
        if mode == 0:
            return False
        return current == self.RED

    def check_win_cells(self, board, last_row, last_col, token):
        dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in dirs:
            cells = [(last_row, last_col)]

            r, c = last_row + dr, last_col + dc
            while 0 <= r < self.rows and 0 <= c < self.cols and board[r][c] == token:
                cells.append((r, c))
                r += dr
                c += dc

            r, c = last_row - dr, last_col - dc
            while 0 <= r < self.rows and 0 <= c < self.cols and board[r][c] == token:
                cells.insert(0, (r, c))
                r -= dr
                c -= dc

            if len(cells) >= self.CONNECT_N:
                return cells[: self.CONNECT_N]
        return []

    # =======================
    # MINIMAX (inchangé)
    # =======================
    def terminal_state(self, grid):
        for r in range(self.rows):
            for c in range(self.cols):
                p = grid[r][c]
                if p == self.EMPTY:
                    continue
                if c + 3 < self.cols and all(grid[r][c + i] == p for i in range(4)):
                    return True, p
                if r + 3 < self.rows and all(grid[r + i][c] == p for i in range(4)):
                    return True, p
                if (
                    r + 3 < self.rows
                    and c + 3 < self.cols
                    and all(grid[r + i][c + i] == p for i in range(4))
                ):
                    return True, p
                if (
                    r + 3 < self.rows
                    and c + 3 < self.cols
                    and all(grid[r + 3 - i][c + i] == p for i in range(4))
                ):
                    return True, p

        if self.is_draw(grid):
            return True, None
        return False, None

    def evaluate_window(self, window, player):
        opp = self.other(player)
        cp = window.count(player)
        co = window.count(opp)
        ce = window.count(self.EMPTY)

        if cp == 4:
            return 100000
        if co == 4:
            return -100000

        score = 0
        if cp == 3 and ce == 1:
            score += 50
        elif cp == 2 and ce == 2:
            score += 10

        if co == 3 and ce == 1:
            score -= 80
        elif co == 2 and ce == 2:
            score -= 10

        return score

    def heuristic_score(self, grid, player):
        score = 0
        center = self.cols // 2
        score += sum(1 for r in range(self.rows) if grid[r][center] == player) * 6

        for r in range(self.rows):
            for c in range(self.cols - 3):
                score += self.evaluate_window(
                    [grid[r][c + i] for i in range(4)], player
                )

        for c in range(self.cols):
            for r in range(self.rows - 3):
                score += self.evaluate_window(
                    [grid[r + i][c] for i in range(4)], player
                )

        for r in range(self.rows - 3):
            for c in range(self.cols - 3):
                score += self.evaluate_window(
                    [grid[r + i][c + i] for i in range(4)], player
                )

        for r in range(self.rows - 3):
            for c in range(self.cols - 3):
                score += self.evaluate_window(
                    [grid[r + 3 - i][c + i] for i in range(4)], player
                )

        return score

    def drop_in_grid(self, grid, col, token):
        for r in range(self.rows - 1, -1, -1):
            if grid[r][col] == self.EMPTY:
                grid[r][col] = token
                return (r, col)
        return None

    def minimax(self, grid, depth, alpha, beta, maximizing, player):
        term, winner = self.terminal_state(grid)
        if term:
            if winner == player:
                return 1_000_000
            if winner == self.other(player):
                return -1_000_000
            return 0

        if depth == 0:
            return self.heuristic_score(grid, player)

        moves = self.valid_columns(grid)
        center = self.cols // 2
        moves.sort(key=lambda c: abs(c - center))

        if maximizing:
            best = -(10**18)
            for col in moves:
                g2 = self.copy_grid(grid)
                self.drop_in_grid(g2, col, player)
                val = self.minimax(g2, depth - 1, alpha, beta, False, player)
                best = max(best, val)
                alpha = max(alpha, best)
                if alpha >= beta:
                    break
            return best
        else:
            opp = self.other(player)
            best = 10**18
            for col in moves:
                g2 = self.copy_grid(grid)
                self.drop_in_grid(g2, col, opp)
                val = self.minimax(g2, depth - 1, alpha, beta, True, player)
                best = min(best, val)
                beta = min(beta, best)
                if alpha >= beta:
                    break
            return best

    # =======================
    # UI (inchangé)
    # =======================
    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Mode joueurs:").pack(side=tk.LEFT)
        mode_combo = ttk.Combobox(
            top,
            textvariable=self.mode_var,
            values=["0", "1", "2"],
            width=4,
            state="readonly",
        )
        mode_combo.pack(side=tk.LEFT, padx=(6, 14))
        mode_combo.bind(
            "<<ComboboxSelected>>", lambda e: self.reset_game(new_game=True)
        )

        ttk.Label(top, text="IA:").pack(side=tk.LEFT)
        ai_combo = ttk.Combobox(
            top,
            textvariable=self.ai_var,
            values=["random", "minimax"],
            width=10,
            state="readonly",
        )
        ai_combo.pack(side=tk.LEFT, padx=(6, 10))
        ai_combo.bind("<<ComboboxSelected>>", lambda e: self._after_state_change(True))

        ttk.Label(top, text="Profondeur:").pack(side=tk.LEFT)
        depth_spin = ttk.Spinbox(
            top,
            from_=1,
            to=8,
            width=5,
            textvariable=self.depth_var,
            command=self.render_ai_scores,
        )
        depth_spin.pack(side=tk.LEFT, padx=(6, 14))

        ttk.Button(
            top, text="Nouvelle partie", command=lambda: self.reset_game(True)
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Stop", command=self.stop_game).pack(side=tk.LEFT, padx=6)

        save_mb = tk.Menubutton(top, text="💾 Sauvegarder ▾", relief="raised")
        save_menu = tk.Menu(save_mb, tearoff=0)
        save_menu.add_command(
            label="Sauvegarder dans la base (PostgreSQL)",
            command=self.save_game_db_flow,
        )
        save_menu.add_command(
            label="Sauvegarder dans un fichier JSON", command=self.save_game_json_flow
        )
        save_mb.configure(menu=save_menu)
        save_mb.pack(side=tk.LEFT, padx=6)

        load_mb = tk.Menubutton(top, text="📂 Charger ▾", relief="raised")
        load_menu = tk.Menu(load_mb, tearoff=0)
        load_menu.add_command(
            label="Charger depuis la base (PostgreSQL)", command=self.load_game_db_flow
        )
        load_menu.add_command(
            label="Charger depuis un fichier JSON", command=self.load_game_json_flow
        )
        load_mb.configure(menu=load_menu)
        load_mb.pack(side=tk.LEFT, padx=6)

        status_bar = ttk.Frame(self, padding=(10, 0))
        status_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 12)).pack(
            anchor="w", pady=8
        )

        tl = ttk.Frame(self, padding=(10, 0))
        tl.pack(side=tk.TOP, fill=tk.X)

        self.tl_label_var = tk.StringVar(value="Coups: 0/0")
        ttk.Label(tl, textvariable=self.tl_label_var).pack(side=tk.LEFT)

        self.timeline_scale = ttk.Scale(
            tl, from_=0, to=0, orient="horizontal", command=self._on_timeline_scale
        )
        self.timeline_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        ttk.Button(tl, text="⏮", width=3, command=self._timeline_prev).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(tl, text="⏭", width=3, command=self._timeline_next).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(tl, text="Fin", width=5, command=self._timeline_end).pack(
            side=tk.LEFT
        )

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.btn_frame = ttk.Frame(left)
        self.btn_frame.pack(fill=tk.X)

        self.canvas = tk.Canvas(left, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.canvas.bind("<Configure>", lambda e: self.draw_board())

    # Timeline helpers
    def _sync_timeline_ui(self):
        try:
            maxv = len(self.moves)
            self.timeline_scale.configure(to=maxv)
            self.timeline_scale.set(self.view_index)
            self.timeline_var.set(self.view_index)
            self.tl_label_var.set(f"Coups: {self.view_index}/{maxv}")
        except Exception:
            pass

    def _timeline_prev(self):
        if self.view_index > 0:
            self.set_view_index(self.view_index - 1)

    def _timeline_next(self):
        if self.view_index < len(self.moves):
            self.set_view_index(self.view_index + 1)

    def _timeline_end(self):
        self.set_view_index(len(self.moves))

    def _on_timeline_scale(self, v):
        try:
            idx = int(float(v) + 0.5)
        except Exception:
            return
        idx = max(0, min(len(self.moves), idx))
        if idx != self.view_index:
            self.set_view_index(idx)

    def set_view_index(self, idx: int):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None
        self.robot_thinking = False

        self.view_index = max(0, min(len(self.moves), int(idx)))

        self.board = self.create_board()
        self.winning_cells = []
        self.game_over = False
        self.winner = None

        last_pos = None
        last_token = None
        for i in range(self.view_index):
            col = self.moves[i]
            token = self.token_for_move_index(i)
            last_token = token
            last_pos = self.drop_token(self.board, col, token)
            if last_pos is None:
                break

        self.current = self.token_for_move_index(self.view_index)

        if self.view_index == len(self.moves):
            if last_pos is not None and last_token is not None:
                rr, cc = last_pos
                cells = self.check_win_cells(self.board, rr, cc, last_token)
                if cells:
                    self.winning_cells = cells
                    self.game_over = True
                    self.winner = last_token
                elif self.is_draw(self.board):
                    self.game_over = True
                    self.winner = None

        self._after_state_change(trigger_robot=False)

    def rebuild_column_widgets(self):
        for w in self.btn_frame.winfo_children():
            w.destroy()

        self.col_buttons = []
        self.score_labels = []

        row_btn = ttk.Frame(self.btn_frame)
        row_btn.pack()
        row_scores = ttk.Frame(self.btn_frame)
        row_scores.pack()

        for c in range(self.cols):
            b = ttk.Button(
                row_btn,
                text=str(c + 1),
                width=4,
                command=lambda cc=c: self.on_click(cc),
            )
            b.pack(side=tk.LEFT, padx=3, pady=2)
            self.col_buttons.append(b)

        for c in range(self.cols):
            v = tk.StringVar(value="")
            lbl = ttk.Label(row_scores, textvariable=v, width=7, anchor="center")
            lbl.pack(side=tk.LEFT, padx=3, pady=(0, 6))
            self.score_labels.append(v)

    def cell_color(self, val):
        if val == self.RED:
            return self.COLOR_RED
        if val == self.YELLOW:
            return self.COLOR_YELLOW
        return self.COLOR_HOLE

    def draw_board(self):
        if self.board is None:
            return

        self.canvas.delete("all")
        W = max(300, self.canvas.winfo_width())
        H = max(300, self.canvas.winfo_height())

        cell = min(W / self.cols, H / self.rows)
        pad = cell * 0.10

        board_w = cell * self.cols
        board_h = cell * self.rows
        x0 = (W - board_w) / 2
        y0 = (H - board_h) / 2

        self.canvas.create_rectangle(
            x0, y0, x0 + board_w, y0 + board_h, fill=self.COLOR_BG, outline=""
        )

        win_set = set(self.winning_cells)
        for r in range(self.rows):
            for c in range(self.cols):
                cx0 = x0 + c * cell + pad
                cy0 = y0 + r * cell + pad
                cx1 = x0 + (c + 1) * cell - pad
                cy1 = y0 + (r + 1) * cell - pad

                fill = self.cell_color(self.board[r][c])
                outline = self.COLOR_WIN if (r, c) in win_set else ""
                width = 4 if (r, c) in win_set else 1
                self.canvas.create_oval(
                    cx0, cy0, cx1, cy1, fill=fill, outline=outline, width=width
                )

    def update_status(self):
        replay_note = ""
        if self.is_replay_view():
            replay_note = f"   (replay: coup {self.view_index}/{len(self.moves)})"

        if self.game_over:
            if self.winner == self.RED:
                msg = f"Partie #{self.game_index} — 🎉 Gagnant : Rouge"
            elif self.winner == self.YELLOW:
                msg = f"Partie #{self.game_index} — 🎉 Gagnant : Jaune"
            else:
                msg = f"Partie #{self.game_index} — 🤝 Match nul"
        else:
            name = "Rouge" if self.current == self.RED else "Jaune"
            msg = f"Partie #{self.game_index} — À jouer : {name}"

        if self.robot_thinking:
            msg += "   (IA réfléchit...)"

        msg += replay_note
        self.status_var.set(msg)

    def set_buttons_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in self.col_buttons:
            b.config(state=state)

    def token_for_move_index(self, i):
        return self.starting_color if i % 2 == 0 else self.other(self.starting_color)

    def play_move(self, col, token):
        pos = self.drop_token(self.board, col, token)
        if pos is None:
            return True

        if self.view_index < len(self.moves):
            del self.moves[self.view_index :]

        self.moves.append(col)
        self.view_index = len(self.moves)

        r, c = pos
        cells = self.check_win_cells(self.board, r, c, token)
        if cells:
            self.winning_cells = cells
            self.game_over = True
            self.winner = token
            self._after_state_change(trigger_robot=False)
            return False

        if self.is_draw(self.board):
            self.winning_cells = []
            self.game_over = True
            self.winner = None
            self._after_state_change(trigger_robot=False)
            return False

        self.current = self.other(self.current)
        self._after_state_change(trigger_robot=True)
        return True

    def on_click(self, col):
        if self.is_replay_view():
            return
        if self.game_over or self.robot_thinking:
            return
        mode = int(self.mode_var.get())
        if not self.is_human_turn(mode, self.current):
            return

        cont = self.play_move(col, self.current)
        if not cont:
            return

        if (
            mode in (0, 1)
            and not self.is_human_turn(mode, self.current)
            and not self.game_over
        ):
            self.after(120, self.robot_step)

    def set_scores_blank(self):
        for v in self.score_labels:
            v.set("")

    def render_ai_scores(self):
        if self.is_replay_view():
            self.set_scores_blank()
            return
        if self.ai_var.get() != "minimax":
            self.set_scores_blank()
            return
        if self.robot_thinking or self.board is None:
            return
        depth = self.clamp_int(self.depth_var.get(), 1, 8, 4)
        self.compute_scores_async(depth)

    def compute_scores_async(self, depth):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        grid0 = self.copy_grid(self.board)
        player = self.current
        valids = self.valid_columns(grid0)

        for c in range(self.cols):
            self.score_labels[c].set("N/A" if c not in valids else "...")

        col_list = list(range(self.cols))

        def step(i=0):
            if self.ai_var.get() != "minimax":
                return
            if self.robot_thinking or self.game_over:
                return
            if self.is_replay_view():
                return
            if i >= len(col_list):
                return

            col = col_list[i]
            if col not in valids:
                self.score_labels[col].set("N/A")
            else:
                g2 = self.copy_grid(grid0)
                self.drop_in_grid(g2, col, player)
                val = self.minimax(g2, depth - 1, -(10**18), 10**18, False, player)
                self.score_labels[col].set(str(int(val)))

            self.pending_after = self.after(40, lambda: step(i + 1))

        step(0)

    def robot_random_column(self, board):
        cols = self.valid_columns(board)
        return random.choice(cols) if cols else None

    def robot_step(self):
        if self.game_over:
            return
        if self.is_replay_view():
            return

        mode = int(self.mode_var.get())
        if self.is_human_turn(mode, self.current):
            self.set_buttons_state(True)
            return

        self.set_buttons_state(False)

        if self.ai_var.get() == "random":
            col = self.robot_random_column(self.board)
            if col is None:
                self.game_over = True
                self.winner = None
                self.winning_cells = []
                self._after_state_change(trigger_robot=False)
                return

            cont = self.play_move(col, self.current)
            if not cont:
                return

            if mode == 0 and not self.game_over:
                self.after(250, self.robot_step)
            else:
                self.set_buttons_state(True)
            return

        depth = self.clamp_int(self.depth_var.get(), 1, 8, 4)
        self.robot_play_minimax_async(depth)

    def robot_play_minimax_async(self, depth):
        if self.game_over:
            return
        if self.is_replay_view():
            return

        self.robot_thinking = True
        self.update_status()
        self.set_buttons_state(False)

        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        grid0 = self.copy_grid(self.board)
        player = self.current
        valids = self.valid_columns(grid0)

        for c in range(self.cols):
            self.score_labels[c].set("N/A" if c not in valids else "...")

        center = self.cols // 2
        col_list = list(range(self.cols))
        col_list.sort(key=lambda c: abs(c - center))

        state = {"best_col": None, "best_val": -(10**18)}

        def step(i=0):
            if self.game_over:
                self.robot_thinking = False
                self.update_status()
                return
            if self.is_replay_view():
                self.robot_thinking = False
                self.update_status()
                return

            if i >= len(col_list):
                best_col = state["best_col"]
                if best_col is None and valids:
                    best_col = random.choice(valids)

                self.robot_thinking = False
                self.update_status()

                if best_col is not None:
                    cont = self.play_move(best_col, player)
                    if not cont:
                        return

                mode = int(self.mode_var.get())
                if mode == 0 and not self.game_over:
                    self.after(250, self.robot_step)
                else:
                    self.set_buttons_state(True)
                return

            col = col_list[i]
            if col not in valids:
                self.score_labels[col].set("N/A")
                self.pending_after = self.after(30, lambda: step(i + 1))
                return

            g2 = self.copy_grid(grid0)
            self.drop_in_grid(g2, col, player)
            val = self.minimax(g2, depth - 1, -(10**18), 10**18, False, player)
            self.score_labels[col].set(str(int(val)))

            if val > state["best_val"]:
                state["best_val"] = val
                state["best_col"] = col

            self.pending_after = self.after(40, lambda: step(i + 1))

        step(0)

    def _after_state_change(self, trigger_robot=True):
        self.draw_board()
        self.update_status()
        self.render_ai_scores()
        self._sync_timeline_ui()

        if self.is_replay_view():
            self.set_buttons_state(False)
            return

        if self.game_over:
            self.set_buttons_state(False)
            return

        mode = int(self.mode_var.get())
        self.set_buttons_state(
            (not self.robot_thinking) and self.is_human_turn(mode, self.current)
        )

        if trigger_robot and (not self.robot_thinking) and (not self.game_over):
            if not self.is_human_turn(mode, self.current):
                self.after(120, self.robot_step)

    def stop_game(self):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.game_over = True
        self.robot_thinking = False
        self.winner = None
        self.winning_cells = []
        self._after_state_change(trigger_robot=False)

    def reset_game(self, new_game=True):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.robot_thinking = False

        cfg = self.load_config()
        self.rows = cfg["rows"]
        self.cols = cfg["cols"]
        self.starting_color = cfg["starting_color"]

        if new_game:
            self.game_index += 1

        self.board = self.create_board()
        self.current = self.starting_color
        self.game_over = False
        self.winner = None
        self.winning_cells = []

        self.moves = []
        self.view_index = 0

        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)

    # =======================
    # SAVE / LOAD FLOWS
    # =======================
    def ask_save_name(self):
        default_name = (
            f"partie_{self.rows}x{self.cols}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        save_name = simpledialog.askstring(
            "Nom de la partie",
            "Donne un nom à la partie :",
            initialvalue=default_name,
            parent=self,
        )
        if save_name is None:
            return None
        save_name = save_name.strip()
        return save_name if save_name else None

    def build_save_payload(self, save_name: str):
        moves_to_save = self.canonical_moves(self.moves)
        return {
            "save_name": save_name,
            "rows": self.rows,
            "cols": self.cols,
            "starting_color": self.starting_color,
            "mode": int(self.mode_var.get()),
            "game_index": self.game_index,
            "moves": moves_to_save,
            "view_index": self.view_index,
            "ai_mode": self.ai_var.get(),
            "ai_depth": self.clamp_int(self.depth_var.get(), 1, 8, 4),
        }

    def save_game_db_flow(self):
        save_name = self.ask_save_name()
        if not save_name:
            return
        try:
            gid, action = self.upsert_game_to_postgres(save_name)
            if action == "cancel":
                return
            if action == "update":
                messagebox.showinfo(
                    "Sauvegarde BD",
                    f"✅ Sauvegarde écrasée !\n\nID: {gid}\nNom: {save_name}",
                )
            else:
                messagebox.showinfo(
                    "Sauvegarde BD",
                    f"✅ Partie sauvegardée en base !\n\nID: {gid}\nNom: {save_name}",
                )
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder en base : {e}")

    def save_game_json_flow(self):
        save_name = self.ask_save_name()
        if not save_name:
            return

        data = self.build_save_payload(save_name)

        path = filedialog.asksaveasfilename(
            title="Sauvegarder la partie",
            defaultextension=".json",
            initialfile=f"{save_name}.json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return

        # ✅ JSON: si fichier existe déjà -> demander écraser
        if os.path.exists(path):
            ok = messagebox.askyesno(
                "Fichier déjà existant",
                f"⚠️ Le fichier existe déjà :\n{path}\n\nVoulez-vous l'écraser ?",
                parent=self,
            )
            if not ok:
                return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Sauvegarde", "✅ Partie sauvegardée !")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder : {e}")

    def load_game_json_flow(self):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None
        self.robot_thinking = False

        path = filedialog.askopenfilename(
            title="Charger une partie", filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Erreur", f"Fichier invalide : {e}")
            return

        self._apply_loaded_payload(data)
        messagebox.showinfo("Chargement", "✅ Partie chargée !")

    def load_game_db_flow(self):
        try:
            games = self.fetch_saved_games_list()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lire la base : {e}")
            return

        if not games:
            messagebox.showinfo("Base vide", "Aucune partie sauvegardée en base.")
            return

        win = tk.Toplevel(self)
        win.title("Charger depuis la base")
        win.geometry("980x420")
        win.transient(self)
        win.grab_set()

        columns = (
            "ID",
            "Nom",
            "Taille",
            "Mode",
            "IA",
            "Conf",
            "ColsUsed",
            "Coups",
            "Date",
        )
        tree = ttk.Treeview(win, columns=columns, show="headings", height=14)

        col_cfg = [
            ("ID", 60, "center"),
            ("Nom", 240, "w"),
            ("Taille", 80, "center"),
            ("Mode", 120, "center"),
            ("IA", 140, "center"),
            ("Conf", 60, "center"),
            ("ColsUsed", 70, "center"),
            ("Coups", 70, "center"),
            ("Date", 160, "center"),
        ]
        for col, w, anchor in col_cfg:
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor=anchor)

        def mode_name(m):
            return {0: "IA vs IA", 1: "Humain vs IA", 2: "Humain vs Humain"}.get(
                int(m), str(m)
            )

        for row in games:
            (
                gid,
                name,
                r,
                c,
                mode,
                ai_mode,
                ai_depth,
                conf,
                cols_used,
                nb_coups,
                save_date,
            ) = row
            date_str = (
                save_date.strftime("%d/%m/%Y %H:%M")
                if hasattr(save_date, "strftime")
                else str(save_date)
            )
            tree.insert(
                "",
                "end",
                values=(
                    gid,
                    name or "",
                    f"{r}x{c}",
                    mode_name(mode),
                    f"{ai_mode} ({ai_depth})",
                    conf,
                    cols_used,
                    nb_coups,
                    date_str,
                ),
            )

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=(0, 10))

        def do_load():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Sélection", "Sélectionne une partie.")
                return
            item = tree.item(sel[0])
            gid = int(item["values"][0])

            try:
                data = self.fetch_saved_game_by_id(gid)
                if not data:
                    messagebox.showerror("Erreur", "Partie introuvable.")
                    return

                moves_val = data[7]
                moves_list = (
                    json.loads(moves_val) if isinstance(moves_val, str) else moves_val
                )

                payload = {
                    "save_name": data[1],
                    "rows": int(data[2]),
                    "cols": int(data[3]),
                    "starting_color": data[4],
                    "mode": int(data[5]),
                    "game_index": int(data[6]),
                    "moves": list(moves_list) if moves_list else [],
                    "view_index": int(data[8]),
                    "ai_mode": data[9],
                    "ai_depth": int(data[10]),
                }

                self._apply_loaded_payload(payload)
                win.destroy()
                messagebox.showinfo(
                    "Chargement",
                    f"✅ Partie chargée depuis la base !\n\nID: {data[0]}\nNom: {data[1]}",
                )
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de charger : {e}")

        ttk.Button(btns, text="Charger", command=do_load).pack(side=tk.LEFT)
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side=tk.RIGHT)

    def _apply_loaded_payload(self, data: dict):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None
        self.robot_thinking = False

        rows = data.get("rows")
        cols = data.get("cols")
        start = data.get("starting_color")
        moves = data.get("moves", [])
        view_index = data.get("view_index", 0)

        if not isinstance(rows, int) or not (4 <= rows <= 20):
            return messagebox.showerror("Erreur", "rows invalide")
        if not isinstance(cols, int) or not (4 <= cols <= 20):
            return messagebox.showerror("Erreur", "cols invalide")
        if start not in (self.RED, self.YELLOW):
            return messagebox.showerror("Erreur", "starting_color invalide")
        if not isinstance(moves, list) or any((not isinstance(x, int)) for x in moves):
            return messagebox.showerror("Erreur", "moves invalide")
        if not isinstance(view_index, int) or not (0 <= view_index <= len(moves)):
            return messagebox.showerror("Erreur", "view_index invalide")

        self.rows = rows
        self.cols = cols
        self.starting_color = start

        self.mode_var.set(str(int(data.get("mode", 2))))
        self.game_index = int(data.get("game_index", 1))
        self.ai_var.set(data.get("ai_mode", "random"))
        self.depth_var.set(str(self.clamp_int(data.get("ai_depth", 4), 1, 8, 4)))

        self.moves = moves
        self.view_index = view_index

        self.board = self.create_board()
        self.winning_cells = []
        self.game_over = False
        self.winner = None

        last_pos = None
        last_token = None
        for i in range(self.view_index):
            col = self.moves[i]
            token = self.token_for_move_index(i)
            last_token = token
            last_pos = self.drop_token(self.board, col, token)
            if last_pos is None:
                break

        self.current = self.token_for_move_index(self.view_index)

        if self.view_index == len(self.moves):
            if last_pos is not None and last_token is not None:
                rr, cc = last_pos
                cells = self.check_win_cells(self.board, rr, cc, last_token)
                if cells:
                    self.winning_cells = cells
                    self.game_over = True
                    self.winner = last_token
                elif self.is_draw(self.board):
                    self.game_over = True
                    self.winner = None

        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)


if __name__ == "__main__":
    Connect4App().mainloop()
