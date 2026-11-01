import asyncio
import logging
import os
import re
import zipfile
from io import BytesIO
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ATTHEME_API_URL = os.getenv("ATTHEME_API_URL", "").strip().rstrip("/")
ATTHEME_API_KEY = os.getenv("ATTHEME_API_KEY", "").strip()
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_PATH = "/" + os.getenv("WEBHOOK_PATH", "/telegram/webhook").strip().strip("/")
PORT = int(os.getenv("PORT", "10000"))
HOST = "0.0.0.0"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
API_TIMEOUT_SECONDS = 45

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("test_bot")

dp = Dispatcher()


def validate_config() -> None:
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "ATTHEME_API_URL": ATTHEME_API_URL,
        "ATTHEME_API_KEY": ATTHEME_API_KEY,
        "WEBHOOK_BASE_URL": WEBHOOK_BASE_URL,
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

    parsed = urlparse(WEBHOOK_BASE_URL)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("WEBHOOK_BASE_URL must be a valid public HTTPS URL.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET):
        raise RuntimeError("WEBHOOK_SECRET must contain 1-256 characters: A-Z, a-z, 0-9, _ or -.")
    if not ATTHEME_API_URL.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise RuntimeError("Use HTTPS for a remote ATTHEME_API_URL.")


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Salom! 👋\n"
        "Rasm yuboring — men uni ranglar bo‘yicha tahlil qilib, "
        "Telegram Android uchun .attheme faylini tayyorlayman.\n\n"
        "JPG, PNG yoki WEBP formatidagi rasm yuboring."
    )


async def get_image_from_message(message: Message) -> tuple[bytes, str] | None:
    telegram_file = None
    filename = "upload"
    if message.photo:
        telegram_file = await message.bot.get_file(message.photo[-1].file_id)
        filename = "photo.jpg"
    elif message.document:
        doc = message.document
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()
        if mime not in {"image/jpeg", "image/png", "image/webp"} and not name.endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return None
        if doc.file_size and doc.file_size > MAX_IMAGE_BYTES:
            raise ValueError("Rasm hajmi 10 MB dan oshmasligi kerak.")
        telegram_file = await message.bot.get_file(doc.file_id)
        filename = doc.file_name or "image"
    else:
        return None

    if telegram_file.file_size and telegram_file.file_size > MAX_IMAGE_BYTES:
        raise ValueError("Rasm hajmi 10 MB dan oshmasligi kerak.")

    buffer = BytesIO()
    await message.bot.download_file(telegram_file.file_path, destination=buffer)
    data = buffer.getvalue()
    if not data:
        raise ValueError("Rasmni yuklab olib bo‘lmadi.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Rasm hajmi 10 MB dan oshmasligi kerak.")
    return data, filename


@dp.message(F.photo | F.document)
async def image_handler(message: Message) -> None:
    try:
        image = await get_image_from_message(message)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    except Exception:
        logger.exception("Telegram image download failed")
        await message.answer("Rasmni yuklab olishda xatolik yuz berdi. Qayta urinib ko‘ring.")
        return

    if image is None:
        await message.answer("Iltimos, JPG, PNG yoki WEBP formatidagi rasm yuboring.")
        return

    image_bytes, filename = image
    status = await message.answer("🎨 Rasm tahlil qilinmoqda, .attheme tayyorlanmoqda...")
    headers = {"X-API-Key": ATTHEME_API_KEY}
    form = aiohttp.FormData()
    form.add_field("image", image_bytes, filename=filename, content_type="application/octet-stream")
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{ATTHEME_API_URL}/api/v1/generate", headers=headers, data=form
            ) as response:
                if response.status == 200:
                    package_data = await response.read()
                    if not package_data:
                        await status.edit_text("API bo‘sh fayl qaytardi. Keyinroq urinib ko‘ring.")
                        return
                    try:
                        with zipfile.ZipFile(BytesIO(package_data)) as package:
                            theme_data = package.read("generated_theme.attheme")
                            wallpaper_data = package.read("chat_wallpaper.jpg")
                    except (zipfile.BadZipFile, KeyError):
                        logger.exception("Theme API returned an invalid theme package")
                        await status.edit_text("API noto‘g‘ri fayl paketi qaytardi.")
                        return

                    await message.answer_document(
                        BufferedInputFile(theme_data, filename="generated_theme.attheme"),
                        caption="✅ 1/2 — Tayyor tema. Telegram Android’da ochib qo‘llang.",
                    )
                    await message.answer_document(
                        BufferedInputFile(wallpaper_data, filename="chat_wallpaper.jpg"),
                        caption="🖼 2/2 — Shu rasmni Telegram’da chat foni sifatida alohida o‘rnating.",
                    )
                    await status.delete()
                    return

                logger.warning("Attheme API returned HTTP %s", response.status)
                messages = {
                    400: "Bu rasm noto‘g‘ri yoki buzilgan. JPG, PNG yoki WEBP yuboring.",
                    401: "API kaliti noto‘g‘ri. Bot administratori sozlamalarni tekshirishi kerak.",
                    413: "Rasm hajmi juda katta. 10 MB dan kichik rasm yuboring.",
                    422: "Rasmdan ranglarni aniqlab bo‘lmadi. Boshqa rasm yuboring.",
                    429: "So‘rovlar limiti oshdi. Biroz kutib qayta urinib ko‘ring.",
                }
                await status.edit_text(messages.get(response.status, "Attheme API vaqtincha ishlamayapti."))
    except asyncio.TimeoutError:
        await status.edit_text("API javobi kechikyapti. Keyinroq urinib ko‘ring.")
    except aiohttp.ClientError:
        logger.exception("Could not connect to Attheme API")
        await status.edit_text("API serveriga ulanib bo‘lmadi. Server manzilini tekshiring.")
    except Exception:
        logger.exception("Unexpected error while generating theme")
        await status.edit_text("Kutilmagan xatolik yuz berdi. Keyinroq urinib ko‘ring.")


@dp.message()
async def fallback_handler(message: Message) -> None:
    await message.answer("Temaga aylantirish uchun menga rasm yuboring. 🙂")


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def on_startup(bot: Bot) -> None:
    webhook_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    logger.info("Telegram webhook configured at %s", webhook_url)


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()


def create_app() -> web.Application:
    validate_config()
    bot = Bot(token=BOT_TOKEN)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application(client_max_size=MAX_IMAGE_BYTES + 1024 * 1024)
    app.router.add_get("/health", health_handler)
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    return app


if __name__ == "__main__":
    application = create_app()
    web.run_app(application, host=HOST, port=PORT, access_log=logger)
