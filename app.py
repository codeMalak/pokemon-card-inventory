from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
import sqlite3, os, traceback, hashlib, secrets, urllib.parse, time, json, io, csv, threading
from functools import wraps
from datetime import datetime
from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_HERE, ".env")

try:
    load_dotenv(_ENV_FILE)
except ImportError:
    # python-dotenv not installed — parse .env manually
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE) as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

try:
    import requests as req_lib
    USE_REQUESTS = True
except ImportError:
    USE_REQUESTS = False

app = Flask(__name__)

# Persist the secret key across restarts so sessions survive reloads.
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
if not os.path.exists(_KEY_FILE):
    _generated = secrets.token_hex(32)
    try:
        with open(_KEY_FILE, "w") as _f:
            _f.write(_generated)
    except OSError:
        pass
    _persisted_key = _generated
else:
    with open(_KEY_FILE) as _f:
        _persisted_key = _f.read().strip()
app.secret_key = os.environ.get("SECRET_KEY") or _persisted_key

DB_PATH        = "pokemon_inventory.db"
TCG_API        = "https://api.pokemontcg.io/v2"
TCG_API_KEY    = os.environ.get("POKEMONTCG_API_KEY", "")
_key_preview   = (TCG_API_KEY[:8] + "…") if TCG_API_KEY else ""
print(f"[CONFIG] TCG API key {'LOADED ✓ (' + _key_preview + ')' if TCG_API_KEY else 'MISSING — requests will be unauthenticated'}")

# ─────────────────────────────────────────────────────────────────────────────
#  In-memory + disk-backed cache
# ─────────────────────────────────────────────────────────────────────────────
_mem_cache = {}
CACHE_TTL_SHORT = 300    # 5 min  – search results
CACHE_TTL_LONG  = 86400  # 24 hrs – set lists, rarities (rarely change)
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def _disk_path(key):
    safe = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{safe}.json")

def cache_get(key, ttl=CACHE_TTL_SHORT):
    # 1) memory
    e = _mem_cache.get(key)
    if e and (time.time() - e["ts"]) < ttl:
        return e["data"]
    # 2) disk
    p = _disk_path(key)
    if os.path.exists(p):
        try:
            with open(p) as f:
                obj = json.load(f)
            if (time.time() - obj["ts"]) < ttl:
                _mem_cache[key] = obj   # warm memory
                return obj["data"]
        except Exception:
            pass
    return None

def cache_set(key, data):
    obj = {"data": data, "ts": time.time()}
    if len(_mem_cache) >= 500:
        oldest = min(_mem_cache, key=lambda k: _mem_cache[k]["ts"])
        del _mem_cache[oldest]
    _mem_cache[key] = obj
    try:
        with open(_disk_path(key), "w") as f:
            json.dump(obj, f)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
#  TCG API helper
# ─────────────────────────────────────────────────────────────────────────────
def tcg_headers():
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    if TCG_API_KEY:
        h["X-Api-Key"] = TCG_API_KEY
    return h

# Per-URL locks so concurrent requests for the same URL don't all hit the API.
# The second thread waits, then finds the result in cache instead of making another call.
_inflight_master = threading.Lock()
_inflight_locks: dict = {}

def tcg_get(url, ttl=CACHE_TTL_SHORT):
    cached = cache_get(url, ttl)
    if cached is not None:
        print(f"[CACHE HIT] {url[:100]}")
        return cached

    with _inflight_master:
        if url not in _inflight_locks:
            _inflight_locks[url] = threading.Lock()
        url_lock = _inflight_locks[url]

    with url_lock:
        # Re-check after acquiring lock — another thread may have just fetched it
        cached = cache_get(url, ttl)
        if cached is not None:
            print(f"[CACHE HIT] {url[:100]}")
            return cached

        print(f"[API CALL ] {url[:100]}")
        data = _http_get_json(url)
        cache_set(url, data)
        return data


def _http_get_json(url):
    """
    Fetch JSON from url, trying requests first then a PowerShell fallback on Windows.
    The PowerShell fallback uses Windows' native WinHTTP stack (same as Chrome),
    which bypasses the SSL inspection issues that block Python's OpenSSL on this machine.
    """
    import sys

    # ── primary: requests ────────────────────────────────────────────────────
    if USE_REQUESTS:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = req_lib.get(url, headers=tcg_headers(), timeout=(10, 30), verify=False)
            if r.status_code == 404:
                return {"data": [], "totalCount": 0}
            r.raise_for_status()
            return r.json()
        except Exception as _e:
            print(f"[WARN] requests failed ({type(_e).__name__}: {_e}), "
                  f"{'trying PowerShell fallback…' if sys.platform == 'win32' else 're-raising'}")
            if sys.platform != 'win32':
                raise

    # ── fallback: PowerShell / WinHTTP (Windows only) ───────────────────────
    if sys.platform == 'win32':
        return _powershell_get_json(url)

    # ── last resort: urllib with SSL verification disabled ───────────────────
    import json as _j, urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    rq = urllib.request.Request(url, headers=tcg_headers())
    with urllib.request.urlopen(rq, timeout=45, context=ctx) as resp:
        return _j.loads(resp.read())


def _powershell_get_json(url):
    """Make an HTTP GET using PowerShell's Invoke-WebRequest (uses WinHTTP like Chrome)."""
    import subprocess, json as _j, sys
    headers = tcg_headers()
    # Build a PowerShell hashtable literal from the headers dict
    pairs = "; ".join(f"'{k}' = '{v}'" for k, v in headers.items())
    ps_script = (
        "$ProgressPreference='SilentlyContinue'; "
        f"$h = @{{{pairs}}}; "
        "$resp = try { "
        f"  Invoke-WebRequest -Uri '{url}' -Headers $h -UseBasicParsing -TimeoutSec 30 "
        "} catch { "
        "  $sc = $_.Exception.Response.StatusCode.value__; "
        "  if ($sc -eq 404) { Write-Output '{\"data\":[],\"totalCount\":0}'; exit 0 } "
        "  Write-Error $_.Exception.Message; exit 1 "
        "}; "
        "$resp.Content"
    )
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, timeout=35
    )
    if result.returncode != 0:
        err = result.stderr.strip() or "PowerShell HTTP request failed"
        raise RuntimeError(err)
    print(f"[PS CALL  ] {url[:100]}")
    return _j.loads(result.stdout)

# ─────────────────────────────────────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE,
            email        TEXT NOT NULL UNIQUE,
            password     TEXT NOT NULL,
            avatar_color TEXT DEFAULT '#3b82f6',
            theme        TEXT DEFAULT 'dark',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            tcg_id       TEXT,
            name         TEXT NOT NULL,
            pokemon_type TEXT,
            rarity       TEXT,
            set_name     TEXT,
            set_id       TEXT,
            set_series   TEXT,
            card_number  TEXT,
            hp           TEXT,
            subtypes     TEXT,
            variant      TEXT DEFAULT 'Normal',
            condition    TEXT DEFAULT 'Near Mint',
            quantity     INTEGER DEFAULT 1,
            market_price REAL DEFAULT 0.0,
            foil_price   REAL DEFAULT 0.0,
            image_small  TEXT,
            image_large  TEXT,
            notes        TEXT,
            is_favorite  INTEGER DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS wishlist (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            tcg_id TEXT, name TEXT NOT NULL, set_name TEXT, card_number TEXT,
            rarity TEXT, market_price REAL DEFAULT 0.0, image_small TEXT,
            max_price REAL DEFAULT 0.0, notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS trade_list (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            tcg_id TEXT, name TEXT NOT NULL, set_name TEXT, card_number TEXT,
            rarity TEXT, condition TEXT DEFAULT 'Near Mint',
            market_price REAL DEFAULT 0.0, asking_price REAL DEFAULT 0.0,
            image_small TEXT, notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, card_id INTEGER NOT NULL,
            target_price REAL NOT NULL, direction TEXT DEFAULT 'below',
            triggered INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(card_id) REFERENCES cards(id)
        );
        CREATE TABLE IF NOT EXISTS set_completion (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            set_id     TEXT NOT NULL,
            set_name   TEXT NOT NULL,
            total_cards INTEGER DEFAULT 0,
            pinned     INTEGER DEFAULT 0,
            UNIQUE(user_id, set_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    # Migrate existing databases that pre-date schema additions.
    # Each statement is attempted individually; failures mean the column already exists.
    _migrations = [
        # cards table — all columns that were added after the initial release
        "ALTER TABLE cards ADD COLUMN tcg_id TEXT",
        "ALTER TABLE cards ADD COLUMN pokemon_type TEXT",
        "ALTER TABLE cards ADD COLUMN rarity TEXT",
        "ALTER TABLE cards ADD COLUMN set_name TEXT",
        "ALTER TABLE cards ADD COLUMN set_id TEXT",
        "ALTER TABLE cards ADD COLUMN set_series TEXT",
        "ALTER TABLE cards ADD COLUMN card_number TEXT",
        "ALTER TABLE cards ADD COLUMN hp TEXT",
        "ALTER TABLE cards ADD COLUMN subtypes TEXT",
        "ALTER TABLE cards ADD COLUMN variant TEXT DEFAULT 'Normal'",
        "ALTER TABLE cards ADD COLUMN condition TEXT DEFAULT 'Near Mint'",
        "ALTER TABLE cards ADD COLUMN quantity INTEGER DEFAULT 1",
        "ALTER TABLE cards ADD COLUMN market_price REAL DEFAULT 0.0",
        "ALTER TABLE cards ADD COLUMN foil_price REAL DEFAULT 0.0",
        "ALTER TABLE cards ADD COLUMN image_small TEXT",
        "ALTER TABLE cards ADD COLUMN image_large TEXT",
        "ALTER TABLE cards ADD COLUMN notes TEXT",
        "ALTER TABLE cards ADD COLUMN is_favorite INTEGER DEFAULT 0",
        # users table
        "ALTER TABLE users ADD COLUMN avatar_color TEXT DEFAULT '#3b82f6'",
        "ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'dark'",
        # wishlist / trade_list extra columns
        "ALTER TABLE wishlist ADD COLUMN max_price REAL DEFAULT 0.0",
        "ALTER TABLE wishlist ADD COLUMN notes TEXT",
        "ALTER TABLE trade_list ADD COLUMN asking_price REAL DEFAULT 0.0",
        "ALTER TABLE trade_list ADD COLUMN notes TEXT",
    ]
    for _sql in _migrations:
        try:
            conn.execute(_sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()

init_db()  # run at import time so `flask run` also initializes the DB

# Complete rarity list — sourced directly from the API, stored statically so we never
# need to call /rarities at runtime. Update this list if new rarities are added.
_STATIC_RARITIES = [
    "ACE SPEC Rare", "Amazing Rare", "Black White Rare", "Classic Collection",
    "Common", "Double Rare", "Hyper Rare", "Illustration Rare", "LEGEND",
    "MEGA_ATTACK_RARE", "Mega Hyper Rare", "Promo", "Radiant Rare", "Rare",
    "Rare ACE", "Rare BREAK", "Rare Holo", "Rare Holo EX", "Rare Holo GX",
    "Rare Holo LV.X", "Rare Holo Star", "Rare Holo V", "Rare Holo VMAX",
    "Rare Holo VSTAR", "Rare Prime", "Rare Prism Star", "Rare Rainbow",
    "Rare Secret", "Rare Shining", "Rare Shiny", "Rare Shiny GX", "Rare Ultra",
    "Shiny Rare", "Shiny Ultra Rare", "Special Illustration Rare",
    "Trainer Gallery Rare Holo", "Ultra Rare", "Uncommon",
]

# ─────────────────────────────────────────────────────────────────────────────
#  Auth
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                            (username, hash_pw(password))).fetchone()
        conn.close()
        if user:
            session.update({"user_id": user["id"], "username": user["username"],
                            "avatar_color": user["avatar_color"], "theme": user["theme"] if "theme" in user.keys() else "dark"})
            return redirect(url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/register", methods=["GET","POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip()
        password = request.form.get("password","")
        confirm  = request.form.get("confirm","")
        if not username or not email or not password:
            error = "All fields are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            import random
            color = random.choice(["#3b82f6","#8b5cf6","#ec4899","#f59e0b","#10b981","#ef4444"])
            try:
                conn = get_db()
                conn.execute("INSERT INTO users (username,email,password,avatar_color) VALUES (?,?,?,?)",
                             (username, email, hash_pw(password), color))
                conn.commit()
                user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                conn.close()
                session.update({"user_id": user["id"], "username": user["username"],
                                "avatar_color": user["avatar_color"], "theme": "dark"})
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "Username or email already taken."
    return render_template("register.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────────────────────────────────────────
#  Main page
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    uid  = session["user_id"]
    page = int(request.args.get("page", 1))
    per  = 40
    conn = get_db()
    total_cards  = conn.execute("SELECT SUM(quantity) FROM cards WHERE user_id=?", (uid,)).fetchone()[0] or 0
    total_unique = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=?", (uid,)).fetchone()[0]
    total_value  = conn.execute("SELECT SUM(market_price*quantity) FROM cards WHERE user_id=?", (uid,)).fetchone()[0] or 0
    rarities_rows= conn.execute("SELECT DISTINCT rarity FROM cards WHERE user_id=? AND rarity!='' ORDER BY rarity",(uid,)).fetchall()
    rarities     = [r["rarity"] for r in rarities_rows if r["rarity"]]
    wl_count     = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id=?",(uid,)).fetchone()[0]
    tl_count     = conn.execute("SELECT COUNT(*) FROM trade_list WHERE user_id=?",(uid,)).fetchone()[0]
    al_count     = conn.execute("SELECT COUNT(*) FROM price_alerts WHERE user_id=? AND triggered=0",(uid,)).fetchone()[0]
    type_stats   = conn.execute("SELECT pokemon_type,COUNT(*) c FROM cards WHERE user_id=? AND pokemon_type!='' GROUP BY pokemon_type ORDER BY c DESC LIMIT 6",(uid,)).fetchall()
    set_stats    = conn.execute("SELECT set_name,COUNT(*) c FROM cards WHERE user_id=? AND set_name!='' GROUP BY set_name ORDER BY c DESC LIMIT 5",(uid,)).fetchall()
    top_value    = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY market_price DESC LIMIT 5",(uid,)).fetchall()
    pinned_sets  = conn.execute("SELECT * FROM set_completion WHERE user_id=? AND pinned=1",(uid,)).fetchall()
    # paginated cards
    offset = (page-1)*per
    cards  = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                          (uid, per, offset)).fetchall()
    total_pages = max(1, (total_unique + per - 1)//per)
    conn.close()
    return render_template("index.html",
        cards=cards, total_cards=total_cards, total_unique=total_unique,
        total_value=total_value, rarities=rarities,
        wishlist_count=wl_count, tradelist_count=tl_count, alerts_count=al_count,
        type_stats=type_stats, set_stats=set_stats, top_value=top_value,
        pinned_sets=pinned_sets, page=page, total_pages=total_pages,
        username=session["username"], avatar_color=session.get("avatar_color","#3b82f6"),
        theme=session.get("theme","dark"))

# ─────────────────────────────────────────────────────────────────────────────
#  API: cards (paginated JSON for infinite scroll)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/cards")
@login_required
def api_cards():
    uid    = session["user_id"]
    page   = int(request.args.get("page", 1))
    per    = int(request.args.get("per", 40))
    q      = request.args.get("q","").lower().strip()
    ftype  = request.args.get("type","").strip()
    frarity= request.args.get("rarity","").strip()
    fcond  = request.args.get("condition","").strip()
    sort   = request.args.get("sort","newest")
    favonly= request.args.get("fav","") == "1"
    conn   = get_db()
    where  = ["user_id=?"]
    params = [uid]
    if q:
        where.append("LOWER(name) LIKE ?"); params.append(f"%{q}%")
    if ftype:
        where.append("LOWER(pokemon_type) LIKE ?"); params.append(f"%{ftype.lower()}%")
    if frarity:
        where.append("rarity=?"); params.append(frarity)
    if fcond:
        where.append("condition=?"); params.append(fcond)
    if favonly:
        where.append("is_favorite=1")
    order = {"newest":"created_at DESC","name":"name ASC",
             "value-desc":"market_price DESC","value-asc":"market_price ASC",
             "qty-desc":"quantity DESC"}.get(sort,"created_at DESC")
    sql = f"SELECT * FROM cards WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?"
    params += [per, (page-1)*per]
    rows = conn.execute(sql, params).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM cards WHERE {' AND '.join(where[:-2] if len(where)>2 else where)}",
                         params[:-2] if len(params)>2 else params).fetchone()[0]
    # safer count
    count_where  = ["user_id=?"];  count_params = [uid]
    if q:       count_where.append("LOWER(name) LIKE ?"); count_params.append(f"%{q}%")
    if ftype:   count_where.append("LOWER(pokemon_type) LIKE ?"); count_params.append(f"%{ftype.lower()}%")
    if frarity: count_where.append("rarity=?"); count_params.append(frarity)
    if fcond:   count_where.append("condition=?"); count_params.append(fcond)
    if favonly: count_where.append("is_favorite=1")
    total = conn.execute(f"SELECT COUNT(*) FROM cards WHERE {' AND '.join(count_where)}", count_params).fetchone()[0]
    conn.close()
    return jsonify({"cards": [dict(r) for r in rows], "total": total, "page": page, "per": per})

# ─────────────────────────────────────────────────────────────────────────────
#  TCG Search  (only fires on explicit user submit, not on keystroke)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/search")
@login_required
def api_search():
    query  = request.args.get("q","").strip()
    number = request.args.get("number","").strip()
    page   = request.args.get("page", 1)

    if not query and not number:
        return jsonify({"data":[], "totalCount":0,
                        "hint":"Enter a Pokémon name or card number and press Enter or click Search."})
    if query and len(query) < 2:
        return jsonify({"data":[], "totalCount":0, "hint":"Type at least 2 letters for the name."})

    parts = []
    if query:
        parts.append(f'name:"{query}*"')
    if number:
        # Support comma-separated numbers: "SV107/SV122, SV108/SV122"
        raw_nums = [n.strip() for n in number.split(",") if n.strip()]
        num_parts = []
        for raw in raw_nums:
            n = raw.split("/")[0].lstrip("0") or "0"
            num_parts.append(f'number:"{n}"')
        if len(num_parts) == 1:
            parts.append(num_parts[0])
        else:
            parts.append("(" + " OR ".join(num_parts) + ")")

    lucene = " ".join(parts)
    # Skip sort for number-only lookups — it's an extra round-trip cost with no benefit
    api_params = {
        "q": lucene, "pageSize": 10, "page": page,
        "select": "id,name,number,set,images,types,subtypes,hp,rarity,tcgplayer,supertypes"
    }
    if query:
        api_params["orderBy"] = "-set.releaseDate"
    params = urllib.parse.urlencode(api_params)
    url = f"{TCG_API}/cards?{params}"
    try:
        data = tcg_get(url, ttl=CACHE_TTL_SHORT)
        return jsonify(data)
    except Exception as e:
        traceback.print_exc()
        msg = str(e)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            hint = ("The card API took too long to respond. "
                    "Try adding a Pokémon name to narrow the search, or try again in a moment.")
            return jsonify({"hint": hint, "data": [], "totalCount": 0})
        if "404" in msg:
            return jsonify({"data": [], "totalCount": 0,
                            "hint": "No cards found for that search."})
        return jsonify({"error": msg, "data": []}), 500

@app.route("/api/rarities")
@login_required
def api_rarities():
    return jsonify({"data": _STATIC_RARITIES})

# ─────────────────────────────────────────────────────────────────────────────
#  Set Completion
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/sets")
@login_required
def sets_page():
    uid  = session["user_id"]
    conn = get_db()
    # Get all unique sets in the user's collection
    owned_sets = conn.execute("""
        SELECT set_id, set_name, COUNT(*) owned_count, SUM(quantity) total_qty,
               SUM(market_price) owned_value
        FROM cards WHERE user_id=? AND set_id!='' AND set_id IS NOT NULL
        GROUP BY set_id ORDER BY set_name
    """, (uid,)).fetchall()
    pinned = conn.execute("SELECT set_id FROM set_completion WHERE user_id=? AND pinned=1",(uid,)).fetchall()
    pinned_ids = {r["set_id"] for r in pinned}
    conn.close()
    return render_template("sets.html", owned_sets=owned_sets, pinned_ids=pinned_ids,
                           username=session["username"], avatar_color=session.get("avatar_color","#3b82f6"),
                           theme=session.get("theme","dark"))

@app.route("/api/set/<set_id>/completion")
@login_required
def set_completion(set_id):
    uid = session["user_id"]
    # Fetch full set card list from TCG API (cached 24h — sets don't change)
    params = urllib.parse.urlencode({
        "q": f'set.id:"{set_id}"',
        "pageSize": 250,
        "orderBy": "number",
        "select": "id,name,number,images,rarity,tcgplayer,types"
    })
    url = f"{TCG_API}/cards?{params}"
    try:
        api_data = tcg_get(url, ttl=CACHE_TTL_LONG)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    all_cards = api_data.get("data", [])
    total_in_set = len(all_cards)

    # User's owned tcg_ids for this set
    conn = get_db()
    owned_rows = conn.execute(
        "SELECT tcg_id, quantity, market_price, condition, variant FROM cards WHERE user_id=? AND set_id=?",
        (uid, set_id)).fetchall()
    conn.close()
    owned_map = {r["tcg_id"]: dict(r) for r in owned_rows}

    owned_count = len(owned_map)
    pct = round(owned_count / total_in_set * 100, 1) if total_in_set else 0

    missing = []
    est_missing_value = 0.0
    for c in all_cards:
        if c["id"] not in owned_map:
            mkt = 0.0
            prices = c.get("tcgplayer",{}).get("prices",{})
            if prices:
                v = prices.get("holofoil") or prices.get("normal") or prices.get("reverseHolofoil") or next(iter(prices.values()), {})
                mkt = v.get("market") or v.get("mid") or 0.0
            est_missing_value += mkt
            missing.append({
                "id": c["id"], "name": c["name"], "number": c.get("number",""),
                "image": c.get("images",{}).get("small",""),
                "rarity": c.get("rarity",""), "market_price": mkt
            })

    return jsonify({
        "set_id": set_id,
        "total": total_in_set,
        "owned": owned_count,
        "pct": pct,
        "missing": missing,
        "est_missing_value": round(est_missing_value, 2)
    })

@app.route("/api/set/<set_id>/pin", methods=["POST"])
@login_required
def pin_set(set_id):
    uid  = session["user_id"]
    data = request.get_json() or {}
    conn = get_db()
    # upsert
    conn.execute("""
        INSERT INTO set_completion (user_id,set_id,set_name,pinned)
        VALUES (?,?,?,1)
        ON CONFLICT(user_id,set_id) DO UPDATE SET pinned=1, set_name=excluded.set_name
    """, (uid, set_id, data.get("set_name","")))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/set/<set_id>/unpin", methods=["POST"])
@login_required
def unpin_set(set_id):
    conn = get_db()
    conn.execute("UPDATE set_completion SET pinned=0 WHERE user_id=? AND set_id=?",
                 (session["user_id"], set_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────────────────────────────────────────
#  AI Card Scanner
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/scan")
@login_required
def scan_page():
    return render_template("scan.html", username=session["username"],
                           avatar_color=session.get("avatar_color","#3b82f6"),
                           theme=session.get("theme","dark"))

@app.route("/api/scan", methods=["POST"])
@login_required
def api_scan():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400
    img_file = request.files["image"]

    # Try to extract text from the card image using OCR
    extracted = {"name": "", "number": ""}

    # Attempt 1: EasyOCR (best for card images)
    try:
        import easyocr
        import numpy as np
        from PIL import Image
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        pil_img = Image.open(img_file.stream).convert("RGB")
        img_arr = np.array(pil_img)
        results = reader.readtext(img_arr)
        texts = [r[1] for r in results if r[2] > 0.4]
        extracted = _parse_ocr_texts(texts)
        img_file.stream.seek(0)
    except ImportError:
        pass
    except Exception as e:
        print(f"EasyOCR error: {e}")
        img_file.stream.seek(0)

    # Attempt 2: Tesseract fallback
    if not extracted["name"]:
        try:
            import pytesseract
            from PIL import Image
            pil_img = Image.open(img_file.stream)
            text = pytesseract.image_to_string(pil_img)
            texts = [t.strip() for t in text.split("\n") if t.strip()]
            extracted = _parse_ocr_texts(texts)
            img_file.stream.seek(0)
        except ImportError:
            pass
        except Exception as e:
            print(f"Tesseract error: {e}")

    if not extracted["name"]:
        return jsonify({
            "error": "Could not read card text. Try a clearer, well-lit photo.",
            "hint": "OCR libraries (easyocr or pytesseract) may not be installed. Run: pip install easyocr"
        }), 422

    # Search TCG API with extracted text
    name   = extracted["name"]
    number = extracted.get("number","")
    parts  = [f'name:"{name}*"']
    if number:
        num_part = number.split("/")[0].lstrip("0") or "0"
        parts.append(f'number:"{num_part}"')
    params = urllib.parse.urlencode({
        "q": " ".join(parts), "pageSize": 8,
        "orderBy": "-set.releaseDate",
        "select": "id,name,number,set,images,types,rarity,tcgplayer,subtypes,hp"
    })
    try:
        data = tcg_get(f"{TCG_API}/cards?{params}")
        return jsonify({"extracted": extracted, "results": data.get("data",[])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _parse_ocr_texts(texts):
    """Heuristic parser: find Pokémon name (largest/first text) and card number (NN/NNN pattern)."""
    import re
    name   = ""
    number = ""
    # Card number pattern: digits/digits or just digits at end of line
    num_re = re.compile(r'\b(\d{1,3})\s*/\s*(\d{2,3})\b')
    # HP line usually looks like "XX HP" or "HPxx"
    hp_re  = re.compile(r'\b\d{2,3}\s*HP\b', re.I)
    for t in texts:
        m = num_re.search(t)
        if m and not number:
            number = f"{m.group(1)}/{m.group(2)}"
        # Skip obvious non-name lines
        if hp_re.search(t):
            continue
        if re.match(r'^[\d\s/]+$', t):
            continue
        if len(t) < 3 or len(t) > 30:
            continue
        if not name and re.search(r'[A-Za-z]', t):
            # First plausible text line is usually the card name
            name = t.strip().title()
    return {"name": name, "number": number}

# ─────────────────────────────────────────────────────────────────────────────
#  Export / Import
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/export/csv")
@login_required
def export_csv():
    uid  = session["user_id"]
    conn = get_db()
    rows = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name","set_name","card_number","rarity","pokemon_type","condition",
                     "variant","quantity","market_price","hp","subtypes","tcg_id","notes"])
    for r in rows:
        writer.writerow([r["name"], r["set_name"], r["card_number"], r["rarity"],
                         r["pokemon_type"], r["condition"], r["variant"] or "Normal",
                         r["quantity"], r["market_price"], r["hp"], r["subtypes"],
                         r["tcg_id"], r["notes"]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()),
                     mimetype="text/csv",
                     as_attachment=True,
                     download_name=f"pokevault_{session['username']}_{datetime.now().strftime('%Y%m%d')}.csv")

@app.route("/export/json")
@login_required
def export_json():
    uid  = session["user_id"]
    conn = get_db()
    rows = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    output = json.dumps({"exported_at": datetime.now().isoformat(),
                         "username": session["username"], "cards": data}, indent=2)
    return send_file(io.BytesIO(output.encode()), mimetype="application/json",
                     as_attachment=True,
                     download_name=f"pokevault_{session['username']}_{datetime.now().strftime('%Y%m%d')}.json")

@app.route("/import", methods=["POST"])
@login_required
def import_cards():
    uid  = session["user_id"]
    f    = request.files.get("file")
    if not f:
        return jsonify({"error": "No file"}), 400
    fname = f.filename.lower()
    imported = 0
    errors   = []
    conn     = get_db()
    try:
        if fname.endswith(".json"):
            data = json.load(f)
            cards = data.get("cards", data) if isinstance(data, dict) else data
            for c in cards:
                try:
                    conn.execute("""INSERT INTO cards
                        (user_id,tcg_id,name,pokemon_type,rarity,set_name,set_id,set_series,
                         card_number,hp,subtypes,variant,condition,quantity,market_price,
                         image_small,image_large,notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid, c.get("tcg_id"), c.get("name","?"), c.get("pokemon_type"),
                         c.get("rarity"), c.get("set_name"), c.get("set_id"),
                         c.get("set_series"), c.get("card_number"), c.get("hp"),
                         c.get("subtypes"), c.get("variant","Normal"),
                         c.get("condition","Near Mint"), int(c.get("quantity",1)),
                         float(c.get("market_price",0)), c.get("image_small"),
                         c.get("image_large"), c.get("notes","")))
                    imported += 1
                except Exception as ex:
                    errors.append(str(ex))
        elif fname.endswith(".csv"):
            import csv as csv_mod
            reader = csv_mod.DictReader(io.StringIO(f.read().decode("utf-8-sig")))
            for row in reader:
                name = (row.get("name") or row.get("Name") or "").strip()
                if not name:
                    continue
                try:
                    conn.execute("""INSERT INTO cards
                        (user_id,name,pokemon_type,rarity,set_name,card_number,
                         variant,condition,quantity,market_price,notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid, name,
                         row.get("pokemon_type") or row.get("Type",""),
                         row.get("rarity") or row.get("Rarity",""),
                         row.get("set_name") or row.get("Set",""),
                         row.get("card_number") or row.get("Number",""),
                         row.get("variant","Normal"),
                         row.get("condition","Near Mint"),
                         int(row.get("quantity") or row.get("Quantity") or 1),
                         float(row.get("market_price") or row.get("Price") or 0),
                         row.get("notes","")))
                    imported += 1
                except Exception as ex:
                    errors.append(f"{name}: {ex}")
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()
    return jsonify({"imported": imported, "errors": errors[:10]})

# ─────────────────────────────────────────────────────────────────────────────
#  Wishlist / Trade / Alerts / Favorites  (unchanged logic, kept compact)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/wishlist")
@login_required
def wishlist():
    uid = session["user_id"]
    conn = get_db()
    items = conn.execute("SELECT * FROM wishlist WHERE user_id=? ORDER BY added_at DESC",(uid,)).fetchall()
    conn.close()
    return render_template("wishlist.html", items=items, username=session["username"],
                           avatar_color=session.get("avatar_color","#3b82f6"), theme=session.get("theme","dark"))

@app.route("/wishlist/add", methods=["POST"])
@login_required
def wishlist_add():
    uid=session["user_id"]; d=request.get_json() or {}
    conn=get_db()
    if not conn.execute("SELECT id FROM wishlist WHERE user_id=? AND tcg_id=?",(uid,d.get("tcg_id"))).fetchone():
        conn.execute("INSERT INTO wishlist (user_id,tcg_id,name,set_name,card_number,rarity,market_price,image_small,max_price,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid,d.get("tcg_id"),d.get("name"),d.get("set_name"),d.get("card_number"),d.get("rarity"),d.get("market_price",0),d.get("image_small"),d.get("max_price",0),d.get("notes","")))
        conn.commit()
    conn.close(); return jsonify({"success":True})

@app.route("/wishlist/delete/<int:item_id>", methods=["POST"])
@login_required
def wishlist_delete(item_id):
    conn=get_db(); conn.execute("DELETE FROM wishlist WHERE id=? AND user_id=?",(item_id,session["user_id"])); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/tradelist")
@login_required
def tradelist():
    uid=session["user_id"]; conn=get_db()
    items=conn.execute("SELECT * FROM trade_list WHERE user_id=? ORDER BY added_at DESC",(uid,)).fetchall()
    conn.close()
    return render_template("tradelist.html", items=items, username=session["username"],
                           avatar_color=session.get("avatar_color","#3b82f6"), theme=session.get("theme","dark"))

@app.route("/tradelist/add", methods=["POST"])
@login_required
def tradelist_add():
    uid=session["user_id"]; d=request.get_json() or {}; conn=get_db()
    conn.execute("INSERT INTO trade_list (user_id,tcg_id,name,set_name,card_number,rarity,condition,market_price,asking_price,image_small,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid,d.get("tcg_id"),d.get("name"),d.get("set_name"),d.get("card_number"),d.get("rarity"),d.get("condition","Near Mint"),d.get("market_price",0),d.get("asking_price",0),d.get("image_small"),d.get("notes","")))
    conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/tradelist/delete/<int:item_id>", methods=["POST"])
@login_required
def tradelist_delete(item_id):
    conn=get_db(); conn.execute("DELETE FROM trade_list WHERE id=? AND user_id=?",(item_id,session["user_id"])); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/alerts/add", methods=["POST"])
@login_required
def alert_add():
    uid=session["user_id"]; d=request.get_json() or {}; conn=get_db()
    conn.execute("INSERT INTO price_alerts (user_id,card_id,target_price,direction) VALUES (?,?,?,?)",
        (uid,d.get("card_id"),d.get("target_price"),d.get("direction","below")))
    conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/alerts/delete/<int:alert_id>", methods=["POST"])
@login_required
def alert_delete(alert_id):
    conn=get_db(); conn.execute("DELETE FROM price_alerts WHERE id=? AND user_id=?",(alert_id,session["user_id"])); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/api/alerts")
@login_required
def api_alerts():
    uid=session["user_id"]; conn=get_db()
    rows=conn.execute("SELECT pa.*,c.name,c.market_price,c.image_small FROM price_alerts pa JOIN cards c ON c.id=pa.card_id WHERE pa.user_id=? ORDER BY pa.created_at DESC",(uid,)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route("/favorite/<int:card_id>", methods=["POST"])
@login_required
def toggle_favorite(card_id):
    conn=get_db()
    conn.execute("UPDATE cards SET is_favorite=1-is_favorite WHERE id=? AND user_id=?",(card_id,session["user_id"]))
    conn.commit()
    row=conn.execute("SELECT is_favorite FROM cards WHERE id=?",(card_id,)).fetchone()
    conn.close(); return jsonify({"success":True,"is_favorite":row["is_favorite"] if row else 0})

# ─────────────────────────────────────────────────────────────────────────────
#  Collection CRUD
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/add", methods=["POST"])
@login_required
def add_card():
    uid=session["user_id"]; cards=request.get_json() or []
    if isinstance(cards,dict): cards=[cards]
    results=[]; conn=get_db()
    for d in cards:
        existing=conn.execute("SELECT id FROM cards WHERE user_id=? AND tcg_id=? AND condition=? AND variant=?",
            (uid,d.get("tcg_id"),d.get("condition","Near Mint"),d.get("variant","Normal"))).fetchone()
        if existing:
            conn.execute("UPDATE cards SET quantity=quantity+? WHERE id=?",(d.get("quantity",1),existing["id"]))
            results.append("incremented")
        else:
            conn.execute("""INSERT INTO cards
              (user_id,tcg_id,name,pokemon_type,rarity,set_name,set_id,set_series,card_number,hp,
               subtypes,variant,condition,quantity,market_price,foil_price,image_small,image_large,notes)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (uid,d.get("tcg_id"),d.get("name"),d.get("pokemon_type"),d.get("rarity"),
               d.get("set_name"),d.get("set_id"),d.get("set_series"),d.get("card_number"),d.get("hp"),
               d.get("subtypes"),d.get("variant","Normal"),d.get("condition","Near Mint"),
               d.get("quantity",1),d.get("market_price",0),d.get("foil_price",0),
               d.get("image_small"),d.get("image_large"),d.get("notes","")))
            results.append("added")
    conn.commit(); conn.close()
    return jsonify({"success":True,"results":results})

@app.route("/delete/<int:card_id>", methods=["POST"])
@login_required
def delete_card(card_id):
    conn=get_db(); conn.execute("DELETE FROM cards WHERE id=? AND user_id=?",(card_id,session["user_id"])); conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/update_quantity/<int:card_id>", methods=["POST"])
@login_required
def update_quantity(card_id):
    delta=request.get_json().get("delta",0); conn=get_db()
    conn.execute("UPDATE cards SET quantity=MAX(0,quantity+?) WHERE id=? AND user_id=?",(delta,card_id,session["user_id"]))
    conn.commit()
    row=conn.execute("SELECT quantity FROM cards WHERE id=?",(card_id,)).fetchone()
    if row and row[0]==0:
        conn.execute("DELETE FROM cards WHERE id=?",(card_id,)); conn.commit()
    conn.close(); return jsonify({"success":True})

# ─────────────────────────────────────────────────────────────────────────────
#  PWA
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "PokéVault",
        "short_name": "PokéVault",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#070b12",
        "theme_color": "#3b82f6",
        "description": "Your Pokémon card collection manager",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png",  "sizes": "512x512",  "type": "image/png"}
        ]
    })

@app.route("/sw.js")
def service_worker():
    sw_code = """
const CACHE = 'pokevault-v2';
const STATIC = ['/static/css/style.css', '/static/js/main.js'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC))));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
));
self.addEventListener('fetch', e => {
  // Never cache API responses or HTML pages — they contain live user data
  if (e.request.url.includes('/api/') ||
      e.request.mode === 'navigate' ||
      e.request.destination === 'document') return;
  // Cache-first for static assets only
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => {
    if (res.ok) { const c = res.clone(); caches.open(CACHE).then(ca => ca.put(e.request, c)); }
    return res;
  })));
});
"""
    from flask import Response
    return Response(sw_code, mimetype="application/javascript")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)