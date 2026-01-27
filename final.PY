

import json
import os
import random
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

CONNECT_N = 4

DEFAULT_CONFIG = {
    "rows": 8,
    "cols": 9,
    "starting_color": "R",  # "R" or "Y"
}

COLOR_NAME = {"R": "Rouge", "Y": "Jaune"}
TOKEN_COLOR = {"R": "#d32f2f", "Y": "#fbc02d"}  # red / yellow-ish
EMPTY_COLOR = "#1e88e5"  # board blue
HOLE_COLOR = "#e3f2fd"   # empty hole color

def other(player: str) -> str:
    return "Y" if player == "R" else "R"


def clamp_int(v, lo, hi, default):
    try:
        x = int(v)
        return max(lo, min(hi, x))
    except Exception:
        return default


class Connect4Game:
    def __init__(self, rows: int, cols: int, starting: str = "R"):
        self.rows = rows
        self.cols = cols
        self.starting = starting if starting in ("R", "Y") else "R"
        self.reset()

    def reset(self):
        self.grid = [["." for _ in range(self.cols)] for _ in range(self.rows)]
        self.current = self.starting
        self.finished = False
        self.winner = None  # "R" or "Y" or None
        self.winning_cells = []  # list[(r,c)]
        self.history = []  # list of columns played
        self.cursor = 0    # how many moves are currently applied (0..len(history))

    def valid_columns(self, grid=None):
        g = grid if grid is not None else self.grid
        valid = []
        for c in range(self.cols):
            if g[0][c] == ".":
                valid.append(c)
        return valid

    def is_full(self, grid=None):
        g = grid if grid is not None else self.grid
        return all(g[0][c] != "." for c in range(self.cols))

    def drop(self, col: int, player: str, grid=None):
        """Return (row, col) if success, else None."""
        g = grid if grid is not None else self.grid
        if col < 0 or col >= self.cols:
            return None
        if g[0][col] != ".":
            return None
        for r in range(self.rows - 1, -1, -1):
            if g[r][col] == ".":
                g[r][col] = player
                return (r, col)
        return None

    def apply_move(self, col: int):
        """Applies a move to the *current timeline* (cursor). If cursor < len(history), truncates redo branch."""
        if self.finished:
            return False, "La partie est terminée."
        if col not in self.valid_columns():
            return False, "Colonne invalide ou pleine."

        # if we were in the past, cut future
        if self.cursor < len(self.history):
            self.history = self.history[: self.cursor]

        pos = self.drop(col, self.current)
        if pos is None:
            return False, "Colonne pleine."

        self.history.append(col)
        self.cursor += 1

        win_cells = self.check_win_from(pos, self.grid)
        if win_cells:
            self.finished = True
            self.winner = self.current
            self.winning_cells = win_cells
        elif self.is_full(self.grid):
            self.finished = True
            self.winner = None
            self.winning_cells = []
        else:
            self.current = other(self.current)

        return True, ""

    def rebuild_from_history(self, cursor: int):
        """Rebuild grid by replaying history[0:cursor]."""
        cursor = max(0, min(cursor, len(self.history)))
        self.grid = [["." for _ in range(self.cols)] for _ in range(self.rows)]
        self.current = self.starting
        self.finished = False
        self.winner = None
        self.winning_cells = []

        last_pos = None
        for i in range(cursor):
            col = self.history[i]
            pos = self.drop(col, self.current)
            if pos is None:
                # corrupted history
                self.finished = True
                self.winner = None
                self.winning_cells = []
                break
            last_pos = pos

            win_cells = self.check_win_from(pos, self.grid)
            if win_cells:
                self.finished = True
                self.winner = self.current
                self.winning_cells = win_cells
                # stop applying moves beyond a terminal state
                cursor = i + 1
                break
            if self.is_full(self.grid):
                self.finished = True
                self.winner = None
                self.winning_cells = []
                cursor = i + 1
                break

            self.current = other(self.current)

        self.cursor = cursor

    def undo(self):
        if self.cursor <= 0:
            return False
        self.rebuild_from_history(self.cursor - 1)
        return True

    def redo(self):
        if self.cursor >= len(self.history):
            return False
        self.rebuild_from_history(self.cursor + 1)
        return True

    def check_win_from(self, last_pos, grid):
        if last_pos is None:
            return []
        (r, c) = last_pos
        player = grid[r][c]
        if player == ".":
            return []

        directions = [
            (0, 1),   # horizontal
            (1, 0),   # vertical
            (1, 1),   # diag \
            (1, -1),  # diag /
        ]

        for dr, dc in directions:
            cells = [(r, c)]

            # extend backward
            rr, cc = r - dr, c - dc
            while 0 <= rr < self.rows and 0 <= cc < self.cols and grid[rr][cc] == player:
                cells.insert(0, (rr, cc))
                rr -= dr
                cc -= dc

            # extend forward
            rr, cc = r + dr, c + dc
            while 0 <= rr < self.rows and 0 <= cc < self.cols and grid[rr][cc] == player:
                cells.append((rr, cc))
                rr += dr
                cc += dc

            if len(cells) >= CONNECT_N:
                # pick a contiguous 4 that includes last_pos
                # simplest: return the first 4 in the line that contains last_pos
                # but to “highlight winning line”, return exactly 4 cells near last_pos
                # We'll choose the 4-window with max closeness to last_pos index.
                idx = cells.index((r, c))
                best = None
                for start in range(0, len(cells) - CONNECT_N + 1):
                    window = cells[start:start + CONNECT_N]
                    if (r, c) in window:
                        # prefer window centered around last_pos
                        center = start + (CONNECT_N - 1) / 2
                        score = abs(center - idx)
                        if best is None or score < best[0]:
                            best = (score, window)
                return best[1] if best else cells[:CONNECT_N]

        return []


# ---------- Minimax (depth-limited) ----------

def copy_grid(grid):
    return [row[:] for row in grid]


def evaluate_window(window, player):
    opp = other(player)
    count_p = window.count(player)
    count_o = window.count(opp)
    count_e = window.count(".")

    if count_p == 4:
        return 100000
    if count_o == 4:
        return -100000

    score = 0
    # Favor building 3s and 2s; penalize opponent threats
    if count_p == 3 and count_e == 1:
        score += 50
    elif count_p == 2 and count_e == 2:
        score += 10

    if count_o == 3 and count_e == 1:
        score -= 80
    elif count_o == 2 and count_e == 2:
        score -= 10
    return score


def heuristic_score(grid, player):
    rows = len(grid)
    cols = len(grid[0])

    score = 0

    # center preference
    center_col = cols // 2
    center_count = sum(1 for r in range(rows) if grid[r][center_col] == player)
    score += center_count * 6

    # Horizontal
    for r in range(rows):
        for c in range(cols - 3):
            window = [grid[r][c + i] for i in range(4)]
            score += evaluate_window(window, player)

    # Vertical
    for c in range(cols):
        for r in range(rows - 3):
            window = [grid[r + i][c] for i in range(4)]
            score += evaluate_window(window, player)

    # Diag \
    for r in range(rows - 3):
        for c in range(cols - 3):
            window = [grid[r + i][c + i] for i in range(4)]
            score += evaluate_window(window, player)

    # Diag /
    for r in range(rows - 3):
        for c in range(cols - 3):
            window = [grid[r + 3 - i][c + i] for i in range(4)]
            score += evaluate_window(window, player)

    return score


def terminal_state(game: Connect4Game, grid):
    # check win by scanning (small boards => OK)
    rows, cols = game.rows, game.cols
    for r in range(rows):
        for c in range(cols):
            p = grid[r][c]
            if p == ".":
                continue
            # only need to detect existence
            # right
            if c + 3 < cols and all(grid[r][c+i] == p for i in range(4)):
                return True, p
            # down
            if r + 3 < rows and all(grid[r+i][c] == p for i in range(4)):
                return True, p
            # diag \
            if r + 3 < rows and c + 3 < cols and all(grid[r+i][c+i] == p for i in range(4)):
                return True, p
            # diag /
            if r + 3 < rows and c + 3 < cols and all(grid[r+3-i][c+i] == p for i in range(4)):
                return True, p

    # draw?
    if all(grid[0][c] != "." for c in range(cols)):
        return True, None
    return False, None


def minimax(game: Connect4Game, grid, depth, alpha, beta, maximizing, player):
    is_term, winner = terminal_state(game, grid)
    if is_term:
        if winner == player:
            return 1000000
        if winner == other(player):
            return -1000000
        return 0
    if depth == 0:
        return heuristic_score(grid, player)

    valid_cols = []
    cols = game.cols
    for c in range(cols):
        if grid[0][c] == ".":
            valid_cols.append(c)

    if maximizing:
        value = -10**18
        for col in valid_cols:
            g2 = copy_grid(grid)
            # drop for 'player'
            _drop_in_grid(game, g2, col, player)
            value = max(value, minimax(game, g2, depth - 1, alpha, beta, False, player))
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value
    else:
        value = 10**18
        opp = other(player)
        for col in valid_cols:
            g2 = copy_grid(grid)
            _drop_in_grid(game, g2, col, opp)
            value = min(value, minimax(game, g2, depth - 1, alpha, beta, True, player))
            beta = min(beta, value)
            if alpha >= beta:
                break
        return value


def _drop_in_grid(game: Connect4Game, grid, col, player):
    for r in range(game.rows - 1, -1, -1):
        if grid[r][col] == ".":
            grid[r][col] = player
            return (r, col)
    return None


# ---------- UI ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Puissance 4 — 8x9 (Random / Minimax)")

        self.config_data = self.load_config()
        self.game_id = 1

        self.game = Connect4Game(
            rows=self.config_data["rows"],
            cols=self.config_data["cols"],
            starting=self.config_data["starting_color"],
        )

        self.ai_mode = tk.StringVar(value="random")  # random|minimax
        self.ai_depth = tk.IntVar(value=4)

        self.players_mode = tk.StringVar(value="1")  # "0","1","2"
        self.human_is = tk.StringVar(value="R")       # for 1-player: which color is human
        self.robot_thinking = False
        self.pending_after = None

        self._build_ui()
        self._render_all()

    # ----- Config / Save / Load -----

    def load_config(self):
        path = "config.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rows = clamp_int(data.get("rows"), 4, 20, DEFAULT_CONFIG["rows"])
                cols = clamp_int(data.get("cols"), 4, 20, DEFAULT_CONFIG["cols"])
                starting = data.get("starting_color", DEFAULT_CONFIG["starting_color"])
                starting = starting if starting in ("R", "Y") else "R"
                return {"rows": rows, "cols": cols, "starting_color": starting}
            except Exception:
                pass
        return dict(DEFAULT_CONFIG)

    def save_config(self):
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, indent=2, ensure_ascii=False)

    def serialize_game(self):
        return {
            "game_id": self.game_id,
            "rows": self.game.rows,
            "cols": self.game.cols,
            "starting_color": self.game.starting,
            "history": self.game.history,
            "cursor": self.game.cursor,
        }

    def deserialize_game(self, data):
        rows = clamp_int(data.get("rows"), 4, 20, self.config_data["rows"])
        cols = clamp_int(data.get("cols"), 4, 20, self.config_data["cols"])
        starting = data.get("starting_color", self.config_data["starting_color"])
        starting = starting if starting in ("R", "Y") else "R"

        self.game = Connect4Game(rows, cols, starting)
        self.game_id = int(data.get("game_id", self.game_id))
        self.game.history = list(data.get("history", []))
        self.game.rebuild_from_history(int(data.get("cursor", len(self.game.history))))

        # update config_data to match loaded game (so UI stays consistent)
        self.config_data["rows"] = rows
        self.config_data["cols"] = cols
        self.config_data["starting_color"] = starting

    # ----- UI construction -----

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        # Mode selection
        ttk.Label(top, text="Mode joueurs:").pack(side=tk.LEFT)
        mode_box = ttk.Combobox(top, width=5, state="readonly",
                                values=["0", "1", "2"],
                                textvariable=self.players_mode)
        mode_box.pack(side=tk.LEFT, padx=(6, 12))
        mode_box.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        ttk.Label(top, text="IA:").pack(side=tk.LEFT)
        ai_box = ttk.Combobox(top, width=9, state="readonly",
                              values=["random", "minimax"],
                              textvariable=self.ai_mode)
        ai_box.pack(side=tk.LEFT, padx=(6, 6))
        ai_box.bind("<<ComboboxSelected>>", lambda e: self._render_ai_scores())

        ttk.Label(top, text="Profondeur:").pack(side=tk.LEFT)
        depth_spin = ttk.Spinbox(top, width=4, from_=1, to=8, textvariable=self.ai_depth,
                                 command=self._render_ai_scores)
        depth_spin.pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(top, text="Humain (si 1 joueur):").pack(side=tk.LEFT)
        human_box = ttk.Combobox(top, width=5, state="readonly",
                                 values=["R", "Y"],
                                 textvariable=self.human_is)
        human_box.pack(side=tk.LEFT, padx=(6, 12))

        ttk.Button(top, text="Nouvelle partie", command=self.new_game).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Redo", command=self.redo).pack(side=tk.LEFT, padx=6)

        ttk.Button(top, text="Sauvegarder", command=self.save_game).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Charger", command=self.load_game).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Paramétrage", command=self.open_settings).pack(side=tk.LEFT, padx=6)

        # Status
        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, padding=(8, 4)).pack(side=tk.TOP, fill=tk.X)

        # Board area
        self.board_frame = ttk.Frame(self, padding=(8, 8))
        self.board_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Column buttons
        self.col_btn_frame = ttk.Frame(self.board_frame)
        self.col_btn_frame.pack(side=tk.TOP, fill=tk.X)

        self.col_buttons = []
        for c in range(self.game.cols):
            b = ttk.Button(self.col_btn_frame, text=str(c+1), width=4,
                           command=lambda cc=c: self.on_human_click(cc))
            b.pack(side=tk.LEFT, padx=2)
            self.col_buttons.append(b)

        # Canvas
        self.canvas = tk.Canvas(self.board_frame, bg="white", highlightthickness=0)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(8, 4))
        self.canvas.bind("<Configure>", lambda e: self._render_board())

        # AI scores under columns
        self.score_frame = ttk.Frame(self.board_frame)
        self.score_frame.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))
        self.score_labels = []
        for c in range(self.game.cols):
            v = tk.StringVar(value="")
            lbl = ttk.Label(self.score_frame, textvariable=v, width=6, anchor="center")
            lbl.pack(side=tk.LEFT, padx=2)
            self.score_labels.append(v)

        # Navigation in history
        nav = ttk.Frame(self, padding=8)
        nav.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(nav, text="Navigation coups:").pack(side=tk.LEFT)
        self.nav_scale = ttk.Scale(nav, from_=0, to=0, value=0, command=self.on_nav_change)
        self.nav_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        self.nav_text = tk.StringVar(value="0 / 0")
        ttk.Label(nav, textvariable=self.nav_text).pack(side=tk.LEFT)

    def _rebuild_column_widgets(self):
        # clear old
        for w in self.col_btn_frame.winfo_children():
            w.destroy()
        for w in self.score_frame.winfo_children():
            w.destroy()

        self.col_buttons = []
        self.score_labels = []

        for c in range(self.game.cols):
            b = ttk.Button(self.col_btn_frame, text=str(c+1), width=4,
                           command=lambda cc=c: self.on_human_click(cc))
            b.pack(side=tk.LEFT, padx=2)
            self.col_buttons.append(b)

        for c in range(self.game.cols):
            v = tk.StringVar(value="")
            lbl = ttk.Label(self.score_frame, textvariable=v, width=6, anchor="center")
            lbl.pack(side=tk.LEFT, padx=2)
            self.score_labels.append(v)

    # ----- Rendering -----

    def _render_all(self):
        self._update_status()
        self._render_board()
        self._update_nav()
        self._render_ai_scores()
        self._maybe_robot_turn()

    def _render_board(self):
        c = self.canvas
        c.delete("all")

        rows, cols = self.game.rows, self.game.cols

        w = max(200, c.winfo_width())
        h = max(200, c.winfo_height())

        # fit cells
        cell = min(w / cols, h / rows)
        pad = cell * 0.08

        board_w = cell * cols
        board_h = cell * rows
        x0 = (w - board_w) / 2
        y0 = (h - board_h) / 2

        # board background
        c.create_rectangle(x0, y0, x0 + board_w, y0 + board_h, fill=EMPTY_COLOR, outline="")

        win_set = set(self.game.winning_cells)

        for r in range(rows):
            for col in range(cols):
                cx0 = x0 + col * cell + pad
                cy0 = y0 + r * cell + pad
                cx1 = x0 + (col + 1) * cell - pad
                cy1 = y0 + (r + 1) * cell - pad

                val = self.game.grid[r][col]
                fill = HOLE_COLOR if val == "." else TOKEN_COLOR[val]

                outline = ""
                width = 1
                if (r, col) in win_set:
                    outline = "#00c853"  # green highlight
                    width = 5

                c.create_oval(cx0, cy0, cx1, cy1, fill=fill, outline=outline, width=width)

    def _update_status(self):
        gid = self.game_id
        cur = self.game.current
        if self.game.finished:
            if self.game.winner is None:
                msg = f"Partie #{gid} — Match nul."
            else:
                msg = f"Partie #{gid} — Gagnant: {COLOR_NAME[self.game.winner]}."
        else:
            msg = f"Partie #{gid} — À jouer: {COLOR_NAME[cur]}."
        if self.robot_thinking:
            msg += "  (IA réfléchit...)"
        self.status.set(msg)

    def _update_nav(self):
        total = len(self.game.history)
        self.nav_scale.configure(to=max(0, total))
        self.nav_scale.set(self.game.cursor)
        self.nav_text.set(f"{self.game.cursor} / {total}")

    def _set_scores_blank(self):
        for v in self.score_labels:
            v.set("")

    def _render_ai_scores(self):
        # Show minimax values under columns only if minimax selected
        if self.ai_mode.get() != "minimax":
            self._set_scores_blank()
            return
        # Only compute/display scores for current position (cursor == len(history))
        # If user is "in the past", still show scores for that position
        # We'll compute quickly at low rate (synchronous) only if not robot thinking.
        if self.robot_thinking:
            return

        depth = clamp_int(self.ai_depth.get(), 1, 8, 4)
        valid = self.game.valid_columns(self.game.grid)

        # for filled columns -> N/A
        for c in range(self.game.cols):
            if c not in valid:
                self.score_labels[c].set("N/A")
            else:
                self.score_labels[c].set("...")

        # compute asynchronously column-by-column for visible progression
        self._compute_scores_async(depth)

    # ----- Interaction -----

    def on_mode_change(self):
        self._maybe_robot_turn()

    def on_human_click(self, col):
        if self.robot_thinking:
            return

        if not self.is_human_turn():
            return

        ok, err = self.game.apply_move(col)
        if not ok:
            messagebox.showinfo("Info", err)
            return

        self._after_any_state_change()

    def on_nav_change(self, val):
        if self.robot_thinking:
            return
        try:
            target = int(float(val) + 0.5)
        except Exception:
            return
        if target == self.game.cursor:
            return
        self.game.rebuild_from_history(target)
        self._after_any_state_change(trigger_robot=False)

    def new_game(self):
        if self.robot_thinking:
            return

        self.game_id += 1
        self.game = Connect4Game(
            rows=self.config_data["rows"],
            cols=self.config_data["cols"],
            starting=self.config_data["starting_color"],
        )
        self._rebuild_column_widgets()
        self._after_any_state_change()

    def undo(self):
        if self.robot_thinking:
            return
        if not self.game.undo():
            return
        self._after_any_state_change(trigger_robot=False)

    def redo(self):
        if self.robot_thinking:
            return
        if not self.game.redo():
            return
        self._after_any_state_change(trigger_robot=False)

    def save_game(self):
        if self.robot_thinking:
            return

        default_name = f"game_{self.game_id}.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.serialize_game(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Erreur", f"Sauvegarde impossible:\n{e}")

    def load_game(self):
        if self.robot_thinking:
            return
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.deserialize_game(data)
            self.save_config()  # keep config consistent
            self._rebuild_column_widgets()
            self._after_any_state_change(trigger_robot=False)
        except Exception as e:
            messagebox.showerror("Erreur", f"Chargement impossible:\n{e}")

    def open_settings(self):
        if self.robot_thinking:
            return

        win = tk.Toplevel(self)
        win.title("Paramétrage")
        win.transient(self)
        win.grab_set()

        rows_var = tk.StringVar(value=str(self.config_data["rows"]))
        cols_var = tk.StringVar(value=str(self.config_data["cols"]))
        start_var = tk.StringVar(value=self.config_data["starting_color"])

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Lignes (4..20):").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=rows_var, width=8).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="Colonnes (4..20):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=cols_var, width=8).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="Couleur qui commence:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(frm, state="readonly", values=["R", "Y"], textvariable=start_var, width=6)\
            .grid(row=2, column=1, sticky="w", pady=4)

        hint = ttk.Label(frm, text="Appliqué à la prochaine 'Nouvelle partie'.", foreground="#555")
        hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 10))

        def apply_and_close():
            r = clamp_int(rows_var.get(), 4, 20, self.config_data["rows"])
            c = clamp_int(cols_var.get(), 4, 20, self.config_data["cols"])
            s = start_var.get() if start_var.get() in ("R", "Y") else self.config_data["starting_color"]
            self.config_data = {"rows": r, "cols": c, "starting_color": s}
            self.save_config()
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(btns, text="Annuler", command=win.destroy).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btns, text="Enregistrer", command=apply_and_close).pack(side=tk.RIGHT)

    # ----- Robot logic -----

    def is_human_turn(self):
        if self.game.finished:
            return False

        m = self.players_mode.get()
        if m == "2":
            return True
        if m == "0":
            return False
        # m == "1"
        return self.game.current == self.human_is.get()

    def is_robot_turn(self):
        if self.game.finished:
            return False
        m = self.players_mode.get()
        if m == "2":
            return False
        if m == "0":
            return True
        # m == "1"
        return self.game.current != self.human_is.get()

    def _maybe_robot_turn(self):
        if self.robot_thinking:
            return
        if self.is_robot_turn():
            self.start_robot_move()

    def start_robot_move(self):
        if self.game.finished or self.robot_thinking:
            return
        if not self.is_robot_turn():
            return

        # Disable column buttons during robot turn
        self.robot_thinking = True
        self._update_status()
        self._render_ai_scores()

        # choose algorithm
        if self.ai_mode.get() == "random":
            self.after(120, self._robot_play_random)
        else:
            depth = clamp_int(self.ai_depth.get(), 1, 8, 4)
            self._robot_play_minimax_async(depth)

    def _robot_play_random(self):
        if self.game.finished:
            self.robot_thinking = False
            self._update_status()
            return

        valid = self.game.valid_columns()
        if not valid:
            self.robot_thinking = False
            self._after_any_state_change()
            return

        col = random.choice(valid)
        self.game.apply_move(col)

        self.robot_thinking = False
        self._after_any_state_change()

    def _compute_scores_async(self, depth):
        # cancel previous
        if self.pending_after is not None:
            try:
                self.after_cancel(self.pending_after)
            except Exception:
                pass
            self.pending_after = None

        player = self.game.current
        valid = self.game.valid_columns(self.game.grid)
        cols = self.game.cols
        grid0 = copy_grid(self.game.grid)

        # compute values column-by-column to show progress
        col_list = list(range(cols))

        def step(i=0):
            if self.ai_mode.get() != "minimax":
                return
            if i >= len(col_list):
                return

            col = col_list[i]
            if col not in valid:
                self.score_labels[col].set("N/A")
            else:
                g2 = copy_grid(grid0)
                _drop_in_grid(self.game, g2, col, player)
                val = minimax(self.game, g2, depth - 1, -10**18, 10**18, False, player)
                # compact display
                self.score_labels[col].set(str(int(val)))
            # schedule next (progress visible)
            self.pending_after = self.after(40, lambda: step(i + 1))

        step(0)

    def _robot_play_minimax_async(self, depth):
        # First show column scores as it thinks, then pick best.
        self._set_scores_blank()
        valid = self.game.valid_columns(self.game.grid)
        cols = self.game.cols
        for c in range(cols):
            self.score_labels[c].set("N/A" if c not in valid else "...")

        player = self.game.current
        grid0 = copy_grid(self.game.grid)

        best_col = None
        best_val = -10**18

        col_list = list(range(cols))

        def step(i=0):
            nonlocal best_col, best_val
            if self.game.finished:
                self.robot_thinking = False
                self._after_any_state_change()
                return

            if i >= len(col_list):
                # play best
                if best_col is None:
                    # fallback random
                    v = self.game.valid_columns()
                    if v:
                        best_col = random.choice(v)
                if best_col is not None:
                    self.game.apply_move(best_col)

                self.robot_thinking = False
                self._after_any_state_change()
                return

            col = col_list[i]
            if col not in valid:
                self.score_labels[col].set("N/A")
                self.pending_after = self.after(30, lambda: step(i + 1))
                return

            g2 = copy_grid(grid0)
            _drop_in_grid(self.game, g2, col, player)
            val = minimax(self.game, g2, depth - 1, -10**18, 10**18, False, player)
            self.score_labels[col].set(str(int(val)))

            if val > best_val:
                best_val = val
                best_col = col

            # progress visible
            self.pending_after = self.after(40, lambda: step(i + 1))

        step(0)

    # ----- State updates -----

    def _after_any_state_change(self, trigger_robot=True):
        self._update_status()
        self._render_board()
        self._update_nav()
        self._render_ai_scores()

        self._update_buttons_state()

        if trigger_robot:
            self._maybe_robot_turn()

    def _update_buttons_state(self):
        can_click = (not self.game.finished) and (not self.robot_thinking) and self.is_human_turn()
        for c, btn in enumerate(self.col_buttons):
            if can_click and c in self.game.valid_columns():
                btn.state(["!disabled"])
            else:
                btn.state(["disabled"])

       

        self._update_status()


if __name__ == "__main__":
    app = App()
    app.minsize(900, 650)
    app.mainloop() 