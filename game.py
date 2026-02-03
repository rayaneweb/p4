# game.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import os
import random
import psycopg2
from psycopg2 import Error
import datetime


class Connect4App(tk.Tk):
    # =======================
    #        CONSTANTS
    # =======================
    EMPTY = "."
    RED = "R"
    YELLOW = "Y"
    CONNECT_N = 4

    CONFIG_PATH = "config.json"

    # Paramètres de connexion PostgreSQL
    DB_HOST = "localhost"
    DB_PORT = 5432
    DB_NAME = "puissance4_db"
    DB_USER = "postgres"
    DB_PASSWORD = "rayane"  # CHANGEZ CE MOT DE PASSE

    COLOR_BG = "#00478e"
    COLOR_HOLE = "#e3f2fd"
    COLOR_RED = "#d32f2f"
    COLOR_YELLOW = "#fbc02d"
    COLOR_WIN = "#00c853"

    def __init__(self):
        super().__init__()
        self.title("Puissance 4+ — Random / Minimax avec Base de Données")
        self.minsize(1050, 700)

        # -------- Config / state --------
        cfg = self.load_config()
        self.rows = cfg["rows"]
        self.cols = cfg["cols"]
        self.starting_color = cfg["starting_color"]

        # Initialisation de la connexion DB
        self.db_connection = None
        self.db_cursor = None
        self.init_database()

        self.board = None
        self.current = self.starting_color
        self.game_over = False
        self.winner = None
        self.winning_cells = []

        self.game_index = 1
        self.moves = []
        self.view_index = 0

        # AI state
        self.robot_thinking = False
        self.pending_after = None

        # UI vars
        self.mode_var = tk.StringVar(value="2")  # 0/1/2
        self.ai_var = tk.StringVar(value="random")  # random/minimax
        self.depth_var = tk.StringVar(value="4")
        self.status_var = tk.StringVar(value="")
        self.nav_var = tk.IntVar(value=0)

        # UI refs
        self.col_buttons = []
        self.score_labels = []

        # Build UI + start
        self._build_ui()
        self.reset_game(new_game=False)

    # =======================
    #        HELPERS
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

    # =======================
    #        DATABASE
    # =======================
    def init_database(self):
        """Initialise la connexion à la base de données et crée les tables si nécessaire"""
        try:
            self.db_connection = psycopg2.connect(
                host=self.DB_HOST,
                port=self.DB_PORT,
                database=self.DB_NAME,
                user=self.DB_USER,
                password=self.DB_PASSWORD,
            )
            self.db_cursor = self.db_connection.cursor()

            # Créer la table si elle n'existe pas
            create_table_query = """
            CREATE TABLE IF NOT EXISTS saved_games (
                id SERIAL PRIMARY KEY,
                save_name VARCHAR(100) NOT NULL,
                save_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rows INTEGER NOT NULL,
                cols INTEGER NOT NULL,
                starting_color CHAR(1) NOT NULL,
                mode INTEGER NOT NULL,
                game_index INTEGER NOT NULL,
                moves JSONB NOT NULL,
                view_index INTEGER NOT NULL,
                ai_mode VARCHAR(20) NOT NULL,
                ai_depth INTEGER NOT NULL
            );
            """
            self.db_cursor.execute(create_table_query)
            self.db_connection.commit()

            print("✅ Connexion à la base de données établie")

        except Error as e:
            print(f"❌ Erreur de connexion à la base de données: {e}")
            # Fallback: continuer sans DB mais avec avertissement
            messagebox.showwarning(
                "Base de données",
                f"Impossible de se connecter à la base de données:\n{e}\n\n"
                "L'application fonctionnera en mode local uniquement.",
            )
            self.db_connection = None
            self.db_cursor = None

    # =======================
    #          CONFIG
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
    #        GAME CORE
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
        # mode == 1 : humain = Rouge
        return current == self.RED

    # --- winning line for highlight ---
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
    #        MINIMAX
    # =======================
    def terminal_state(self, grid):
        # scan for any 4
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

        # horiz
        for r in range(self.rows):
            for c in range(self.cols - 3):
                score += self.evaluate_window(
                    [grid[r][c + i] for i in range(4)], player
                )

        # vert
        for c in range(self.cols):
            for r in range(self.rows - 3):
                score += self.evaluate_window(
                    [grid[r + i][c] for i in range(4)], player
                )

        # diag \
        for r in range(self.rows - 3):
            for c in range(self.cols - 3):
                score += self.evaluate_window(
                    [grid[r + i][c + i] for i in range(4)], player
                )

        # diag /
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
    #           UI
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
        ai_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self._after_state_change(trigger_robot=True),
        )

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
            top, text="Nouvelle partie", command=lambda: self.reset_game(new_game=True)
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Stop", command=self.stop_game).pack(side=tk.LEFT, padx=6)

        # Ajout d'un menu déroulant pour sauvegarder
        save_menu = tk.Menubutton(top, text="💾 Sauver", relief="raised")
        save_menu.pack(side=tk.LEFT, padx=6)
        save_menu.menu = tk.Menu(save_menu, tearoff=0)
        save_menu["menu"] = save_menu.menu
        save_menu.menu.add_command(
            label="Dans la base de données", command=lambda: self.save_game(db=True)
        )
        save_menu.menu.add_command(
            label="Dans un fichier", command=lambda: self.save_game(db=False)
        )

        # Ajout d'un menu déroulant pour charger
        load_menu = tk.Menubutton(top, text="📂 Charger", relief="raised")
        load_menu.pack(side=tk.LEFT, padx=6)
        load_menu.menu = tk.Menu(load_menu, tearoff=0)
        load_menu["menu"] = load_menu.menu
        load_menu.menu.add_command(
            label="Depuis la base de données", command=lambda: self.load_game(db=True)
        )
        load_menu.menu.add_command(
            label="Depuis un fichier", command=lambda: self.load_game(db=False)
        )

        status_bar = ttk.Frame(self, padding=(10, 0))
        status_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 12)).pack(
            anchor="w", pady=8
        )

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body, width=120)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0))

        self.btn_frame = ttk.Frame(left)
        self.btn_frame.pack(fill=tk.X)

        self.canvas = tk.Canvas(left, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.canvas.bind("<Configure>", lambda e: self.draw_board())

        ttk.Label(right, text="Navigation\ncoups", justify="center").pack(pady=(0, 8))
        self.nav_scale = tk.Scale(
            right,
            from_=0,
            to=0,
            orient="vertical",
            showvalue=False,
            variable=self.nav_var,
            length=520,
            command=lambda v: self.on_nav_change(int(float(v))),
        )
        self.nav_scale.pack(fill="y", expand=True)

        self.nav_text = ttk.Label(right, text="0/0")
        self.nav_text.pack(pady=8)

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

    # =======================
    #     STATUS / NAV
    # =======================
    def update_status(self):
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
        self.status_var.set(msg)

    def set_buttons_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in self.col_buttons:
            b.config(state=state)

    def update_nav(self):
        total = len(self.moves)
        self.nav_scale.config(to=total)
        self.nav_scale.set(self.view_index)
        self.nav_text.config(text=f"{self.view_index}/{total}")

    def token_for_move_index(self, i):
        return self.starting_color if i % 2 == 0 else self.other(self.starting_color)

    def rebuild_board_upto(self, k):
        k = max(0, min(k, len(self.moves)))

        self.board = self.create_board()
        self.winning_cells = []
        self.game_over = False
        self.winner = None

        last_pos = None
        last_token = None

        for i in range(k):
            col = self.moves[i]
            token = self.token_for_move_index(i)
            last_token = token
            last_pos = self.drop_token(self.board, col, token)
            if last_pos is None:
                break

        self.view_index = k
        self.current = self.token_for_move_index(k)

        # recalcul gagnant si on est sur une position finale
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

    def on_nav_change(self, k):
        if self.robot_thinking:
            return
        self.rebuild_board_upto(k)

    # =======================
    #        MOVES
    # =======================
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

    # =======================
    #    SCORES (MINIMAX)
    # =======================
    def set_scores_blank(self):
        for v in self.score_labels:
            v.set("")

    def render_ai_scores(self):
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

            self.pending_after = self.after(40, lambda: step(i + 1))  # ~25 fps

        step(0)

    # =======================
    #         ROBOT
    # =======================
    def robot_random_column(self, board):
        cols = self.valid_columns(board)
        return random.choice(cols) if cols else None

    def robot_step(self):
        if self.game_over:
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

            self.pending_after = self.after(40, lambda: step(i + 1))  # ~25 fps

        step(0)

    # =======================
    #      STATE PIPELINE
    # =======================
    def _after_state_change(self, trigger_robot=True):
        self.draw_board()
        self.update_nav()
        self.update_status()
        self.render_ai_scores()

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

    # =======================
    #        COMMANDS
    # =======================
    def stop_game(self):
        # stop any async job
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
        # stop any async job
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.robot_thinking = False

        # reload config each new game
        cfg = self.load_config()
        self.rows = cfg["rows"]
        self.cols = cfg["cols"]
        self.starting_color = cfg["starting_color"]

        if new_game:
            self.game_index += 1

        # state
        self.board = self.create_board()
        self.current = self.starting_color
        self.game_over = False
        self.winner = None
        self.winning_cells = []

        self.moves = []
        self.view_index = 0

        # rebuild UI for new size
        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)

    # =======================
    #       SAVE / LOAD
    # =======================
    def save_game(self, db=True):
        # Demander un nom pour la sauvegarde
        save_name = simpledialog.askstring(
            "Sauvegarder la partie", "Nom de la sauvegarde:", parent=self
        )
        if not save_name:
            return

        data = {
            "rows": self.rows,
            "cols": self.cols,
            "starting_color": self.starting_color,
            "mode": int(self.mode_var.get()),
            "game_index": self.game_index,
            "moves": self.moves,
            "view_index": self.view_index,
            "ai_mode": self.ai_var.get(),
            "ai_depth": self.clamp_int(self.depth_var.get(), 1, 8, 4),
        }

        # Option 1: Sauvegarder dans la base de données
        if db and self.db_connection:
            try:
                insert_query = """
                INSERT INTO saved_games 
                (save_name, rows, cols, starting_color, mode, game_index, moves, view_index, ai_mode, ai_depth)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """

                self.db_cursor.execute(
                    insert_query,
                    (
                        save_name,
                        data["rows"],
                        data["cols"],
                        data["starting_color"],
                        data["mode"],
                        data["game_index"],
                        json.dumps(data["moves"]),
                        data["view_index"],
                        data["ai_mode"],
                        data["ai_depth"],
                    ),
                )
                self.db_connection.commit()

                messagebox.showinfo(
                    "Sauvegarde",
                    f"✅ Partie '{save_name}' sauvegardée dans la base de données !",
                )
                return

            except Error as e:
                messagebox.showerror("Erreur DB", f"Erreur lors de la sauvegarde: {e}")
                # Fallback sur fichier
                if messagebox.askyesno(
                    "Erreur", "Voulez-vous sauvegarder dans un fichier à la place?"
                ):
                    self.save_game(db=False)
                return

        # Option 2: Sauvegarder dans un fichier JSON
        path = filedialog.asksaveasfilename(
            title="Sauvegarder la partie dans un fichier",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{save_name}.json",
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Sauvegarde", f"✅ Partie sauvegardée dans '{path}' !")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder : {e}")

    def load_game(self, db=True):
        # stop any async job
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.robot_thinking = False

        # Option 1: Charger depuis la base de données
        if db and self.db_connection:
            try:
                # Récupérer la liste des sauvegardes
                self.db_cursor.execute(
                    """
                    SELECT id, save_name, save_date 
                    FROM saved_games 
                    ORDER BY save_date DESC
                """
                )
                saves = self.db_cursor.fetchall()

                if not saves:
                    messagebox.showinfo(
                        "Chargement",
                        "Aucune sauvegarde trouvée dans la base de données.",
                    )
                    if messagebox.askyesno(
                        "Chargement",
                        "Voulez-vous charger depuis un fichier à la place?",
                    ):
                        self.load_game(db=False)
                    return

                # Créer une fenêtre de sélection
                selection_window = tk.Toplevel(self)
                selection_window.title("Charger une partie depuis la base")
                selection_window.geometry("500x350")

                tk.Label(
                    selection_window,
                    text="Sélectionnez une sauvegarde:",
                    font=("Arial", 12, "bold"),
                ).pack(pady=10)

                # Créer un Treeview pour afficher les sauvegardes
                columns = ("ID", "Nom", "Date")
                tree = ttk.Treeview(
                    selection_window, columns=columns, show="headings", height=8
                )

                tree.heading("ID", text="ID")
                tree.heading("Nom", text="Nom")
                tree.heading("Date", text="Date de sauvegarde")

                tree.column("ID", width=50, anchor="center")
                tree.column("Nom", width=200)
                tree.column("Date", width=200)

                tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

                # Ajouter les sauvegardes
                for save in saves:
                    save_id, save_name, save_date = save
                    tree.insert(
                        "",
                        "end",
                        values=(
                            save_id,
                            save_name,
                            save_date.strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )

                selected_id = None

                def on_select():
                    nonlocal selected_id
                    selection = tree.selection()
                    if not selection:
                        messagebox.showwarning(
                            "Sélection", "Veuillez sélectionner une sauvegarde."
                        )
                        return

                    item = tree.item(selection[0])
                    selected_id = item["values"][0]
                    selection_window.destroy()
                    load_from_db(selected_id)

                def on_cancel():
                    selection_window.destroy()

                btn_frame = tk.Frame(selection_window)
                btn_frame.pack(pady=10)

                tk.Button(btn_frame, text="Charger", command=on_select, width=12).pack(
                    side=tk.LEFT, padx=5
                )
                tk.Button(
                    btn_frame,
                    text="Charger depuis fichier",
                    command=lambda: [
                        selection_window.destroy(),
                        self.load_game(db=False),
                    ],
                    width=18,
                ).pack(side=tk.LEFT, padx=5)
                tk.Button(btn_frame, text="Annuler", command=on_cancel, width=12).pack(
                    side=tk.LEFT, padx=5
                )

                selection_window.transient(self)
                selection_window.grab_set()

                def load_from_db(save_id):
                    try:
                        self.db_cursor.execute(
                            """
                            SELECT rows, cols, starting_color, mode, game_index, 
                                   moves, view_index, ai_mode, ai_depth
                            FROM saved_games WHERE id = %s
                        """,
                            (save_id,),
                        )

                        data = self.db_cursor.fetchone()
                        if not data:
                            messagebox.showerror("Erreur", "Sauvegarde introuvable")
                            return

                        (
                            rows,
                            cols,
                            start_color,
                            mode,
                            game_index,
                            moves_json,
                            view_index,
                            ai_mode,
                            ai_depth,
                        ) = data

                        # Convertir JSON en liste
                        moves = json.loads(moves_json)

                        # Appliquer les données chargées
                        self.apply_loaded_data(
                            rows,
                            cols,
                            start_color,
                            mode,
                            game_index,
                            moves,
                            view_index,
                            ai_mode,
                            ai_depth,
                        )

                        messagebox.showinfo(
                            "Chargement",
                            f"✅ Partie '{save_name}' chargée depuis la base de données !",
                        )

                    except Error as e:
                        messagebox.showerror(
                            "Erreur DB", f"Erreur lors du chargement: {e}"
                        )

                return

            except Error as e:
                messagebox.showerror("Erreur DB", f"Erreur d'accès à la base: {e}")
                if messagebox.askyesno(
                    "Erreur", "Voulez-vous charger depuis un fichier à la place?"
                ):
                    self.load_game(db=False)
                return

        # Option 2: Charger depuis un fichier JSON
        path = filedialog.askopenfilename(
            title="Charger une partie depuis un fichier", filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Erreur", f"Fichier invalide : {e}")
            return

        # Validation des données
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

        # Appliquer les données
        self.apply_loaded_data(
            rows,
            cols,
            start,
            int(data.get("mode", 2)),
            int(data.get("game_index", 1)),
            moves,
            view_index,
            data.get("ai_mode", "random"),
            self.clamp_int(data.get("ai_depth", 4), 1, 8, 4),
        )

        messagebox.showinfo(
            "Chargement", f"✅ Partie chargée depuis '{os.path.basename(path)}' !"
        )

    def apply_loaded_data(
        self,
        rows,
        cols,
        start_color,
        mode,
        game_index,
        moves,
        view_index,
        ai_mode,
        ai_depth,
    ):
        """Applique les données chargées (utilisé par load_game)"""
        self.rows = rows
        self.cols = cols
        self.starting_color = start_color

        self.mode_var.set(str(mode))
        self.game_index = game_index
        self.ai_var.set(ai_mode)
        self.depth_var.set(str(ai_depth))

        self.moves = moves
        self.view_index = view_index

        # Reconstruire le board
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

        # Détecter l'état terminal
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

        # Reconstruire l'UI
        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)

    # =======================
    #       DESTRUCTOR
    # =======================
    def destroy(self):
        """Ferme proprement la connexion à la DB"""
        if self.db_cursor:
            self.db_cursor.close()
        if self.db_connection:
            self.db_connection.close()
            print("✅ Connexion à la base de données fermée")
        super().destroy()


if __name__ == "__main__":
    app = Connect4App()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.destroy()
