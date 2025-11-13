import os
import re
import io
import json
import zipfile
import threading
import datetime
import urllib.parse
import urllib.request
from html.parser import HTMLParser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

CACHE_FILE = os.path.join(os.path.expanduser("~"), ".game_save_backup_cache.json")
DEFAULT_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "GameSaveBackups")
PCGW_API = "https://www.pcgamingwiki.com/w/api.php"

# -----------------------------
# Helpers: persistence & logging
# -----------------------------
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def log_append(widget, text):
    widget.configure(state="normal")
    widget.insert("end", text + "\n")
    widget.see("end")
    widget.configure(state="disabled")

# -----------------------------
# PCGamingWiki HTML parser
# -----------------------------
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._buf = io.StringIO()
    def handle_data(self, data):
        self._buf.write(data)
    def get_text(self):
        return self._buf.getvalue()

# -----------------------------
# PCGamingWiki lookup
# -----------------------------
def pcgw_search_title(game_name):
    params = {
        "action": "opensearch",
        "search": game_name,
        "limit": 1,
        "namespace": 0,
        "format": "json",
    }
    url = PCGW_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    if data and len(data) >= 2 and data[1]:
        return data[1][0]
    return None

def pcgw_find_save_section_index(title):
    params = {"action": "parse", "page": title, "prop": "sections", "format": "json"}
    url = PCGW_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    sections = data.get("parse", {}).get("sections", [])
    for s in sections:
        if s.get("line", "").strip().lower() == "save game data location":
            return s.get("index")
    for s in sections:
        if "save game data location" in s.get("line", "").strip().lower():
            return s.get("index")
    return None

def pcgw_get_save_section_html(title, index):
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "section": index,
        "format": "json",
    }
    url = PCGW_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    return data.get("parse", {}).get("text", {}).get("*", "")

def extract_windows_paths_from_html(html):
    parser = TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    patterns = [
        r"[A-Za-z]:\\[^\n\r<>|\?\*\"]+",
        r"%[A-Za-z_]+%\\[^\n\r<>|\?\*\"]+",
        r"~\\[^\n\r<>|\?\*\"]+",
        r"\\Users\\[^\\\n\r]+\\[^\n\r<>|\?\*\"]+",
        r"Documents\\[^\n\r<>|\?\*\"]+",
        r"Saved Games\\[^\n\r<>|\?\*\"]+",
        r"AppData\\Roaming\\[^\n\r<>|\?\*\"]+",
        r"AppData\\Local\\[^\n\r<>|\?\*\"]+",
        r"OneDrive\\Documents\\[^\n\r<>|\?\*\"]+",
    ]
    rx = re.compile("(" + ")|(".join(patterns) + ")")
    candidates = set(m.group(0) for m in rx.finditer(text))
    cleaned = []
    for p in candidates:
        p2 = p.strip().rstrip(". ;:\"')(")
        if len(p2.lower().split("\\")) < 2:
            continue
        cleaned.append(p2)
    return sorted(set(cleaned))

# -----------------------------
# Path expansion & discovery
# -----------------------------
def expand_path_hint(path_hint):
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    saved = os.path.join(home, "Saved Games")
    envmap = {
        "%USERPROFILE%": home,
        "%HOMEPATH%": os.environ.get("HOMEPATH", home),
        "%HOMEDRIVE%": os.environ.get("HOMEDRIVE", "C:"),
        "%APPDATA%": os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
        "%LOCALAPPDATA%": os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local")),
        "%PROGRAMDATA%": os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        "%PUBLIC%": os.environ.get("PUBLIC", r"C:\Users\Public"),
    }
    p = path_hint
    if p.startswith("~\\") or p.startswith("~/"):
        p = os.path.join(home, p[2:])
    lowered = p.lower()
    if lowered.startswith("documents\\"):
        p = os.path.join(docs, p.split("\\", 1)[1])
    elif lowered.startswith("saved games\\"):
        p = os.path.join(saved, p.split("\\", 1)[1])
    for k, v in envmap.items():
        p = p.replace(k, v)
    p = p.replace("/", "\\")
    return os.path.normpath(p)

def enumerate_existing_paths(path_hints):
    found = []
    for hint in path_hints:
        expanded = expand_path_hint(hint)
        if os.path.exists(expanded):
            found.append(expanded)
    return sorted(set(found))

# -----------------------------
# Backup logic
# -----------------------------
def make_backup(game_name, paths, backup_root, log_widget):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\-\. ]", "_", game_name).strip() or "Game"
    out_dir = os.path.join(backup_root, safe_name)
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"{safe_name}_{ts}.zip")

    log_append(log_widget, f"→ Creating backup: {zip_path}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for base in paths:
            base = os.path.normpath(base)
            if os.path.isdir(base):
                for root, dirs, files in os.walk(base):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.join(safe_name, os.path.relpath(fpath, start=os.path.dirname(base)))
                        try:
                            zf.write(fpath, arcname)
                        except Exception as e:
                            log_append(log_widget, f"   ⚠ Skipped {fpath}: {e}")
            else:
                arcname = os.path.join(safe_name, os.path.basename(base))
                try:
                    zf.write(base, arcname)
                except Exception as e:
                    log_append(log_widget, f"   ⚠ Skipped {base}: {e}")

    log_append(log_widget, "✓ Backup complete.")
    return zip_path

# -----------------------------
# Main workflow
# -----------------------------
def find_paths_for_game(game_name, log_widget):
    cache = load_cache()
    key = game_name.strip().lower()
    if key in cache and cache[key].get("paths"):
        paths = cache[key]["paths"]
        existing = enumerate_existing_paths(paths)
        if existing:
            log_append(log_widget, f"Found cached paths for '{game_name}'.")
            return existing, paths

    log_append(log_widget, f"Searching PCGamingWiki for '{game_name}'…")
    title = pcgw_search_title(game_name)
    if not title:
        log_append(log_widget, "No page found on PCGamingWiki.")
        return [], []
    log_append(log_widget, f"→ Best match: {title}")

    idx = pcgw_find_save_section_index(title)
    if not idx:
        log_append(log_widget, "This page doesn't have a clear 'Save game data location' section.")
        return [], []

    html = pcgw_get_save_section_html(title, idx)
    hints = extract_windows_paths_from_html(html)
    if not hints:
        log_append(log_widget, "Couldn't extract any Windows save paths from the page.")
        return [], []

    log_append(log_widget, f"Found {len(hints)} potential path hints. Checking which exist on this PC…")
    existing = enumerate_existing_paths(hints)

    cache[key] = {"title": title, "hints": hints, "paths": existing}
    save_cache(cache)

    return existing, hints

# -----------------------------
# Game detection (Steam + Epic)
# -----------------------------
def read_text(path, max_bytes=5_000_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return ""

def detect_steam_libraries():
    libs = set()
    candidates = [
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Steam"),
        os.path.expandvars(r"%PROGRAMFILES%\Steam"),
        os.path.expandvars(r"%LOCALAPPDATA%\Steam"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Steam"),
    ]
    for base in candidates:
        if not base or not os.path.isdir(base):
            continue
        vdf = os.path.join(base, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            libs.add(os.path.join(base, "steamapps"))
            text = read_text(vdf)
            for m in re.finditer(r"\"path\"\s*\"([^\"]+)\"", text):
                p = m.group(1)
                steamapps = os.path.join(p, "steamapps")
                if os.path.isdir(steamapps):
                    libs.add(steamapps)
    return sorted(libs)

def parse_steam_appmanifests(steamapps_dir):
    games = {}
    for fname in os.listdir(steamapps_dir):
        if not fname.startswith("appmanifest_") or not fname.endswith(".acf"):
            continue
        path = os.path.join(steamapps_dir, fname)
        text = read_text(path)
        name = None
        installdir = None
        m_name = re.search(r"\"name\"\s*\"([^\"]+)\"", text)
        m_dir = re.search(r"\"installdir\"\s*\"([^\"]+)\"", text)
        if m_name:
            name = m_name.group(1)
        if m_dir:
            installdir = m_dir.group(1)
        if name:
            games[name] = {
                "platform": "Steam",
                "manifest": path,
                "install_dir": os.path.join(os.path.dirname(steamapps_dir), "common", installdir) if installdir else None,
            }
    return games

def detect_epic_games():
    games = {}
    manidir = os.path.expandvars(r"%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests")
    if os.path.isdir(manidir):
        for fname in os.listdir(manidir):
            if not fname.lower().endswith(".item"):
                continue
            path = os.path.join(manidir, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                name = data.get("DisplayName") or data.get("AppName")
                install = data.get("InstallLocation") or data.get("InstallFolder")
                if name:
                    games[name] = {"platform": "Epic", "manifest": path, "install_dir": install}
            except Exception:
                continue
    return games

def detect_installed_games(log_widget=None):
    all_games = {}
    steam_libs = detect_steam_libraries()
    if log_widget:
        log_append(log_widget, f"Steam libraries: {len(steam_libs)} found")
    for lib in steam_libs:
        all_games.update(parse_steam_appmanifests(lib))
    epic = detect_epic_games()
    if log_widget:
        log_append(log_widget, f"Epic games detected: {len(epic)}")
    all_games.update(epic)
    if not all_games and log_widget:
        log_append(log_widget, "No games detected via Steam/Epic.")
    return all_games

# -----------------------------
# GUI
# -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Game Save Backup")
        self.geometry("820x560")
        self.minsize(800, 520)

        self.backup_dir = tk.StringVar(value=DEFAULT_BACKUP_DIR)
        self.games = {}  # name -> metadata

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        # Row 1: game chooser
        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Label(row1, text="Installed game:").pack(side="left")
        self.game_combo = ttk.Combobox(row1, state="readonly", values=["(refresh to detect)"])
        self.game_combo.set("(refresh to detect)")
        self.game_combo.pack(side="left", fill="x", expand=True, padx=8)
        self.refresh_btn = ttk.Button(row1, text="Refresh games", command=self.on_refresh_games)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        self.find_btn = ttk.Button(row1, text="Backup selected", command=self.on_find_and_backup)
        self.find_btn.pack(side="left")

        # Row 2: backup folder
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="Backup folder:").pack(side="left")
        self.dir_entry = ttk.Entry(row2, textvariable=self.backup_dir)
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row2, text="Browse…", command=self.on_browse).pack(side="left")

        # Results
        paned = ttk.Panedwindow(frm, orient="vertical")
        paned.pack(fill="both", expand=True)

        # Found paths list
        paths_frame = ttk.Labelframe(paned, text="Detected Save Paths (existing on this PC)")
        self.paths_list = tk.Listbox(paths_frame, height=8)
        self.paths_list.pack(fill="both", expand=True, padx=8, pady=8)
        paned.add(paths_frame, weight=1)

        # Log box
        log_frame = ttk.Labelframe(paned, text="Log")
        self.log = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        paned.add(log_frame, weight=1)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

        # Load games initially
        self.after(100, self.on_refresh_games)

    def set_busy(self, busy=True):
        state = "disabled" if busy else "normal"
        for w in (self.find_btn, self.refresh_btn, self.game_combo, self.dir_entry):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def on_browse(self):
        path = filedialog.askdirectory(initialdir=self.backup_dir.get() or os.path.expanduser("~"))
        if path:
            self.backup_dir.set(path)

    def on_refresh_games(self):
        def worker():
            try:
                self.set_busy(True)
                self.status.set("Scanning for installed games (Steam/Epic)…")
                games = detect_installed_games(self.log)
                self.games = games
                names = sorted(games.keys()) or ["(none detected)"]
                self.game_combo.configure(values=names)
                self.game_combo.set(names[0])
                self.status.set(f"Detected {len(games)} games.")
            except Exception as e:
                log_append(self.log, f"Error detecting games: {e}")
                self.status.set("Error")
            finally:
                self.set_busy(False)
        threading.Thread(target=worker, daemon=True).start()

    def on_find_and_backup(self):
        game = self.game_combo.get().strip()
        if not game or game in ("(none detected)", "(refresh to detect)"):
            messagebox.showwarning("Select a game", "Please pick a game from the dropdown or refresh.")
            return
        backup_root = self.backup_dir.get().strip() or DEFAULT_BACKUP_DIR
        os.makedirs(backup_root, exist_ok=True)

        def worker():
            try:
                self.set_busy(True)
                self.status.set(f"Looking up save paths for {game}…")
                self.paths_list.delete(0, "end")

                existing, _hints = find_paths_for_game(game, self.log)
                if not existing:
                    log_append(self.log, "No existing save paths were found on this PC for that title.")
                    self.status.set("No paths found.")
                    return

                for p in existing:
                    self.paths_list.insert("end", p)

                self.status.set("Backing up…")
                zip_path = make_backup(game, existing, backup_root, self.log)
                self.status.set(f"Done: {zip_path}")
                messagebox.showinfo("Backup complete", f"Backup created:\n{zip_path}")
            except Exception as e:
                log_append(self.log, f"Error: {e}")
                self.status.set("Error")
            finally:
                self.set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app = App()
    app.mainloop()
