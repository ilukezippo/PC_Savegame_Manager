import os
import re
import io
import sys
import json
import zipfile
import threading
import datetime
import urllib.parse
import urllib.request
from html.parser import HTMLParser
import shutil
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# -----------------------------
# App metadata
# -----------------------------
APP_VERSION = "v1.0"
APP_TITLE = f"PC Savegame Manager {APP_VERSION}"
DATE_APP = "2025/11/13"

# Directories / cache
CACHE_FILE = os.path.join(os.path.expanduser("~"), ".pc_savegame_manager_cache.json")
DEFAULT_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "GameSaveBackups")

# GitHub + Donate
GITHUB_REPO_URL = "https://github.com/ilukezippo/PC_Savegame_Manager"
GITHUB_RELEASES_PAGE = GITHUB_REPO_URL + "/releases"
GITHUB_API_LATEST = "https://api.github.com/repos/ilukezippo/PC_Savegame_Manager/releases/latest"
DONATE_PAGE = "https://buymeacoffee.com/ilukezippo"

PCGW_API = "https://www.pcgamingwiki.com/w/api.php"


# -----------------------------
# Cache load/save
# -----------------------------
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


def log_append(widget, text):
    widget.config(state="normal")
    widget.insert("end", text + "\n")
    widget.see("end")
    widget.config(state="disabled")


# -----------------------------
# Resource path + app icon
# -----------------------------
def resource_path(p):
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, p)


def set_app_icon(root):
    path = resource_path("logo.png")
    if os.path.exists(path):
        try:
            img = tk.PhotoImage(file=path)
            root.iconphoto(True, img)
            root._icon_img_ref = img
        except:
            pass


# -----------------------------
# HTML parser
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
# PCGamingWiki functions
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
    if len(data) >= 2 and data[1]:
        return data[1][0]
    return None


def pcgw_find_save_section_index(title):
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
    for s in sections:
        if "save game data location" in s.get("line", "").strip().lower():
            return s.get("index")
    return None


def pcgw_get_save_section_html(title, idx):
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "section": idx,
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
        r"[A-Za-z]:\\[^\n\r<>\|\?\*\"]+",
        r"%[A-Za-z_]+%\\[^\n\r<>\|\?\*\"]+",
        r"~\\[^\n\r<>\|\?\*\"]+",
        r"\\Users\\[^\\\n\r]+\\[^\n\r<>\|\?\*\"]+",
        r"Documents\\[^\n\r<>\|\?\*\"]+",
        r"Saved Games\\[^\n\r<>\|\?\*\"]+",
        r"AppData\\Roaming\\[^\n\r<>\|\?\*\"]+",
        r"AppData\\Local\\[^\n\r<>\|\?\*\"]+",
        r"OneDrive\\Documents\\[^\n\r<>\|\?\*\"]+",
    ]

    rx = re.compile("(" + ")|(".join(patterns) + ")")
    candidates = set(m.group(0) for m in rx.finditer(text))

    cleaned = []
    for c in candidates:
        p = c.strip().rstrip(". ;:\"')(")
        if len(p.split("\\")) < 2:
            continue
        cleaned.append(p)

    return sorted(set(cleaned))


# -----------------------------
# Path expansion
# -----------------------------
def expand_path_hint(h):
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    saved = os.path.join(home, "Saved Games")

    env = {
        "%USERPROFILE%": home,
        "%HOMEPATH%": os.environ.get("HOMEPATH", home),
        "%HOMEDRIVE%": os.environ.get("HOMEDRIVE", "C:"),
        "%APPDATA%": os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming")),
        "%LOCALAPPDATA%": os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local")),
        "%PROGRAMDATA%": os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        "%PUBLIC%": os.environ.get("PUBLIC", r"C:\Users\Public"),
    }

    p = h

    if p.startswith("~\\") or p.startswith("~/"):
        p = os.path.join(home, p[2:])

    l = p.lower()
    if l.startswith("documents\\"):
        p = os.path.join(docs, p.split("\\", 1)[1])
    elif l.startswith("saved games\\"):
        p = os.path.join(saved, p.split("\\", 1)[1])

    for k, v in env.items():
        p = p.replace(k, v)

    return os.path.normpath(p.replace("/", "\\"))


def enumerate_existing_paths(hints):
    found = []
    for hint in hints:
        exp = expand_path_hint(hint)
        if os.path.exists(exp):
            found.append(exp)
    return sorted(set(found))


# -----------------------------
# Backup creation
# -----------------------------
def make_backup(game_name, paths, backup_root, log_widget):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\s.-]", "_", game_name).strip() or "Game"
    out_dir = os.path.join(backup_root, safe_name)
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"{safe_name}_{timestamp}.zip")

    log_append(log_widget, f"→ Creating backup: {zip_path}")

    records = []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for idx, base in enumerate(paths):
            base = os.path.normpath(base)

            if os.path.isdir(base):
                records.append({"index": idx, "type": "dir", "base": base})
                for root, dirs, files in os.walk(base):
                    for f in files:
                        fpath = os.path.join(root, f)
                        rel = os.path.relpath(fpath, base)
                        arcname = f"{idx}/{rel}"
                        try:
                            z.write(fpath, arcname)
                        except Exception as e:
                            log_append(log_widget, f"⚠ Skipped {fpath}: {e}")
            else:
                records.append({"index": idx, "type": "file", "base": base})
                rel = os.path.basename(base)
                arcname = f"{idx}/{rel}"
                try:
                    z.write(base, arcname)
                except Exception as e:
                    log_append(log_widget, f"⚠ Skipped {base}: {e}")

        meta = {"game": game_name, "paths": records}
        z.writestr("__pcsm_paths.json", json.dumps(meta, ensure_ascii=False, indent=2))

    log_append(log_widget, "✓ Backup complete.")
    return zip_path


# -----------------------------
# Search for save paths
# -----------------------------
def find_save_paths(game_name, log_widget):
    cache = load_cache()
    key = game_name.lower()

    if key in cache and cache[key].get("hints"):
        existing = enumerate_existing_paths(cache[key]["hints"])
        if existing:
            log_append(log_widget, f"Found cached paths for '{game_name}'.")
            return existing, cache[key]["hints"]

    log_append(log_widget, f"Searching PCGamingWiki for '{game_name}'…")
    title = pcgw_search_title(game_name)
    if not title:
        return [], []

    log_append(log_widget, f"→ Matched: {title}")

    idx = pcgw_find_save_section_index(title)
    if not idx:
        return [], []

    html = pcgw_get_save_section_html(title, idx)
    hints = extract_windows_paths_from_html(html)

    if not hints:
        return [], []

    existing = enumerate_existing_paths(hints)

    cache[key] = {"hints": hints}
    save_cache(cache)

    return existing, hints


# -----------------------------
# Main App
# -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("900x600")
        self.minsize(900, 580)
        set_app_icon(self)

        self.style = ttk.Style(self)
        self.style.configure("Big.TButton", padding=(12, 8), font=("Segoe UI", 10, "bold"))

        cache = load_cache()
        last_dir = cache.get("last_backup_dir", DEFAULT_BACKUP_DIR)
        self.backup_dir = tk.StringVar(value=last_dir)

        self.suggestion_box = None
        self.suggest_after_id = None
        self.found_paths = []  # last found save paths

        # Header
        self.build_header()

        # Notebook
        self.notebook = ttk.Notebook(self)
        self.tab_backup = ttk.Frame(self.notebook)
        self.tab_restore = ttk.Frame(self.notebook)
        self.tab_about = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_backup, text="Backup")
        self.notebook.add(self.tab_restore, text="Restore")
        self.notebook.add(self.tab_about, text="About")
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Build tabs
        self.build_backup_tab()
        self.build_restore_tab()
        self.build_about_tab()

        # Center + auto-check for updates
        self.after(100, self.center)
        self.after(1200, self.check_latest_app_version_async)

    # -------------------------
    # Header with logo + title
    # -------------------------
    def build_header(self):
        header = ttk.Frame(self, padding=(10, 10))
        header.pack(fill="x")


        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
                # Load original
                orig = tk.PhotoImage(file=logo_path)

                # Target height (like Windows App Updater)
                target_h = 40
                ratio = orig.width() / orig.height()
                target_w = int(target_h * ratio)

                # Shrink using built-in subsample
                # Determine best integer subsample factor
                fx = max(1, orig.width() // target_w)
                fy = max(1, orig.height() // target_h)

                self.header_logo = orig.subsample(fx, fy)

                tk.Label(header, image=self.header_logo).pack(side="left", padx=(0, 10))



        ttk.Label(
            header,
            text=APP_TITLE,
            font=("Segoe UI", 18, "bold")
        ).pack(side="left")

    def center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = (sw // 2) - (w // 2)
        y = (sh // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # -----------------------------
    # BACKUP TAB
    # -----------------------------
    def build_backup_tab(self):
        frame = ttk.Frame(self.tab_backup, padding=12)
        frame.pack(fill="both", expand=True)

        # Row 1: Game name + Find + Backup
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=8)

        ttk.Label(row1, text="Game name:").pack(side="left")
        self.game_entry = ttk.Entry(row1)
        self.game_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.game_entry.bind("<KeyRelease>", self.on_game_typed)
        self.game_entry.bind("<Down>", self.on_entry_down)
        self.game_entry.bind("<Return>", self.on_entry_return)

        ttk.Button(
            row1,
            text="Find Save Paths",
            command=self.on_find_paths,
            style="Big.TButton"
        ).pack(side="left", padx=6)

        self.backup_btn = ttk.Button(
            row1,
            text="Backup Files",
            command=self.on_backup,
            state="disabled",
            style="Big.TButton"
        )
        self.backup_btn.pack(side="left")

        # Row 2: Backup folder
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=8)

        ttk.Label(row2, text="Backup folder:").pack(side="left")
        ttk.Entry(row2, textvariable=self.backup_dir).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row2, text="Browse…", command=self.on_browse, style="Big.TButton").pack(side="left")

        # Split: detected paths + log
        paned = ttk.Panedwindow(frame, orient="vertical")
        paned.pack(fill="both", expand=True)

        paths_box = ttk.Labelframe(paned, text="Detected Save Paths")
        self.paths_list = tk.Listbox(paths_box, height=8)
        self.paths_list.pack(fill="both", expand=True, padx=8, pady=8)
        self.paths_list.bind("<Double-Button-1>", self.open_selected_path)
        paned.add(paths_box, weight=1)

        log_box = ttk.Labelframe(paned, text="Log")
        self.log = tk.Text(log_box, state="disabled", wrap="word", height=10)
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        paned.add(log_box, weight=1)

    # -----------------------------
    # RESTORE TAB
    # -----------------------------
    def build_restore_tab(self):
        frame = ttk.Frame(self.tab_restore, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Backup ZIP file:").pack(anchor="w")
        self.restore_zip = tk.StringVar()
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Entry(row, textvariable=self.restore_zip).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse ZIP", command=self.browse_zip, style="Big.TButton").pack(side="left", padx=8)

        ttk.Label(
            frame,
            text="Restores files back to their original save locations stored in the backup metadata."
        ).pack(anchor="w", pady=(10, 6))

        ttk.Button(
            frame,
            text="Restore Backup",
            command=self.restore_backup,
            style="Big.TButton"
        ).pack(pady=10)

    # -----------------------------
    # ABOUT TAB
    # -----------------------------
    def build_about_tab(self):
        frame = ttk.Frame(self.tab_about, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="PC Savegame Manager", font=("Segoe UI", 14, "bold")).pack(pady=(0, 4))
        ttk.Label(
            frame,
            text="is a freeware Python app to detect, back up, and restore PC game save data.",
            wraplength=520,
            justify="center"
        ).pack(pady=(0, 8))

        ttk.Label(frame, text=f"Version {APP_VERSION} - {DATE_APP}").pack(pady=(0, 10))

        # Author
        row = ttk.Frame(frame)
        row.pack()
        ttk.Label(row, text="Author: ilukezippo (BoYaqoub)").pack(side="left")

        # Email
        email_row = ttk.Frame(frame)
        email_row.pack(pady=(8, 0))
        ttk.Label(email_row, text="For any feedback contact: ").pack(side="left")
        email_lbl = tk.Label(
            email_row,
            text="ilukezippo@gmail.com",
            fg="#1a73e8",
            cursor="hand2",
            font=("Segoe UI", 9, "underline")
        )
        email_lbl.pack(side="left")
        email_lbl.bind("<Button-1>", lambda e: webbrowser.open("mailto:ilukezippo@gmail.com"))

        # GitHub link
        link_row = ttk.Frame(frame)
        link_row.pack(pady=(8, 0))
        tk.Label(link_row, text="Info and latest updates at ").pack(side="left")
        gh_lbl = tk.Label(
            link_row,
            text=GITHUB_REPO_URL,
            fg="#1a73e8",
            cursor="hand2",
            font=("Segoe UI", 9, "underline")
        )
        gh_lbl.pack(side="left")
        gh_lbl.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_REPO_URL))

        # Buttons: GitHub / Release / Donate / Check for Update
        btn_wrap = ttk.Frame(frame)
        btn_wrap.pack(pady=(16, 8))

        ttk.Button(
            btn_wrap,
            text="Open GitHub Page",
            style="Big.TButton",
            command=lambda: webbrowser.open(GITHUB_REPO_URL)
        ).pack(fill="x", pady=3)

        ttk.Button(
            btn_wrap,
            text="Open Releases Page",
            style="Big.TButton",
            command=lambda: webbrowser.open(GITHUB_RELEASES_PAGE)
        ).pack(fill="x", pady=3)

        ttk.Button(
            btn_wrap,
            text="Donate ❤️",
            style="Big.TButton",
            command=lambda: webbrowser.open(DONATE_PAGE)
        ).pack(fill="x", pady=3)

        ttk.Button(
            frame,
            text="Check for Update",
            style="Big.TButton",
            command=self.manual_check_for_update
        ).pack(pady=(8, 0))

    # -----------------------------
    # Backup functions
    # -----------------------------
    def on_browse(self):
        d = filedialog.askdirectory(initialdir=self.backup_dir.get())
        if d:
            self.backup_dir.set(d)
            cache = load_cache()
            cache["last_backup_dir"] = d
            save_cache(cache)

    def on_find_paths(self):
        game = self.game_entry.get().strip()
        if not game:
            messagebox.showwarning("Missing input", "Please type a game name.")
            return

        self.paths_list.delete(0, "end")
        self.backup_btn.config(state="disabled")
        log_append(self.log, f"Finding save paths for: {game}")

        def worker():
            try:
                found, hints = find_save_paths(game, self.log)
                self.found_paths = found

                if not found:
                    self.after(0, lambda: messagebox.showwarning(
                        "No Save Files Found",
                        "No save files were found for this game.\n"
                        "Make sure the game is installed & has been run at least once."
                    ))
                    return

                def after_ui():
                    self.paths_list.delete(0, "end")
                    for p in found:
                        self.paths_list.insert("end", p)
                    self.backup_btn.config(state="normal")

                self.after(0, after_ui)

            except Exception as e:
                self.after(0, lambda: log_append(self.log, f"Error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_backup(self):
        if not self.found_paths:
            messagebox.showerror("Error", "No save paths found. Please run 'Find Save Paths' first.")
            return

        game = self.game_entry.get().strip()
        backup_root = self.backup_dir.get() or DEFAULT_BACKUP_DIR
        os.makedirs(backup_root, exist_ok=True)

        cache = load_cache()
        cache["last_backup_dir"] = backup_root
        save_cache(cache)

        zip_path = make_backup(game, self.found_paths, backup_root, self.log)
        messagebox.showinfo("Backup Complete", f"Backup created:\n{zip_path}")

    def open_selected_path(self, event=None):
        sel = self.paths_list.curselection()
        if not sel:
            return
        p = self.paths_list.get(sel[0])
        try:
            os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
        except:
            pass

    # -----------------------------
    # Restore functions
    # -----------------------------
    def browse_zip(self):
        f = filedialog.askopenfilename(filetypes=[("ZIP Files", "*.zip")])
        if f:
            self.restore_zip.set(f)

    def restore_backup(self):
        zipf = self.restore_zip.get().strip()
        if not zipf or not os.path.isfile(zipf):
            messagebox.showerror("Error", "Please select a valid backup ZIP.")
            return

        try:
            with zipfile.ZipFile(zipf, "r") as z:
                try:
                    meta = json.loads(z.read("__pcsm_paths.json").decode("utf-8"))
                except:
                    messagebox.showerror("Error", "Backup missing metadata.")
                    return

                paths_meta = meta.get("paths", [])
                if not paths_meta:
                    messagebox.showerror("Error", "Metadata contains no save paths.")
                    return

                index_map = {p["index"]: p for p in paths_meta}

                # Check conflicts
                conflict = False
                for zinfo in z.infolist():
                    if zinfo.filename == "__pcsm_paths.json" or zinfo.filename.endswith("/"):
                        continue
                    parts = zinfo.filename.split("/", 1)
                    if len(parts) != 2:
                        continue
                    idx_s, rel = parts
                    try:
                        idx = int(idx_s)
                    except:
                        continue
                    rec = index_map.get(idx)
                    if not rec:
                        continue
                    base = rec["base"]
                    typ = rec["type"]
                    dest = os.path.join(base, rel) if typ == "dir" else base
                    if os.path.exists(dest):
                        conflict = True
                        break

                if conflict:
                    ok = messagebox.askokcancel(
                        "Overwrite files?",
                        "Some destination files already exist.\n\n"
                        "Press Overwrite to replace ALL existing files,\n"
                        "or Cancel to abort restore."
                    )
                    if not ok:
                        return

                # Perform restore (overwrite all)
                count = 0
                for zinfo in z.infolist():
                    if zinfo.filename == "__pcsm_paths.json" or zinfo.filename.endswith("/"):
                        continue
                    parts = zinfo.filename.split("/", 1)
                    if len(parts) != 2:
                        continue
                    idx_s, rel = parts
                    try:
                        idx = int(idx_s)
                    except:
                        continue
                    rec = index_map.get(idx)
                    if not rec:
                        continue
                    base = rec["base"]
                    typ = rec["type"]
                    dest = os.path.join(base, rel) if typ == "dir" else base
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(zinfo) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1

                messagebox.showinfo("Restore Complete", f"Files restored: {count}")

        except Exception as e:
            messagebox.showerror("Error", f"Restore failed:\n{e}")

    # -----------------------------
    # Autocomplete
    # -----------------------------
    def on_game_typed(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return

        text = self.game_entry.get().strip()

        if self.suggest_after_id:
            self.after_cancel(self.suggest_after_id)

        if len(text) < 2:
            if self.suggestion_box:
                self.suggestion_box.destroy()
                self.suggestion_box = None
            return

        self.suggest_after_id = self.after(300, lambda: self.run_suggestion_search(text))

    def run_suggestion_search(self, text):
        def worker(q):
            results = []
            try:
                params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": q,
                    "srlimit": 20,
                    "format": "json",
                }
                url = PCGW_API + "?" + urllib.parse.urlencode(params)
                with urllib.request.urlopen(url, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
                results = [i["title"] for i in data.get("query", {}).get("search", [])]
            except:
                pass
            self.after(0, lambda: self.show_suggestions(results))

        threading.Thread(target=worker, args=(text,), daemon=True).start()

    def show_suggestions(self, results):
        if self.suggestion_box:
            self.suggestion_box.destroy()

        if not results:
            return

        lb = tk.Listbox(self, height=min(10, len(results)))
        for r in results:
            lb.insert("end", r)

        x = self.game_entry.winfo_rootx() - self.winfo_rootx()
        y = (self.game_entry.winfo_rooty() - self.winfo_rooty()
             + self.game_entry.winfo_height())
        lb.place(x=x, y=y, width=self.game_entry.winfo_width())

        lb.bind("<Up>", self.on_suggest_up)
        lb.bind("<Down>", self.on_suggest_down)
        lb.bind("<Return>", self.on_suggest_enter)
        lb.bind("<ButtonRelease-1>", self.on_suggest_click)
        lb.bind("<Escape>", lambda e: self.destroy_suggestion_box())

        self.suggestion_box = lb

    def destroy_suggestion_box(self):
        if self.suggestion_box:
            self.suggestion_box.destroy()
            self.suggestion_box = None

    def on_entry_down(self, e):
        if self.suggestion_box:
            self.suggestion_box.focus_set()
            self.suggestion_box.selection_set(0)
        return "break"

    def on_entry_return(self, e):
        if self.suggestion_box:
            self.select_suggestion()
            return "break"

    def on_suggest_up(self, e):
        lb = self.suggestion_box
        if not lb:
            return "break"
        sel = lb.curselection()
        if not sel:
            lb.selection_set(0)
        else:
            i = sel[0]
            if i > 0:
                lb.selection_clear(i)
                lb.selection_set(i - 1)
        return "break"

    def on_suggest_down(self, e):
        lb = self.suggestion_box
        if not lb:
            return "break"
        sel = lb.curselection()
        if not sel:
            lb.selection_set(0)
        else:
            i = sel[0]
            if i < lb.size() - 1:
                lb.selection_clear(i)
                lb.selection_set(i + 1)
        return "break"

    def on_suggest_enter(self, e):
        self.select_suggestion()
        return "break"

    def on_suggest_click(self, e):
        self.select_suggestion()

    def select_suggestion(self):
        if not self.suggestion_box:
            return
        sel = self.suggestion_box.curselection()
        if not sel:
            return
        val = self.suggestion_box.get(sel[0])
        self.game_entry.delete(0, "end")
        self.game_entry.insert("end", val)
        self.destroy_suggestion_box()
        self.game_entry.focus_set()

    # -----------------------------
    # Update check helpers
    # -----------------------------
    def _parse_ver_tuple(self, v: str):
        nums = re.findall(r"\d+", v)
        return tuple(int(n) for n in nums[:4]) or (0,)

    def manual_check_for_update(self):
        """Manual check from About tab."""
        def worker():
            try:
                req = urllib.request.Request(
                    GITHUB_API_LATEST,
                    headers={"User-Agent": "PC-Savegame-Manager"}
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                tag = str(data.get("tag_name") or data.get("name") or "").strip()
                cur = APP_VERSION
                newer = bool(tag and self._parse_ver_tuple(tag) > self._parse_ver_tuple(cur))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Update check failed", str(e)))
                return

            def after():
                if newer:
                    if messagebox.askyesno(
                        "New Version Available",
                        f"A newer version {tag} is available.\n\nOpen the releases page now?"
                    ):
                        webbrowser.open(GITHUB_RELEASES_PAGE)
                else:
                    messagebox.showinfo("You're up to date", f"Current version {cur} is the latest.")

            self.after(0, after)

        threading.Thread(target=worker, daemon=True).start()

    def check_latest_app_version_async(self):
        """Automatic check on startup; silent on errors."""
        def worker():
            try:
                req = urllib.request.Request(
                    GITHUB_API_LATEST,
                    headers={"User-Agent": "PC-Savegame-Manager"}
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                tag = str(data.get("tag_name") or data.get("name") or "").strip()
                if tag and self._parse_ver_tuple(tag) > self._parse_ver_tuple(APP_VERSION):
                    def _ask():
                        if messagebox.askyesno(
                            "New Version Available",
                            f"A newer version {tag} is available.\n\nOpen the releases page now?"
                        ):
                            webbrowser.open(GITHUB_RELEASES_PAGE)
                    self.after(0, _ask)
            except Exception:
                # Ignore any error on auto-check
                pass

        threading.Thread(target=worker, daemon=True).start()


# -----------------------------
# Run app
# -----------------------------
if __name__ == "__main__":
    App().mainloop()
