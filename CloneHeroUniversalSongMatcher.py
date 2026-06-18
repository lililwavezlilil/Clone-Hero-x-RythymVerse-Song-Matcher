import os
import sys
import threading
import logging
import re
import sys
import json
import time
import tkinter as tk
from tkinter import filedialog

# Safely silence the Flask startup banner
import flask.cli
flask.cli.show_server_banner = lambda *args, **kwargs: None

from flask import Flask, request, jsonify
from flask_cors import CORS
from thefuzz import fuzz
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Enables ANSI escape sequences in Windows terminals
os.system('')

app = Flask(__name__)
CORS(app)

# Gag Flask request logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ==========================================
# CONFIGURATION & FIRST RUN SETUP
# ==========================================
CONFIG_FILE = "CH_Settings.txt"
SONGS_DIRECTORY = None
LOCAL_SONGS_CACHE = []

def setup_directory():
    global SONGS_DIRECTORY
    songs_directory = None

    # 1. Try to read the directory from the config file if it exists
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            lines = [line for line in f if line.strip() and not line.strip().startswith('#')]
            if lines:
                songs_directory = lines[0].strip()

    # 2. Check if the directory we found actually exists
    is_valid_dir = songs_directory and os.path.isdir(songs_directory)

    if is_valid_dir:
        print(f"\033[36mLoaded Songs directory from {CONFIG_FILE}:\033[0m")
        print(f"\033[90m{songs_directory}\033[0m\n")

    # 3. If missing or invalid, prompt the user with the modern GUI
    if not is_valid_dir:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\033[36mFirst time setup: Please select your Clone Hero 'songs' folder from the popup window...\033[0m")
        
        # Initialize tkinter and hide the main background window
        root = tk.Tk()
        root.withdraw()
        # Force the dialog to pop up in front of the console
        root.attributes('-topmost', True) 
        
        songs_directory = filedialog.askdirectory(title="Select your Clone Hero 'songs' folder")
        root.destroy()
        
        if not songs_directory:
            print("\n\033[31mFolder selection cancelled. Exiting.\033[0m")
            input("Press Enter to exit...")
            sys.exit()

        # Normalize path slashes for Windows
        songs_directory = os.path.normpath(songs_directory)

        # 4. Generate the config file for Notepad editing later
        config_template = f"""# Clone Hero Midi 2 Chart Configuration
# You can safely edit the path below using Notepad.
# Just make sure it points to your actual Clone Hero Songs directory.

{songs_directory}
"""
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(config_template)
        print(f"\033[32mSaved! You can change this path anytime by editing {CONFIG_FILE} in Notepad.\033[0m\n")

    SONGS_DIRECTORY = songs_directory

setup_directory()

# Standard Terminal Colors
GREEN = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m'
YELLOW = '\033[93m'
BRACKET_COLOR = '\033[90m' 
RESET = '\033[0m'

# --- DASHBOARD STATE VARIABLES ---
BOOT_MESSAGE = ""
ACTIVE_DISPLAYS = {}
LAST_RENDERED_TEXT = ""
display_lock = threading.RLock()

# --- DEBOUNCE STATE ---
_redraw_timer = None

def schedule_redraw():
    """Debounced redraw — collapses bursts of updates into a single draw 50ms later."""
    global _redraw_timer
    if _redraw_timer:
        _redraw_timer.cancel()
    _redraw_timer = threading.Timer(0.05, redraw_terminal)
    _redraw_timer.start()

def generate_waiting_message():
    rv = f"\033[38;2;255;255;255mRhythmVerse{RESET}"
    ce = f"\033[38;2;255;204;0mCHORUS \033[38;2;50;170;255mENCORE{RESET}"
    raw_csc = "CUSTOM SONGS CENTRAL"
    start_rgb = (255, 170, 0)
    end_rgb = (255, 50, 200)
    csc_styled = ""
    for i, char in enumerate(raw_csc):
        r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * (i / max(1, len(raw_csc) - 1)))
        g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * (i / max(1, len(raw_csc) - 1)))
        b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * (i / max(1, len(raw_csc) - 1)))
        csc_styled += f"\033[38;2;{r};{g};{b}m{char}"
    csc_styled += RESET
    return f"Waiting for {rv}, {ce}, {csc_styled}..."

WAITING_MSG = generate_waiting_message()

# --- 1. DEFINING WATCHER CLASS ---
class SongFolderWatcher(FileSystemEventHandler):
    def __init__(self): self.timer = None
    def on_any_event(self, event):
        if event.is_directory or os.path.basename(event.src_path).lower() == '.stfolder': return
        if self.timer: self.timer.cancel()
        self.timer = threading.Timer(2.0, self.trigger_update)
        self.timer.start()
    def trigger_update(self):
        global LOCAL_SONGS_CACHE
        LOCAL_SONGS_CACHE = build_song_cache(is_auto_refresh=True)

# --- 2. INSTANTIATING AFTER DEFINITION ---
event_handler = SongFolderWatcher()
observer = Observer()
observer.schedule(event_handler, path=SONGS_DIRECTORY, recursive=True)
observer.start()

def get_site_prefix(source):
    PREFIX_WIDTH = 25 
    if "enchor" in source:
        styled_text = f"\033[38;2;255;204;0mCHORUS \033[38;2;50;170;255mENCORE"
        visible_text = "[CHORUS ENCORE]"
    elif "rhythmverse" in source:
        styled_text = f"\033[38;2;255;255;255mRhythmVerse"
        visible_text = "[RhythmVerse]"
    elif "customsongscentral" in source or "docs.google" in source:
        raw_str = "Custom Songs Central"
        start_rgb, end_rgb = (255, 170, 0), (255, 50, 200)
        styled_text = ""
        for i, char in enumerate(raw_str):
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * (i / max(1, len(raw_str) - 1)))
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * (i / max(1, len(raw_str) - 1)))
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * (i / max(1, len(raw_str) - 1)))
            styled_text += f"\033[38;2;{r};{g};{b}m{char}"
        visible_text = "[Custom Songs Central]"
    else:
        styled_text = f"\033[38;2;200;200;200m{source[:20]}"
        visible_text = f"[{source[:20]}]"
    padding = " " * max(0, PREFIX_WIDTH - len(visible_text))
    return f"{BRACKET_COLOR}[{styled_text}{BRACKET_COLOR}]{RESET}{padding}"

def redraw_terminal():
    global LAST_RENDERED_TEXT 
    with display_lock:
        lines = []
            
        lines.append(f"{GREEN}===================================================={RESET}")
        lines.append(f"{GREEN}      Clone Hero Universal Song Matcher v1.1.1{RESET}")
        lines.append(f"{GREEN}===================================================={RESET}")
        lines.append("")
        lines.append(BOOT_MESSAGE)
        lines.append("-" * 50)
        lines.append("Server is running! Syncing with RhythmVerse x Chorus Encore x Custom Songs Central...\n")
        
        if not ACTIVE_DISPLAYS:
            lines.append(WAITING_MSG)
        else:
            for source, data in ACTIVE_DISPLAYS.items():
                items = data.get('items', [])
                if not items: continue
                prefix = get_site_prefix(source)
                for item in items:
                    artist, title, status = item.get('artist', 'Unknown'), item.get('title', 'Unknown'), item.get('status', 'UNKNOWN')
                    if status == 'HAVE': lines.append(f"{prefix}{artist} - {title} {GREEN}[✅ HAVE]{RESET}")
                    elif status == 'DONT_HAVE': lines.append(f"{prefix}{artist} - {title} {RED}[❌ Don't have]{RESET}")
                    elif status == 'DOWNLOADING': lines.append(f"{prefix}{artist} - {title} {YELLOW}[⏳ DOWNLOADING/EXTRACTING...]{RESET}")
        
        formatted_lines = [f"{line}\033[K" for item in lines for line in str(item).split('\n')]
        output_text = '\n'.join(formatted_lines)
        
        if output_text != LAST_RENDERED_TEXT:
            # ANSI Magic:
            # \033[2J -> Clears the entire visible screen
            # \033[3J -> Clears the entire scrollback buffer (This fixes your issue)
            # \033[H  -> Moves the cursor back to the top left corner (0,0)
            sys.stdout.write('\033[2J\033[3J\033[H' + output_text + '\n')
            sys.stdout.flush()
            LAST_RENDERED_TEXT = output_text

def monitor_active_displays():
    while True:
        time.sleep(0.5)
        needs_redraw = False
        current_time = time.time()
        with display_lock:
            sources_to_remove = []
            for source, data in ACTIVE_DISPLAYS.items():
                if current_time - data.get('last_seen', 0) > 5.0: 
                    sources_to_remove.append(source)
            for source in sources_to_remove:
                ACTIVE_DISPLAYS.pop(source, None)
                needs_redraw = True
        
        if needs_redraw: 
            redraw_terminal()

def clean_text(text):
    text = text.lower().strip()
    if text.startswith("the "): text = text[4:]
    text = re.sub(r'\[.*?\]', '', text)
    phrases_to_remove = ["(original version)", "(original mix)", "(original)", "(rechart)", "(fixed)", "[fixed]"]
    for phrase in phrases_to_remove: text = text.replace(phrase, "")
    text = re.sub(r'\(\s*(?:feat|ft)\.?\s+[^)]+\)', '', text)
    text = re.sub(r'\s+(?:feat|ft)\.?\s+.*$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_ini_manually(file_path):
    artist, title = "", ""
    try:
        with open(file_path, 'rb') as f: raw_data = f.read()
    except Exception: return artist, title 
    decoded_text = ""
    if raw_data.startswith(b'\xff\xfe') or raw_data.startswith(b'\xfe\xff'):
        decoded_text = raw_data.decode('utf-16', errors='ignore')
    else:
        try: decoded_text = raw_data.decode('utf-8-sig', errors='strict')
        except UnicodeDecodeError: decoded_text = raw_data.decode('latin-1', errors='ignore')
    for line in decoded_text.splitlines():
        line = line.replace('\x00', '').strip()
        if line.lower().startswith("artist") and "=" in line: artist = clean_text(line.split("=", 1)[1])
        elif (line.lower().startswith("name") or line.lower().startswith("title")) and "=" in line: title = clean_text(line.split("=", 1)[1])
    return artist, title

def build_song_cache(is_auto_refresh=False):
    global BOOT_MESSAGE
    cache = []
    for root, dirs, files in os.walk(SONGS_DIRECTORY):
        dirs[:] = [d for d in dirs if d.lower() != '.stfolder']
        if not dirs:
            song_ini = next((f for f in files if f.lower() == 'song.ini'), None)
            if song_ini:
                artist, title = parse_ini_manually(os.path.join(root, song_ini))
                if title: cache.append({'artist': artist if artist else "unknown", 'title': title})
    BOOT_MESSAGE = f"Target Directory: {CYAN}{SONGS_DIRECTORY}{RESET}\nScan complete! Loaded {len(cache)} songs into memory."
    redraw_terminal()
    return cache

LOCAL_SONGS_CACHE = build_song_cache()

@app.route('/change_folder', methods=['GET'])
def change_folder():
    global SONGS_DIRECTORY, LOCAL_SONGS_CACHE, ACTIVE_DISPLAYS, observer, event_handler
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(title="Select your NEW Clone Hero 'songs' folder")
    root.destroy()
    if folder and os.path.exists(folder):
        SONGS_DIRECTORY = os.path.normpath(folder)
        # Update file
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Clone Hero Midi 2 Chart Configuration\n\n{SONGS_DIRECTORY}\n")
        
        with display_lock: ACTIVE_DISPLAYS.clear()
        LOCAL_SONGS_CACHE = build_song_cache(is_auto_refresh=False)
        observer.unschedule_all()
        observer.schedule(event_handler, path=SONGS_DIRECTORY, recursive=True)
        redraw_terminal()
        return jsonify({"status": "success", "folder": folder})
    return jsonify({"status": "cancelled"})

@app.route('/sync', methods=['POST'])
def sync_display():
    data = request.json
    if not data: return jsonify({"status": "ok"})
    source = data.get('source', 'Unknown')
    items = data.get('items', [])
    with display_lock:
        existing_items = ACTIVE_DISPLAYS.get(source, {}).get('items', [])
        ACTIVE_DISPLAYS[source] = {'items': items, 'last_seen': time.time()}
        # Only schedule a redraw if the displayed content actually changed
        if items != existing_items:
            schedule_redraw()
    return jsonify({"status": "ok"})

@app.route('/unload', methods=['GET', 'POST', 'OPTIONS'])
def unload_display():
    source = request.args.get('source')
    if not source:
        try:
            data = request.get_json(silent=True) or {}
            source = data.get('source', 'Unknown')
        except: source = 'Unknown'
        
    if not source or source == 'Unknown': return jsonify({"status": "ok"})
    
    with display_lock:
        if source in ACTIVE_DISPLAYS:
            ACTIVE_DISPLAYS.pop(source, None)
            redraw_terminal() 
    return jsonify({"status": "ok"})

@app.route('/check_batch', methods=['POST'])
def check_batch():
    data = request.json
    if not data: return jsonify([])
    items = data.get('items', []) if isinstance(data, dict) else data
    results = []
    strict_words = ["cover", "remix", "live", "acoustic", "vip", "instrumental"]
    for item in items:
        orig_artist, orig_title = item.get('artist', '').strip(), item.get('title', '').strip()
        t_artist, t_title = clean_text(orig_artist), clean_text(orig_title)
        t_combined = f"{t_artist} {t_title}"
        if not t_artist or not t_title:
            results.append({"owned": False})
            continue
        found = False
        for local_song in LOCAL_SONGS_CACHE:
            l_combined = f"{local_song['artist']} {local_song['title']}"
            is_valid = True
            for word in strict_words:
                if (word in l_combined) != (word in t_combined):
                    is_valid = False
                    break
            if not is_valid: continue 
            a_match = fuzz.token_set_ratio(t_artist, local_song['artist']) > 80
            t_match = fuzz.token_set_ratio(t_title, local_song['title']) > 85
            c_match = fuzz.token_set_ratio(t_combined, l_combined) > 88
            if (a_match and t_match) or c_match:
                results.append({"owned": True})
                found = True
                break
        if not found: results.append({"owned": False})
    return jsonify(results)

@app.route('/check', methods=['GET'])
def check_song():
    orig_artist, orig_title = request.args.get('artist', '').strip(), request.args.get('title', '').strip()
    t_artist, t_title = clean_text(orig_artist), clean_text(orig_title)
    t_combined = f"{t_artist} {t_title}"
    strict_words = ["cover", "remix", "live", "acoustic", "vip", "instrumental"]
    if not t_artist or not t_title: return jsonify({"error": "Missing artist or title"}), 400
    for local_song in LOCAL_SONGS_CACHE:
        l_combined = f"{local_song['artist']} {local_song['title']}"
        is_valid = True
        for word in strict_words:
            if (word in l_combined) != (word in t_combined):
                is_valid = False
                break
        if not is_valid: continue
        if (fuzz.token_set_ratio(t_artist, local_song['artist']) > 80 and fuzz.token_set_ratio(t_title, local_song['title']) > 85) or fuzz.token_set_ratio(t_combined, l_combined) > 88:
            return jsonify({"owned": True})
    return jsonify({"owned": False})

if __name__ == '__main__':
    monitor_thread = threading.Thread(target=monitor_active_displays, daemon=True)
    monitor_thread.start()
    app.run(port=5000, debug=False, use_reloader=False)