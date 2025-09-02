# Sicily Pricing Engine (v1.0)
Micro-servizio **Availability & Dynamic Pricing** per pacchetti turistici (demo).

## Cosa fa
- Calcola disponibilità e prezzo dinamico (stagionalità, anticipo prenotazione, coupon, ospiti extra)
- API REST: `/availability` (GET), `/quote` (POST), `/book` (POST)
- Widget HTML/JS da incorporare su Wix

## Avvio rapido in locale
1. Installare Python 3.10+
2. Da terminale:
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
3. Test veloce (nuovo terminale):
   ```bash
   curl -X POST http://localhost:8000/quote \
     -H "Content-Type: application/json" \
     -d '{"checkin":"2025-09-20","checkout":"2025-09-24","guests":2}'
   ```

## Deploy (es. Render/Railway/Fly)
- Runtime: Python 3.10+
- **Start command**: `gunicorn app:app`
- Porta: usare variabile `PORT` se la piattaforma la impone (già gestita in `app.py`).
- Dipendenze: `requirements.txt`

## Embed su Wix
- Aggiungi elemento **Incorpora → HTML**.
- Incolla il contenuto di `embed.html` e sostituisci `YOUR_API_BASE` con l'URL della tua API (https://…).
- Salva e pubblica.

## Registrazione SIAE (deposito software)
Include nel pacchetto ZIP:
- `app.py`, `embed.html`, `requirements.txt`, questo `README.md`
- `ARCHITECTURE.md` (facoltativo), `CHANGELOG.md` (facoltativo)
Comprimi e deposita come “software” (opera dell’ingegno).

## Endpoint
- `GET /availability?date=YYYY-MM-DD` → `{ ok, available, slots, reason? }`
- `POST /quote` body:
  ```json
  {"checkin":"2025-09-20","checkout":"2025-09-24","guests":2,"coupon":"WELCOME10"}
  ```
  risposta: `{ ok, product, nights, total_price, currency }`
- `POST /book` body:
  ```json
  {"checkin":"2025-09-20","checkout":"2025-09-24","guests":2,"customer":{"name":"Mario","email":"m@x.it"}}
  ```
  risposta: `{ ok, booking_id, ... }`
