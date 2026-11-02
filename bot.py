import asyncio
import logging
import os
import re
from io import BytesIO
from urllib.parse import unquote, urlparse

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
MAX_THEME_NAME_LENGTH = 80
API_TIMEOUT_SECONDS = 60

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("test_bot")

dp = Dispatcher(storage=MemoryStorage())


class ThemeFlow(StatesGroup):
    waiting_for_name = State()


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
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Salom! 👋\n"
        "Rasm yuboring — men uning ranglarini tahlil qilib, "
        "Telegram Android uchun .attheme faylini yarataman.\n\n"
        "JPG, PNG yoki WEBP formatidagi rasm yuboring. "
        "Keyin undan tema nomini so‘rayman."
    )


@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Jarayon bekor qilindi. Yangi rasm yuborishingiz mumkin.")


async def get_image_from_message(message: Message) -> tuple[bytes, str] | None:
    telegram_file = None
    filename = "photo.jpg"

    if message.photo:
        telegram_file = await message.bot.get_file(message.photo[-1].file_id)
    elif message.document:
        doc = message.document
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()
        allowed_names = (".jpg", ".jpeg", ".png", ".webp")
        if mime not in {"image/jpeg", "image/png", "image/webp"} and not name.endswith(allowed_names):
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
    image_bytes = buffer.getvalue()

    if not image_bytes:
        raise ValueError("Rasmni yuklab olib bo‘lmadi.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Rasm hajmi 10 MB dan oshmasligi kerak.")

    return image_bytes, filename


def get_response_filename(content_disposition: str | None) -> str:
    if content_disposition:
        match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
        if match:
            filename = unquote(match.group(1)).strip().strip('"')
            if filename.lower().endswith(".attheme"):
                return filename
    return "generated_theme.attheme"


async def generate_theme(
    image_bytes: bytes,
    image_filename: str,
    theme_name: str,
) -> tuple[bytes, str]:
    headers = {"X-API-Key": ATTHEME_API_KEY}
    form = aiohttp.FormData()
    form.add_field(
        "image",
        image_bytes,
        filename=image_filename,
        content_type="application/octet-stream",
    )
    # This field is part of the API's multipart/form-data contract.
    form.add_field("theme_name", theme_name)

    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{ATTHEME_API_URL}/api/v1/generate",
            headers=headers,
            data=form,
        ) as response:
            if response.status != 200:
                logger.warning("Attheme API returned HTTP %s", response.status)
                error_messages = {
                    400: "Rasm formati noto‘g‘ri yoki fayl buzilgan. JPG, PNG yoki WEBP yuboring.",
                    401: "API kaliti noto‘g‘ri. Administrator ATTHEME_API_KEY sozlamasini tekshirishi kerak.",
                    413: "Rasm hajmi API limitidan oshdi. 10 MB dan kichik rasm yuboring.",
                    422: "Rasmni tema ranglariga aylantirib bo‘lmadi. Boshqa rasm yuboring.",
                    429: "API so‘rovlar limiti tugadi. Bir daqiqadan keyin qayta urinib ko‘ring.",
                    500: "API ichki xatolikka uchradi. Keyinroq urinib ko‘ring.",
                }
                raise RuntimeError(error_messages.get(
                    response.status,
                    f"Attheme API xatolik qaytardi (HTTP {response.status}).",
                ))

            theme_bytes = await response.read()
            if not theme_bytes:
                raise RuntimeError("API bo‘sh .attheme fayl qaytardi.")

            filename = get_response_filename(
                response.headers.get("Content-Disposition")
            )
            return theme_bytes, filename


@dp.message(F.photo | F.document)
async def image_handler(message: Message, state: FSMContext) -> None:
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
    await state.update_data(image_bytes=image_bytes, image_filename=filename)
    await state.set_state(ThemeFlow.waiting_for_name)
    await message.answer(
        "📝 Rasm qabul qilindi. Endi tema uchun nom yozing.\n"
        "Masalan: My Purple Theme yoki Тёмная ночь\n\n"
        "Nom 80 ta belgidan oshmasin. Bekor qilish: /cancel"
    )


@dp.message(ThemeFlow.waiting_for_name, F.text)
async def theme_name_handler(message: Message, state: FSMContext) -> None:
    theme_name = (message.text or "").strip()
    if not theme_name:
        await message.answer("Tema nomini yozing yoki /cancel yuboring.")
        return
    if len(theme_name) > MAX_THEME_NAME_LENGTH:
        await message.answer("Tema nomi 80 ta belgidan oshmasligi kerak. Qisqaroq nom kiriting.")
        return

    data = await state.get_data()
    image_bytes = data.get("image_bytes")
    image_filename = data.get("image_filename", "photo.jpg")
    if not image_bytes:
        await state.clear()
        await message.answer("Rasm ma’lumoti topilmadi. Iltimos, rasmni qayta yuboring.")
        return

    status = await message.answer("🎨 Ranglar tahlil qilinmoqda va tema yaratilmoqda...")
    try:
        theme_bytes, output_filename = await generate_theme(
            image_bytes=image_bytes,
            image_filename=image_filename,
            theme_name=theme_name,
        )
        await message.answer_document(
            BufferedInputFile(theme_bytes, filename=output_filename),
            caption=(
                f"✅ **{theme_name}** temasi tayyor!\n\n"
                "Faylni Telegram Android’da ochib, temani qo‘llashingiz mumkin."
            ),
            parse_mode="Markdown",
        )
        await status.edit_text("Tayyor! Yana tema yaratish uchun yangi rasm yuboring. ✨")
    except asyncio.TimeoutError:
        await status.edit_text("API javobi kechikyapti. Birozdan keyin qayta urinib ko‘ring.")
    except aiohttp.ClientError:
        logger.exception("Could not connect to Attheme API")
        await status.edit_text("API serveriga ulanib bo‘lmadi. Server manzilini tekshiring.")
    except RuntimeError as exc:
        await status.edit_text(str(exc))
    except Exception:
        logger.exception("Unexpected error while generating theme")
        await status.edit_text("Kutilmagan xatolik yuz berdi. Keyinroq urinib ko‘ring.")
    finally:
        await state.clear()


@dp.message(ThemeFlow.waiting_for_name)
async def invalid_theme_name_handler(message: Message) -> None:
    await message.answer("Tema nomini oddiy matn ko‘rinishida yuboring yoki /cancel yozing.")


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
