"""
OUTIL DE VISUALISATION DE LA BASE DE DONNÉES PUISSANCE 4
Version compatible avec l'application game.py (table saved_games uniquement)
Mission 2.2 : Navigation dans les parties et positions
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import psycopg2
import json
import hashlib
from datetime import datetime
import os

# =======================
# CONFIGURATION DATABASE
# =======================
DB_CONFIG = {
    "host": "localhost",
    "database": "puissance4_db",
    "user": "postgres",
    "password": "rayane",  # CHANGEZ SI NÉCESSAIRE
    "port": 5432,
}


class DatabaseViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Visualisateur Base de Données Puissance 4 - Mission 2.2")
        self.geometry("1400x800")

        # Connexion à la base
        self.conn = None
        self.connect_to_db()

        # Variables d'état
        self.current_game_id = None
        self.moves = []
        self.view_index = 0
        self.board_rows = 8
        self.board_cols = 9
        self.starting_color = "R"

        # Variables d'interface
        self.search_var = tk.StringVar()

        # Constantes graphiques
        self.COLORS = {
            "bg": "#00478e",
            "hole": "#e3f2fd",
            "red": "#d32f2f",
            "yellow": "#fbc02d",
            "win": "#00c853",
            "grid": "#1e88e5",
        }

        self.EMPTY = "."
        self.RED = "R"
        self.YELLOW = "Y"

        # Construction de l'interface
        self.build_ui()

        # Chargement initial
        self.load_games_list()

    # =======================
    # CONNEXION DATABASE
    # =======================

    def connect_to_db(self):
        try:
            self.conn = psycopg2.connect(**DB_CONFIG)
            print("✅ Connecté à la base de données")
        except Exception as e:
            messagebox.showerror(
                "Erreur de connexion",
                f"Impossible de se connecter à la base:\n{str(e)}\n\n"
                f"Assurez-vous que:\n"
                f"1. PostgreSQL est en cours d'exécution\n"
                f"2. La base 'puissance4_db' existe\n"
                f"3. Les identifiants sont corrects\n"
                f"4. La table 'saved_games' existe",
            )
            self.destroy()

    def execute_query(self, query, params=None, fetch=True):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if fetch:
                    return cursor.fetchall()
                else:
                    self.conn.commit()
                    return cursor.rowcount
        except Exception as e:
            print(f"❌ Erreur requête: {e}")
            messagebox.showerror("Erreur SQL", str(e))
            return None

    # =======================
    # INTERFACE GRAPHIQUE
    # =======================

    def build_ui(self):
        # Barre supérieure
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="🔍 Recherche:", font=("Arial", 10)).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind("<Return>", lambda e: self.load_games_list())

        ttk.Button(top_frame, text="Rechercher", command=self.load_games_list).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(top_frame, text="Actualiser", command=self.refresh_all).pack(
            side=tk.LEFT, padx=5
        )

        # Boutons d'action
        action_frame = ttk.Frame(top_frame)
        action_frame.pack(side=tk.RIGHT)

        ttk.Button(
            action_frame, text="📤 Importer JSON", command=self.import_json
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_frame, text="📊 Statistiques", command=self.show_stats).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            action_frame, text="🗑 Supprimer", command=self.delete_selected_game
        ).pack(side=tk.LEFT, padx=2)

        # Conteneur principal
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Panneau gauche : Liste des parties
        left_panel = ttk.Frame(main_container, width=450)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        left_panel.pack_propagate(False)

        # Liste des parties avec scrollbar
        list_frame = ttk.LabelFrame(left_panel, text="Parties sauvegardées", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Treeview pour les parties
        columns = ("ID", "Nom", "Taille", "Mode", "IA", "Coups", "Date")
        self.games_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=20
        )

        # Configuration des colonnes
        col_config = [
            ("ID", 50, "center"),
            ("Nom", 150, "w"),
            ("Taille", 70, "center"),
            ("Mode", 100, "center"),
            ("IA", 120, "center"),
            ("Coups", 70, "center"),
            ("Date", 120, "center"),
        ]

        for col, width, anchor in col_config:
            self.games_tree.heading(col, text=col)
            self.games_tree.column(col, width=width, anchor=anchor)

        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.games_tree.yview
        )
        self.games_tree.configure(yscrollcommand=scrollbar.set)

        self.games_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.games_tree.bind("<<TreeviewSelect>>", self.on_game_select)

        # Panneau droit : Visualisation
        right_panel = ttk.Frame(main_container)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Info de la partie
        info_frame = ttk.LabelFrame(
            right_panel, text="Informations de la partie", padding=10
        )
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.info_text = tk.Text(info_frame, height=8, width=60, font=("Courier", 9))
        self.info_text.pack(fill=tk.BOTH, expand=True)

        # Canvas pour le plateau
        canvas_frame = ttk.LabelFrame(
            right_panel, text="Visualisation du plateau", padding=10
        )
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Contrôles de navigation
        nav_frame = ttk.Frame(right_panel)
        nav_frame.pack(fill=tk.X, pady=10)

        ttk.Button(nav_frame, text="⏮ Début", command=lambda: self.navigate_to(0)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(nav_frame, text="◀ Précédent", command=self.prev_move).pack(
            side=tk.LEFT, padx=2
        )

        self.nav_label = ttk.Label(nav_frame, text="Coup 0/0", font=("Arial", 10))
        self.nav_label.pack(side=tk.LEFT, padx=10)

        ttk.Button(nav_frame, text="Suivant ▶", command=self.next_move).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(nav_frame, text="Fin ⏭", command=self.go_to_end).pack(
            side=tk.LEFT, padx=2
        )

        self.nav_scale = tk.Scale(
            nav_frame,
            from_=0,
            to=0,
            orient="horizontal",
            showvalue=True,
            command=self.on_scale_move,
            length=300,
        )
        self.nav_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # Panneau inférieur : Détails position
        bottom_frame = ttk.LabelFrame(
            right_panel, text="Détails de la position", padding=10
        )
        bottom_frame.pack(fill=tk.X, pady=(10, 0))

        self.pos_info_text = tk.Text(
            bottom_frame, height=6, width=60, font=("Courier", 9)
        )
        self.pos_info_text.pack(fill=tk.BOTH, expand=True)

    # =======================
    # FONCTIONNALITÉS PRINCIPALES
    # =======================

    def load_games_list(self):
        """Charge la liste des parties depuis saved_games"""
        self.games_tree.delete(*self.games_tree.get_children())

        query = """
        SELECT 
            id,
            save_name,
            CONCAT(rows, 'x', cols) as taille,
            CASE mode
                WHEN 0 THEN 'IA vs IA'
                WHEN 1 THEN 'Humain vs IA'
                WHEN 2 THEN 'Humain vs Humain'
                ELSE 'Inconnu'
            END as mode_jeu,
            CONCAT(ai_mode, ' (', ai_depth, ')') as ia,
            jsonb_array_length(moves) as nb_coups,
            TO_CHAR(save_date, 'DD/MM HH24:MI') as date_save
        FROM saved_games
        WHERE 1=1
        """

        params = []

        # Recherche texte
        search_text = self.search_var.get().strip()
        if search_text:
            query += " AND (save_name ILIKE %s OR id::TEXT LIKE %s)"
            params.extend([f"%{search_text}%", f"%{search_text}%"])

        query += " ORDER BY save_date DESC LIMIT 100"

        games = self.execute_query(query, params)

        if games:
            for game in games:
                self.games_tree.insert("", "end", values=game)

    def on_game_select(self, event):
        """Quand une partie est sélectionnée"""
        selection = self.games_tree.selection()
        if not selection:
            return

        item = self.games_tree.item(selection[0])
        game_id = item["values"][0]
        self.current_game_id = game_id
        self.load_game_details(game_id)

    def load_game_details(self, game_id):
        """Charge les détails d'une partie"""
        query = """
        SELECT 
            id, save_name, rows, cols, starting_color,
            mode, game_index, ai_mode, ai_depth,
            moves, view_index, save_date
        FROM saved_games 
        WHERE id = %s
        """

        result = self.execute_query(query, (game_id,))

        if result and result[0]:
            game_data = result[0]

            # Décoder les mouvements JSON
            moves_json = game_data[9]  # moves est à l'index 9
            if moves_json:
                # Si c'est déjà un string JSON, le parser
                if isinstance(moves_json, str):
                    self.moves = json.loads(moves_json)
                else:
                    # Si c'est déjà une liste (déjà désérialisé par psycopg2)
                    self.moves = moves_json
            else:
                self.moves = []

            self.board_rows = game_data[2]  # rows
            self.board_cols = game_data[3]  # cols
            self.starting_color = game_data[4]  # starting_color
            self.view_index = game_data[10] if len(game_data) > 10 else 0  # view_index

            # Afficher les informations
            info = f"""
╔══════════════════════════════════════════════════════════════╗
║ PARTIE: {game_data[1]} (ID: {game_data[0]})                  
╠══════════════════════════════════════════════════════════════╣
║ • Taille: {self.board_rows}x{self.board_cols}                                      
║ • Premier joueur: {'Rouge' if self.starting_color == 'R' else 'Jaune'}                
║ • Mode: {self.get_mode_name(game_data[5])}                    
║ • Index partie: {game_data[6]}                                
║ • IA: {game_data[7]} (profondeur: {game_data[8]})               
║ • Coups joués: {len(self.moves)}                                  
║ • Position actuelle: {self.view_index}                        
║ • Sauvegardée: {game_data[11].strftime('%d/%m/%Y %H:%M:%S')}   
╚══════════════════════════════════════════════════════════════╝
            """

            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(1.0, info)
            self.info_text.config(state="disabled")

            # Mettre à jour la navigation
            self.update_navigation()

            # Afficher la position actuelle
            self.display_current_position()

    def display_current_position(self):
        """Affiche la position actuelle sur le canvas"""
        if not self.moves and self.view_index == 0:
            # Afficher plateau vide
            board = [
                [self.EMPTY for _ in range(self.board_cols)]
                for _ in range(self.board_rows)
            ]
            self.draw_board(board)
            self.display_position_info(None)
            return

        # Reconstruire le board jusqu'à view_index
        board = self.reconstruct_board(self.view_index)
        self.draw_board(board)

        # Afficher info position
        move_info = {
            "index": self.view_index,
            "column": (
                self.moves[self.view_index - 1]
                if self.view_index > 0 and self.view_index <= len(self.moves)
                else None
            ),
            "player": self.get_player_at_index(self.view_index),
            "board": board,
        }
        self.display_position_info(move_info)

    def reconstruct_board(self, up_to_index):
        """Reconstruit le plateau jusqu'à un index donné"""
        # Créer plateau vide
        board = [
            [self.EMPTY for _ in range(self.board_cols)] for _ in range(self.board_rows)
        ]

        # Rejouer les coups
        current_color = self.starting_color
        for i in range(min(up_to_index, len(self.moves))):
            col = self.moves[i]

            # Trouver la première ligne vide dans cette colonne
            for row in range(self.board_rows - 1, -1, -1):
                if board[row][col] == self.EMPTY:
                    board[row][col] = current_color
                    break

            # Changer de joueur
            current_color = self.YELLOW if current_color == self.RED else self.RED

        return board

    def get_player_at_index(self, move_index):
        """Détermine quel joueur doit jouer à un index donné"""
        if move_index == 0:
            return self.starting_color

        # Le joueur qui vient de jouer au coup précédent
        if move_index <= len(self.moves):
            # Si le coup a été joué, déterminer qui a joué
            return (
                self.YELLOW
                if ((move_index - 1) % 2 == 1) ^ (self.starting_color == self.YELLOW)
                else self.RED
            )
        else:
            # Sinon, déterminer qui devrait jouer
            return (
                self.YELLOW
                if (move_index % 2 == 1) ^ (self.starting_color == self.YELLOW)
                else self.RED
            )

    def draw_board(self, board):
        """Dessine le plateau sur le canvas"""
        self.canvas.delete("all")

        if not board:
            return

        rows = len(board)
        cols = len(board[0])

        # Dimensions
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width < 10 or canvas_height < 10:
            canvas_width = 500
            canvas_height = 500

        # Calcul des cellules
        cell_size = min(canvas_width / cols, canvas_height / rows) * 0.8
        margin_x = (canvas_width - cols * cell_size) / 2
        margin_y = (canvas_height - rows * cell_size) / 2

        # Dessiner le fond
        self.canvas.create_rectangle(
            margin_x,
            margin_y,
            margin_x + cols * cell_size,
            margin_y + rows * cell_size,
            fill=self.COLORS["bg"],
            outline="",
        )

        # Dessiner les trous et jetons
        hole_radius = cell_size * 0.4

        for r in range(rows):
            for c in range(cols):
                center_x = margin_x + c * cell_size + cell_size / 2
                center_y = margin_y + r * cell_size + cell_size / 2

                # Couleur selon le contenu
                if board[r][c] == self.RED:
                    color = self.COLORS["red"]
                elif board[r][c] == self.YELLOW:
                    color = self.COLORS["yellow"]
                else:
                    color = self.COLORS["hole"]

                # Dessiner le jeton/trou
                self.canvas.create_oval(
                    center_x - hole_radius,
                    center_y - hole_radius,
                    center_x + hole_radius,
                    center_y + hole_radius,
                    fill=color,
                    outline=self.COLORS["grid"],
                    width=2,
                )

        # Afficher les numéros de colonnes
        for c in range(cols):
            x = margin_x + c * cell_size + cell_size / 2
            y = margin_y + rows * cell_size + 20
            self.canvas.create_text(
                x, y, text=str(c + 1), fill="white", font=("Arial", 12, "bold")
            )

    def display_position_info(self, move):
        """Affiche les informations de la position"""
        if move is None:
            info = """
╔══════════════════════════════════════════════════════════════╗
║ POSITION INITIALE - Coup 0                                        
╠══════════════════════════════════════════════════════════════╣
║ • Aucun coup joué                                           
║ • Plateau vide                                              
║ • Prochain joueur: Rouge                                    
╚══════════════════════════════════════════════════════════════╝
            """
        else:
            player_name = "Rouge" if move["player"] == "R" else "Jaune"
            col_info = (
                f"Colonne: {move['column'] + 1}"
                if move["column"] is not None and move["index"] > 0
                else "Aucun coup"
            )

            info = f"""
╔══════════════════════════════════════════════════════════════╗
║ POSITION - Coup {move['index']}                                        
╠══════════════════════════════════════════════════════════════╣
║ • {col_info}                                      
║ • Joueur actuel: {player_name}                  
║ • Hash de position: {self.calculate_board_hash(move['board'])[:16]}...
╚══════════════════════════════════════════════════════════════╝
            """

        self.pos_info_text.delete(1.0, tk.END)
        self.pos_info_text.insert(1.0, info)
        self.pos_info_text.config(state="disabled")

    # =======================
    # NAVIGATION
    # =======================

    def update_navigation(self):
        """Met à jour les contrôles de navigation"""
        total = len(self.moves)
        self.nav_scale.config(to=max(0, total))
        self.nav_scale.set(self.view_index)
        self.nav_label.config(text=f"Coup {self.view_index}/{total}")

    def navigate_to(self, index):
        """Va à un coup spécifique"""
        if 0 <= index <= len(self.moves):
            self.view_index = index
            self.update_navigation()
            self.display_current_position()

    def prev_move(self):
        """Coup précédent"""
        if self.view_index > 0:
            self.navigate_to(self.view_index - 1)

    def next_move(self):
        """Coup suivant"""
        if self.view_index < len(self.moves):
            self.navigate_to(self.view_index + 1)

    def go_to_end(self):
        """Va au dernier coup"""
        if self.moves:
            self.navigate_to(len(self.moves))

    def on_scale_move(self, value):
        """Quand le curseur de navigation est bougé"""
        try:
            index = int(float(value))
            self.navigate_to(index)
        except:
            pass

    # =======================
    # FONCTIONNALITÉS AVANCÉES
    # =======================

    def import_json(self):
        """Importe une partie depuis un fichier JSON"""
        filepath = filedialog.askopenfilename(
            title="Importer une partie JSON",
            filetypes=[("Fichiers JSON", "*.json"), ("Tous les fichiers", "*.*")],
        )

        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                game_data = json.load(f)

            # Vérifier la structure du fichier
            required_fields = ["rows", "cols", "starting_color", "moves"]
            for field in required_fields:
                if field not in game_data:
                    raise ValueError(f"Champ manquant: {field}")

            # Vérifier si la partie existe déjà
            query = "SELECT id FROM saved_games WHERE save_name = %s"
            existing = self.execute_query(
                query, (os.path.basename(filepath).replace(".json", ""),)
            )

            if existing:
                messagebox.showinfo(
                    "Partie existante",
                    f"Une partie avec ce nom existe déjà (ID: {existing[0][0]})",
                )
                return

            # Insérer la nouvelle partie
            query = """
            INSERT INTO saved_games 
            (save_name, rows, cols, starting_color, mode, game_index, 
             moves, view_index, ai_mode, ai_depth)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """

            save_name = os.path.basename(filepath).replace(".json", "")

            params = (
                save_name,
                game_data["rows"],
                game_data["cols"],
                game_data["starting_color"],
                game_data.get("mode", 2),
                game_data.get("game_index", 1),
                json.dumps(game_data["moves"]),
                game_data.get("view_index", 0),
                game_data.get("ai_mode", "random"),
                game_data.get("ai_depth", 4),
            )

            result = self.execute_query(query, params, fetch=False)

            if result:
                new_game_id = self.execute_query("SELECT LASTVAL()")[0][0]
                messagebox.showinfo(
                    "Succès", f"Partie importée avec succès! ID: {new_game_id}"
                )
                self.load_games_list()
            else:
                messagebox.showerror("Erreur", "Échec de l'importation")

        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de l'import: {str(e)}")

    def show_stats(self):
        """Affiche les statistiques générales"""
        query = """
        SELECT 
            COUNT(*) as total_games,
            COUNT(DISTINCT moves) as unique_games,
            AVG(jsonb_array_length(moves))::INTEGER as avg_moves,
            MIN(jsonb_array_length(moves)) as min_moves,
            MAX(jsonb_array_length(moves)) as max_moves,
            COUNT(DISTINCT rows || 'x' || cols) as different_sizes,
            MODE() WITHIN GROUP (ORDER BY ai_mode) as most_common_ai
        FROM saved_games
        """

        stats = self.execute_query(query)

        if stats and stats[0]:
            stats_data = stats[0]

            stats_text = f"""
╔══════════════════════════════════════════════════════════════╗
║ STATISTIQUES GÉNÉRALES                                      
╠══════════════════════════════════════════════════════════════╣
║ • Parties totales: {stats_data[0] or 0}                                  
║ • Parties uniques: {stats_data[1] or 0}                                  
║ • Coups moyens par partie: {stats_data[2] or 0}                          
║ • Coups minimum: {stats_data[3] or 0}                                    
║ • Coups maximum: {stats_data[4] or 0}                                    
║ • Tailles différentes: {stats_data[5] or 0}                              
║ • IA la plus utilisée: {stats_data[6] or 'N/A'}                          
╚══════════════════════════════════════════════════════════════╝
            """

            messagebox.showinfo("Statistiques", stats_text)
        else:
            messagebox.showinfo("Statistiques", "Aucune donnée disponible")

    def delete_selected_game(self):
        """Supprime la partie sélectionnée"""
        selection = self.games_tree.selection()
        if not selection:
            messagebox.showwarning(
                "Aucune sélection", "Veuillez sélectionner une partie à supprimer"
            )
            return

        item = self.games_tree.item(selection[0])
        game_id = item["values"][0]
        game_name = item["values"][1]

        confirm = messagebox.askyesno(
            "Confirmer suppression",
            f"Voulez-vous vraiment supprimer la partie '{game_name}' (ID: {game_id}) ?\n\n"
            "Cette action est irréversible.",
        )

        if confirm:
            try:
                query = "DELETE FROM saved_games WHERE id = %s"
                result = self.execute_query(query, (game_id,), fetch=False)

                if result:
                    messagebox.showinfo("Succès", "Partie supprimée avec succès")
                    self.load_games_list()
                    # Réinitialiser l'affichage
                    self.current_game_id = None
                    self.moves = []
                    self.view_index = 0
                    self.canvas.delete("all")
                    self.info_text.delete(1.0, tk.END)
                    self.pos_info_text.delete(1.0, tk.END)
                    self.update_navigation()
                else:
                    messagebox.showerror("Erreur", "Échec de la suppression")

            except Exception as e:
                messagebox.showerror(
                    "Erreur", f"Erreur lors de la suppression: {str(e)}"
                )

    # =======================
    # UTILITAIRES
    # =======================

    def calculate_board_hash(self, board):
        """Calcule le hash SHA-256 d'une position"""
        if not board:
            return "N/A"
        board_str = json.dumps(board)
        return hashlib.sha256(board_str.encode()).hexdigest()

    def get_mode_name(self, mode_code):
        """Convertit le code mode en nom lisible"""
        modes = {0: "IA vs IA", 1: "Humain vs IA", 2: "Humain vs Humain"}
        return modes.get(mode_code, f"Mode {mode_code}")

    def refresh_all(self):
        """Rafraîchit toutes les données"""
        self.load_games_list()
        if self.current_game_id:
            self.load_game_details(self.current_game_id)

    def __del__(self):
        """Ferme la connexion à la base"""
        if self.conn:
            self.conn.close()


# =======================
# PROGRAMME PRINCIPAL
# =======================

if __name__ == "__main__":
    # Vérifier les dépendances
    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2 n'est pas installé. Installez-le avec:")
        print("   pip install psycopg2-binary")
        exit(1)

    app = DatabaseViewer()
    app.mainloop()
