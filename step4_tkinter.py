import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import random

CONFIG_PATH = "config.json"

COLOR_BG = "#00478e"
COLOR_HOLE = "#e3f2fd"
COLOR_RED = "#d32f2f"
COLOR_YELLOW = "#fbc02d"
COLOR_WIN = "#00c853"
EMPTY = "."
RED = "R"
YELLOW = "Y"


# =======================
#        UTILS
# =======================

def other(token):
    return YELLOW if token == RED else RED

def copy_grid(g):
    return [row[:] for row in g]

def clamp_int(v, lo, hi, default):
    try:
        x = int(v)
        return max(lo, min(hi, x))
    except Exception:
        return default


# =======================
#        CONFIG
# =======================

def load_config(path=CONFIG_PATH):
    default = {"rows": 8, "cols": 9, "starting_color": RED}

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

    if not isinstance(rows, int) or rows < 4 or rows > 20:
        rows = default["rows"]
    if not isinstance(cols, int) or cols < 4 or cols > 20:
        cols = default["cols"]
    if start not in (RED, YELLOW):
        start = default["starting_color"]

    return {"rows": rows, "cols": cols, "starting_color": start}


# =======================
#      MINIMAX CORE
# =======================

def terminal_state(grid, rows, cols):
    for r in range(rows):
        for c in range(cols):
            p = grid[r][c]
            if p == EMPTY:
                continue

            if c + 3 < cols and all(grid[r][c+i] == p for i in range(4)):
                return True, p
            if r + 3 < rows and all(grid[r+i][c] == p for i in range(4)):
                return True, p
            if r + 3 < rows and c + 3 < cols and all(grid[r+i][c+i] == p for i in range(4)):
                return True, p
            if r + 3 < rows and c + 3 < cols and all(grid[r+3-i][c+i] == p for i in range(4)):
                return True, p

    if all(grid[0][c] != EMPTY for c in range(cols)):
        return True, None

    return False, None

def evaluate_window(window, player):
    opp = other(player)
    cp = window.count(player)
    co = window.count(opp)
    ce = window.count(EMPTY)

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

def heuristic_score(grid, rows, cols, player):
    score = 0

    center = cols // 2
    score += sum(1 for r in range(rows) if grid[r][center] == player) * 6

    for r in range(rows):
        for c in range(cols - 3):
            score += evaluate_window([grid[r][c+i] for i in range(4)], player)

    for c in range(cols):
        for r in range(rows - 3):
            score += evaluate_window([grid[r+i][c] for i in range(4)], player)

    for r in range(rows - 3):
        for c in range(cols - 3):
            score += evaluate_window([grid[r+i][c+i] for i in range(4)], player)

    for r in range(rows - 3):
        for c in range(cols - 3):
            score += evaluate_window([grid[r+3-i][c+i] for i in range(4)], player)

    return score

def drop_in_grid(grid, rows, col, token):
    for r in range(rows - 1, -1, -1):
        if grid[r][col] == EMPTY:
            grid[r][col] = token
            return (r, col)
    return None

def valid_columns(grid, cols):
    return [c for c in range(cols) if grid[0][c] == EMPTY]

def minimax(grid, rows, cols, depth, alpha, beta, maximizing, player):
    term, winner = terminal_state(grid, rows, cols)
    if term:
        if winner == player:
            return 1_000_000
        if winner == other(player):
            return -1_000_000
        return 0

    if depth == 0:
        return heuristic_score(grid, rows, cols, player)

    moves = valid_columns(grid, cols)
    center = cols // 2
    moves.sort(key=lambda c: abs(c - center))

    if maximizing:
        best = -10**18
        for col in moves:
            g2 = copy_grid(grid)
            drop_in_grid(g2, rows, col, player)
            val = minimax(g2, rows, cols, depth-1, alpha, beta, False, player)
            best = max(best, val)
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best
    else:
        opp = other(player)
        best = 10**18
        for col in moves:
            g2 = copy_grid(grid)
            drop_in_grid(g2, rows, col, opp)
            val = minimax(g2, rows, cols, depth-1, alpha, beta, True, player)
            best = min(best, val)
            beta = min(beta, best)
            if alpha >= beta:
                break
        return best


# =======================
#          GUI
# =======================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Puissance 4+ — Random / Minimax")
        self.minsize(1050, 700)

        # Game state
        self.rows = 8
        self.cols = 9
        self.board = None
        self.current = RED
        self.starting_color = RED
        self.game_over = False
        self.winner = None            # ✅ important
        self.winning_cells = []
        self.game_index = 1

        self.mode = 2
        self.moves = []
        self.view_index = 0

        # AI
        self.robot_thinking = False
        self.pending_after = None

        # UI vars
        self.mode_var = tk.StringVar(value="2")
        self.ai_var = tk.StringVar(value="random")
        self.depth_var = tk.StringVar(value="4")
        self.status_var = tk.StringVar(value="")
        self.nav_var = tk.IntVar(value=0)

        # UI refs
        self.col_buttons = []
        self.score_labels = []

        self._build_ui()
        self.reset_game(new_game=False)

    # ---------- UI build ----------

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Mode joueurs:").pack(side=tk.LEFT)
        mode_combo = ttk.Combobox(top, textvariable=self.mode_var, values=["0", "1", "2"],
                                  width=4, state="readonly")
        mode_combo.pack(side=tk.LEFT, padx=(6, 14))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self.reset_game(new_game=True))

        ttk.Label(top, text="IA:").pack(side=tk.LEFT)
        ai_combo = ttk.Combobox(top, textvariable=self.ai_var, values=["random", "minimax"],
                                width=10, state="readonly")
        ai_combo.pack(side=tk.LEFT, padx=(6, 10))
        ai_combo.bind("<<ComboboxSelected>>", lambda e: self._after_state_change(trigger_robot=True))

        ttk.Label(top, text="Profondeur:").pack(side=tk.LEFT)
        depth_spin = ttk.Spinbox(top, from_=1, to=8, width=5, textvariable=self.depth_var,
                                 command=lambda: self.render_ai_scores())
        depth_spin.pack(side=tk.LEFT, padx=(6, 14))

        ttk.Button(top, text="Nouvelle partie", command=lambda: self.reset_game(new_game=True)).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Stop", command=self.stop_game).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="💾 Sauver", command=self.save_game).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="📂 Charger", command=self.load_game).pack(side=tk.LEFT, padx=6)

        status_bar = ttk.Frame(self, padding=(10, 0))
        status_bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 12)).pack(anchor="w", pady=8)

        # Board
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

        # Nav
        ttk.Label(right, text="Navigation\ncoups", justify="center").pack(pady=(0, 8))
        self.nav_scale = tk.Scale(
            right, from_=0, to=0, orient="vertical",
            showvalue=False, variable=self.nav_var, length=520,
            command=lambda v: self.on_nav_change(int(float(v)))
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
            b = ttk.Button(row_btn, text=str(c+1), width=4, command=lambda cc=c: self.on_click(cc))
            b.pack(side=tk.LEFT, padx=3, pady=2)
            self.col_buttons.append(b)

        for c in range(self.cols):
            v = tk.StringVar(value="")
            lbl = ttk.Label(row_scores, textvariable=v, width=7, anchor="center")
            lbl.pack(side=tk.LEFT, padx=3, pady=(0, 6))
            self.score_labels.append(v)

    # ---------- Drawing ----------

    def cell_color(self, val):
        if val == RED:
            return COLOR_RED
        if val == YELLOW:
            return COLOR_YELLOW
        return COLOR_HOLE

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

        self.canvas.create_rectangle(x0, y0, x0 + board_w, y0 + board_h, fill=COLOR_BG, outline="")

        win_set = set(self.winning_cells)

        for r in range(self.rows):
            for c in range(self.cols):
                cx0 = x0 + c * cell + pad
                cy0 = y0 + r * cell + pad
                cx1 = x0 + (c+1) * cell - pad
                cy1 = y0 + (r+1) * cell - pad

                fill = self.cell_color(self.board[r][c])
                outline = COLOR_WIN if (r, c) in win_set else ""
                width = 4 if (r, c) in win_set else 1
                self.canvas.create_oval(cx0, cy0, cx1, cy1, fill=fill, outline=outline, width=width)

    # ---------- Win detection (cells) ----------

    def check_win_cells(self, last_row, last_col, token):
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in directions:
            cells = [(last_row, last_col)]

            r, c = last_row + dr, last_col + dc
            while 0 <= r < self.rows and 0 <= c < self.cols and self.board[r][c] == token:
                cells.append((r, c))
                r += dr
                c += dc

            r, c = last_row - dr, last_col - dc
            while 0 <= r < self.rows and 0 <= c < self.cols and self.board[r][c] == token:
                cells.insert(0, (r, c))
                r -= dr
                c -= dc

            if len(cells) >= 4:
                return cells[:4]
        return []

    def is_draw(self):
        return all(self.board[0][c] != EMPTY for c in range(self.cols))

    # ---------- Status / Buttons ----------

    def update_status(self):
        if self.game_over:
            if self.winner == RED:
                msg = f"Partie #{self.game_index} — 🎉 Gagnant : Rouge"
            elif self.winner == YELLOW:
                msg = f"Partie #{self.game_index} — 🎉 Gagnant : Jaune"
            else:
                msg = f"Partie #{self.game_index} — 🤝 Match nul"
        else:
            name = "Rouge" if self.current == RED else "Jaune"
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

    # ---------- Navigation / History ----------

    def token_for_move_index(self, i):
        return self.starting_color if i % 2 == 0 else other(self.starting_color)

    def rebuild_board_upto(self, k):
        k = max(0, min(k, len(self.moves)))

        self.board = create_board(self.rows, self.cols)
        self.winning_cells = []
        self.game_over = False
        self.winner = None

        for i in range(k):
            col = self.moves[i]
            token = self.token_for_move_index(i)
            drop_token(self.board, col, token)

        self.view_index = k
        self.current = self.token_for_move_index(k)

        # ⚠️ IMPORTANT: après navigation, on ne lance PAS le robot automatiquement
        self._after_state_change(trigger_robot=False)

    def on_nav_change(self, k):
        if self.robot_thinking:
            return
        self.rebuild_board_upto(k)

    # ---------- Moves ----------

    def play_move(self, col, token):
        pos = drop_token(self.board, col, token)
        if pos is None:
            return True

        # couper redo si on est dans le passé
        if self.view_index < len(self.moves):
            del self.moves[self.view_index:]

        self.moves.append(col)
        self.view_index = len(self.moves)

        row, _ = pos

        cells = self.check_win_cells(row, col, token)
        if cells:
            self.winning_cells = cells
            self.game_over = True
            self.winner = token  # ✅ gagnant stocké
            self._after_state_change(trigger_robot=False)
            return False

        if self.is_draw():
            self.winning_cells = []
            self.game_over = True
            self.winner = None
            self._after_state_change(trigger_robot=False)
            return False

        self.current = other(self.current)
        self._after_state_change(trigger_robot=True)
        return True

    def on_click(self, col):
        if self.game_over or self.robot_thinking:
            return
        if not is_human_turn(self.mode, self.current):
            return

        cont = self.play_move(col, self.current)
        if not cont:
            return

        if self.mode in (0, 1) and not is_human_turn(self.mode, self.current) and not self.game_over:
            self.after(120, self.robot_step)

    # ---------- AI scores under columns ----------

    def set_scores_blank(self):
        for v in self.score_labels:
            v.set("")

    def render_ai_scores(self):
        if self.ai_var.get() != "minimax":
            self.set_scores_blank()
            return
        if self.robot_thinking:
            return

        depth = clamp_int(self.depth_var.get(), 1, 8, 4)
        self.compute_scores_async(depth)

    def compute_scores_async(self, depth):
        # annuler tâche précédente
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        grid0 = copy_grid(self.board)
        player = self.current
        valids = valid_columns(grid0, self.cols)

        for c in range(self.cols):
            self.score_labels[c].set("N/A" if c not in valids else "...")

        col_list = list(range(self.cols))

        def step(i=0):
            if self.ai_var.get() != "minimax":
                return
            if self.robot_thinking:
                return
            if i >= len(col_list):
                return

            col = col_list[i]
            if col not in valids:
                self.score_labels[col].set("N/A")
            else:
                g2 = copy_grid(grid0)
                drop_in_grid(g2, self.rows, col, player)
                val = minimax(g2, self.rows, self.cols, depth-1, -10**18, 10**18, False, player)
                self.score_labels[col].set(str(int(val)))

            self.pending_after = self.after(40, lambda: step(i+1))  # ~25fps

        step(0)

    # ---------- Robot (random / minimax async) ----------

    def robot_step(self):
        if self.game_over:
            return

        if is_human_turn(self.mode, self.current):
            self.set_buttons_state(True)
            return

        self.set_buttons_state(False)

        if self.ai_var.get() == "random":
            col = robot_random_column(self.board)
            if col is None:
                self.game_over = True
                self.winner = None
                self.winning_cells = []
                self._after_state_change(trigger_robot=False)
                return

            cont = self.play_move(col, self.current)
            if not cont:
                return

            if self.mode == 0 and not self.game_over:
                self.after(250, self.robot_step)
            else:
                self.set_buttons_state(True)
            return

        depth = clamp_int(self.depth_var.get(), 1, 8, 4)
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

        grid0 = copy_grid(self.board)
        player = self.current
        valids = valid_columns(grid0, self.cols)

        for c in range(self.cols):
            self.score_labels[c].set("N/A" if c not in valids else "...")

        center = self.cols // 2
        col_list = list(range(self.cols))
        col_list.sort(key=lambda c: abs(c - center))

        state = {"best_col": None, "best_val": -10**18}

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

                if self.mode == 0 and not self.game_over:
                    self.after(250, self.robot_step)
                else:
                    self.set_buttons_state(True)
                return

            col = col_list[i]
            if col not in valids:
                self.score_labels[col].set("N/A")
                self.pending_after = self.after(30, lambda: step(i+1))
                return

            g2 = copy_grid(grid0)
            drop_in_grid(g2, self.rows, col, player)
            val = minimax(g2, self.rows, self.cols, depth-1, -10**18, 10**18, False, player)
            self.score_labels[col].set(str(int(val)))

            if val > state["best_val"]:
                state["best_val"] = val
                state["best_col"] = col

            self.pending_after = self.after(40, lambda: step(i+1))  # ~25fps

        step(0)

    # ---------- State update pipeline ----------

    def _after_state_change(self, trigger_robot=True):
        self.draw_board()
        self.update_nav()
        self.update_status()
        self.render_ai_scores()

        # ✅ STOP total si partie finie
        if self.game_over:
            self.set_buttons_state(False)
            return

        # sinon activer si humain
        self.set_buttons_state((not self.robot_thinking) and is_human_turn(self.mode, self.current))

        if trigger_robot and (not self.robot_thinking) and (not self.game_over):
            if not is_human_turn(self.mode, self.current):
                self.after(120, self.robot_step)

    # ---------- Commands ----------

    def stop_game(self):
        self.game_over = True
        self.robot_thinking = False
        self.winner = None
        self.winning_cells = []
        self._after_state_change(trigger_robot=False)

    def reset_game(self, new_game=True):
        # stop any async
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.robot_thinking = False
        self.mode = int(self.mode_var.get())

        cfg = load_config()
        self.rows = cfg["rows"]
        self.cols = cfg["cols"]
        self.current = cfg["starting_color"]
        self.starting_color = self.current

        if new_game:
            self.game_index += 1

        self.moves = []
        self.view_index = 0
        self.game_over = False
        self.winner = None
        self.winning_cells = []
        self.board = create_board(self.rows, self.cols)

        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)

    # ---------- Save / Load ----------

    def save_game(self):
        data = {
            "rows": self.rows,
            "cols": self.cols,
            "starting_color": self.starting_color,
            "mode": self.mode,
            "game_index": self.game_index,
            "moves": self.moves,
            "view_index": self.view_index,
            "ai_mode": self.ai_var.get(),
            "ai_depth": clamp_int(self.depth_var.get(), 1, 8, 4),
        }

        path = filedialog.asksaveasfilename(
            title="Sauvegarder la partie",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Sauvegarde", "✅ Partie sauvegardée !")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder : {e}")

    def load_game(self):
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        self.robot_thinking = False

        path = filedialog.askopenfilename(
            title="Charger une partie",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Erreur", f"Fichier invalide : {e}")
            return

        rows = data.get("rows")
        cols = data.get("cols")
        start = data.get("starting_color")
        mv = data.get("moves", [])
        vi = data.get("view_index", 0)

        if not isinstance(rows, int) or not (4 <= rows <= 20):
            return messagebox.showerror("Erreur", "rows invalide")
        if not isinstance(cols, int) or not (4 <= cols <= 20):
            return messagebox.showerror("Erreur", "cols invalide")
        if start not in (RED, YELLOW):
            return messagebox.showerror("Erreur", "starting_color invalide")
        if not isinstance(mv, list) or any((not isinstance(x, int)) for x in mv):
            return messagebox.showerror("Erreur", "moves invalide")
        if not isinstance(vi, int) or not (0 <= vi <= len(mv)):
            return messagebox.showerror("Erreur", "view_index invalide")

        self.rows = rows
        self.cols = cols
        self.starting_color = start
        self.current = start
        self.mode = int(data.get("mode", 2))
        self.game_index = int(data.get("game_index", 1))
        self.moves = mv
        self.view_index = vi

        self.ai_var.set(data.get("ai_mode", "random"))
        self.depth_var.set(str(clamp_int(data.get("ai_depth", 4), 1, 8, 4)))
        self.mode_var.set(str(self.mode))

        self.board = create_board(self.rows, self.cols)
        self.winning_cells = []
        self.game_over = False
        self.winner = None

        # rejouer jusqu'à view_index
        for i in range(self.view_index):
            col = self.moves[i]
            token = self.starting_color if i % 2 == 0 else other(self.starting_color)
            drop_token(self.board, col, token)

        self.current = self.starting_color if self.view_index % 2 == 0 else other(self.starting_color)

        self.rebuild_column_widgets()
        self._after_state_change(trigger_robot=True)

        messagebox.showinfo("Chargement", "✅ Partie chargée !")


if __name__ == "__main__":
    App().mainloop()
