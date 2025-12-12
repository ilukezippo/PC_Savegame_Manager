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
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

# -----------------------------
# App metadata
# -----------------------------
APP_VERSION = "v1.2"
APP_TITLE = f"PC Savegame Manager {APP_VERSION}"
DATE_APP = "2025/12/12"

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
    """Thread-safe append to a Tk Text widget."""
    def _do():
        try:
            widget.config(state="normal")
            widget.insert("end", text + "\n")
            widget.see("end")
            widget.config(state="disabled")
        except Exception:
            # If widget was destroyed while a worker was still running
            pass

    try:
        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            widget.after(0, _do)
    except Exception:
        pass



# -----------------------------
# Resource path + app icon
# -----------------------------
def resource_path(relative_path):
    try:
        # PyInstaller creates _MEIPASS at runtime
        base_path = sys._MEIPASS
    except Exception:
        # Running in normal Python environment
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)



def set_app_icon(root):
    path = resource_path("logo.ico")
    if os.path.exists(path):
        try:
            root.iconbitmap(resource_path("logo.ico"))
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
# Loading (Modal) Window
# -----------------------------
class LoadingWindow:
    """A simple modal loading window that can be shown from the UI thread."""
    def __init__(self, root):
        self.root = root
        self.win = None
        self.msg_var = tk.StringVar(value="Working...")
        self._show_count = 0

    def show(self, message="Working..."):
        self._show_count += 1
        self.msg_var.set(message)

        # Already visible -> just update text
        if self.win and self.win.winfo_exists():
            try:
                self.win.lift()
            except Exception:
                pass
            return

        self.win = tk.Toplevel(self.root)
        self.win.title("Working")
        self.win.resizable(False, False)
        self.win.transient(self.root)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)  # disable close

        pad = 14
        wrap = ttk.Frame(self.win, padding=(pad, pad))
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, textvariable=self.msg_var, font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))

        pb = ttk.Progressbar(wrap, mode="indeterminate", length=320)
        pb.pack()
        pb.start(10)

        # Center it over the main window
        self.root.update_idletasks()
        self.win.update_idletasks()
        rwx = self.root.winfo_rootx()
        rwy = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        ww = self.win.winfo_width()
        wh = self.win.winfo_height()
        x = rwx + (rw // 2) - (ww // 2)
        y = rwy + (rh // 2) - (wh // 2)
        self.win.geometry(f"{ww}x{wh}+{x}+{y}")

        try:
            self.win.grab_set()
        except Exception:
            pass

    def hide(self):
        self._show_count = max(0, self._show_count - 1)
        if self._show_count > 0:
            return
        if self.win and self.win.winfo_exists():
            try:
                self.win.grab_release()
            except Exception:
                pass
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None


# -----------------------------
# Main App
# -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1000x650")
        self.minsize(1000, 620)
        set_app_icon(self)

        # =============================
        # Global UI Styling (Option A)
        # =============================
        style = ttk.Style(self)

        style.configure("TNotebook.Tab", padding=(20, 12), font=("Segoe UI", 12, "bold"))
        style.configure("TLabel", font=("Segoe UI", 12))
        style.configure("TEntry", font=("Segoe UI", 12))
        style.configure("Big.TButton", padding=(14, 10), font=("Segoe UI", 12, "bold"))

        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 12))
        self.option_add("*Font", ("Segoe UI", 12))

        # =============================
        # Load cache
        # =============================
        cache = load_cache()
        last_dir = cache.get("last_backup_dir", DEFAULT_BACKUP_DIR)
        self.backup_dir = tk.StringVar(value=last_dir)

        self.suggestion_box = None
        self.suggest_after_id = None
        self.found_paths = []
        self.loading = LoadingWindow(self)

        self.suggest_seq = 0
        self.last_suggest_query = ""
        self.suppress_suggestions = False

        # Header
        self.build_header()

        # Notebook
        self.notebook = ttk.Notebook(self)
        self.tab_backup = ttk.Frame(self.notebook, padding=15)
        self.tab_restore = ttk.Frame(self.notebook, padding=15)
        self.tab_google = ttk.Frame(self.notebook, padding=15)
        self.tab_about = ttk.Frame(self.notebook, padding=15)

        self.notebook.add(self.tab_backup, text="Backup")
        self.notebook.add(self.tab_restore, text="Restore")
        self.notebook.add(self.tab_google, text="Sync with Google Drive")
        self.notebook.add(self.tab_about, text="About")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # Hide suggestions when clicking anywhere else (forces focus out)
        self.bind_all("<Button-1>", self._any_click_force_focus_out, add="+")

        # Build tabs (game_entry is created in build_backup_tab)
        self.build_backup_tab()
        self.build_restore_tab()
        self.build_google_tab()
        self.build_about_tab()

        # NOW bind the entry focus/click to refresh suggestions again
        if hasattr(self, "game_entry") and self.game_entry is not None:
            self.game_entry.bind("<FocusIn>", self._entry_refocus_check_suggestions, add="+")
            self.game_entry.bind("<Button-1>", self._entry_refocus_check_suggestions, add="+")

        # Center + auto-check for updates
        self.after(100, self.center)
        self.after(1200, self.check_latest_app_version_async)


    def _any_click_force_focus_out(self, event):
        # If game_entry not created yet, do nothing
        if not hasattr(self, "game_entry") or self.game_entry is None:
            return

        clicked = None
        try:
            clicked = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            pass

        # If click is on entry or on suggestion box, keep it
        if clicked is self.game_entry or clicked is self.suggestion_box:
            return

        # Force focus away from entry
        try:
            if clicked is not None:
                clicked.focus_set()
            else:
                self.focus_set()
        except Exception:
            self.focus_set()

        # Hide suggestions immediately
        self.destroy_suggestion_box()


    def _entry_refocus_check_suggestions(self, event=None):
        # Delay so focus is applied first
        self.after(1, self._entry_refocus_check_suggestions_now)


    def _entry_refocus_check_suggestions_now(self):
        # Only show on Backup tab (index 0)
        try:
            if self.notebook.index("current") != 0:
                return
        except Exception:
            return

        txt = self.game_entry.get().strip()

        # Always hide first
        self.destroy_suggestion_box()

        # Re-check name again (fresh)
        if len(txt) < 2:
            return

        class _E:
            keysym = ""

        self.on_game_typed(_E())


    # -------------------------
    # Header with logo + title
    # -------------------------
    def build_header(self):
        header = ttk.Frame(self, padding=(10, 10))
        header.pack(fill="x")

        # Load header PNG logo (scaled automatically)
        logo_png = resource_path("logo.png")
        if os.path.exists(logo_png):
            try:
                orig = tk.PhotoImage(file=logo_png)

                target_h = 40  # final height of the header icon
                orig_h = orig.height()
                orig_w = orig.width()

                # compute scale (subsample requires integers)
                scale = max(1, orig_h // target_h)

                self.header_logo = orig.subsample(scale, scale)
                tk.Label(header, image=self.header_logo).pack(side="left", padx=(0, 10))
            except:
                pass

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
    # Async helpers + loading
    # -----------------------------
    def run_async(self, loading_text, work_fn, on_success=None, on_error=None, show_loading=True):
        """Run work_fn() in a daemon thread; marshal callbacks back to the UI thread."""
        if show_loading:
            self.loading.show(loading_text)

        def _worker():
            try:
                result = work_fn()
            except Exception as e:
                tb = traceback.format_exc()

                def _err():
                    if show_loading:
                        self.loading.hide()
                    if on_error:
                        on_error(e, tb)
                    else:
                        messagebox.showerror("Error", str(e))

                self.after(0, _err)
            else:
                def _ok():
                    if show_loading:
                        self.loading.hide()
                    if on_success:
                        on_success(result)
                self.after(0, _ok)

        threading.Thread(target=_worker, daemon=True).start()

    def on_tab_changed(self, event=None):
        # Hide suggestions when switching tabs + invalidate any pending suggestion worker
        self.suggest_seq += 1
        if self.suggest_after_id:
            try:
                self.after_cancel(self.suggest_after_id)
            except Exception:
                pass
            self.suggest_after_id = None
        self.destroy_suggestion_box()


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
        self.game_entry.bind("<FocusOut>", self.on_game_entry_focus_out)

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
    # GOOGLE CLOUD TAB
    # -----------------------------
    def build_google_tab(self):
        frame = ttk.Frame(self.tab_google, padding=12)
        frame.pack(fill="both", expand=True)

        # Save Game Folder
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=8)
        ttk.Label(row1, text="Save Game Folder:").pack(side="left")
        self.google_save_path = tk.StringVar()
        ttk.Entry(row1, textvariable=self.google_save_path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row1, text="Browse…", command=self.browse_save_path, style="Big.TButton").pack(side="left")

        # Google Drive Folder
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=8)
        ttk.Label(row2, text="Google Drive Sync Folder:").pack(side="left")
        self.google_drive_path = tk.StringVar()
        ttk.Entry(row2, textvariable=self.google_drive_path).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row2, text="Browse…", command=self.browse_drive_path, style="Big.TButton").pack(side="left")

        # Sync button
        ttk.Button(
            frame,
            text="Sync Save to Cloud",
            style="Big.TButton",
            command=self.sync_backup_to_cloud
        ).pack(pady=(16, 10))

        # =========================
        # Scrollable instructions UI
        # =========================

        tips = ttk.Labelframe(frame, text="How to sync saves to Google Drive (Step-by-step)", padding=8)
        tips.pack(fill="both", expand=True, padx=2, pady=(0, 10))

        # Canvas + Scrollbar
        canvas = tk.Canvas(tips, highlightthickness=0)
        vscroll = ttk.Scrollbar(tips, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # The scrollable content frame (put labels inside this)
        tips_body = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=tips_body, anchor="nw")

        def _update_scrollregion(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _resize_inner(_=None):
            # Make inner frame match canvas width so text wraps correctly
            canvas.itemconfigure(canvas_window, width=canvas.winfo_width())

        tips_body.bind("<Configure>", _update_scrollregion)
        canvas.bind("<Configure>", _resize_inner)

        # Mouse wheel support (Windows)
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # Bind when mouse is over the instructions area
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ---- helper for steps (use tips_body now) ----
        def _step(txt):
            ttk.Label(tips_body, text=txt, wraplength=760, justify="left").pack(anchor="w", fill="x", pady=2)

        # ---- clickable download link row (inside tips_body) ----
        def _open_gdrive_download():
            webbrowser.open("https://www.google.com/drive/download/")

        row_link = ttk.Frame(tips_body)
        row_link.pack(anchor="w", fill="x", pady=(0, 4))

        ttk.Label(row_link, text="1- Download and install ").pack(side="left")
        link = tk.Label(
            row_link,
            text="Google Drive for desktop",
            fg="#1a73e8",
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: _open_gdrive_download())
        ttk.Label(row_link, text=" then sign in.").pack(side="left")

        # ---- your steps ----
        _step(
            "2- Create a NEW empty folder inside your Google Drive to store this game's saves (example: Google Drive\\PC Saves\\Elden Ring).")
        _step("3- In this tab, select:")
        _step("   • Save Game Folder: the ORIGINAL folder where the game currently saves.")
        _step("   • Google Drive Sync Folder: the NEW folder you created inside Google Drive.")
        _step("4- IMPORTANT: Run the app as Administrator (needed for the junction command: mklink /J).")
        _step("5- Click 'Sync Save to Cloud'. The app will do these actions:")
        _step("   • Rename your save folder to: <SaveFolder>_backup (only the first time).")
        _step("   • Create a junction at the original save path pointing to your Google Drive folder.")
        _step("   • Copy all existing save files from <SaveFolder>_backup into Google Drive.")
        _step(
            "6- After that, the game still saves to the SAME old path, but Windows redirects it into Google Drive automatically.")
        _step(
            "7- Test it: open the game, create/modify a save, then check the Google Drive folder and confirm files are updating.")
        _step(
            "8- On another PC: install Google Drive for desktop, let it sync the same game folder, then set that PC's Save Game Folder and Google Drive Sync Folder the same way and press Sync.")

        ttk.Label(
            tips_body,
            text="Tip: Always use a separate folder per game inside Google Drive. Do not pick the root 'Google Drive' folder.",
            wraplength=760,
            justify="left"
        ).pack(anchor="w", fill="x", pady=(8, 0))

    # -----------------------------
    # GOOGLE CLOUD SYNC LOGIC
    # -----------------------------

    def sync_backup_to_cloud(self):
        save_path = self.google_save_path.get().strip()
        drive_path = self.google_drive_path.get().strip()

        if not save_path or not os.path.isdir(save_path):
            messagebox.showerror("Invalid Save Path", "Please select a valid save directory.")
            return

        if not drive_path or not os.path.isdir(drive_path):
            messagebox.showerror("Invalid Google Drive Path", "Please select a valid Google Drive sync directory.")
            return

        def work():
            backup_path = save_path + "_backup"

            # rename original save folder (once)
            if not os.path.exists(backup_path):
                os.rename(save_path, backup_path)

            # Create junction to Google Drive folder
            cmd = f'mklink /J "{save_path}" "{drive_path}"'
            result = os.system(cmd)
            if result != 0:
                raise RuntimeError("Failed to create junction. Run the app as Administrator.")

            # Copy existing save data into Drive folder
            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(drive_path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

            return True

        def ok(_):
            messagebox.showinfo("Success", "Cloud sync link created successfully!")

        def err(e, tb):
            messagebox.showerror("Error", f"Failed to sync:\n{e}")

        self.run_async("Linking + syncing to cloud…", work, on_success=ok, on_error=err, show_loading=True)

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

        def work():
            found, hints = find_save_paths(game, self.log)
            return (found, hints)

        def ok(res):
            found, hints = res
            self.found_paths = found

            if not found:
                messagebox.showwarning(
                    "No Save Files Found",
                    "No save files were found for this game.\n"
                    "Make sure the game is installed & has been run at least once."
                )
                return

            self.paths_list.delete(0, "end")
            for p in found:
                self.paths_list.insert("end", p)
            self.backup_btn.config(state="normal")

        def err(e, tb):
            log_append(self.log, f"Error: {e}")

        self.run_async("Finding save paths…", work, on_success=ok, on_error=err, show_loading=True)


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

        def work():
            return make_backup(game, self.found_paths, backup_root, self.log)

        def ok(zip_path):
            messagebox.showinfo("Backup Complete", f"Backup created:\n{zip_path}")

        def err(e, tb):
            messagebox.showerror("Backup Failed", f"{e}")

        self.run_async("Creating backup…", work, on_success=ok, on_error=err, show_loading=True)

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
    
    def browse_save_path(self):
        d = filedialog.askdirectory()
        if d:
            self.google_save_path.set(d)

    def browse_drive_path(self):
        d = filedialog.askdirectory()
        if d:
            self.google_drive_path.set(d)

    
    def browse_zip(self):
        f = filedialog.askopenfilename(filetypes=[("ZIP Files", "*.zip")])
        if f:
            self.restore_zip.set(f)


    def restore_backup(self):
        zipf = self.restore_zip.get().strip()
        if not zipf or not os.path.isfile(zipf):
            messagebox.showerror("Error", "Please select a valid backup ZIP.")
            return

        # Phase 1: analyze metadata + conflicts in background
        def analyze():
            with zipfile.ZipFile(zipf, "r") as z:
                try:
                    meta = json.loads(z.read("__pcsm_paths.json").decode("utf-8"))
                except Exception:
                    raise RuntimeError("Backup missing metadata.")

                paths_meta = meta.get("paths", [])
                if not paths_meta:
                    raise RuntimeError("Metadata contains no save paths.")

                index_map = {p["index"]: p for p in paths_meta}

                conflict = False
                file_count = 0

                for zinfo in z.infolist():
                    if zinfo.filename == "__pcsm_paths.json" or zinfo.filename.endswith("/"):
                        continue
                    parts = zinfo.filename.split("/", 1)
                    if len(parts) != 2:
                        continue
                    idx_s, rel = parts
                    try:
                        idx = int(idx_s)
                    except Exception:
                        continue
                    rec = index_map.get(idx)
                    if not rec:
                        continue
                    base = rec["base"]
                    typ = rec["type"]
                    dest = os.path.join(base, rel) if typ == "dir" else base
                    file_count += 1
                    if os.path.exists(dest):
                        conflict = True
                return {"conflict": conflict, "file_count": file_count}

        def after_analyze(info):
            conflict = info["conflict"]

            if conflict:
                ok = messagebox.askokcancel(
                    "Overwrite files?",
                    "Some destination files already exist.\n\n"
                    "Press Overwrite to replace ALL existing files,\n"
                    "or Cancel to abort restore."
                )
                if not ok:
                    return

            # Phase 2: do actual restore in background
            def do_restore():
                with zipfile.ZipFile(zipf, "r") as z:
                    meta = json.loads(z.read("__pcsm_paths.json").decode("utf-8"))
                    paths_meta = meta.get("paths", [])
                    index_map = {p["index"]: p for p in paths_meta}

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
                        except Exception:
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
                    return count

            def after_restore(count):
                messagebox.showinfo("Restore Complete", f"Files restored: {count}")

            def err_restore(e, tb):
                messagebox.showerror("Error", f"Restore failed:\n{e}")

            self.run_async("Restoring files…", do_restore, on_success=after_restore, on_error=err_restore, show_loading=True)

        def err_analyze(e, tb):
            messagebox.showerror("Error", f"Restore failed:\n{e}")

        self.run_async("Preparing restore…", analyze, on_success=after_analyze, on_error=err_analyze, show_loading=True)

    # -----------------------------
    # Autocomplete
    # -----------------------------

    def on_game_typed(self, event):
        if self.suppress_suggestions:
            return
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return

        # Only suggest on Backup tab
        try:
            if self.notebook.index("current") != 0:
                return
        except Exception:
            return

        text_in = self.game_entry.get().strip()

        if self.suggest_after_id:
            try:
                self.after_cancel(self.suggest_after_id)
            except Exception:
                pass
            self.suggest_after_id = None

        if len(text_in) < 2:
            self.destroy_suggestion_box()
            return

        self.suggest_seq += 1
        seq = self.suggest_seq
        self.last_suggest_query = text_in

        self.suggest_after_id = self.after(300, lambda: self.run_suggestion_search(text_in, seq))

    def run_suggestion_search(self, text, seq):
        def worker(q, seq):
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
            self.after(0, lambda: self.show_suggestions(results, q, seq))

        threading.Thread(target=worker, args=(text, seq,), daemon=True).start()

    def show_suggestions(self, results, query, seq):
        # Ignore stale results or when user left the Backup tab
        try:
            if seq != self.suggest_seq:
                return
            if self.notebook.index("current") != 0:
                return
        except Exception:
            return

        # If the user already typed something different, ignore
        current = self.game_entry.get().strip()
        if not current or not current.lower().startswith(query.lower()):
            return

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
        # ✅ stop dropdown from reopening when we set text programmatically
        self.suppress_suggestions = True
        try:
            self.game_entry.delete(0, "end")
            self.game_entry.insert("end", val)
            self.destroy_suggestion_box()
            self.game_entry.focus_set()
        finally:
            # re-enable after the click event finishes
            self.after(50, lambda: setattr(self, "suppress_suggestions", False))



    def on_game_entry_focus_out(self, event=None):
        # Clicking the suggestion list temporarily moves focus away; delay then decide
        def _maybe_close():
            try:
                f = self.focus_get()
                if self.suggestion_box and f is self.suggestion_box:
                    return
            except Exception:
                pass
            self.destroy_suggestion_box()

        self.after(150, _maybe_close)

    # -----------------------------
    # Update check helpers
    # -----------------------------
    def _parse_ver_tuple(self, v: str):
        nums = re.findall(r"\d+", v)
        return tuple(int(n) for n in nums[:4]) or (0,)


    def manual_check_for_update(self):
        """Manual check from About tab."""

        def work():
            req = urllib.request.Request(
                GITHUB_API_LATEST,
                headers={"User-Agent": "PC-Savegame-Manager"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            tag = str(data.get("tag_name") or data.get("name") or "").strip()
            cur = APP_VERSION
            newer = bool(tag and self._parse_ver_tuple(tag) > self._parse_ver_tuple(cur))
            return (tag, cur, newer)

        def ok(res):
            tag, cur, newer = res
            if newer:
                if messagebox.askyesno(
                    "New Version Available",
                    f"A newer version {tag} is available.\n\nOpen the releases page now?"
                ):
                    webbrowser.open(GITHUB_RELEASES_PAGE)
            else:
                messagebox.showinfo("You're up to date", f"Current version {cur} is the latest.")

        def err(e, tb):
            messagebox.showerror("Update check failed", str(e))

        self.run_async("Checking for updates…", work, on_success=ok, on_error=err, show_loading=True)

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
