# app.py — Sicily Pricing Engine (v1.2)
# - Flask + CORS
# - Date tolleranti (YYYY-MM-DD o DD/MM/YYYY)
# - Quote + Book
# - / and /healthz
# - Salvataggio su Postgres opzionale (DATABASE_URL)

from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

# --- DB (opzionale: si attiva se esiste DATABASE_URL) ---
engine = None
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = Flask(__name__)
CORS(app)

# ---- CONFIG PRODOTTO / LISTINI ----
ROOM_TYPES = {
    "standard": {"base_price_per_night": 70.0,  "max_guests": 2},
    "deluxe":   {"base_price_per_night": 95.0,  "max_guests": 3},
    "family":   {"base_price_per_night": 120.0, "max_guests": 4},
}

PRODUCT = {
    "id": "sicily-stay-car-01",
    "name": "Sicily Starter Pack (Alloggio + Auto)",
    "min_stay_nights": 2,
    "blackout_dates": ["2025-08-15"],
    "capacity_per_day": 5
}

# Stagionalità (fattori moltiplicativi)
SEASON_FACTORS = [
    {"from": "2025-06-01", "to": "2025-09-15", "factor": 1.25},   # alta
    {"from": "2025-12-20", "to": "2026-01-06", "factor": 1.20},   # festivo
]

# Sconti prenotazione anticipata (giorni prima del check-in)
ADVANCE_TIERS = [
    {"days": 120, "discount": 0.10},
    {"days": 60,  "discount": 0.06},
    {"days": 30,  "discount": 0.03},
]

# Coupon
COUPONS = {"WELCOME10": 0.10, "STUDENT5": 0.05}

# "DB" di capacità in memoria (demo)
BOOKINGS = defaultdict(int)  # key = "YYYY-MM-DD" -> count

# ---- UTIL ----
def parse_date(s: str):
    """Accetta 'YYYY-MM-DD' oppure 'DD/MM/YYYY'."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data non valida: '{s}'. Usa formato YYYY-MM-DD o DD/MM/YYYY")

def daterange(d1, d2):
    cur = d1
    while cur < d2:
        yield cur
        cur += timedelta(days=1)

def is_blackout(d):
    return d.strftime("%Y-%m-%d") in PRODUCT["blackout_dates"]

def season_factor(d):
    for s in SEASON_FACTORS:
        if parse_date(s["from"]) <= d <= parse_date(s["to"]):
            return s["factor"]
    return 1.0

def advance_discount(today, checkin):
    days = (checkin - today).days
    for tier in ADVANCE_TIERS:
        if days >= tier["days"]:
            return tier["discount"]
    return 0.0

def valid_capacity(d):
    return BOOKINGS[d.strftime("%Y-%m-%d")] < PRODUCT["capacity_per_day"]

def quote_price(checkin, checkout, guests, *, coupon=None, today=None, room_type="standard"):
    room_type = (room_type or "standard").lower()
    if room_type not in ROOM_TYPES:
        return (False, f"Tipologia camera non valida: {room_type}", None)

    RT = ROOM_TYPES[room_type]

    if guests < 1 or guests > RT["max_guests"]:
        return (False, f"Numero ospiti non valido per {room_type} (max {RT['max_guests']})", None)

    nights = (checkout - checkin).days
    if nights < PRODUCT["min_stay_nights"]:
        return (False, f"Soggiorno troppo breve (min {PRODUCT['min_stay_nights']} notti)", None)

    # blackout / capacità
    for d in daterange(checkin, checkout):
        if is_blackout(d):
            return (False, f"Data non disponibile: {d}", None)
        if not valid_capacity(d):
            return (False, f"Superata capacità per il giorno: {d}", None)

    # prezzo base notte * stagionalità
    total = 0.0
    for d in daterange(checkin, checkout):
        total += RT["base_price_per_night"] * season_factor(d)

    # sovrapprezzo ospiti extra (>2)
    if guests > 2:
        total *= (1 + 0.10 * (guests - 2))

    if not today:
        today = datetime.utcnow().date()
    total *= (1 - advance_discount(today, checkin))

    if coupon and coupon in COUPONS:
        total *= (1 - COUPONS[coupon])

    return (True, "ok", round(total, 2))

# ---- INIT DB (solo se DATABASE_URL presente) ----
def init_db():
    if not engine:
        return
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            booking_id VARCHAR(32) NOT NULL,
            product_id VARCHAR(64) NOT NULL,
            room_type VARCHAR(32) NOT NULL,
            checkin DATE NOT NULL,
            checkout DATE NOT NULL,
            guests INTEGER NOT NULL,
            total_price NUMERIC(10,2) NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """))

if engine:
    from sqlalchemy import text  # già importato sopra se engine
    init_db()

# ---- ROUTES ----
@app.route("/", methods=["GET"])
def root():
    return {
        "ok": True,
        "service": "sicily-pricing-engine-v1",
        "endpoints": {
            "availability": "/availability?date=YYYY-MM-DD",
            "quote": "/quote (POST)",
            "book": "/book (POST)",
            "health": "/healthz"
        }
    }, 200

@app.route("/healthz", methods=["GET"])
def health():
    return "OK", 200

@app.route("/availability", methods=["GET"])
def availability():
    date_str = request.args.get("date")
    try:
        d = parse_date(date_str)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if is_blackout(d):
        return jsonify({"ok": True, "available": False, "reason": "blackout"})
    slots = PRODUCT["capacity_per_day"] - BOOKINGS[d.strftime("%Y-%m-%d")]
    return jsonify({"ok": True, "available": slots > 0, "slots": max(0, slots)})

@app.route("/quote", methods=["POST"])
def quote():
    data = request.json or {}
    try:
        checkin  = parse_date(data["checkin"])
        checkout = parse_date(data["checkout"])
        guests   = int(data["guests"])
        coupon   = data.get("coupon")
        room_type = (data.get("room_type") or "standard").lower()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Parametri non validi: {e}"}), 400

    ok, msg, price = quote_price(checkin, checkout, guests, coupon=coupon, room_type=room_type)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    return jsonify({
        "ok": True,
        "product": PRODUCT["id"],
        "room_type": room_type,
        "nights": (checkout - checkin).days,
        "total_price": price,
        "currency": "EUR"
    })

@app.route("/book", methods=["POST"])
def book():
    data = request.json or {}
    try:
        checkin  = parse_date(data["checkin"])
        checkout = parse_date(data["checkout"])
        guests   = int(data["guests"])
        customer = data["customer"]  # {"name":..., "email":...}
        room_type = (data.get("room_type") or "standard").lower()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Parametri non validi: {e}"}), 400

    ok, msg, price = quote_price(checkin, checkout, guests, coupon=data.get("coupon"), room_type=room_type)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    # blocca capacità (demo)
    for d in daterange(checkin, checkout):
        BOOKINGS[d.strftime("%Y-%m-%d")] += 1

    booking_id = f"BK-{int(datetime.utcnow().timestamp())}"

    # salva su DB se configurato
    if engine:
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bookings
                    (booking_id, product_id, room_type, checkin, checkout, guests, total_price, customer_name, customer_email)
                    VALUES
                    (:booking_id, :product_id, :room_type, :checkin, :checkout, :guests, :total_price, :customer_name, :customer_email)
                """), dict(
                    booking_id=booking_id,
                    product_id=PRODUCT["id"],
                    room_type=room_type,
                    checkin=checkin.isoformat(),
                    checkout=checkout.isoformat(),
                    guests=guests,
                    total_price=price,
                    customer_name=customer.get("name",""),
                    customer_email=customer.get("email",""),
                ))
        except Exception as e:
            # se il DB fallisce, restituiamo errore chiaro
            return jsonify({"ok": False, "error": f"Errore salvataggio DB: {e}"}), 500

    return jsonify({
        "ok": True,
        "booking_id": booking_id,
        "product": PRODUCT["id"],
        "room_type": room_type,
        "customer": customer,
        "checkin": checkin.strftime("%Y-%m-%d"),
        "checkout": checkout.strftime("%Y-%m-%d"),
        "guests": guests,
        "total_price": price,
        "status": "reserved"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
