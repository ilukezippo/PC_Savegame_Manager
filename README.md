# PC Savegame Manager

A Windows tool that automatically **detects**, **backs up**, and **restores** PC game save data using information from **PCGamingWiki**.

🔹 Detect save file locations (Documents, AppData, Steam paths, custom paths)  
🔹 Backup all save files into a timestamped ZIP  
🔹 Restore saves to their original location  
🔹 Automatic + manual update checking via GitHub  
🔹 Clean, modern UI (like Windows App Updater)  
🔹 Support for multiple save folders per game  
🔹 Intelligent path detection and expansion  
🔹 Autocomplete game search with PCGamingWiki API  

---

## 🚀 Features

### 🔍 Smart Save Detection
- Uses PCGamingWiki API to detect:
  - Local save folders
  - Roaming saves
  - `%APPDATA%`
  - `%LOCALAPPDATA%`
  - `Saved Games`
  - OneDrive paths

### 💾 Backup Engine
- Creates timestamped ZIP archives
- Stores metadata (`__pcsm_paths.json`)
- Supports:
  - Multiple save directories
  - Single-file saves
  - Repeated backups per game

### ♻️ Restore Engine
- Reads metadata from backup ZIP  
- Restores automatically to original paths  
- Overwrites existing saves cleanly  
- Shows conflict warning once (Overwrite / Cancel)

### 🔄 Update System
- Auto-check for new versions at startup  
- Manual “Check for Update” in About tab  
- Integrates with GitHub releases automatically  

### 🎮 UI / UX
- Modern Windows-like interface  
- Includes header logo  
- Autocomplete game suggestion list  
- Keyboard + mouse control for suggestions  
- Double-click to open detected paths  
- Scrollable log + detailed messages  

---

## 📦 Installing

### Download the latest EXE:
👉 **[Releases](https://github.com/ilukezippo/PC_Savegame_Manager/releases)**

Or run from source:

```bash
python PC_Savegame_Manager.py
