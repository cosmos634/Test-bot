import asyncio
import logging
import os
from io import BytesIO

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ATTHEME_API_URL = os.getenv("ATTHEME_API_URL", "http://127.0.0.1:8000").strip().rstrip("/")
ATTHEME_API_KEY = os.getenv("ATTHEME_API_KEY", "").strip()
MAX_IMAGE_BYTES = 10 * 1024 * 1024
API_TIMEOUT_SECONDS = 45

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("test_bot")

dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Salom! 👋\n"
        "Rasm yuboring — men uni ranglar bo‘yicha tahlil qilib, "
        "Telegram Android uchun .attheme faylini tayyorlayman.\n\n"
        "Hozircha JPG, PNG yoki WEBP rasm yuboring."
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
    form.add_field(
        "image",
        image_bytes,
        filename=filename,
        content_type="application/octet-stream",
    )

    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{ATTHEME_API_URL}/api/v1/generate",
                headers=headers,
                data=form,
            ) as response:
                if response.status == 200:
                    theme_data = await response.read()
                    if not theme_data:
                        await status.edit_text("API bo‘sh fayl qaytardi. Keyinroq urinib ko‘ring.")
                        return
                    document = BufferedInputFile(theme_data, filename="generated_theme.attheme")
                    await message.answer_document(
                        document,
                        caption="✅ Tayyor! Telegram Android’da faylni ochib, temani qo‘llashingiz mumkin.",
                    )
                    await status.delete()
                    return

                try:
                    error_data = await response.json(content_type=None)
                    detail = error_data.get("detail", error_data.get("message", ""))
                    if isinstance(detail, dict):
                        detail = detail.get("message", "")
                except Exception:
                    detail = ""

                logger.warning("Attheme API returned HTTP %s", response.status)
                if response.status == 400:
                    text = "Bu rasm formati noto‘g‘ri yoki fayl buzilgan. JPG, PNG yoki WEBP yuboring."
                elif response.status == 401:
                    text = "API autentifikatsiya xatosi. Bot administratori API kalitini tekshirishi kerak."
                elif response.status == 413:
                    text = "Rasm hajmi juda katta. 10 MB dan kichik rasm yuboring."
                elif response.status == 422:
                    text = "Rasmdan ranglarni aniqlab bo‘lmadi. Boshqa rasm yuborib ko‘ring."
                elif response.status == 429:
                    text = "So‘rovlar limiti oshdi. Biroz kutib, qayta urinib ko‘ring."
                else:
                    text = "Attheme API vaqtincha ishlamayapti. Keyinroq urinib ko‘ring."
                await status.edit_text(text)
    except asyncio.TimeoutError:
        await status.edit_text("API javobi kechikyapti. Birozdan keyin qayta urinib ko‘ring.")
    except aiohttp.ClientError:
        logger.exception("Could not connect to Attheme API")
        await status.edit_text("API serveriga ulanib bo‘lmadi. Server manzilini tekshiring.")
    except Exception:
        logger.exception("Unexpected error while generating theme")
        await status.edit_text("Kutilmagan xatolik yuz berdi. Keyinroq urinib ko‘ring.")


@dp.message()
async def fallback_handler(message: Message) -> None:
    await message.answer("Temaga aylantirish uchun menga rasm yuboring. 🙂")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN .env faylida sozlanmagan.")
    if not ATTHEME_API_KEY:
        raise RuntimeError("ATTHEME_API_KEY .env faylida sozlanmagan.")
    if not ATTHEME_API_URL:
        raise RuntimeError("ATTHEME_API_URL .env faylida sozlanmagan.")

    bot = Bot(token=BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
