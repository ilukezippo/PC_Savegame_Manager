# PC Savegame Manager

A Windows tool that automatically **detects**, **backs up**, and **restores** PC game save data using information from **PCGamingWiki**.

✅ Works great for:
- PC games (Steam / Epic / etc.)
- Cracked PC games
- Emulator games
- Syncing save files across **two or more PCs** (via Google Drive)

---

## 🚀 Features

### 🔍 Smart Save Detection
- Uses the PCGamingWiki API to detect save locations such as:
  - `Documents`
  - `Saved Games`
  - `%APPDATA%`
  - `%LOCALAPPDATA%`
  - `AppData\Roaming`
  - `AppData\Local`
  - OneDrive / cloud-mapped paths (when present)

### 💾 Backup Engine
- Creates timestamped ZIP archives per game
- Stores restore metadata inside every ZIP: `__pcsm_paths.json`
- Supports:
  - Multiple save folders per game
  - Single-file saves
  - Repeated backups per game without overwriting

### ♻️ Restore Engine
- Reads metadata from the backup ZIP
- Restores files back to the original save locations
- Warns if files already exist (overwrite confirmation)

### ☁️ Google Drive Sync (Multi-PC Saves)
- Link a game’s original save folder to a folder inside Google Drive
- Keeps saves synced across multiple PCs automatically
- Uses a Windows junction method (Admin required)

### 🔄 Update System
- Auto-checks for new versions at startup
- Manual “Check for Update” button in the About tab

### 🎮 UI / UX
- Clean, modern Windows-like interface
- Autocomplete game suggestions (PCGamingWiki search)
- Log output + detected paths list

---

## 📦 Installing

### Download the latest EXE
👉 **Releases:** https://github.com/ilukezippo/PC_Savegame_Manager/releases

---

## 📝 Notes
- Save detection depends on PCGamingWiki entries (some games may have missing/limited info).
- For Google Drive sync, the app must run as **Administrator** to create the junction.

---

## ❤️ Support
If you like the app and want to support development:
👉 https://buymeacoffee.com/ilukezippo
