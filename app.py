import os
import json
import time
import threading
import io
import random
import uuid
import math
import websocket
import ssl
import sqlite3
import requests
import psycopg2
from flask import Flask, render_template_string, request, jsonify, send_file, Response
from PIL import Image, ImageDraw, ImageFont, ImageOps

app = Flask(__name__)

# =============================================================================
# 1. CONFIG & LOCKS
# =============================================================================
DB_LOCK = threading.Lock()
GAME_LOCK = threading.Lock()
ASSETS = {}

# =============================================================================
# 2. ASSETS GENERATION (FAIL-SAFE MODE)
# =============================================================================
def create_fallback_coin(text, color_type):
    """Generates a coin programmatically if download fails"""
    coin_size = 300
    img = Image.new('RGBA', (coin_size, coin_size), (0,0,0,0))
    d = ImageDraw.Draw(img)
    
    if color_type == "gold":
        main_color = (255, 215, 0)
        outline_color = (184, 134, 11)
    else:
        main_color = (192, 192, 192)
        outline_color = (105, 105, 105)

    d.ellipse([5, 5, 295, 295], fill=main_color, outline=outline_color, width=5)
    d.ellipse([25, 25, 275, 275], outline=(255, 255, 255, 100), width=3)
    
    try: font = ImageFont.truetype("arial.ttf", 150)
    except: font = ImageFont.load_default()
    
    # Draw Text centered
    # Fallback for text size calculation
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((300-w)/2, (300-h)/2 - 20), text, font=font, fill=outline_color)
    except:
        d.text((120, 100), text, fill=outline_color) # Basic positioning
        
    return img

def load_image_from_url(url, fallback_text, color_type):
    try:
        print(f"Attempting to download asset: {fallback_text}...")
        response = requests.get(url, stream=True, timeout=5) # 5 sec timeout
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content)).convert("RGBA")
        print(f"Success: Loaded {fallback_text}")
        return img.resize((300, 300))
    except Exception as e:
        print(f"⚠️ Warning: Could not download {fallback_text}. Using Generator. Error: {e}")
        return create_fallback_coin(fallback_text, color_type)

## =============================================================================
# ENGINE: GENERATE NUMBER ASSETS (BIG CYAN PNGs)
# =============================================================================
def get_high_quality_font(size):
    """
    Ye function high-quality font load karega.
    Pehle Server ke andar dhundhega, nahi mila to Internet se layega.
    """
    # 1. Linux/Render Server Paths (Common locations)
    linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "arialbd.ttf",
        "Arial_Bold.ttf"
    ]
    
    # Try loading from system
    for path in linux_fonts:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
            
    # 2. Download from Internet (Backup)
    try:
        url = "https://github.com/google/fonts/raw/main/apache/robotoslab/RobotoSlab-Black.ttf"
        resp = requests.get(url, timeout=5)
        return ImageFont.truetype(io.BytesIO(resp.content), size)
    except:
        pass
        
    # 3. Fallback (Agar sab fail ho jaye)
    return ImageFont.load_default()

def create_number_png(number, font):
    """
    Har number ke liye ek 300x300 ki Transparent PNG generate karta hai.
    Color: CYAN 🩵
    """
    # 1. Create Transparent Box (300x300)
    img = Image.new('RGBA', (300, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    text = str(number)
    text_color = (0, 255, 255) # 🩵 CYAN COLOR
    
    # 2. Calculate Center Position
    # Box center is 150, 150
    try:
        # New PIL method (Perfect Centering)
        draw.text((150, 150), text, font=font, fill=text_color, anchor="mm")
    except:
        # Old PIL method (Manual Calculation)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((300 - w) / 2, (300 - h) / 2 - 20), text, font=font, fill=text_color)
        
    return img

def init_assets():
    # --- 1. BOARD BACKGROUND ---
    # Dark Background
    board = Image.new('RGB', (900, 900), (10, 12, 20))
    draw = ImageDraw.Draw(board)
    
    # Colors
    cyan_line = (0, 255, 255)
    dark_bg_line = (0, 80, 80)
    magenta_border = (255, 0, 255)
    
    # --- 2. DRAW GRID LINES ---
    # Vertical
    for x in [300, 600]:
        draw.line([(x, 20), (x, 880)], fill=dark_bg_line, width=25) 
        draw.line([(x, 20), (x, 880)], fill=cyan_line, width=8)
    # Horizontal
    for y in [300, 600]:
        draw.line([(20, y), (880, y)], fill=dark_bg_line, width=25)
        draw.line([(20, y), (880, y)], fill=cyan_line, width=8)
    # Border
    draw.rectangle([5, 5, 895, 895], outline=magenta_border, width=12)

    # --- 3. NUMBER GENERATOR ENGINE ---
    # Hum Font Size 180 (Bohot Bada) use karenge
    big_font = get_high_quality_font(180)
    
    print("Generating Number Assets (1-9)...")
    
    for i in range(1, 10):
        # A. Har number ka PNG generate karein
        num_img = create_number_png(i, big_font)
        
        # B. Grid Position Calculate karein
        row = (i - 1) // 3
        col = (i - 1) % 3
        
        x_pos = col * 300
        y_pos = row * 300
        
        # C. Board par paste karein (Mapping)
        # Mask use kar rahe hain taaki transparency maintain rahe
        board.paste(num_img, (x_pos, y_pos), num_img)

    ASSETS['board'] = board

    # --- 4. X & O ASSETS ---
    x_img = Image.new('RGBA', (300, 300), (0,0,0,0))
    dx = ImageDraw.Draw(x_img)
    # X - Red/Pink
    dx.line([(60,60), (240,240)], fill=(255, 0, 80), width=45)
    dx.line([(240,60), (60,240)], fill=(255, 0, 80), width=45)
    ASSETS['x'] = x_img

    o_img = Image.new('RGBA', (300, 300), (0,0,0,0))
    do = ImageDraw.Draw(o_img)
    # O - Green
    do.ellipse([60,60,240,240], outline=(0, 255, 100), width=45)
    ASSETS['o'] = o_img

    # --- 5. COIN ASSETS ---
    HEADS_URL = "https://www.dropbox.com/scl/fi/sig75nm1i98d8z4jx2yw8/file_0000000026b471fda1f5631420800dd3.png?rlkey=36ov7cpwd90kejav4a7atkhh3&st=tf3jt0np&dl=1"
    TAILS_URL = "https://www.dropbox.com/scl/fi/0s35obflw2dl9r7zulaug/file_0000000085c871fd9a6e9c9b93f39cd9.png?rlkey=g5dx0anpmnjk0h6ysz4d6osqa&st=awly0km3&dl=1"
    
    ASSETS['heads'] = load_image_from_url(HEADS_URL, "H", "gold")
    ASSETS['tails'] = load_image_from_url(TAILS_URL, "T", "silver")
# Run asset init immediately
try:
    init_assets()
except Exception as e:
    print(f"CRITICAL ASSET ERROR: {e}")

# --- ANIMATION ---
def create_spin_gif():
    frames = []
    base_h = ASSETS['heads'].resize((200, 200))
    base_t = ASSETS['tails'].resize((200, 200))
    
    W, H = 400, 500
    total_frames = 15
    
    for i in range(total_frames):
        frame = Image.new('RGBA', (W, H), (0,0,0,0))
        progress = i / (total_frames - 1)
        height = 4 * progress * (1 - progress) * 350
        y_pos = 400 - height
        scale = abs(math.cos(i * 1.5))
        w = int(200 * scale)
        if w < 1: w = 1
        
        coin = (base_h if i % 2 == 0 else base_t).resize((w, 200))
        frame.paste(coin, ((W - w)//2, int(y_pos)), coin)
        frames.append(frame)
        
    img_io = io.BytesIO()
    frames[0].save(img_io, format='GIF', save_all=True, append_images=frames[1:], duration=50, loop=0, disposal=2)
    img_io.seek(0)
    return img_io.getvalue()

def get_static_result(result):
    img = ASSETS['heads'] if result == "HEADS" else ASSETS['tails']
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return img_io.getvalue()

# =============================================================================
# 3. DATABASE
# =============================================================================
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_SQLITE = False if DATABASE_URL else True
DB_FILE_NAME = "howdies_v16.db" 
TABLE_NAME = "howdies_gamers_v16" 

def get_db():
    if USE_SQLITE: return sqlite3.connect(DB_FILE_NAME)
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    with DB_LOCK: 
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE_NAME} 
                       (username VARCHAR(255) PRIMARY KEY, wins INTEGER, score INTEGER, avatar_url TEXT)''')
            conn.commit()
            conn.close()
        except Exception as e: print("DB Init Error:", e)

def update_score(username, points, avatar_url=""):
    with DB_LOCK: 
        try:
            conn = get_db()
            c = conn.cursor()
            ph = "?" if USE_SQLITE else "%s"
            c.execute(f"SELECT score, wins FROM {TABLE_NAME} WHERE username={ph}", (username,))
            data = c.fetchone()
            
            new_score = 0
            if data:
                new_score = data[0] + points
                new_wins = data[1] + (1 if points > 0 else 0)
                if avatar_url:
                    c.execute(f"UPDATE {TABLE_NAME} SET score={ph}, wins={ph}, avatar_url={ph} WHERE username={ph}", (new_score, new_wins, avatar_url, username))
                else:
                    c.execute(f"UPDATE {TABLE_NAME} SET score={ph}, wins={ph} WHERE username={ph}", (new_score, new_wins, username))
            else:
                new_score = 1000 + points
                new_wins = 1 if points > 0 else 0
                c.execute(f"INSERT INTO {TABLE_NAME} (username, score, wins, avatar_url) VALUES ({ph}, {ph}, {ph}, {ph})", (username, new_score, new_wins, avatar_url))
            conn.commit(); conn.close()
            return new_score 
        except Exception as e: print(f"DB Error: {e}"); return 0

def get_score(username):
    try:
        conn = get_db(); c = conn.cursor(); ph = "?" if USE_SQLITE else "%s"
        c.execute(f"SELECT score FROM {TABLE_NAME} WHERE username={ph}", (username,))
        data = c.fetchone(); conn.close()
        return data[0] if data else 1000
    except: return 1000

def get_leaderboard_data():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute(f"SELECT username, score, wins, avatar_url FROM {TABLE_NAME} ORDER BY score DESC LIMIT 50")
        data = c.fetchall(); conn.close(); return data
    except: return []

init_db()

# =============================================================================
# 4. BOT CORE
# =============================================================================
BOT = {
    "ws": None, "status": "DISCONNECTED",
    "user": "", "pass": "", "room": "", 
    "token": "", "user_id": None, 
    "room_id": None, "domain": "", "should_run": False, "avatars": {}
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
    if len(DEBUG_LOGS) > 300: DEBUG_LOGS.pop(0)

def perform_login(username, password):
    url = "https://api.howdies.app/api/login"
    try:
        payload = {"username": username, "password": password}
        response = requests.post(url, json=payload, timeout=15)
        save_debug("API_LOGIN", response.text)
        if response.status_code == 200:
            data = response.json()
            token = None; uid = None
            if "token" in data: token = data["token"]
            elif "data" in data and "token" in data["data"]: token = data["data"]["token"]
            if "id" in data: uid = data["id"]
            elif "userId" in data: uid = data["userId"]
            elif "data" in data and "id" in data["data"]: uid = data["data"]["id"]
            if token:
                BOT["user_id"] = uid
                return token
        return None
    except Exception as e: save_debug("API_ERROR", str(e)); return None

def upload_image_to_howdies(image_bytes, is_gif=False):
    if not BOT["token"] or not BOT["user_id"]: return None
    url = "https://api.howdies.app/api/upload"
    try:
        filename = f"{uuid.uuid4()}.gif" if is_gif else f"{uuid.uuid4()}.png"
        mime = 'image/gif' if is_gif else 'image/png'
        files = {'file': (filename, image_bytes, mime)}
        data = {'UserID': BOT["user_id"], 'token': BOT["token"], 'uploadType': 'image'}
        resp = requests.post(url, data=data, files=files, timeout=20)
        save_debug("UPLOAD_RESP", resp.text)
        if resp.status_code == 200:
            resp_json = resp.json()
            if "url" in resp_json: return resp_json["url"]
            if "data" in resp_json: return resp_json["data"]
        return None
    except Exception as e: save_debug("UPLOAD_ERR", str(e)); return None

def bot_thread():
    while BOT["should_run"]:
        try:
            if not BOT["token"]:
                BOT["status"] = "FETCHING TOKEN"
                token = perform_login(BOT["user"], BOT["pass"])
                if not token:
                    BOT["status"] = "AUTH FAILED"
                    time.sleep(10)
                    continue
                BOT["token"] = token
            BOT["status"] = "CONNECTING WS"
            ws_url = f"wss://app.howdies.app/howdies?token={BOT['token']}"
            ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
            BOT["ws"] = ws
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        except Exception as e: save_debug("CRASH", str(e))
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
        if data.get("handler") == "joinchatroom" and data.get("roomid"):
            BOT["room_id"] = data["roomid"]
            save_debug("SYSTEM", f"Captured Room ID: {BOT['room_id']}")
        sender = data.get("from") or data.get("username")
        if sender and data.get("avatar_url"): BOT["avatars"][sender] = data["avatar_url"]
        if data.get("handler") not in ["receipt_ack", "ping", "pong"]: save_debug("IN", data)
        if data.get("handler") in ["chatroommessage", "message"]:
            msg_body = data.get("text") or data.get("body")
            if msg_body and sender:
                av = BOT["avatars"].get(sender, "https://cdn-icons-png.flaticon.com/512/149/149071.png")
                save_chat(sender, msg_body, av, "text")
                if sender != BOT["user"]: game_engine(sender, msg_body)
    except Exception as e: save_debug("MSG ERROR", str(e))

def on_error(ws, error): save_debug("WS ERROR", str(error))
def on_close(ws, c, m): BOT["status"] = "DISCONNECTED"

def send_msg(text, type="text", url=""):
    if BOT["ws"]:
        target_room = BOT["room_id"] if BOT["room_id"] else BOT["room"]
        pkt = {"handler": "chatroommessage", "id": str(time.time()), "type": type, "roomid": target_room, "text": text, "url": url, "length": "0"}
        try:
            BOT["ws"].send(json.dumps(pkt))
            bot_av = "https://cdn-icons-png.flaticon.com/512/4712/4712035.png"
            display = "[IMAGE SENT]" if url else text
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
                if now - game['last_active'] > 60: to_remove.append(host)
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
        send_msg("🎮 **COMMANDS:**\n• `!start` (TicTacToe)\n• `!flip` (Toss)\n• `!flip head` (Bet)\n• `!flip tail` (Bet)\n• `!score`")
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
            else: send_msg(f"⚠ {user}, no active game found.")
        return

    # --- FLIP ---
    if msg.startswith("!flip"):
        parts = msg.split()
        guess = None
        if len(parts) > 1:
            raw_guess = parts[1].upper()
            if raw_guess in ["H", "HEAD", "HEADS"]: guess = "HEADS"
            elif raw_guess in ["T", "TAIL", "TAILS"]: guess = "TAILS"
        
        result = random.choice(["HEADS", "TAILS"])
        
        def process_flip():
            send_msg(f"@{user} tossed the coin! 🌪️")
            spin_gif = create_spin_gif()
            spin_url = upload_image_to_howdies(spin_gif, is_gif=True)
            if spin_url: send_msg("", "image", spin_url)
            
            time.sleep(3.5)
            res_png = get_static_result(result)
            res_url = upload_image_to_howdies(res_png, is_gif=False)
            
            if res_url: send_msg("", "image", res_url)
            
            outcome_text = f"✨ Result: **{result}**"
            new_bal = 0
            if guess:
                if guess == result:
                    new_bal = update_score(user, 50)
                    outcome_text += f"\n🎉 **YOU WON!** (+50 pts)\n💰 Balance: {new_bal}"
                else:
                    new_bal = update_score(user, -20)
                    outcome_text += f"\n❌ **YOU LOST** (-20 pts)\n💰 Balance: {new_bal}"
            else:
                new_bal = get_score(user)
                outcome_text += f"\n💰 Balance: {new_bal}"

            time.sleep(0.5)
            send_msg(outcome_text)
        
        threading.Thread(target=process_flip).start()
        return

    # --- TICTACTOE ---
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
            ACTIVE_GAMES[user] = {"host": user, "mode": mode, "board": [" "]*9, "turn": "X", "p1": user, "p2": "🤖 TitanBot" if mode=="bot" else None, "last_active": time.time(), "bet": bet}
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
        if game["mode"] == "pvp" and game["p2"] is None: return send_msg(f"⚠ {user}, waiting for Player 2!")
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
    if 'board' not in ASSETS: init_assets()
    base = ASSETS['board'].copy()
    x_img, o_img = ASSETS['x'], ASSETS['o']
    for i, c in enumerate(game["board"]):
        if c == 'X': base.paste(x_img, ((i%3)*300, (i//3)*300), x_img)
        elif c == 'O': base.paste(o_img, ((i%3)*300, (i//3)*300), o_img)
    if line:
        draw = ImageDraw.Draw(base)
        idx = [int(k) for k in line.split(',')]
        s, e = idx[0], idx[2]
        draw.line([((s%3)*300+150, (s//3)*300+150), ((e%3)*300+150, (e//3)*300+150)], fill="#ffd700", width=30)
    img_io = io.BytesIO()
    base.save(img_io, 'PNG')
    img_io.seek(0)
    uploaded_url = upload_image_to_howdies(img_io.getvalue())
    if uploaded_url: send_msg("", "image", uploaded_url)
    else:
        base_url = BOT.get('domain', '')
        fallback = f"{base_url}render?b={b_str}&w={line}&h={host}&t={int(time.time())}"
        send_msg(f"🖼 {fallback}", "text", "")

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

LEADERBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>TITAN RANKINGS</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #050505; color: #fff; font-family: monospace; margin: 0; padding: 20px; }
        .card { background: #111; border: 1px solid #333; padding: 15px; margin-bottom: 12px; display: flex; align-items: center; }
        .avatar { width: 50px; height: 50px; border-radius: 50%; margin-right: 15px; }
        .info { flex: 1; }
        .score { font-size: 20px; color: #00ff41; font-weight: bold; }
    </style>
</head>
<body>
    <h1 style="color:#00f3ff;text-align:center">TITAN LEGENDS</h1>
    {% for u in users %}
    <div class="card">
        <div style="font-size:20px;width:40px">#{{loop.index}}</div>
        <img class="avatar" src="{{ u[3] or 'https://via.placeholder.com/50' }}">
        <div class="info">
            <div style="font-weight:bold;font-size:18px">{{ u[0] }}</div>
            <div style="color:#888">Wins: {{ u[2] }}</div>
        </div>
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
    <title>TITAN V16</title>
    <style>
        body { margin: 0; background: #050505; color: #e0e6ed; font-family: monospace; height: 100vh; display: flex; flex-direction: column; }
        #login-view { position: absolute; top:0; left:0; width:100%; height:100%; z-index: 99; display: flex; justify-content: center; align-items: center; background: #000; }
        .login-card { width: 300px; padding: 20px; background: #111; border: 1px solid #333; text-align: center; }
        input { width: 90%; padding: 10px; margin-bottom: 10px; background: #000; border: 1px solid #333; color: #fff; }
        button { padding: 10px; background: #00f3ff; border: none; cursor: pointer; width: 100%; font-weight: bold; }
        #app-view { display: none; height: 100%; flex-direction: column; width: 100%; }
        header { height: 50px; background: #111; border-bottom: 1px solid #333; display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
        .content { flex: 1; position: relative; overflow: hidden; }
        .tab-content { position: absolute; top:0; left:0; width:100%; height:100%; display: none; flex-direction: column; }
        .active-tab { display: flex; }
        #chat-container { flex: 1; overflow-y: auto; padding: 15px; }
        .msg-row { margin-bottom: 10px; }
        .bubble { background: #1e1e1e; padding: 8px; display: inline-block; border-radius: 8px; max-width: 80%; }
        .debug-logs { flex: 1; overflow-y: auto; padding: 10px; background: #000; font-size: 10px; }
        nav { height: 50px; background: #000; border-top: 1px solid #333; display: flex; }
        .nav-btn { flex: 1; background: transparent; border: none; color: #555; cursor: pointer; font-weight: bold; }
        .active { color: #00f3ff; background: #111; }
        iframe { width: 100%; height: 100%; border: none; }
    </style>
</head>
<body>
    <div id="login-view">
        <div class="login-card">
            <h2 style="color:#00f3ff">TITAN V16</h2>
            <input id="u" placeholder="Howdies Username">
            <input id="p" type="password" placeholder="Password">
            <input id="r" placeholder="Room Name">
            <button onclick="login()">CONNECT</button>
        </div>
    </div>
    <div id="app-view">
        <header>
            <span>TITAN PANEL</span>
            <span id="status-badge">OFFLINE</span>
            <button onclick="logout()" style="width:auto;background:red;color:#fff">X</button>
        </header>
        <div class="content">
            <div id="tab-chat" class="tab-content active-tab">
                <div id="chat-container"></div>
            </div>
            <div id="tab-lb" class="tab-content">
                <iframe src="/leaderboard"></iframe>
            </div>
            <div id="tab-debug" class="tab-content">
                <div style="padding:5px;border-bottom:1px solid #333">
                    <a href="/download_logs" style="color:#00f3ff">Download Logs</a>
                    <button onclick="clearData()" style="width:auto;padding:2px 5px;margin-left:10px">Clear</button>
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
                    <div class="msg-row" style="text-align:${m.type==='bot'?'right':'left'}">
                        <div class="bubble"><b>${m.user}:</b> ${m.msg}</div>
                    </div>`).join('');
                const dbg = document.getElementById('debug-log-area');
                dbg.innerHTML = d.debug.slice(-30).map(l => `<div style="margin-bottom:5px"><span style="color:${l.dir==='IN'?'#0f0':'#0ff'}">${l.dir}</span> ${JSON.stringify(l.data)}</div>`).join('');
            });
        }, 1000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)