"""
=============================================================================
  🇲🇦 Mazouty — Backend API (Production)
  GasBuddy pour le Maroc
  Stack : FastAPI + SQLite + JWT Auth
=============================================================================
"""

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import sqlite3
import os
import uuid
import math
import shutil

# ─────────────────────────────────────────────
# CONFIGURATION (variables d'environnement)
# ─────────────────────────────────────────────

SECRET_KEY = os.environ.get("SECRET_KEY", "mazouty-change-this-in-production-please")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
DATABASE = os.environ.get("DATABASE_PATH", "mazouty.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")
DOMAIN = os.environ.get("DOMAIN", "mazouty.site")
POINTS_NEW_PRICE = 10
POINTS_CORRECTION = 15
POINTS_CONFIRMATION = 5
MAX_CONFIRMATIONS = 5

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────

app = FastAPI(
    title="Mazouty API",
    description="GasBuddy pour le Maroc — Prix de carburant communautaires",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"https://{DOMAIN}",
        f"https://www.{DOMAIN}",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

FRONTEND_DIR = "frontend"
if os.path.exists(FRONTEND_DIR):
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def create_token(user_id: int, username: str):
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(
    token: str = Depends(oauth2_scheme), db: sqlite3.Connection = Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return dict(user)


# ─────────────────────────────────────────────
# MODÈLES
# ─────────────────────────────────────────────

class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class PriceSubmit(BaseModel):
    station_id: int
    fuel_type: str
    price: float
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class PriceCorrection(BaseModel):
    price_id: int
    new_price: float


# ─────────────────────────────────────────────
# BASE DE DONNÉES
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            contributions_count INTEGER DEFAULT 0,
            corrections_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT UNIQUE,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            address TEXT,
            city TEXT DEFAULT 'Casablanca',
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            phone TEXT,
            website TEXT,
            rating REAL,
            user_ratings_total INTEGER,
            business_status TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS fuel_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id INTEGER NOT NULL,
            fuel_type TEXT NOT NULL CHECK(fuel_type IN ('gasoil', 'sp95', 'gpl')),
            price REAL NOT NULL CHECK(price > 0 AND price < 30),
            user_id INTEGER NOT NULL,
            contributed_at TEXT DEFAULT (datetime('now')),
            photo_url TEXT,
            latitude REAL,
            longitude REAL,
            is_correction INTEGER DEFAULT 0,
            corrects_price_id INTEGER,
            confirmed_count INTEGER DEFAULT 0,
            FOREIGN KEY (station_id) REFERENCES stations(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (corrects_price_id) REFERENCES fuel_prices(id)
        );
        CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            confirmed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (price_id) REFERENCES fuel_prices(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(price_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            user_id INTEGER PRIMARY KEY,
            subscription_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_stations_brand ON stations(brand);
        CREATE INDEX IF NOT EXISTS idx_stations_city ON stations(city);
        CREATE INDEX IF NOT EXISTS idx_stations_coords ON stations(latitude, longitude);
        CREATE INDEX IF NOT EXISTS idx_prices_station ON fuel_prices(station_id);
        CREATE INDEX IF NOT EXISTS idx_prices_date ON fuel_prices(contributed_at);
        CREATE INDEX IF NOT EXISTS idx_users_points ON users(points DESC);
    """)
    conn.close()

init_db()


# ─────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_latest_prices(db, station_id):
    prices = {}
    for fuel_type in ["gasoil", "sp95", "gpl"]:
        row = db.execute(
            """SELECT fp.id, fp.price, fp.contributed_at, u.username, fp.photo_url, fp.confirmed_count
            FROM fuel_prices fp JOIN users u ON fp.user_id = u.id
            WHERE fp.station_id = ? AND fp.fuel_type = ?
            ORDER BY fp.contributed_at DESC LIMIT 1""",
            (station_id, fuel_type),
        ).fetchone()
        if row:
            updated = row["contributed_at"]
            try:
                updated_dt = datetime.strptime(updated[:19], "%Y-%m-%d %H:%M:%S")
                age_hours = (datetime.utcnow() - updated_dt).total_seconds() / 3600
                freshness = "fresh" if age_hours < 24 else "recent" if age_hours < 168 else "old"
            except:
                freshness = "unknown"
            prices[fuel_type] = {
                "price_id": row["id"],
                "price": row["price"],
                "updated": updated,
                "by": row["username"],
                "photo": row["photo_url"],
                "confirmations": row["confirmed_count"],
                "freshness": freshness,
            }
    return prices if prices else None


# ─────────────────────────────────────────────
# REDIRECT / → /app
# ─────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return RedirectResponse(url="/app")


@app.get("/api/info", tags=["Info"])
def api_info():
    return {"name": "Mazouty API", "version": "2.0.0", "docs": "/docs"}


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.post("/auth/register", tags=["Auth"])
def register(user: UserRegister, db: sqlite3.Connection = Depends(get_db)):
    existing = db.execute(
        "SELECT id FROM users WHERE username = ? OR email = ?",
        (user.username, user.email),
    ).fetchone()
    if existing:
        raise HTTPException(400, "Ce nom d'utilisateur ou email existe déjà")
    if len(user.password) < 6:
        raise HTTPException(400, "Le mot de passe doit faire au moins 6 caractères")
    password_hash = pwd_context.hash(user.password)
    cursor = db.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        (user.username, user.email, password_hash),
    )
    db.commit()
    user_id = cursor.lastrowid
    token = create_token(user_id, user.username)
    return {"message": "Compte créé", "token": token, "user": {"id": user_id, "username": user.username, "points": 0}}


@app.post("/auth/login", tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT * FROM users WHERE username = ?", (form.username,)).fetchone()
    if not user or not pwd_context.verify(form.password, user["password_hash"]):
        raise HTTPException(401, "Nom d'utilisateur ou mot de passe incorrect")
    token = create_token(user["id"], user["username"])
    return {"access_token": token, "token_type": "bearer", "user": {"id": user["id"], "username": user["username"], "points": user["points"]}}


@app.get("/auth/me", tags=["Auth"])
def get_me(user: dict = Depends(get_current_user)):
    return {k: user[k] for k in ["id", "username", "email", "points", "contributions_count", "corrections_count", "created_at"]}


# ─────────────────────────────────────────────
# STATIONS
# ─────────────────────────────────────────────

@app.get("/stations", tags=["Stations"])
def list_stations(brand: Optional[str] = None, city: Optional[str] = None, limit: int = Query(50, le=200), offset: int = 0, db: sqlite3.Connection = Depends(get_db)):
    query = "SELECT * FROM stations WHERE 1=1"
    params = []
    if brand:
        query += " AND brand = ?"; params.append(brand)
    if city:
        query += " AND city LIKE ?"; params.append(f"%{city}%")
    query += " ORDER BY brand, name LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = db.execute(query, params).fetchall()
    stations = []
    for row in rows:
        station = dict(row)
        station["latest_prices"] = get_latest_prices(db, row["id"])
        stations.append(station)
    total = db.execute("SELECT COUNT(*) as c FROM stations WHERE 1=1" + (" AND brand = ?" if brand else "") + (" AND city LIKE ?" if city else ""), ([brand] if brand else []) + ([f"%{city}%"] if city else [])).fetchone()["c"]
    return {"total": total, "stations": stations}


@app.get("/stations/nearby", tags=["Stations"])
def nearby_stations(lat: float, lon: float, radius_km: float = Query(5, le=50), limit: int = Query(20, le=50), sort_by: str = Query("distance"), brand: Optional[str] = None, db: sqlite3.Connection = Depends(get_db)):
    if sort_by not in ("distance", "price_gasoil", "price_sp95"):
        sort_by = "distance"
    delta_lat = radius_km / 111.32
    delta_lon = radius_km / (111.32 * math.cos(math.radians(lat)))
    query = "SELECT * FROM stations WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?"
    params = [lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon]
    if brand:
        query += " AND brand = ?"; params.append(brand)
    rows = db.execute(query, params).fetchall()
    stations = []
    for row in rows:
        dist = haversine(lat, lon, row["latitude"], row["longitude"])
        if dist <= radius_km:
            station = dict(row)
            station["distance_km"] = round(dist, 2)
            station["latest_prices"] = get_latest_prices(db, row["id"])
            stations.append(station)
    if sort_by == "price_gasoil":
        stations.sort(key=lambda s: s.get("latest_prices", {}).get("gasoil", {}).get("price", 999) if s.get("latest_prices") else 999)
    elif sort_by == "price_sp95":
        stations.sort(key=lambda s: s.get("latest_prices", {}).get("sp95", {}).get("price", 999) if s.get("latest_prices") else 999)
    else:
        stations.sort(key=lambda s: s["distance_km"])
    return {"count": len(stations[:limit]), "stations": stations[:limit]}


@app.get("/stations/{station_id}", tags=["Stations"])
def get_station(station_id: int, db: sqlite3.Connection = Depends(get_db)):
    station = db.execute("SELECT * FROM stations WHERE id = ?", (station_id,)).fetchone()
    if not station:
        raise HTTPException(404, "Station introuvable")
    result = dict(station)
    result["latest_prices"] = get_latest_prices(db, station_id)
    history = db.execute("SELECT fp.*, u.username FROM fuel_prices fp JOIN users u ON fp.user_id = u.id WHERE fp.station_id = ? ORDER BY fp.contributed_at DESC LIMIT 20", (station_id,)).fetchall()
    result["price_history"] = [dict(h) for h in history]
    return result


@app.get("/stations/brands/list", tags=["Stations"])
def list_brands(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT brand, COUNT(*) as count FROM stations GROUP BY brand ORDER BY count DESC").fetchall()
    return [{"brand": r["brand"], "count": r["count"]} for r in rows]


# ─────────────────────────────────────────────
# PRIX
# ─────────────────────────────────────────────

@app.post("/prices", tags=["Prix"])
def submit_price(price_data: PriceSubmit, user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    station = db.execute("SELECT id FROM stations WHERE id = ?", (price_data.station_id,)).fetchone()
    if not station: raise HTTPException(404, "Station introuvable")
    if price_data.fuel_type not in ("gasoil", "sp95", "gpl"): raise HTTPException(400, "Type invalide")
    if price_data.price <= 0 or price_data.price > 30: raise HTTPException(400, "Prix invalide")
    cursor = db.execute("INSERT INTO fuel_prices (station_id, fuel_type, price, user_id, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?)",
        (price_data.station_id, price_data.fuel_type, price_data.price, user["id"], price_data.latitude, price_data.longitude))
    db.execute("UPDATE users SET points = points + ?, contributions_count = contributions_count + 1 WHERE id = ?", (POINTS_NEW_PRICE, user["id"]))
    db.commit()
    return {"message": f"Prix enregistré ! +{POINTS_NEW_PRICE} points", "price_id": cursor.lastrowid, "points_earned": POINTS_NEW_PRICE, "new_total_points": user["points"] + POINTS_NEW_PRICE}


@app.post("/prices/{price_id}/photo", tags=["Prix"])
async def upload_price_photo(price_id: int, photo: UploadFile = File(...), user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    price_row = db.execute("SELECT * FROM fuel_prices WHERE id = ? AND user_id = ?", (price_id, user["id"])).fetchone()
    if not price_row: raise HTTPException(404, "Prix introuvable")
    ext = photo.filename.split(".")[-1] if "." in photo.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    db.execute("UPDATE fuel_prices SET photo_url = ? WHERE id = ?", (f"/uploads/{filename}", price_id))
    db.commit()
    return {"message": "Photo ajoutée", "photo_url": f"/uploads/{filename}"}


@app.post("/prices/correct", tags=["Prix"])
def correct_price(correction: PriceCorrection, user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    original = db.execute("SELECT * FROM fuel_prices WHERE id = ?", (correction.price_id,)).fetchone()
    if not original: raise HTTPException(404, "Prix introuvable")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not original["contributed_at"].startswith(today): raise HTTPException(400, "Correction du jour uniquement")
    if original["user_id"] == user["id"]: raise HTTPException(400, "Pas votre propre prix")
    if correction.new_price <= 0 or correction.new_price > 30: raise HTTPException(400, "Prix invalide")
    cursor = db.execute("INSERT INTO fuel_prices (station_id, fuel_type, price, user_id, is_correction, corrects_price_id) VALUES (?, ?, ?, ?, 1, ?)",
        (original["station_id"], original["fuel_type"], correction.new_price, user["id"], correction.price_id))
    db.execute("UPDATE users SET points = points + ?, corrections_count = corrections_count + 1 WHERE id = ?", (POINTS_CORRECTION, user["id"]))
    db.commit()
    return {"message": f"Correction ! +{POINTS_CORRECTION} points", "price_id": cursor.lastrowid, "points_earned": POINTS_CORRECTION}


@app.post("/prices/{price_id}/confirm", tags=["Prix"])
def confirm_price(price_id: int, user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    price_row = db.execute("SELECT * FROM fuel_prices WHERE id = ?", (price_id,)).fetchone()
    if not price_row: raise HTTPException(404, "Prix introuvable")
    if price_row["user_id"] == user["id"]: raise HTTPException(400, "Pas votre propre prix")
    if price_row["confirmed_count"] >= MAX_CONFIRMATIONS: raise HTTPException(400, "Maximum de confirmations atteint")
    existing = db.execute("SELECT id FROM confirmations WHERE price_id = ? AND user_id = ?", (price_id, user["id"])).fetchone()
    if existing: raise HTTPException(400, "Déjà confirmé")
    db.execute("INSERT INTO confirmations (price_id, user_id) VALUES (?, ?)", (price_id, user["id"]))
    db.execute("UPDATE fuel_prices SET confirmed_count = confirmed_count + 1 WHERE id = ?", (price_id,))
    db.execute("UPDATE users SET points = points + ? WHERE id = ?", (POINTS_CONFIRMATION, user["id"]))
    db.commit()
    return {"message": f"Confirmé ! +{POINTS_CONFIRMATION} points", "points_earned": POINTS_CONFIRMATION, "new_confirmed_count": price_row["confirmed_count"] + 1}


@app.get("/prices/recent", tags=["Prix"])
def recent_prices(limit: int = Query(20, le=100), fuel_type: Optional[str] = None, db: sqlite3.Connection = Depends(get_db)):
    query = "SELECT fp.*, s.name as station_name, s.brand, s.address, u.username FROM fuel_prices fp JOIN stations s ON fp.station_id = s.id JOIN users u ON fp.user_id = u.id"
    params = []
    if fuel_type: query += " WHERE fp.fuel_type = ?"; params.append(fuel_type)
    query += " ORDER BY fp.contributed_at DESC LIMIT ?"; params.append(limit)
    return [dict(r) for r in db.execute(query, params).fetchall()]


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

@app.post("/notifications/subscribe", tags=["Notifications"])
def subscribe_notifications(subscription: dict, user: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    import json as json_module
    db.execute("INSERT OR REPLACE INTO push_subscriptions (user_id, subscription_json) VALUES (?, ?)", (user["id"], json_module.dumps(subscription)))
    db.commit()
    return {"message": "Notifications activées"}


# ─────────────────────────────────────────────
# CLASSEMENT & STATS
# ─────────────────────────────────────────────

@app.get("/leaderboard", tags=["Classement"])
def leaderboard(limit: int = Query(20, le=100), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT username, points, contributions_count, corrections_count FROM users WHERE contributions_count > 0 ORDER BY points DESC LIMIT ?", (limit,)).fetchall()
    return [{"rank": i + 1, "username": r["username"], "points": r["points"], "contributions": r["contributions_count"], "corrections": r["corrections_count"]} for i, r in enumerate(rows)]


@app.get("/stats", tags=["Stats"])
def global_stats(db: sqlite3.Connection = Depends(get_db)):
    return {
        "total_stations": db.execute("SELECT COUNT(*) as c FROM stations").fetchone()["c"],
        "total_prices": db.execute("SELECT COUNT(*) as c FROM fuel_prices").fetchone()["c"],
        "prices_today": db.execute("SELECT COUNT(*) as c FROM fuel_prices WHERE contributed_at >= date('now')").fetchone()["c"],
        "total_users": db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"],
        "brands": [{"brand": b["brand"], "count": b["c"]} for b in db.execute("SELECT brand, COUNT(*) as c FROM stations GROUP BY brand ORDER BY c DESC").fetchall()],
    }
