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
    """Extract all text within an HTML snippet."""
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
    """Return the best page title for a game using PCGamingWiki opensearch."""
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
    # data = [search, titles[], descriptions[], links[]]
    if data and len(data) >= 2 and data[1]:
        return data[1][0]
    return None


def pcgw_find_save_section_index(title):
    """Get the section index for 'Save game data location'."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "sections",
        "format": "json",
    }
    url = PCGW_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    sections = data.get("parse", {}).get("sections", [])
    for s in sections:
        if s.get("line", "").strip().lower() == "save game data location":
            return s.get("index")
    # Some pages use 'Save game data location (Windows)' etc.
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
    html = data.get("parse", {}).get("text", {}).get("*", "")
    return html


def extract_windows_paths_from_html(html):
    """Heuristic: pull plausible Windows save paths from a section's HTML text."""
    parser = TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    # Common Windows path patterns
    patterns = [
        r"[A-Za-z]:\\[^\n\r<>\|\?\*\"]+",                 # Absolute paths like C:\Users\...\Game
        r"%[A-Za-z_]+%\\[^\n\r<>\|\?\*\"]+",               # %APPDATA%\Foo
        r"~\\[^\n\r<>\|\?\*\"]+",                          # ~\Saved Games\...
        r"\\Users\\[^\\\n\r]+\\[^\n\r<>\|\?\*\"]+",     # \Users\Name\...
        r"Documents\\[^\n\r<>\|\?\*\"]+",                    # Documents\My Games\...
        r"Saved Games\\[^\n\r<>\|\?\*\"]+",                 # Saved Games\Game
        r"AppData\\Roaming\\[^\n\r<>\|\?\*\"]+",          # AppData\Roaming\...
        r"AppData\\Local\\[^\n\r<>\|\?\*\"]+",            # AppData\Local\...
        r"OneDrive\\Documents\\[^\n\r<>\|\?\*\"]+",       # OneDrive paths
    ]
    rx = re.compile("(" + ")|(".join(patterns) + ")")
    candidates = set(m.group(0) for m in rx.finditer(text))
    # Filter out obviously non-Windows or note lines
    cleaned = []
    for p in candidates:
        # remove trailing punctuation
        p2 = p.strip().rstrip(". ;:\"')(")
        # Skip if it's just 'Documents' etc.
        tokens = p2.lower().split("\\")
        if len(tokens) < 2:
            continue
        cleaned.append(p2)
    return sorted(set(cleaned))

# -----------------------------
# Path expansion & discovery
# -----------------------------

def expand_path_hint(path_hint):
    """Expand environment variables and common placeholders for Windows user."""
    # Map common variables to real locations
    home = os.path.expanduser("~")
    # Known special folders
    docs = os.path.join(home, "Documents")
    saved = os.path.join(home, "Saved Games")

    envmap = {
        "%USERPROFILE%": home,
        "%HOMEPATH%": os.environ.get("HOMEPATH", home),
        "%HOMEDRIVE%": os.environ.get("HOMEDRIVE", "C:"),
        "%APPDATA%": os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
        "%LOCALAPPDATA%": os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local")),
        "%PROGRAMDATA%": os.environ.get("PROGRAMDATA", r"C:\\ProgramData"),
        "%PUBLIC%": os.environ.get("PUBLIC", r"C:\\Users\\Public"),
    }

    p = path_hint

    # Handle tilde
    if p.startswith("~\\") or p.startswith("~/"):
        p = os.path.join(home, p[2:])

    # If it begins with Documents or Saved Games, prepend home
    lowered = p.lower()
    if lowered.startswith("documents\\"):
        p = os.path.join(docs, p.split("\\", 1)[1])
    elif lowered.startswith("saved games\\"):
        p = os.path.join(saved, p.split("\\", 1)[1])

    # Replace %VARS%
    for k, v in envmap.items():
        p = p.replace(k, v)

    # Normalize backslashes
    p = p.replace("/", "\\")
    return os.path.normpath(p)


def enumerate_existing_paths(path_hints):
    """Return list of real, existing directories/files from hints."""
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

    # Create ZIP and add files
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for base in paths:
            base = os.path.normpath(base)
            if os.path.isdir(base):
                for root, dirs, files in os.walk(base):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        # Preserve relative path under the base directory
                        arcname = os.path.join(safe_name, os.path.relpath(fpath, start=os.path.dirname(base)))
                        try:
                            zf.write(fpath, arcname)
                        except Exception as e:
                            log_append(log_widget, f"   ⚠ Skipped {fpath}: {e}")
            else:
                # single file
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
    # 1) Check cache first
    cache = load_cache()
    key = game_name.strip().lower()
    if key in cache and cache[key].get("paths"):
        paths = cache[key]["paths"]
        existing = enumerate_existing_paths(paths)
        if existing:
            log_append(log_widget, f"Found cached paths for '{game_name}'.")
            return existing, paths

    # 2) PCGamingWiki lookup
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

    # Update cache (store hints even if not found, to avoid re-query)
    cache[key] = {"title": title, "hints": hints, "paths": existing}
    save_cache(cache)

    return existing, hints

# -----------------------------
# GUI
# -----------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Game Save Backup")
        self.geometry("720x520")
        self.minsize(700, 500)

        self.backup_dir = tk.StringVar(value=DEFAULT_BACKUP_DIR)

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Label(row1, text="Game name:").pack(side="left")
        self.game_entry = ttk.Entry(row1)
        self.game_entry.pack(side="left", fill="x", expand=True, padx=8)

        self.find_btn = ttk.Button(row1, text="Find & Backup", command=self.on_find_and_backup)
        self.find_btn.pack(side="left")

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

        # Keyboard focus
        self.game_entry.focus_set()

    def set_busy(self, busy=True):
        state = "disabled" if busy else "normal"
        self.find_btn.configure(state=state)
        self.game_entry.configure(state=state)

    def on_browse(self):
        path = filedialog.askdirectory(initialdir=self.backup_dir.get() or os.path.expanduser("~"))
        if path:
            self.backup_dir.set(path)

    def on_find_and_backup(self):
        game = self.game_entry.get().strip()
        if not game:
            messagebox.showwarning("Input required", "Please type a game name.")
            return
        backup_root = self.backup_dir.get().strip() or DEFAULT_BACKUP_DIR
        os.makedirs(backup_root, exist_ok=True)

        def worker():
            try:
                self.set_busy(True)
                self.status.set("Looking up save paths…")
                self.paths_list.delete(0, "end")

                existing, hints = find_paths_for_game(game, self.log)
                if not existing:
                    log_append(self.log, "No existing save paths were found on this PC. You can:")
                    log_append(self.log, "• Click the 'Detected Save Paths' list if any appear later, or")
                    log_append(self.log, "• Manually add the folder before retrying.")
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
