# ThemeGram Attheme API — Test Bot

A webhook-based aiogram 3 test bot for Render. It accepts an image, asks the user for a theme name, forwards both fields to the Attheme Generator API, and returns the generated .attheme file. It uses an aiohttp web server and Telegram webhook — not polling.

## Deploy to Render

Create a Web Service from this repository.

- Runtime: Python
- Build Command: pip install -r requirements.txt
- Start Command: python bot.py

Render sets PORT automatically. The app binds to 0.0.0.0 and exposes GET /health.

## Environment variables

Set these in Render → your service → Environment:

| Variable | Meaning |
|---|---|
| BOT_TOKEN | Token from BotFather for this separate test bot |
| WEBHOOK_BASE_URL | Public HTTPS URL of this Render service |
| WEBHOOK_SECRET | Random secret for Telegram webhook request verification |
| WEBHOOK_PATH | Optional; default /telegram/webhook |
| ATTHEME_API_URL | Public HTTPS base URL of the Attheme API; do not add /api/v1/generate |
| ATTHEME_API_KEY | Must exactly match API_KEY on the Attheme API service |
| PORT | Leave unset; Render provides it automatically |
| LOG_LEVEL | Optional; default INFO |

Generate a webhook secret locally:

    python -c "import secrets; print(secrets.token_urlsafe(32))"

Set WEBHOOK_BASE_URL to the exact public URL Render assigns to this bot service. Do not add /telegram/webhook to the base URL; the application adds the route itself.

## Local setup

    git clone https://github.com/cosmos634/Test-bot.git
    cd Test-bot
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env

Fill in all required values in .env. For local webhook testing, Telegram still needs a publicly reachable HTTPS URL; use a secure HTTPS tunnel and set WEBHOOK_BASE_URL to that tunnel URL.

Run: python bot.py

## User flow

1. User sends /start.
2. User sends a JPG, PNG, or WEBP image (maximum 10 MiB).
3. Bot asks for a theme name (maximum 80 characters).
4. User enters the name. /cancel cancels the current operation.
5. Bot sends the image and theme_name as multipart fields to POST /api/v1/generate, with the X-API-Key header.
6. API returns the generated .attheme file. The bot reads the UTF-8 filename from Content-Disposition and sends the file to the user.

The API key stays on the server and is never shown to Telegram users. The theme-name prompt uses in-memory FSM storage; pending prompts are cleared if the bot process restarts.

## Important

- This bot uses webhook mode only. Do not run start_polling() with the same token.
- Do not run two active deployments with the same BOT_TOKEN; they would overwrite the webhook URL or compete for updates.
- Use a dedicated token for this test bot, not the production ThemeGram token.
- Keep all secrets in Render environment variables or local .env; never commit .env.
- Use HTTPS for both public Render service URLs.
- Render free instances may sleep; first webhook requests can be delayed while the service wakes up.

## Troubleshooting

- Telegram webhook conflict / wrong URL: confirm only this service uses this test bot token and that WEBHOOK_BASE_URL is correct.
- 401 from Attheme API: ATTHEME_API_KEY does not match the API server's API_KEY.
- Cannot connect to API: check ATTHEME_API_URL and the API service health endpoint.
- 422 from API: the uploaded image could not be processed; try another supported image.
- 429 from API: its configured rate limit has been reached; wait before retrying.
- Render says no open ports: ensure Start Command is python bot.py; the app binds to 0.0.0.0:$PORT.
- Invalid webhook secret: keep WEBHOOK_SECRET unchanged between deploys; the app registers it with Telegram at startup.