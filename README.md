# ThemeGram Attheme API — Test Bot

A webhook-based aiogram 3 test bot for Render. It accepts an image, forwards it to the standalone Attheme Generator API, and returns the generated `.attheme` file. It uses an aiohttp web server and Telegram webhook — **not polling**.

## Deploy to Render

Create a **Web Service** from this repository.

- **Runtime:** Python
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`

Render sets `PORT` automatically. The app binds to `0.0.0.0` and exposes `GET /health`.

## Environment variables

Set these in Render → your service → Environment:

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | Token from BotFather for this separate test bot |
| `WEBHOOK_BASE_URL` | Public HTTPS URL of this Render service, e.g. `https://test-bot-name.onrender.com` |
| `WEBHOOK_SECRET` | Random secret for Telegram webhook request verification |
| `WEBHOOK_PATH` | Optional; default `/telegram/webhook` |
| `ATTHEME_API_URL` | Public HTTPS base URL of the Attheme API |
| `ATTHEME_API_KEY` | Must match `API_KEY` on the Attheme API service |
| `PORT` | Leave unset; Render provides it automatically |
| `LOG_LEVEL` | Optional; default `INFO` |

Generate a webhook secret locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set `WEBHOOK_BASE_URL` to the exact public URL Render assigns to this bot service. Do not add `/telegram/webhook` to the base URL; the application adds the route itself.

## Local setup

```bash
git clone https://github.com/cosmos634/Test-bot.git
cd Test-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in all required values in `.env`. For local webhook testing, Telegram still needs a publicly reachable HTTPS URL; use a secure HTTPS tunnel and set `WEBHOOK_BASE_URL` to that tunnel URL.

Run:

```bash
python bot.py
```

## How it works

1. On startup, the bot registers `WEBHOOK_BASE_URL + WEBHOOK_PATH` with Telegram.
2. Telegram sends updates to the aiohttp webhook endpoint.
3. The bot downloads the user's image into memory and checks the 10 MB limit.
4. It posts the image to `POST /api/v1/generate` with the `X-API-Key` header.
5. It sends the returned `generated_theme.attheme` document to the user.

The webhook handler validates Telegram's `X-Telegram-Bot-Api-Secret-Token` header. `GET /health` returns a simple health status for Render.

## Important

- This bot uses **webhook mode only**. Do not run `start_polling()` with the same token.
- Do not run two active deployments with the same `BOT_TOKEN`; they would overwrite the webhook URL or compete for updates.
- Use a dedicated token for this test bot, not the production ThemeGram token.
- Keep all secrets in Render environment variables or local `.env`; never commit `.env`.
- The API key remains server-side and is never shown to Telegram users.
- Use HTTPS for both public Render service URLs.
- Render free instances may sleep; first webhook requests can be delayed while the service wakes up.

## Troubleshooting

- **Telegram webhook conflict / wrong URL:** confirm only this service uses this test bot token and that `WEBHOOK_BASE_URL` is correct.
- **401 from Attheme API:** `ATTHEME_API_KEY` does not match the API server's `API_KEY`.
- **Cannot connect to API:** check `ATTHEME_API_URL` and the API service health endpoint.
- **Render says no open ports:** ensure Start Command is `python bot.py`; the app binds to `0.0.0.0:$PORT`.
- **Invalid webhook secret:** keep `WEBHOOK_SECRET` unchanged between deploys; the app registers it with Telegram at startup.
