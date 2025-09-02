# ARCHITECTURE
- **Pricing rules**: stagionalità (fattori), anticipo (sconti per prenotazione anticipata), ospiti extra, coupon.
- **Capacity**: contatore in memoria per demo (per ambiente produttivo usare DB).
- **API**: Flask + CORS abilitato. Da esporre dietro Gunicorn in deploy.
- **Widget**: HTML/JS che chiama `/quote` e mostra il totale.

## Note per estensioni
- Aggiungere persistenza (SQLite/Postgres) per BOOKING.
- Validare date e limiti con schema (pydantic/Marshmallow).
- Aggiungere `/cancel` e pagamenti (Stripe/PayPal) in futuro.
