import os, json, time, threading, queue, uuid, requests, ssl, random
import websocket
from flask import Flask
import importlib, sys, traceback

# ======================
# CONFIG
# ======================
BOT = {"ws": None, "token": "", "status": "DISCONNECTED", "rooms": {}, "should_run": False}
ACTIVE_GAMES = {}           # {room_name: {game_id: {...}}}
PLUGINS = {}                # {plugin_name: module}
PLUGIN_FOLDER = "plugins"
DB_LOCK = threading.Lock()
GAME_LOCK = threading.Lock()

# ======================
# DATABASE (Thread Safe)
# ======================
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_SQLITE = not DATABASE_URL

if USE_SQLITE:
    import sqlite3
    DB_FILE = "bot.db"
    def get_db():
        return sqlite3.connect(DB_FILE)
else:
    import psycopg2
    def get_db():
        return psycopg2.connect(DATABASE_URL, sslmode="require")

# Initialize database tables for users, games, plugin data
def init_db():
    with DB_LOCK:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                username VARCHAR PRIMARY KEY, score INTEGER DEFAULT 1000, wins INTEGER DEFAULT 0
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS game_scores (
                username VARCHAR, game_name VARCHAR, score INTEGER DEFAULT 0, PRIMARY KEY(username, game_name)
            )""")
            conn.commit()
            conn.close()
        except Exception as e:
            print("DB Init Error:", e)
init_db()

# ======================
# PLUGIN SYSTEM
# ======================
def load_plugin(name):
    try:
        if name in PLUGINS: return f"{name} already loaded"
        module = importlib.import_module(f"{PLUGIN_FOLDER}.{name}")
        if hasattr(module, "setup"):
            module.setup(BOT, ACTIVE_GAMES)
        PLUGINS[name] = module
        return f"Loaded plugin: {name}"
    except Exception as e:
        traceback.print_exc()
        return f"Error loading plugin {name}: {e}"

def unload_plugin(name):
    try:
        if name not in PLUGINS: return f"{name} not loaded"
        module = PLUGINS[name]
        if hasattr(module, "teardown"):
            module.teardown()
        del sys.modules[f"{PLUGIN_FOLDER}.{name}"]
        del PLUGINS[name]
        return f"Unloaded plugin: {name}"
    except Exception as e:
        traceback.print_exc()
        return f"Error unloading plugin {name}: {e}"

def reload_plugin(name):
    unload_plugin(name)
    return load_plugin(name)

# Auto-load all plugins from folder on startup
def load_all_plugins():
    for file in os.listdir(PLUGIN_FOLDER):
        if file.endswith(".py") and file != "__init__.py":
            load_plugin(file[:-3])
load_all_plugins()

# ======================
# WEBSOCKET BOT CORE
# ======================
def perform_login(username, password):
    url = "https://api.howdies.app/api/login"
    try:
        r = requests.post(url, json={"username": username, "password": password}, timeout=10)
        data = r.json()
        token = data.get("token") or data.get("data", {}).get("token")
        return token
    except:
        return None

def bot_ws_thread(username, password, room):
    while BOT["should_run"]:
        try:
            if not BOT["token"]:
                BOT["status"] = "FETCHING TOKEN"
                BOT["token"] = perform_login(username, password)
                if not BOT["token"]:
                    BOT["status"] = "AUTH FAILED"
                    time.sleep(10)
                    continue

            BOT["status"] = "CONNECTING WS"
            ws_url = f"wss://app.howdies.app/howdies?token={BOT['token']}"
            ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message,
                                        on_error=on_error, on_close=on_close)
            BOT["ws"] = ws
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        except Exception as e:
            print("WS CRASH:", e)
            time.sleep(5)

def on_open(ws):
    print("WS OPENED")
    BOT["status"] = "ONLINE"

def on_message(ws, msg):
    try:
        data = json.loads(msg)
        # pass message to plugins
        for plugin in PLUGINS.values():
            if hasattr(plugin, "on_message"):
                try: plugin.on_message(data)
                except: traceback.print_exc()
    except: traceback.print_exc()

def on_error(ws, err): print("WS ERROR:", err)
def on_close(ws, c, r): BOT["status"] = "DISCONNECTED"

def send_msg(room, text, type="text"):
    if BOT["ws"] and room:
        pkt = {"handler":"chatroommessage","id":str(time.time()),"roomid":room,"type":type,"text":text,"length":"0"}
        try: BOT["ws"].send(json.dumps(pkt))
        except: pass

# ======================
# GAME ENGINE
# ======================
def start_game(room, game_name, players=[]):
    with GAME_LOCK:
        game_id = str(uuid.uuid4())
        if room not in ACTIVE_GAMES: ACTIVE_GAMES[room] = {}
        ACTIVE_GAMES[room][game_id] = {
            "name": game_name, "players": players, "state": {}, "last_active": time.time()
        }
        return game_id

def end_game(room, game_id):
    with GAME_LOCK:
        game = ACTIVE_GAMES.get(room, {}).pop(game_id, None)
        if game:
            send_msg(room, f"🛑 Game {game['name']} ended due to inactivity.")

def idle_checker():
    while True:
        time.sleep(5)
        now = time.time()
        with GAME_LOCK:
            for room, games in list(ACTIVE_GAMES.items()):
                for gid, game in list(games.items()):
                    if now - game["last_active"] > 90:
                        end_game(room, gid)

threading.Thread(target=idle_checker, daemon=True).start()

# ======================
# FLASK DASHBOARD (Simplest Endpoint for Testing)
# ======================
flask_app = Flask(__name__)

@flask_app.route("/api/load_plugin", methods=["POST"])
def api_load_plugin():
    data = request.json
    name = data.get("name")
    result = load_plugin(name)
    return {"result": result}

@flask_app.route("/api/unload_plugin", methods=["POST"])
def api_unload_plugin():
    data = request.json
    name = data.get("name")
    result = unload_plugin(name)
    return {"result": result}

if __name__ == "__main__":
    BOT["should_run"] = True
    threading.Thread(target=bot_ws_thread, args=("master_user","master_pass","MainRoom"), daemon=True).start()
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
