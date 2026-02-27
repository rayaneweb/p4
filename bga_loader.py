# bga_loader.py
"""
Interface pour charger une partie BGA spécifique dans la base
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import psycopg2
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DB_CONFIG = {
    "host": "localhost",
    "database": "puissance4_db",
    "user": "postgres",
    "password": "rayane",
    "port": 5432,
}


class BGALoaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chargeur de parties BGA")
        self.geometry("800x600")

        self.driver = None
        self.setup_ui()

    def setup_ui(self):
        # Frame principal
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Titre
        ttk.Label(
            main_frame, text="🎮 Charger une partie BGA", font=("Arial", 16, "bold")
        ).pack(pady=10)

        # Zone d'entrée du numéro de table
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=10)

        ttk.Label(input_frame, text="Numéro de table BGA:", font=("Arial", 12)).pack(
            side=tk.LEFT, padx=5
        )

        self.table_var = tk.StringVar()
        ttk.Entry(
            input_frame, textvariable=self.table_var, width=20, font=("Arial", 12)
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            input_frame, text="Charger", command=self.load_game, style="Accent.TButton"
        ).pack(side=tk.LEFT, padx=5)

        # Zone de statut
        status_frame = ttk.LabelFrame(main_frame, text="Statut", padding=10)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.status_text = scrolledtext.ScrolledText(
            status_frame, height=15, font=("Courier", 10)
        )
        self.status_text.pack(fill=tk.BOTH, expand=True)

        # Boutons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(
            button_frame, text="Voir dans Database Viewer", command=self.open_db_viewer
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Jouer la partie", command=self.play_game).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="Fermer", command=self.quit).pack(
            side=tk.RIGHT, padx=5
        )

    def log(self, message, level="INFO"):
        """Ajoute un message dans la zone de statut"""
        timestamp = time.strftime("%H:%M:%S")
        self.status_text.insert(tk.END, f"[{timestamp}] {level}: {message}\n")
        self.status_text.see(tk.END)
        self.update()

    def init_driver(self):
        """Initialise le driver Chrome"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

        options = Options()
        options.add_argument("--start-maximized")
        self.driver = webdriver.Chrome(options=options)
        return self.driver

    def extract_moves_from_gamereview(self, table_id):
        """Extrait les coups depuis /gamereview"""
        url = f"https://boardgamearena.com/gamereview?table={table_id}"
        self.log(f"🌐 Accès à {url}")
        self.driver.get(url)

        WebDriverWait(self.driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)

        page_text = self.driver.find_element(By.TAG_NAME, "body").text

        # Extraction des coups
        pattern = re.compile(
            r"^(.+?)\s+place un pion dans la colonne\s+(\d+)\s*$", re.MULTILINE
        )
        rows = pattern.findall(page_text)

        # Mapping des joueurs
        name_to_pid = {}
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
            for a in links:
                href = a.get_attribute("href") or ""
                m = re.search(r"/player\?id=(\d+)", href)
                if not m:
                    continue
                pid = m.group(1)
                name = (a.text or "").strip()
                if name and name not in name_to_pid:
                    name_to_pid[name] = pid
        except Exception as e:
            self.log(f"⚠️ Erreur mapping joueurs: {e}")

        moves = []
        move_id = 1
        for player_name, col_str in rows:
            player_name = player_name.strip()
            try:
                col = int(col_str) - 1  # Convertir en 0-based
            except Exception:
                continue
            pid = name_to_pid.get(player_name, "unknown")
            moves.append(
                {
                    "move_id": move_id,
                    "col": col,
                    "player_id": str(pid),
                    "player_name": player_name,
                }
            )
            move_id += 1

        return moves, name_to_pid

    def detect_board_size(self, page_text):
        """Détecte la taille du plateau"""
        lower = page_text.lower()
        if "9x9" in lower or "9×9" in lower:
            return (9, 9)

        size_re = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", re.IGNORECASE)
        m = size_re.search(page_text)
        if m:
            r = int(m.group(1))
            c = int(m.group(2))
            if 4 <= r <= 20 and 4 <= c <= 20:
                return (r, c)
        return None

    def save_to_database(self, table_id, moves, rows, cols, players):
        """Sauvegarde la partie dans la base de données"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Préparation des données
            cols_0_based = [m["col"] for m in moves]
            distinct_cols = len(set(cols_0_based))

            # Vérification des doublons
            cur.execute(
                """
                SELECT id FROM saved_games 
                WHERE rows = %s AND cols = %s AND moves = %s::jsonb
            """,
                (rows, cols, json.dumps(cols_0_based)),
            )

            existing = cur.fetchone()
            if existing:
                self.log(f"⚠️ Partie déjà existante (ID: {existing[0]})")
                return existing[0]

            # Insertion
            save_name = f"BGA_table_{table_id}"
            cur.execute(
                """
                INSERT INTO saved_games 
                (save_name, rows, cols, starting_color, mode, game_index,
                 moves, view_index, ai_mode, ai_depth, confidence, distinct_cols)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    save_name,
                    rows,
                    cols,
                    "R",
                    2,
                    1,
                    json.dumps(cols_0_based),
                    len(moves),
                    "bga",
                    4,
                    3,
                    distinct_cols,
                ),
            )

            game_id = cur.fetchone()[0]
            conn.commit()

            self.log(f"✅ Partie sauvegardée avec ID: {game_id}")
            return game_id

        except Exception as e:
            self.log(f"❌ Erreur DB: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def load_game(self):
        """Charge une partie depuis BGA"""
        table_id = self.table_var.get().strip()
        if not table_id:
            messagebox.showerror("Erreur", "Veuillez entrer un numéro de table")
            return

        self.status_text.delete(1.0, tk.END)
        self.log(f"🔍 Chargement de la table {table_id}...")

        driver = None
        try:
            driver = self.init_driver()

            # Étape 1: Récupération des coups
            self.log("📊 Extraction des coups depuis /gamereview...")
            moves, players = self.extract_moves_from_gamereview(table_id)

            if not moves:
                self.log("❌ Aucun coup trouvé!")
                return

            self.log(f"✅ {len(moves)} coups trouvés")

            # Étape 2: Détection taille plateau
            page_text = driver.find_element(By.TAG_NAME, "body").text
            size = self.detect_board_size(page_text)

            if size:
                rows, cols = size
                self.log(f"📏 Taille plateau: {rows}x{cols}")
            else:
                rows, cols = 9, 9
                self.log(f"⚠️ Taille non détectée, utilisation 9x9")

            # Étape 3: Sauvegarde DB
            game_id = self.save_to_database(table_id, moves, rows, cols, players)

            if game_id:
                self.log("=" * 50)
                self.log("🎉 PARTIE CHARGÉE AVEC SUCCÈS!")
                self.log(f"   Table BGA: {table_id}")
                self.log(f"   ID en base: {game_id}")
                self.log(f"   Joueurs: {', '.join(players.keys())}")
                self.log(f"   Coups: {len(moves)}")
                self.log("=" * 50)

                # Sauvegarde locale
                out_path = Path("scraped_moves") / f"bga_table_{table_id}.json"
                out_path.parent.mkdir(exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "table_id": table_id,
                            "game_id": game_id,
                            "moves": moves,
                            "players": players,
                            "size": [rows, cols],
                        },
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                self.log(f"💾 Sauvegarde locale: {out_path}")

        except Exception as e:
            self.log(f"❌ Erreur: {e}")
            messagebox.showerror("Erreur", str(e))
        finally:
            if driver:
                driver.quit()

    def open_db_viewer(self):
        """Ouvre le Database Viewer"""
        import subprocess

        subprocess.Popen(["python", "database_viewer.py"])

    def play_game(self):
        """Lance la partie dans l'interface web"""
        import webbrowser

        webbrowser.open("http://localhost:8000")


if __name__ == "__main__":
    app = BGALoaderApp()
    app.mainloop()
