# app.py — Sicily Pricing Engine (v1.3)
# - Endpoints per widget Wix: /availability, /quote, /book
# - Route di cortesia: / e /healthz
# - Postgres opzionale (DATABASE_URL)
# - Email opzionali via SendGrid (SENDGRID_API_KEY, NOTIFY_EMAIL)
# - Date tolleranti: "YYYY-MM-DD" o "DD/MM/YYYY"

from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

# ---------------------------
#  Opzioni / Integrazioni
# ---------------------------
DATABASE_URL    = os.getenv("DATABASE_URL")        # es. postgres://...
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")   # opzionale
NOTIFY_EMAIL     = os.getenv("NOTIFY_EMAIL")       # opzionale (mittente/destinatario)
ADMIN_TOKEN      = os.getenv("ADMIN_TOKEN", "")    # opzionale per endpoint admin

# DB opzionale (SQLAlchemy) — attivo solo se DATABASE_URL presente
engine = None
if DATABASE_URL:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Email opzionale (SendGrid) — attivo solo se API key + email presenti
import requests
def send_booking_email(booking_dict: dict):
    """
    Invia email best-effort. Se SENDGRID_API_KEY o NOTIFY_EMAIL mancano, esce senza fare nulla.
    Puoi attivarla in futuro impostando le variabili d'ambiente su Render.
    """
    if not (SENDGRID_API_KEY and NOTIFY_EMAIL):
        return  # email disabilitata

    subject = f"Nuova prenotazione {booking_dict['booking_id']} - {booking_dict['customer']['name']}"
    lines = [
        "Nuova prenotazione ricevuta:",
        f"Booking ID: {booking_dict['booking_id']}",
        f"Prodotto: {booking_dict['product']} | Camera: {booking_dict['room_type']}",
        f"Check-in: {booking_dict['checkin']} | Check-out: {booking_dict['checkout']}",
        f"Ospiti: {booking_dict['guests']}",
        f"Totale: € {booking_dict['total_price']}",
        f"Cliente: {booking_dict['customer']['name']} <{booking_dict['customer']['email']}>",
    ]
    payload = {
        "personalizations": [{
            "to": [{"email": NOTIFY_EMAIL}],
            "subject": subject
        }],
        "from": {"email": NOTIFY_EMAIL},
        "content": [{"type": "text/plain", "value": "\n".join(lines)}]
    }
    # copia al cliente (se c'è)
    customer_email = booking_dict.get("customer", {}).get("email")
    if customer_email:
        payload["personalizations"][0].setdefault("cc", []).append({"email": customer_email})

    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload, timeout=10
        )
        r.raise_for_status()
    except Exception as e:
        # non blocchiamo la prenotazione per un problema email
        app.logger.warning(f"SendGrid error: {e}")

app = Flask(__name__)
CORS(app)

# ---------------------------
#  Config prezzi / prodotto
# ---------------------------
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

SEASON_FACTORS = [
    {"from": "2025-06-01", "to": "2025-09-15", "factor": 1.25},   # alta
    {"from": "2025-12-20", "to": "2026-01-06", "factor": 1.20},   # festivo
]

ADVANCE_TIERS = [
    {"days": 120, "discount": 0.10},
    {"days": 60,  "discount": 0.06},
    {"days": 30,  "discount": 0.03},
]

COUPONS = {"WELCOME10": 0.10, "STUDENT5": 0.05}

# Capacità in memoria (demo); il DB salva solo le prenotazioni
BOOKINGS = defaultdict(int)  # key = "YYYY-MM-DD" -> count

# ---------------------------
#  Util
# ---------------------------
def parse_date(s: str):
    """Accetta 'YYYY-MM-DD' o 'DD/MM/YYYY' e ritorna date()."""
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

def is_blackout(d): return d.strftime("%Y-%m-%d") in PRODUCT["blackout_dates"]

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
        return (False, f"Ospiti non validi per {room_type} (max {RT['max_guests']})", None)

    nights = (checkout - checkin).days
    if nights < PRODUCT["min_stay_nights"]:
        return (False, f"Soggiorno minimo {PRODUCT['min_stay_nights']} notti", None)

    for d in daterange(checkin, checkout):
        if is_blackout(d):        return (False, f"Data non disponibile: {d}", None)
        if not valid_capacity(d): return (False, f"Capacità esaurita nel giorno: {d}", None)

    total = 0.0
    for d in daterange(checkin, checkout):
        total += RT["base_price_per_night"] * season_factor(d)

    if guests > 2:
        total *= (1 + 0.10 * (guests - 2))  # +10% per ospite oltre 2

    if not today:
        today = datetime.utcnow().date()
    total *= (1 - advance_discount(today, checkin))

    if coupon and coupon in COUPONS:
        total *= (1 - COUPONS[coupon])

    return (True, "ok", round(total, 2))

# ---------------------------
#  Init DB (se disponibile)
# ---------------------------
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
    from sqlalchemy import text  # import qui per sicurezza
    init_db()

# ---------------------------
#  Routes pubbliche
# ---------------------------
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
        checkin   = parse_date(data["checkin"])
        checkout  = parse_date(data["checkout"])
        guests    = int(data["guests"])
        coupon    = data.get("coupon")
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
        checkin   = parse_date(data["checkin"])
        checkout  = parse_date(data["checkout"])
        guests    = int(data["guests"])
        customer  = data["customer"]  # {"name":..., "email":...}
        room_type = (data.get("room_type") or "standard").lower()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Parametri non validi: {e}"}), 400

    ok, msg, price = quote_price(checkin, checkout, guests, coupon=data.get("coupon"), room_type=room_type)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    # blocco capacità (demo in memoria)
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
            return jsonify({"ok": False, "error": f"Errore salvataggio DB: {e}"}), 500

    # risposta standard
    response = {
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
    }

    # email best-effort (non blocca la prenotazione se fallisce)
    try:
        send_booking_email(response)
    except Exception as e:
        app.logger.warning(f"Email error: {e}")

    return jsonify(response)

# ---------------------------
#  Endpoint admin (opzionali)
# ---------------------------
def _is_admin(req): return bool(ADMIN_TOKEN) and req.args.get("token") == ADMIN_TOKEN

@app.route("/admin/bookings", methods=["GET"])
def admin_bookings():
    if not _is_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    if not engine:
        return jsonify({"ok": True, "db": False, "note": "DB non configurato",
                        "bookings_sample": list(BOOKINGS.items())[:10]})
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT booking_id, product_id, room_type, checkin, checkout, guests,
                   total_price, customer_name, customer_email, created_at
            FROM bookings
            ORDER BY created_at DESC
            LIMIT 200
        """)).mappings().all()
    return jsonify({"ok": True, "count": len(rows), "items": [dict(r) for r in rows]})

@app.route("/admin/export.csv", methods=["GET"])
def admin_export_csv():
    if not _is_admin(request):
        return "Unauthorized", 403
    if not engine:
        return "DB non configurato", 400
    import csv, io
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT booking_id, product_id, room_type, checkin, checkout, guests,
                   total_price, customer_name, customer_email, created_at
            FROM bookings
            ORDER BY created_at DESC
        """)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["booking_id","product_id","room_type","checkin","checkout","guests",
                "total_price","customer_name","customer_email","created_at"])
    w.writerows(rows)
    return buf.getvalue(), 200, {"Content-Type": "text/csv; charset=utf-8"}

# ---------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
