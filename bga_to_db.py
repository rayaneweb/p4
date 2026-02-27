# scrape_replay_selenium_max40_nodup.py
# ============================================================
# ✅ Login BGA manuel (Chrome)
# ✅ Récupère jusqu'à 40 joueurs depuis le classement Connect4 (scroll dynamique)
# ✅ Pour chaque joueur -> récupère ses parties terminées (tables)
# ✅ Pour chaque table -> /table?table=... (size) + /gamereview?table=... (moves)
# ✅ Fallback archive replay via window.g_gamelogs
# ✅ Skip tables déjà scrapées (cache JSON local)
# ✅ Skip import DB si déjà importée (cache JSON local)
# ✅ Import automatique via bga_import.import_bga_moves (si présent)
# ============================================================

import json
import time
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# CONFIG
# ============================================================

GAME_ID = 1186  # connectfour
FINISHED = 1  # 1 = terminées

ROWS = 9
COLS = 9
CONFIANCE = 3  # 3=BGA/humain

ONLY_9X9 = True
STRICT_SIZE_CHECK = True

MAX_PLAYERS = 40
MAX_TABLES_PER_PLAYER = 80

# scrolling
SLEEP_SCROLL = 0.6
RANKING_MAX_SECONDS = 90
GAMESTATS_MAX_SECONDS = 45
NO_NEW_ROUNDS_TO_STOP = 4

PAUSE_BETWEEN_PLAYERS = 0.6
PAUSE_BETWEEN_TABLES = 1.0

BASE = "https://boardgamearena.com"

PROJECT_DIR = Path(__file__).resolve().parent
OUT_DIR = PROJECT_DIR / "scraped_moves"
OUT_DIR.mkdir(exist_ok=True)

SCRAPED_CACHE_PATH = PROJECT_DIR / "scraped_tables.json"


# ============================================================
# CACHE (skip duplicates)
# ============================================================


def load_scraped_cache():
    """
    Cache format:
    {
      "scraped": ["123", "456", ...],
      "imported": ["123", ...],
      "failed": {"789": "error msg", ...}
    }
    """
    if SCRAPED_CACHE_PATH.exists():
        try:
            data = json.loads(SCRAPED_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("scraped", [])
                data.setdefault("imported", [])
                data.setdefault("failed", {})
                # normalize to str
                data["scraped"] = [str(x) for x in data["scraped"]]
                data["imported"] = [str(x) for x in data["imported"]]
                data["failed"] = {str(k): str(v) for k, v in data["failed"].items()}
                return data
        except Exception:
            pass
    return {"scraped": [], "imported": [], "failed": {}}


def save_scraped_cache(cache: dict):
    SCRAPED_CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def mark_scraped(cache: dict, table_id: str):
    table_id = str(table_id)
    if table_id not in cache["scraped"]:
        cache["scraped"].append(table_id)


def mark_imported(cache: dict, table_id: str):
    table_id = str(table_id)
    if table_id not in cache["imported"]:
        cache["imported"].append(table_id)
    cache["failed"].pop(table_id, None)


def mark_failed(cache: dict, table_id: str, err: Exception | str):
    table_id = str(table_id)
    cache["failed"][table_id] = str(err)[:800] if err is not None else "unknown error"


# ============================================================
# DRIVER
# ============================================================


def make_driver(headless: bool = False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1400,900")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


# ============================================================
# LOGIN (manuel) + FIX DOMAINE
# ============================================================


def login_bga_manual(driver):
    global BASE
    print("🔐 Ouverture BGA login (manuel)...")
    driver.get(f"{BASE}/account")

    print("👉 Connecte-toi MANUELLEMENT dans Chrome.")
    input("✅ Quand tu es connecté (avatar visible), appuie sur ENTER...")

    print("✅ URL actuelle :", driver.current_url)
    u = urlparse(driver.current_url)
    BASE = f"{u.scheme}://{u.netloc}"
    print("✅ BASE fixé à :", BASE)


# ============================================================
# SCROLL UTIL
# ============================================================


def scroll_to_bottom(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")


# ============================================================
# SIZE depuis table page (fiable)
# ============================================================


def get_board_size_from_table_page(driver, table_id: str):
    try:
        tid = str(int(str(table_id)))
    except Exception:
        return None

    url = f"{BASE}/table?table={tid}"
    driver.get(url)

    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.ID, "gameoption_100_displayed_value"))
        )
        time.sleep(0.6)
        el = driver.find_element(By.ID, "gameoption_100_displayed_value")
        val = (el.text or "").strip()
        m = re.search(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", val)
        if m:
            r = int(m.group(1))
            c = int(m.group(2))
            return (r, c)
    except Exception:
        pass

    return None


# ============================================================
# 0) Joueurs depuis le classement (ID + PSEUDO) - MAX 40
# ============================================================


def collect_players_from_ranking(driver, max_players: int):
    """
    Retourne une liste: [(player_id, pseudo), ...]
    Scroll dynamique jusqu'à atteindre max_players ou stabilisation.
    """
    url = f"{BASE}/gamepanel?game=connectfour"
    print("🏁 Ouverture page classement:", url)
    driver.get(url)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2)

    def extract_players_now():
        anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
        out = []
        seen = set()
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = re.search(r"/player\?id=(\d+)", href)
            if not m:
                continue
            pid = m.group(1)
            pseudo = (a.text or "").strip()
            if not pseudo:
                continue
            if pid in seen:
                continue
            seen.add(pid)
            out.append((pid, pseudo))
        return out

    stable_rounds = 0
    last_count = 0
    t0 = time.time()

    while True:
        players_now = extract_players_now()
        cur_count = len(players_now)

        if cur_count >= max_players:
            break

        if cur_count <= last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = cur_count

        if stable_rounds >= NO_NEW_ROUNDS_TO_STOP:
            break
        if time.time() - t0 > RANKING_MAX_SECONDS:
            break

        scroll_to_bottom(driver)
        time.sleep(SLEEP_SCROLL)

    players = extract_players_now()[:max_players]
    print(f"✅ Joueurs trouvés = {len(players)} (max={max_players})")
    if players:
        print("   sample:", players[:5])
    return players


# ============================================================
# 1) TABLE IDS depuis gamestats (profil parties)
# ============================================================


def get_connect4_table_ids(
    driver, player_id: str, game_id: int, finished: int, limit: int
):
    """
    Scroll dynamique sur /gamestats pour charger plus d'entrées.
    """
    url = f"{BASE}/gamestats?player={player_id}&game_id={game_id}&finished={finished}"
    driver.get(url)
    time.sleep(2)

    t0 = time.time()
    stable_rounds = 0
    last_len = 0

    while True:
        html = driver.page_source or ""
        raw = re.findall(r"(?:/table\?table=|table\?table=|[?&]table=)(\d+)", html)
        uniq = []
        seen = set()
        for t in raw:
            try:
                n = int(t)
                if n > 0:
                    s = str(n)
                    if s not in seen:
                        seen.add(s)
                        uniq.append(s)
            except ValueError:
                pass

        cur_len = len(uniq)

        # Stop conditions
        if cur_len >= limit:
            return uniq[:limit]

        if cur_len <= last_len:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_len = cur_len

        if stable_rounds >= NO_NEW_ROUNDS_TO_STOP:
            return uniq[:limit]
        if time.time() - t0 > GAMESTATS_MAX_SECONDS:
            return uniq[:limit]

        scroll_to_bottom(driver)
        time.sleep(0.7)


# ============================================================
# 2) Detect board size anchored
# ============================================================

SIZE_RE = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", re.IGNORECASE)


def detect_board_size_anchored(page_text: str):
    if not page_text:
        return None

    lower = page_text.lower()
    if "9x9" in lower or "9×9" in lower:
        return (9, 9)

    for line in page_text.splitlines():
        l = line.strip()
        if not l:
            continue
        ll = l.lower()

        anchored = (
            ("board" in ll and "size" in ll)
            or ("taille" in ll and "plateau" in ll)
            or ("grid" in ll and "size" in ll)
        )
        if not anchored:
            continue

        m = SIZE_RE.search(l)
        if m:
            r = int(m.group(1))
            c = int(m.group(2))
            if 4 <= r <= 20 and 4 <= c <= 20:
                return (r, c)

    return None


# ============================================================
# 3) Extraction coups via /gamereview?table=...
# ============================================================


def extract_size_and_moves_from_gamereview(driver, table_id: str):
    url = f"{BASE}/gamereview?table={table_id}"
    driver.get(url)

    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(1.2)

    body_el = driver.find_element(By.TAG_NAME, "body")
    page_text = body_el.text or ""

    size = detect_board_size_anchored(page_text)

    # Map pseudo -> player_id (depuis liens visibles)
    name_to_pid = {}
    try:
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
        for a in links:
            href = a.get_attribute("href") or ""
            m = re.search(r"/player\?id=(\d+)", href)
            if not m:
                continue
            pid = m.group(1)
            name = (a.text or "").strip()
            if name and name not in name_to_pid:
                name_to_pid[name] = pid
    except Exception:
        pass

    # FR: "... place un pion dans la colonne X"
    pattern = re.compile(
        r"^(.+?)\s+place un pion dans la colonne\s+(\d+)\s*$", re.MULTILINE
    )
    rows = pattern.findall(page_text)

    moves = []
    move_id = 1
    for player_name, col_str in rows:
        player_name = player_name.strip()
        try:
            col = int(col_str)
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

    return size, moves


# ============================================================
# 4) Fallback archive replay via g_gamelogs
# ============================================================

EXTRACT_JS = r"""
return (function () {
  const byMove = new Map();
  for (const pkt of (window.g_gamelogs || [])) {
    const mid = Number(pkt && pkt.move_id);
    if (!Number.isFinite(mid)) continue;

    const data = (pkt.data || []);
    const disc = data.find(d => d && d.type === "playDisc");
    if (!disc || !disc.args) continue;

    const col = Number(disc.args.x);
    const pid = String(disc.args.player_id);
    if (!Number.isFinite(col)) continue;

    byMove.set(mid, { col, pid });
  }

  const moves = [...byMove.entries()]
    .sort((a,b)=>a[0]-b[0])
    .map(([move_id, v]) => ({ move_id, col: v.col, player_id: v.pid }));

  return { count: moves.length, moves };
})();
"""


def wait_gamelogs(driver, max_wait=30):
    end = time.time() + max_wait
    while time.time() < end:
        n = driver.execute_script(
            "return (window.g_gamelogs && window.g_gamelogs.length) || 0;"
        )
        if int(n) > 0:
            return True
        time.sleep(0.5)
    return False


def resolve_real_replay_url_from_table(driver, table_id: str):
    table_url = f"{BASE}/table?table={table_id}"
    driver.get(table_url)

    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    try:
        a = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'a[href*="/archive/replay/"]')
            )
        )
        href = a.get_attribute("href")
        if href:
            return href
    except Exception:
        pass

    html = driver.page_source or ""
    m = re.search(r'(/archive/replay/[^"\']+)', html)
    if m:
        rel = m.group(1)
        return rel if rel.startswith("http") else urljoin(BASE, rel)
    return None


def extract_moves_from_replay_url(driver, replay_url: str):
    driver.get(replay_url)
    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2)

    ok = wait_gamelogs(driver, max_wait=30)
    if not ok:
        return []

    for _ in range(1, 6):
        payload = driver.execute_script(EXTRACT_JS)
        if payload and payload.get("count", 0) > 0:
            return payload["moves"]
        time.sleep(1.0)
    return []


# ============================================================
# 5) Import DB (via bga_import)
# ============================================================


def import_into_db(moves, save_name: str):
    from bga_import import import_bga_moves

    return import_bga_moves(
        moves,
        rows=ROWS,
        cols=COLS,
        confiance=CONFIANCE,
        save_name=save_name,
        starting_color="R",
    )


# ============================================================
# MAIN
# ============================================================


def main():
    driver = make_driver(headless=False)
    cache = load_scraped_cache()
    scraped_set = set(cache["scraped"])
    imported_set = set(cache["imported"])

    print(
        f"🧠 Cache chargé: scraped={len(scraped_set)}, imported={len(imported_set)}, failed={len(cache['failed'])}"
    )
    print(f"📌 Cache file: {SCRAPED_CACHE_PATH}")

    try:
        login_bga_manual(driver)

        players = collect_players_from_ranking(driver, max_players=MAX_PLAYERS)
        if not players:
            print("❌ Aucun joueur trouvé depuis le classement.")
            return

        total_seen = 0
        total_scraped_new = 0
        total_imported = 0
        total_skipped_cached = 0

        for idx, (player_id, pseudo) in enumerate(players, start=1):
            print("\n==============================")
            print(f" Joueur {idx}/{len(players)}: {pseudo} ({player_id})")

            table_ids = get_connect4_table_ids(
                driver, player_id, GAME_ID, FINISHED, MAX_TABLES_PER_PLAYER
            )
            print(f"    Tables trouvées (brut) = {len(table_ids)}")

            for tid in table_ids:
                tid = str(tid)
                total_seen += 1

                # ✅ skip si déjà scrapée
                if tid in scraped_set:
                    print(f"   ⏭️ Table {tid} déjà scrapée (cache) -> skip")
                    total_skipped_cached += 1
                    continue

                print(f"   🎲 Table: {tid}")

                # --- size check via /table ---
                size = get_board_size_from_table_page(driver, tid)

                if ONLY_9X9:
                    if size is None:
                        if STRICT_SIZE_CHECK:
                            print("        SKIP (size unknown)")
                            mark_scraped(
                                cache, tid
                            )  # on marque quand même pour éviter boucles infinies
                            scraped_set.add(tid)
                            save_scraped_cache(cache)
                            time.sleep(PAUSE_BETWEEN_TABLES)
                            continue
                    else:
                        r, c = size
                        if (r, c) != (9, 9):
                            print(f"        SKIP (size {r}x{c} not 9x9)")
                            mark_scraped(cache, tid)
                            scraped_set.add(tid)
                            save_scraped_cache(cache)
                            time.sleep(PAUSE_BETWEEN_TABLES)
                            continue

                # --- gamereview extraction ---
                try:
                    _size_from_gamereview, moves = (
                        extract_size_and_moves_from_gamereview(driver, tid)
                    )
                except Exception as e:
                    moves = []
                    print("      ⚠️ gamereview failed:", e)

                if moves:
                    names = sorted(
                        {
                            m.get("player_name", "")
                            for m in moves
                            if m.get("player_name")
                        }
                    )
                    if names:
                        print("       Joueurs détectés:", " vs ".join(names))
                    print(f"      ✅ {len(moves)} coups (gamereview)")

                # --- fallback replay archive ---
                if not moves:
                    replay_url = resolve_real_replay_url_from_table(driver, tid)
                    if replay_url:
                        print("       Archive replay:", replay_url)
                        try:
                            moves = extract_moves_from_replay_url(driver, replay_url)
                        except Exception as e:
                            moves = []
                            print("      ⚠️ archive extraction failed:", e)

                        if moves:
                            print(f"      ✅ {len(moves)} coups (archive)")

                if not moves:
                    print("      ❌ Aucun coup trouvé (skip)")
                    # on marque scrapée pour ne plus y revenir (tu peux enlever si tu veux re-try plus tard)
                    mark_scraped(cache, tid)
                    scraped_set.add(tid)
                    save_scraped_cache(cache)
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                # --- save JSON ---
                out_path = OUT_DIR / f"moves_{pseudo}_{player_id}_table_{tid}.json"
                out_path.write_text(
                    json.dumps(moves, indent=2, ensure_ascii=False), encoding="utf-8"
                )

                # ✅ mark as scraped
                mark_scraped(cache, tid)
                scraped_set.add(tid)
                save_scraped_cache(cache)
                total_scraped_new += 1

                # --- import DB if not already imported ---
                if tid in imported_set:
                    print("      ⏭️ Import DB déjà fait (cache) -> skip import")
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                save_name = f"BGA_table_{tid}_from_{pseudo}"
                try:
                    game_id_db = import_into_db(moves, save_name=save_name)
                    print("      💾 Import DB OK id_partie =", game_id_db)
                    total_imported += 1
                    mark_imported(cache, tid)
                    imported_set.add(tid)
                    save_scraped_cache(cache)
                except Exception as e:
                    print("      ❌ Import DB FAILED:", e)
                    mark_failed(cache, tid, e)
                    save_scraped_cache(cache)

                time.sleep(PAUSE_BETWEEN_TABLES)

            time.sleep(PAUSE_BETWEEN_PLAYERS)

        print("\n==============================")
        print(f"🎉 Terminé.")
        print(f"   Tables vues             = {total_seen}")
        print(f"   Tables déjà cache (skip)= {total_skipped_cached}")
        print(f"   Tables scrapées nouvelles= {total_scraped_new}")
        print(f"   Parties importées DB     = {total_imported}")
        print(f"📁 JSON moves enregistrés dans: {OUT_DIR}")
        print(f"🧠 Cache: {SCRAPED_CACHE_PATH}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
