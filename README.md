# ThemeGram Attheme API — Test Bot

A small aiogram 3 test bot that accepts an image, forwards it to the standalone ThemeGram Attheme Generator API, and returns the generated `.attheme` file.

## Requirements

- Python 3.11+
- A Telegram bot token
- A running/deployed Attheme Generator API and its API key

## Setup

```bash
git clone https://github.com/cosmos634/Test-bot.git
cd Test-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set:

- `BOT_TOKEN`: token for this test bot (never commit it).
- `ATTHEME_API_URL`: API origin, e.g. `https://your-api-host.example` (without `/api/v1/generate`).
- `ATTHEME_API_KEY`: the single API key configured on the generator API server.

Run:

```bash
python bot.py
```

Send `/start` to the bot, then send a JPEG, PNG, or WEBP photo/document. The bot returns `generated_theme.attheme`.

## Notes

- The API key stays on the bot server and is never sent to Telegram users.
- Do not commit `.env`; it is ignored by Git.
- The bot does not store uploaded images. It downloads into memory and forwards bytes to the API.
- Production API URLs must use HTTPS.
- The generator API must already be deployed and reachable by this bot.

## Troubleshooting

- `401`: the API key in `.env` does not match the API server's configured key.
- `413`: the image is larger than the API's upload limit.
- `429`: wait before sending another image.
- `502/503/504`: API unavailable or timed out; check the API deployment and URL.
