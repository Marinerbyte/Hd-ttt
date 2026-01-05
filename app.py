import os
import json
import time
import threading
import io
import random
import websocket
import ssl
import sqlite3
import requests
import psycopg2
from flask import Flask, render_template_string, request, jsonify, send_file, Response
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# =============================================================================
# 1. THREAD LOCKS & CONFIG
# =============================================================================
DB_LOCK = threading.Lock()
GAME_LOCK = threading.Lock()
ASSETS = {}

# =============================================================================
# 2. HIGH QUALITY ASSETS (CYBERPUNK NEON)
# =============================================================================
def init_assets():
    # Board Background
    board = Image.new('RGB', (900, 900), (10, 10, 16)) 
    draw = ImageDraw.Draw(board)
    cyan_glow = (0, 255, 255)
    purple_glow = (180, 0, 255)
    dark_grid = (0, 80, 80)

    # Glowing Grid
    for x in [300, 600]:
        draw.line([(x, 20), (x, 880)], fill=dark_grid, width=25) 
        draw.line([(x, 20), (x, 880)], fill=cyan_glow, width=8)

    for y in [300, 600]:
        draw.line([(20, y), (880, y)], fill=dark_grid, width=25)
        draw.line([(20, y), (880, y)], fill=cyan_glow, width=8)

    # Border
    draw.rectangle([5, 5, 895, 895], outline=purple_glow, width=12)
    ASSETS['board'] = board

    # X Symbol (Neon Red)
    x_img = Image.new('RGBA', (300, 300), (0,0,0,0))
    dx = ImageDraw.Draw(x_img)
    dx.line([(60,60), (240,240)], fill=(200, 0, 50, 150), width=35) # Glow
    dx.line([(240,60), (60,240)], fill=(200, 0, 50, 150), width=35)
    dx.line([(60,60), (240,240)], fill=(255, 0, 80), width=20) # Core
    dx.line([(240,60), (60,240)], fill=(255, 0, 80), width=20)
    ASSETS['x'] = x_img

    # O Symbol (Neon Green)
    o_img = Image.new('RGBA', (300, 300), (0,0,0,0))
    do = ImageDraw.Draw(o_img)
    do.ellipse([60,60,240,240], outline=(0, 200, 50, 150), width=35) # Glow
    do.ellipse([60,60,240,240], outline=(0, 255, 100), width=20) # Core
    ASSETS['o'] = o_img

init_assets()

# =============================================================================
# 3. DATABASE MANAGER
# =============================================================================
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_SQLITE = False if DATABASE_URL else True
DB_FILE_NAME = "howdies_v7.db" 
TABLE_NAME = "howdies_gamers_v7" 

def get_db():
    if USE_SQLITE: return sqlite3.connect(DB_FILE_NAME)
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    with DB_LOCK: 
        try:
            conn = get_db()
            c = conn.cursor()
            query = f'''CREATE TABLE IF NOT EXISTS {TABLE_NAME} 
                       (username VARCHAR(255) PRIMARY KEY, wins INTEGER, score INTEGER, avatar_url TEXT)'''
            c.execute(query)
            conn.commit()
            conn.close()
        except Exception as e: print("DB Error:", e)

def update_score(username, points, avatar_url=""):
    with DB_LOCK: 
        try:
            conn = get_db()
            c = conn.cursor()
            ph = "?" if USE_SQLITE else "%s"
            
            c.execute(f"SELECT score, wins FROM {TABLE_NAME} WHERE username={ph}", (username,))
            data = c.fetchone()
            
            if data:
                new_score = data[0] + points
                new_wins = data[1] + (1 if points > 0 else 0)
                if avatar_url:
                    c.execute(f"UPDATE {TABLE_NAME} SET score={ph}, wins={ph}, avatar_url={ph} WHERE username={ph}", 
                              (new_score, new_wins, avatar_url, username))
                else:
                    c.execute(f"UPDATE {TABLE_NAME} SET score={ph}, wins={ph} WHERE username={ph}", 
                              (new_score, new_wins, username))
            else:
                initial_score = 1000 + points
                initial_wins = 1 if points > 0 else 0
                c.execute(f"INSERT INTO {TABLE_NAME} (username, score, wins, avatar_url) VALUES ({ph}, {ph}, {ph}, {ph})", 
                          (username, initial_score, initial_wins, avatar_url))
            conn.commit()
            conn.close()
        except Exception as e: print(f"Score Update Error: {e}")

def get_score(username):
    try:
        conn = get_db()
        c = conn.cursor()
        ph = "?" if USE_SQLITE else "%s"
        c.execute(f"SELECT score FROM {TABLE_NAME} WHERE username={ph}", (username,))
        data = c.fetchone()
        conn.close()
        return data[0] if data else 1000
    except: return 1000

def get_leaderboard_data():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(f"SELECT username, score, wins, avatar_url FROM {TABLE_NAME} ORDER BY score DESC LIMIT 50")
        data = c.fetchall()
        conn.close()
        return data
    except: return []

init_db()

# =============================================================================
# 4. BOT CORE (Fixes & Logging)
# =============================================================================
BOT = {
    "ws": None, "status": "DISCONNECTED",
    "user": "", "pass": "", "room": "", "token": "",
    "room_id": None, # Stores numeric ID (e.g. 45)
    "domain": "", "should_run": False, "avatars": {}
}

CHAT_HISTORY = []
DEBUG_LOGS = []

def save_chat(user, msg, avatar="", type="text"):
    timestamp = time.strftime("%H:%M")
    CHAT_HISTORY.append({"user": user, "msg": msg, "avatar": avatar, "time": timestamp, "type": type})
    if len(CHAT_HISTORY) > 100: CHAT_HISTORY.pop(0)

def save_debug(direction, payload):
    timestamp = time.strftime("%H:%M:%S")
    try:
        if isinstance(payload, str): payload = json.loads(payload)
    except: pass
    DEBUG_LOGS.append({"time": timestamp, "dir": direction, "data": payload})
    if len(DEBUG_LOGS) > 500: DEBUG_LOGS.pop(0) # Keep 500 lines for download

def get_auth_token(username, password):
    url = "https://api.howdies.app/api/login"
    try:
        payload = {"username": username, "password": password}
        response = requests.post(url, json=payload, timeout=15)
        save_debug("API_LOGIN", response.text)
        if response.status_code == 200:
            data = response.json()
            if "token" in data: return data["token"]
            if "data" in data and "token" in data["data"]: return data["data"]["token"]
        return None
    except Exception as e:
        save_debug("API_ERROR", str(e))
        return None

def bot_thread():
    while BOT["should_run"]:
        try:
            if not BOT["token"]:
                BOT["status"] = "FETCHING TOKEN..."
                token = get_auth_token(BOT["user"], BOT["pass"])
                if not token:
                    BOT["status"] = "AUTH FAILED"
                    time.sleep(10)
                    continue
                BOT["token"] = token

            BOT["status"] = "CONNECTING WS..."
            ws_url = f"wss://app.howdies.app/howdies?token={BOT['token']}"
            
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            BOT["ws"] = ws
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
        except Exception as e:
            save_debug("CRASH", str(e))
        
        if BOT["should_run"]:
            BOT["status"] = "RETRYING (5s)..."
            time.sleep(5)

def on_open(ws):
    BOT["status"] = "AUTHENTICATING"
    login_pkt = {"handler": "login", "username": BOT["user"], "password": BOT["pass"]}
    ws.send(json.dumps(login_pkt))
    save_debug("OUT", login_pkt)
    
    time.sleep(0.5)

    join_pkt = {"handler": "joinchatroom", "id": str(time.time()), "name": BOT["room"], "roomPassword": ""}
    ws.send(json.dumps(join_pkt))
    save_debug("OUT", join_pkt)
    
    BOT["status"] = "ONLINE"
    threading.Thread(target=pinger, daemon=True).start()
    threading.Thread(target=idle_game_checker, daemon=True).start()

def pinger():
    while BOT["ws"] and BOT["ws"].sock and BOT["ws"].sock.connected:
        time.sleep(20)
        try: BOT["ws"].send(json.dumps({"handler": "ping"}))
        except: break

def on_message(ws, message):
    try:
        data = json.loads(message)
        
        # ID Capture Fix
        if data.get("handler") == "joinchatroom" and data.get("roomid"):
            BOT["room_id"] = data["roomid"]
            save_debug("SYSTEM", f"Captured Room ID: {BOT['room_id']}")

        sender = data.get("from") or data.get("username")
        if sender and data.get("avatar_url"): 
            BOT["avatars"][sender] = data["avatar_url"]

        if data.get("handler") not in ["receipt_ack", "ping", "pong"]: 
            save_debug("IN", data)

        if data.get("handler") in ["chatroommessage", "message"]:
            msg_body = data.get("text") or data.get("body")
            if msg_body and sender:
                av = BOT["avatars"].get(sender, "https://cdn-icons-png.flaticon.com/512/149/149071.png")
                save_chat(sender, msg_body, av, "text")
                if sender != BOT["user"]:
                    game_engine(sender, msg_body)
            
    except Exception as e: save_debug("MSG ERROR", str(e))

def on_error(ws, error): save_debug("WS ERROR", str(error))
def on_close(ws, c, m): BOT["status"] = "DISCONNECTED"

def send_msg(text, type="text", url=""):
    if BOT["ws"]:
        target_room = BOT["room_id"] if BOT["room_id"] else BOT["room"]

        # Prevent Crash: Send Image as Text
        final_text = text
        if type == "image" or url:
            type = "text"
            final_text = f"🖼 {url}"
            url = "" 
        
        pkt = {
            "handler": "chatroommessage",
            "id": str(time.time()),
            "type": type,
            "roomid": target_room,
            "text": final_text,
            "url": "",
            "length": "0"
        }
        try:
            BOT["ws"].send(json.dumps(pkt))
            bot_av = "https://cdn-icons-png.flaticon.com/512/4712/4712035.png"
            display = "[IMAGE]" if "🖼" in final_text else final_text
            save_chat("TitanBot", display, bot_av, "bot")
            save_debug("OUT", pkt)
        except: pass

# =============================================================================
# 5. GAME LOGIC
# =============================================================================
ACTIVE_GAMES = {}

def idle_game_checker():
    while BOT["should_run"]:
        time.sleep(5)
        now = time.time()
        to_remove = []
        with GAME_LOCK:
            for host, game in ACTIVE_GAMES.items():
                if now - game['last_active'] > 60:
                    to_remove.append(host)
        
        for host in to_remove:
            game = None
            with GAME_LOCK:
                if host in ACTIVE_GAMES: game = ACTIVE_GAMES.pop(host)
            if game:
                bet = game.get("bet", 0)
                if bet > 0:
                    update_score(game['p1'], bet)
                    if game['p2'] and "Bot" not in game['p2']: update_score(game['p2'], bet)
                send_msg(f"🛑 **TIMEOUT!** Game hosted by {host} ended.")

def game_engine(user, msg):
    msg = msg.strip().lower()
    
    if msg == "!help":
        send_msg("🎮 **COMMANDS:**\n• `!start` (vs Bot)\n• `!start pvp`\n• `!start bet 500`\n• `!join <host>`\n• `!score`\n• `!reset`")
        return

    if msg == "!score":
        bal = get_score(user)
        domain = BOT.get('domain', '')
        link = f" | 🏆 Rank: {domain}leaderboard" if domain else ""
        send_msg(f"💳 {user}: **{bal}** pts{link}")
        return

    if msg == "!reset":
        with GAME_LOCK:
            if user in ACTIVE_GAMES:
                g = ACTIVE_GAMES[user]
                if g.get("bet", 0) > 0: update_score(user, g["bet"])
                del ACTIVE_GAMES[user]
                send_msg(f"♻ Game reset for {user}.")
            else:
                send_msg(f"⚠ {user}, no active game found.")
        return

    if msg.startswith("!start"):
        with GAME_LOCK:
            if find_user_game_unsafe(user): return send_msg(f"⚠ {user}, type `!reset` first.")
        
        mode = "pvp" if "pvp" in msg else "bot"
        bet = 0
        if "bet" in msg:
            try: bet = int(msg.split("bet")[1].split()[0])
            except: pass
        
        if bet > 0:
            if get_score(user) < bet: return send_msg("⚠ Low Balance!")
            update_score(user, -bet)
            
        with GAME_LOCK:
            ACTIVE_GAMES[user] = {
                "host": user, "mode": mode, "board": [" "]*9, "turn": "X",
                "p1": user, "p2": "🤖 TitanBot" if mode=="bot" else None,
                "last_active": time.time(), "bet": bet
            }
        
        send_board(user)
        bet_txt = f" (Bet: {bet})" if bet else ""
        if mode=="pvp": send_msg(f"🎮 **PvP LOBBY{bet_txt}**\nHost: {user}\nWaiting: `!join {user}`")
        else: send_msg(f"🤖 **BOT MATCH{bet_txt}**\n{user} (X) vs TitanBot (O)\nType `1-9` to move.")
        return

    if msg.startswith("!join"):
        with GAME_LOCK:
            if find_user_game_unsafe(user): return send_msg("⚠ You are playing.")
        
        parts = msg.split()
        if len(parts) < 2: return send_msg("Usage: `!join <host>`")
        host_target = parts[1]
        
        game = None
        target_host_key = None
        with GAME_LOCK:
            for h in ACTIVE_GAMES:
                if h.lower() == host_target.lower(): 
                    game = ACTIVE_GAMES[h]
                    target_host_key = h
                    break
        
        if not game: return send_msg("⚠ Game not found.")
        if game["mode"] == "bot" or game["p2"]: return send_msg("⚠ Lobby Full/Bot.")
        
        bet = game.get("bet", 0)
        if bet > 0:
            if get_score(user) < bet: return send_msg("⚠ No funds.")
            update_score(user, -bet)

        with GAME_LOCK:
            ACTIVE_GAMES[target_host_key]["p2"] = user
            ACTIVE_GAMES[target_host_key]["last_active"] = time.time()
            
        pot = f"\n💰 POT: {bet*2}" if bet else ""
        send_msg(f"⚔ **MATCH STARTED!**\n{user} (O) joined {game['p1']}.{pot}")
        return

    if msg.isdigit():
        move = int(msg)
        game = None
        with GAME_LOCK: game = find_user_game_unsafe(user)
        
        if not game or move < 1 or move > 9: return
        if game["mode"] == "pvp" and game["p2"] is None:
            send_msg(f"⚠ {user}, waiting for Player 2!")
            return

        game["last_active"] = time.time()
        curr = game["p1"] if game["turn"] == "X" else game["p2"]
        if not curr: return

        if game["mode"] == "bot":
            if user != game["p1"] or game["turn"] == "O": return
        elif user != curr: return
        
        idx = move - 1
        if game["board"][idx] != " ": return send_msg("⚠ Taken!")
        game["board"][idx] = game["turn"]
        
        if process_turn(game, user): return
        
        if game["mode"] == "bot":
            game["turn"] = "O"
            threading.Timer(1.0, run_bot, args=[game['host']]).start()
        else:
            game["turn"] = "O" if game["turn"] == "X" else "X"
            send_board(game['host'])

def find_user_game_unsafe(u):
    for h, d in ACTIVE_GAMES.items():
        if d['p1'] == u or d['p2'] == u: return d
    return None

def run_bot(host):
    with GAME_LOCK:
        if host not in ACTIVE_GAMES: return
        game = ACTIVE_GAMES[host]
        b = game["board"]
        avail = [i for i,x in enumerate(b) if x == " "]
        if not avail: return
        
        move = None
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for s in ["O", "X"]:
            for x,y,z in wins:
                if b[x]==s and b[y]==s and b[z]==" ": move=z; break
                if b[x]==s and b[z]==s and b[y]==" ": move=y; break
                if b[y]==s and b[z]==s and b[x]==" ": move=x; break
            if move: break
        if not move: move = random.choice(avail)
        game["board"][move] = "O"
    
    if process_turn(game, "TitanBot"): return
    
    with GAME_LOCK:
        if host in ACTIVE_GAMES:
            ACTIVE_GAMES[host]["turn"] = "X"
            send_board(host)

def process_turn(game, mover):
    b = game["board"]
    win = None
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for x,y,z in wins:
        if b[x]==b[y]==b[z] and b[x]!=" ": win=f"{x},{y},{z}"; break
        
    host = game['host']
    bet = game.get("bet", 0)
    
    if win:
        send_board(host, win)
        prize = ""
        if "Bot" not in mover:
            amt = bet * 2 if bet > 0 else 50
            av = BOT["avatars"].get(mover, "")
            update_score(mover, amt, av)
            prize = f" (+{amt} pts)"
        send_msg(f"🏆 **{mover} WINS!**{prize}")
        with GAME_LOCK:
            if host in ACTIVE_GAMES: del ACTIVE_GAMES[host]
        return True
        
    elif " " not in b:
        send_board(host)
        if bet > 0:
            update_score(game['p1'], bet)
            if game['p2'] and "Bot" not in game['p2']: update_score(game['p2'], bet)
        send_msg(f"🤝 **DRAW!** Refunded.")
        with GAME_LOCK:
            if host in ACTIVE_GAMES: del ACTIVE_GAMES[host]
        return True
    return False

def send_board(host, line=""):
    game = ACTIVE_GAMES.get(host)
    if not game: return
    b_str = "".join(game["board"]).replace(" ", "_")
    base = BOT.get('domain', '')
    if not base: return
    url = f"{base}render?b={b_str}&w={line}&h={host}&t={int(time.time())}"
    send_msg("", "image", url)

# =============================================================================
# 6. FLASK ROUTES
# =============================================================================
@app.route('/')
def index(): return render_template_string(UI_TEMPLATE)

@app.route('/leaderboard')
def leaderboard():
    users = get_leaderboard_data()
    return render_template_string(LEADERBOARD_TEMPLATE, users=users)

@app.route('/connect', methods=['POST'])
def connect():
    if BOT["should_run"]: return jsonify({"status": "Already Running"})
    d = request.json
    BOT.update({"user": d['u'], "pass": d['p'], "room": d['r'], "should_run": True, "domain": request.url_root})
    threading.Thread(target=bot_thread, daemon=True).start()
    return jsonify({"status": "Starting..."})

@app.route('/disconnect', methods=['POST'])
def disconnect():
    BOT["should_run"] = False
    if BOT["ws"]: BOT["ws"].close()
    return jsonify({"status": "Stopped"})

@app.route('/clear_data', methods=['POST'])
def clear_data():
    CHAT_HISTORY.clear()
    DEBUG_LOGS.clear()
    return jsonify({"status": "Cleared"})

@app.route('/get_data')
def get_data():
    return jsonify({"status": BOT["status"], "chat": CHAT_HISTORY, "debug": DEBUG_LOGS})

@app.route('/download_logs')
def download_logs():
    log_str = "\n".join([f"[{x['time']}] {x['dir']}: {x['data']}" for x in DEBUG_LOGS])
    return Response(log_str, mimetype="text/plain", headers={"Content-Disposition": "attachment;filename=titan_logs.txt"})

@app.route('/render')
def render():
    try:
        b_str = request.args.get('b', '_________')
        w_line = request.args.get('w', '')
        if 'board' not in ASSETS: init_assets()
        base = ASSETS['board'].copy()
        x_img, o_img = ASSETS['x'], ASSETS['o']
        for i, c in enumerate(b_str):
            if c in ['X', 'O']:
                sym = x_img if c == 'X' else o_img
                base.paste(sym, ((i%3)*300, (i//3)*300), sym)
        if w_line:
            draw = ImageDraw.Draw(base)
            idx = [int(k) for k in w_line.split(',')]
            s, e = idx[0], idx[2]
            draw.line([((s%3)*300+150, (s//3)*300+150), ((e%3)*300+150, (e//3)*300+150)], fill="#ffd700", width=25)
        img_io = io.BytesIO()
        base.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')
    except: return "Error", 500

# =============================================================================
# 7. UI TEMPLATES
# =============================================================================
LEADERBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>TITAN RANKINGS</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@600&display=swap" rel="stylesheet">
    <style>
        body { background: #050505; color: #fff; font-family: 'Rajdhani', sans-serif; margin: 0; padding: 20px; }
        h1 { text-align: center; color: #00f3ff; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 30px; }
        .card { background: #111; border: 1px solid #333; border-radius: 12px; padding: 15px; margin-bottom: 12px; display: flex; align-items: center; transition: 0.2s; }
        .card:hover { border-color: #00f3ff; transform: scale(1.02); }
        .rank { font-size: 24px; width: 50px; text-align: center; font-weight: bold; color: #555; }
        .rank-1 { color: #FFD700; font-size: 30px; text-shadow: 0 0 10px gold; }
        .avatar { width: 55px; height: 55px; border-radius: 50%; background: #222; margin-right: 15px; object-fit: cover; }
        .info { flex: 1; }
        .name { font-size: 18px; font-weight: bold; display: block; color: #e0e0e0; }
        .score { font-size: 20px; color: #00ff41; font-weight: bold; }
    </style>
</head>
<body>
    <h1>🏆 Global Legends</h1>
    {% for u in users %}
    <div class="card">
        <div class="rank {% if loop.index == 1 %}rank-1{% endif %}">#{{loop.index}}</div>
        <img class="avatar" src="{{ u[3] if u[3] else 'https://cdn-icons-png.flaticon.com/512/149/149071.png' }}">
        <div class="info"><span class="name">{{ u[0] }}</span><span style="color:#888;font-size:12px">Wins: {{ u[2] }}</span></div>
        <div class="score">{{ u[1] }}</div>
    </div>
    {% endfor %}
</body>
</html>
"""

UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>TITAN V7</title>
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #050505; --panel: #111; --primary: #00f3ff; --text: #e0e6ed; }
        body { margin: 0; background: var(--bg); color: var(--text); font-family: 'Rajdhani', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        #login-view { position: absolute; top:0; left:0; width:100%; height:100%; z-index: 999; display: flex; justify-content: center; align-items: center; background: #000; }
        .login-card { width: 85%; max-width: 320px; padding: 25px; background: #111; border: 1px solid #333; border-radius: 12px; text-align: center; }
        input { width: 100%; padding: 12px; margin-bottom: 12px; background: #000; border: 1px solid #333; color: #fff; border-radius: 6px; }
        .btn-login { width: 100%; padding: 12px; background: var(--primary); font-weight: bold; border: none; border-radius: 6px; cursor: pointer; }
        #app-view { display: none; height: 100%; flex-direction: column; width: 100%; }
        header { height: 50px; background: #111; border-bottom: 1px solid #333; display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
        .content { flex: 1; position: relative; overflow: hidden; }
        .tab-content { position: absolute; top:0; left:0; width:100%; height:100%; display: none; flex-direction: column; }
        .active-tab { display: flex; }
        #chat-container { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 10px; }
        .msg-row { display: flex; gap: 10px; } .msg-right { flex-direction: row-reverse; }
        .bubble { background: #1e1e1e; padding: 8px 12px; border-radius: 8px; font-size: 13px; max-width: 80%; }
        .debug-logs { flex: 1; overflow-y: auto; padding: 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; background: #000; }
        .log-entry { margin-bottom: 5px; border-bottom: 1px solid #222; }
        nav { height: 50px; background: #000; border-top: 1px solid #333; display: flex; }
        .nav-btn { flex: 1; background: transparent; border: none; color: #555; font-weight: bold; cursor: pointer; }
        .nav-btn.active { color: var(--primary); background: #0a0a0a; }
        iframe { width: 100%; height: 100%; border: none; }
    </style>
</head>
<body>
    <div id="login-view">
        <div class="login-card">
            <h2 style="color:var(--primary)">TITAN OS V7</h2>
            <input id="u" placeholder="Howdies Username">
            <input id="p" type="password" placeholder="Password">
            <input id="r" placeholder="Room Name (e.g. Life)">
            <button onclick="login()" class="btn-login">SYSTEM CONNECT</button>
        </div>
    </div>
    <div id="app-view">
        <header>
            <span>TITAN PANEL</span>
            <span id="status-badge" style="font-size:10px;color:#666">OFFLINE</span>
            <button onclick="logout()" style="background:#f03;border:none;color:#fff;padding:2px 8px;border-radius:3px">X</button>
        </header>
        <div class="content">
            <div id="tab-chat" class="tab-content active-tab">
                <div id="chat-container"></div>
            </div>
            <div id="tab-lb" class="tab-content">
                <iframe src="/leaderboard"></iframe>
            </div>
            <div id="tab-debug" class="tab-content">
                <div style="padding:5px;background:#111;border-bottom:1px solid #333;display:flex;justify-content:space-between">
                    <span style="color:#666;font-size:10px">DEBUG TERMINAL</span>
                    <div>
                        <a href="/download_logs" target="_blank" style="background:#00f3ff;color:#000;text-decoration:none;font-size:10px;padding:2px 5px;border-radius:2px;font-weight:bold">DOWNLOAD LOGS</a>
                        <button onclick="clearData()" style="background:#333;border:none;color:#fff;font-size:10px;padding:2px 5px;border-radius:2px">CLEAR</button>
                    </div>
                </div>
                <div id="debug-log-area" class="debug-logs"></div>
            </div>
        </div>
        <nav>
            <button onclick="switchTab('chat')" id="btn-chat" class="nav-btn active">CHAT</button>
            <button onclick="switchTab('lb')" id="btn-lb" class="nav-btn">RANKS</button>
            <button onclick="switchTab('debug')" id="btn-debug" class="nav-btn">DEBUG</button>
        </nav>
    </div>
    <script>
        function switchTab(t) {
            document.querySelectorAll('.tab-content').forEach(e=>e.classList.remove('active-tab'));
            document.querySelectorAll('.nav-btn').forEach(e=>e.classList.remove('active'));
            document.getElementById('tab-'+t).classList.add('active-tab');
            document.getElementById('btn-'+t).classList.add('active');
            if(t==='lb') document.querySelector('iframe').src = '/leaderboard';
        }
        function login() {
            const u=document.getElementById('u').value, p=document.getElementById('p').value, r=document.getElementById('r').value;
            if(!u||!p||!r) return alert("Fill all!");
            document.getElementById('login-view').style.display='none';
            document.getElementById('app-view').style.display='flex';
            fetch('/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({u,p,r})});
        }
        function logout() { fetch('/disconnect', {method:'POST'}); location.reload(); }
        function clearData() { fetch('/clear_data', {method: 'POST'}); }
        setInterval(() => {
            fetch('/get_data').then(r=>r.json()).then(d => {
                document.getElementById('status-badge').innerText = d.status;
                document.getElementById('status-badge').style.color = d.status==='ONLINE'?'#0f0':'#666';
                const c = document.getElementById('chat-container');
                c.innerHTML = d.chat.map(m => `
                    <div class="msg-row ${m.type==='bot'?'msg-right':''}">
                        <div class="bubble"><b>${m.user}:</b> ${m.msg}</div>
                    </div>`).join('');
                const dbg = document.getElementById('debug-log-area');
                dbg.innerHTML = d.debug.slice(-30).map(l => `<div class="log-entry"><span style="color:${l.dir==='IN'?'#0f0':l.dir==='OUT'?'#0ff':'#f00'}">${l.dir}</span> ${JSON.stringify(l.data)}</div>`).join('');
            });
        }, 1000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)