from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import sqlite3, os, traceback, hashlib, secrets, urllib.parse
from functools import wraps
from datetime import datetime

try:
    import requests as req_lib
    USE_REQUESTS = True
except ImportError:
    USE_REQUESTS = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
DB_PATH = "pokemon_inventory.db"
TCG_API = "https://api.pokemontcg.io/v2"
TCG_API_KEY = os.environ.get("POKEMONTCG_API_KEY", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

def tcg_headers():
    h = {"Content-Type": "application/json"}
    if TCG_API_KEY:
        h["X-Api-Key"] = TCG_API_KEY
    return h

def tcg_get(url):
    if USE_REQUESTS:
        r = req_lib.get(url, headers=tcg_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    import json as _j, urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    rq = urllib.request.Request(url, headers=tcg_headers())
    with urllib.request.urlopen(rq, timeout=10, context=ctx) as resp:
        return _j.loads(resp.read())

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

def current_user():
    if "user_id" not in session:
        return None
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return u

# ── DB Init ───────────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT NOT NULL UNIQUE,
            email     TEXT NOT NULL UNIQUE,
            password  TEXT NOT NULL,
            avatar_color TEXT DEFAULT '#3b82f6',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            tcg_id       TEXT,
            name         TEXT NOT NULL,
            pokemon_type TEXT,
            rarity       TEXT,
            set_name     TEXT,
            set_series   TEXT,
            card_number  TEXT,
            hp           TEXT,
            subtypes     TEXT,
            condition    TEXT DEFAULT 'Near Mint',
            quantity     INTEGER DEFAULT 1,
            market_price REAL DEFAULT 0.0,
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
            tcg_id       TEXT,
            name         TEXT NOT NULL,
            set_name     TEXT,
            card_number  TEXT,
            rarity       TEXT,
            market_price REAL DEFAULT 0.0,
            image_small  TEXT,
            max_price    REAL DEFAULT 0.0,
            notes        TEXT,
            added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS trade_list (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            tcg_id       TEXT,
            name         TEXT NOT NULL,
            set_name     TEXT,
            card_number  TEXT,
            rarity       TEXT,
            condition    TEXT DEFAULT 'Near Mint',
            market_price REAL DEFAULT 0.0,
            asking_price REAL DEFAULT 0.0,
            image_small  TEXT,
            notes        TEXT,
            added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS price_alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            card_id      INTEGER NOT NULL,
            target_price REAL NOT NULL,
            direction    TEXT DEFAULT 'below',
            triggered    INTEGER DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(card_id) REFERENCES cards(id)
        );
    """)
    conn.commit()
    conn.close()

# ── Auth ──────────────────────────────────────────────────────────────────────

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
            session["user_id"]   = user["id"]
            session["username"]  = user["username"]
            session["avatar_color"] = user["avatar_color"]
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
            colors = ["#3b82f6","#8b5cf6","#ec4899","#f59e0b","#10b981","#ef4444"]
            import random
            color = random.choice(colors)
            try:
                conn = get_db()
                conn.execute("INSERT INTO users (username,email,password,avatar_color) VALUES (?,?,?,?)",
                             (username, email, hash_pw(password), color))
                conn.commit()
                user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                conn.close()
                session["user_id"]     = user["id"]
                session["username"]    = user["username"]
                session["avatar_color"]= user["avatar_color"]
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "Username or email already taken."
    return render_template("register.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Main Page ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    uid  = session["user_id"]
    conn = get_db()
    cards        = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    total_cards  = conn.execute("SELECT SUM(quantity) FROM cards WHERE user_id=?", (uid,)).fetchone()[0] or 0
    total_unique = conn.execute("SELECT COUNT(*) FROM cards WHERE user_id=?", (uid,)).fetchone()[0]
    total_value  = conn.execute("SELECT SUM(market_price*quantity) FROM cards WHERE user_id=?", (uid,)).fetchone()[0] or 0
    # Dynamic rarities from user's own collection
    rarities_rows = conn.execute("SELECT DISTINCT rarity FROM cards WHERE user_id=? AND rarity IS NOT NULL AND rarity!='' ORDER BY rarity", (uid,)).fetchall()
    rarities = [r["rarity"] for r in rarities_rows]
    wishlist_count   = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id=?", (uid,)).fetchone()[0]
    tradelist_count  = conn.execute("SELECT COUNT(*) FROM trade_list WHERE user_id=?", (uid,)).fetchone()[0]
    alerts_count     = conn.execute("SELECT COUNT(*) FROM price_alerts WHERE user_id=? AND triggered=0", (uid,)).fetchone()[0]
    # Stat breakdowns
    type_stats  = conn.execute("SELECT pokemon_type, COUNT(*) as cnt FROM cards WHERE user_id=? AND pokemon_type IS NOT NULL GROUP BY pokemon_type ORDER BY cnt DESC LIMIT 6", (uid,)).fetchall()
    set_stats   = conn.execute("SELECT set_name, COUNT(*) as cnt FROM cards WHERE user_id=? AND set_name IS NOT NULL GROUP BY set_name ORDER BY cnt DESC LIMIT 5", (uid,)).fetchall()
    top_value   = conn.execute("SELECT * FROM cards WHERE user_id=? ORDER BY market_price DESC LIMIT 5", (uid,)).fetchall()
    favorites   = conn.execute("SELECT * FROM cards WHERE user_id=? AND is_favorite=1 ORDER BY created_at DESC", (uid,)).fetchall()
    conn.close()
    return render_template("index.html",
        cards=cards, total_cards=total_cards, total_unique=total_unique,
        total_value=total_value, rarities=rarities,
        wishlist_count=wishlist_count, tradelist_count=tradelist_count, alerts_count=alerts_count,
        type_stats=type_stats, set_stats=set_stats, top_value=top_value, favorites=favorites,
        username=session["username"], avatar_color=session.get("avatar_color","#3b82f6")
    )

# ── Wishlist Page ─────────────────────────────────────────────────────────────

@app.route("/wishlist")
@login_required
def wishlist():
    uid  = session["user_id"]
    conn = get_db()
    items = conn.execute("SELECT * FROM wishlist WHERE user_id=? ORDER BY added_at DESC", (uid,)).fetchall()
    conn.close()
    return render_template("wishlist.html", items=items, username=session["username"], avatar_color=session.get("avatar_color","#3b82f6"))

@app.route("/wishlist/add", methods=["POST"])
@login_required
def wishlist_add():
    uid = session["user_id"]
    d   = request.get_json() or {}
    conn = get_db()
    existing = conn.execute("SELECT id FROM wishlist WHERE user_id=? AND tcg_id=?", (uid, d.get("tcg_id"))).fetchone()
    if not existing:
        conn.execute("INSERT INTO wishlist (user_id,tcg_id,name,set_name,card_number,rarity,market_price,image_small,max_price,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, d.get("tcg_id"), d.get("name"), d.get("set_name"), d.get("card_number"),
             d.get("rarity"), d.get("market_price",0), d.get("image_small"), d.get("max_price",0), d.get("notes","")))
        conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/wishlist/delete/<int:item_id>", methods=["POST"])
@login_required
def wishlist_delete(item_id):
    conn = get_db()
    conn.execute("DELETE FROM wishlist WHERE id=? AND user_id=?", (item_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ── Trade List ────────────────────────────────────────────────────────────────

@app.route("/tradelist")
@login_required
def tradelist():
    uid  = session["user_id"]
    conn = get_db()
    items = conn.execute("SELECT * FROM trade_list WHERE user_id=? ORDER BY added_at DESC", (uid,)).fetchall()
    conn.close()
    return render_template("tradelist.html", items=items, username=session["username"], avatar_color=session.get("avatar_color","#3b82f6"))

@app.route("/tradelist/add", methods=["POST"])
@login_required
def tradelist_add():
    uid = session["user_id"]
    d   = request.get_json() or {}
    conn = get_db()
    conn.execute("INSERT INTO trade_list (user_id,tcg_id,name,set_name,card_number,rarity,condition,market_price,asking_price,image_small,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, d.get("tcg_id"), d.get("name"), d.get("set_name"), d.get("card_number"),
         d.get("rarity"), d.get("condition","Near Mint"), d.get("market_price",0),
         d.get("asking_price",0), d.get("image_small"), d.get("notes","")))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/tradelist/delete/<int:item_id>", methods=["POST"])
@login_required
def tradelist_delete(item_id):
    conn = get_db()
    conn.execute("DELETE FROM trade_list WHERE id=? AND user_id=?", (item_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ── Price Alerts ──────────────────────────────────────────────────────────────

@app.route("/alerts/add", methods=["POST"])
@login_required
def alert_add():
    uid = session["user_id"]
    d   = request.get_json() or {}
    conn = get_db()
    conn.execute("INSERT INTO price_alerts (user_id,card_id,target_price,direction) VALUES (?,?,?,?)",
        (uid, d.get("card_id"), d.get("target_price"), d.get("direction","below")))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/alerts/delete/<int:alert_id>", methods=["POST"])
@login_required
def alert_delete(alert_id):
    conn = get_db()
    conn.execute("DELETE FROM price_alerts WHERE id=? AND user_id=?", (alert_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/alerts")
@login_required
def api_alerts():
    uid = session["user_id"]
    conn = get_db()
    alerts = conn.execute("""
        SELECT pa.*, c.name, c.market_price, c.image_small FROM price_alerts pa
        JOIN cards c ON c.id = pa.card_id
        WHERE pa.user_id=? ORDER BY pa.created_at DESC
    """, (uid,)).fetchall()
    conn.close()
    return jsonify([dict(a) for a in alerts])

# ── Favorites toggle ──────────────────────────────────────────────────────────

@app.route("/favorite/<int:card_id>", methods=["POST"])
@login_required
def toggle_favorite(card_id):
    conn = get_db()
    conn.execute("UPDATE cards SET is_favorite = 1 - is_favorite WHERE id=? AND user_id=?",
                 (card_id, session["user_id"]))
    conn.commit()
    row = conn.execute("SELECT is_favorite FROM cards WHERE id=?", (card_id,)).fetchone()
    conn.close()
    return jsonify({"success": True, "is_favorite": row["is_favorite"] if row else 0})

# ── TCG API proxy ─────────────────────────────────────────────────────────────

@app.route("/api/search")
@login_required
def api_search():
    query = request.args.get("q","").strip()
    number = request.args.get("number","").strip()
    page  = request.args.get("page", 1)
    if not query and not number:
        return jsonify({"data": [], "totalCount": 0})

    # Build flexible Lucene query
    parts = []
    if query:
        parts.append(f'name:"{query}*"')
    if number:
        parts.append(f'number:"{number}"')
    lucene = " ".join(parts)

    params = urllib.parse.urlencode({
        "q": lucene,
        "pageSize": 24,
        "page": page,
        "orderBy": "-set.releaseDate"
    })
    url = f"{TCG_API}/cards?{params}"
    try:
        data = tcg_get(url)
        return jsonify(data)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "data": []}), 500

@app.route("/api/rarities")
@login_required
def api_rarities():
    """Fetch all rarities available in the TCG API."""
    try:
        data = tcg_get(f"{TCG_API}/rarities")
        return jsonify(data)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"data": []}), 500

# ── Collection CRUD ───────────────────────────────────────────────────────────

@app.route("/add", methods=["POST"])
@login_required
def add_card():
    uid = session["user_id"]
    cards = request.get_json() or []
    if isinstance(cards, dict):
        cards = [cards]
    results = []
    conn = get_db()
    for d in cards:
        existing = conn.execute("SELECT id FROM cards WHERE user_id=? AND tcg_id=? AND condition=?",
                                (uid, d.get("tcg_id"), d.get("condition","Near Mint"))).fetchone()
        if existing:
            conn.execute("UPDATE cards SET quantity=quantity+? WHERE id=?", (d.get("quantity",1), existing["id"]))
            results.append("incremented")
        else:
            conn.execute("""INSERT INTO cards
              (user_id,tcg_id,name,pokemon_type,rarity,set_name,set_series,card_number,hp,
               subtypes,condition,quantity,market_price,image_small,image_large,notes)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (uid, d.get("tcg_id"), d.get("name"), d.get("pokemon_type"), d.get("rarity"),
               d.get("set_name"), d.get("set_series"), d.get("card_number"), d.get("hp"),
               d.get("subtypes"), d.get("condition","Near Mint"), d.get("quantity",1),
               d.get("market_price",0), d.get("image_small"), d.get("image_large"), d.get("notes","")))
            results.append("added")
    conn.commit()
    conn.close()
    return jsonify({"success": True, "results": results})

@app.route("/delete/<int:card_id>", methods=["POST"])
@login_required
def delete_card(card_id):
    conn = get_db()
    conn.execute("DELETE FROM cards WHERE id=? AND user_id=?", (card_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/update_quantity/<int:card_id>", methods=["POST"])
@login_required
def update_quantity(card_id):
    delta = request.get_json().get("delta", 0)
    conn  = get_db()
    conn.execute("UPDATE cards SET quantity=MAX(0,quantity+?) WHERE id=? AND user_id=?",
                 (delta, card_id, session["user_id"]))
    conn.commit()
    row = conn.execute("SELECT quantity FROM cards WHERE id=?", (card_id,)).fetchone()
    if row and row[0] == 0:
        conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        conn.commit()
    conn.close()
    return jsonify({"success": True})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
