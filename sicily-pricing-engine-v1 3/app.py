# app.py
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from collections import defaultdict
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # abilita chiamate dal widget Wix

# ---- CONFIG "PRODOTTO" ----
PRODUCT = {
    "id": "sicily-stay-car-01",
    "name": "Sicily Starter Pack (Alloggio + Auto)",
    "base_price_per_night": 72.0,      # prezzo base
    "max_guests": 4,
    "min_stay_nights": 2,
    "blackout_dates": ["2025-08-15"],  # es. ferragosto
    "capacity_per_day": 5              # quante prenotazioni al giorno
}

# Stagionalità (fattori moltiplicativi)
SEASON_FACTORS = [
    {"from":"2025-06-01","to":"2025-09-15","factor":1.25},  # alta
    {"from":"2025-12-20","to":"2026-01-06","factor":1.20},  # festivo
]

# Sconti per anticipo prenotazione (giorni prima check-in)
ADVANCE_TIERS = [
    {"days":120,"discount":0.10},
    {"days":60, "discount":0.06},
    {"days":30, "discount":0.03},
]

# Coupon semplici
COUPONS = {
    "WELCOME10": 0.10,
    "STUDENT5": 0.05
}

# "Database" in memoria (per demo)
BOOKINGS = defaultdict(int)  # key: "YYYY-MM-DD" -> count

# ---- UTIL ----
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

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

def quote_price(checkin, checkout, guests, coupon=None, today=None):
    if guests < 1 or guests > PRODUCT["max_guests"]:
        return (False, "Numero ospiti non valido", None)

    nights = (checkout - checkin).days
    if nights < PRODUCT["min_stay_nights"]:
        return (False, "Soggiorno troppo breve", None)

    # blackout / capacity
    for d in daterange(checkin, checkout):
        if is_blackout(d):
            return (False, f"Data non disponibile: {d}", None)
        if not valid_capacity(d):
            return (False, f"Superata capacità per il giorno: {d}", None)

    # prezzo base
    total = 0.0
    for d in daterange(checkin, checkout):
        total += PRODUCT["base_price_per_night"] * season_factor(d)

    # sovrapprezzo per ospite extra (>2)
    if guests > 2:
        total *= (1 + 0.10 * (guests - 2))

    # sconto anticipo
    if not today:
        today = datetime.utcnow().date()
    total *= (1 - advance_discount(today, checkin))

    # coupon
    if coupon and coupon in COUPONS:
        total *= (1 - COUPONS[coupon])

    return (True, "ok", round(total, 2))

# ---- API ----
@app.route("/availability", methods=["GET"])
def availability():
    date = request.args.get("date")
    try:
        d = parse_date(date)
    except:
        return jsonify({"ok":False, "error":"Formato data atteso YYYY-MM-DD"}), 400
    if is_blackout(d):
        return jsonify({"ok":True, "available":False, "reason":"blackout"})
    slots = PRODUCT["capacity_per_day"] - BOOKINGS[d.strftime("%Y-%m-%d")]
    return jsonify({"ok":True, "available": slots>0, "slots": max(0, slots)})

@app.route("/quote", methods=["POST"])
def quote():
    data = request.json or {}
    try:
        checkin = parse_date(data["checkin"])
        checkout = parse_date(data["checkout"])
        guests = int(data["guests"])
    except:
        return jsonify({"ok":False,"error":"Parametri obbligatori: checkin, checkout, guests"}), 400

    coupon = data.get("coupon")
    ok, msg, price = quote_price(checkin, checkout, guests, coupon=coupon)
    if not ok:
        return jsonify({"ok":False, "error":msg}), 400
    return jsonify({
        "ok": True,
        "product": PRODUCT["id"],
        "nights": (checkout-checkin).days,
        "total_price": price,
        "currency": "EUR"
    })

@app.route("/book", methods=["POST"])
def book():
    data = request.json or {}
    try:
        checkin = parse_date(data["checkin"])
        checkout = parse_date(data["checkout"])
        guests = int(data["guests"])
        customer = data["customer"]  # {"name":..., "email":...}
    except:
        return jsonify({"ok":False,"error":"Parametri obbligatori: checkin, checkout, guests, customer"}), 400

    ok, msg, price = quote_price(checkin, checkout, guests, coupon=data.get("coupon"))
    if not ok:
        return jsonify({"ok":False, "error":msg}), 400

    # "blocca" capacità
    for d in daterange(checkin, checkout):
        BOOKINGS[d.strftime("%Y-%m-%d")] += 1

    return jsonify({
        "ok": True,
        "booking_id": f"BK-{int(datetime.utcnow().timestamp())}",
        "product": PRODUCT["id"],
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
