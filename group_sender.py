import os
import sys
import logging
from client_instance import client
from dotenv import load_dotenv
from database import get_message_by_id, is_message_processed, get_keywords_by_type
from bot_instance import bot
from telethon.tl.types import PeerChannel, PeerChat
from telethon.errors import ChannelInvalidError, ChannelPrivateError, ChannelPublicGroupNaError


load_dotenv()
SUPERGROUP_ID = int(os.getenv("SUPERGROUP_ID"))
TOPIC_ID = int(os.getenv("TOPIC_ID"))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# # Ключевые слова (можно позже вынести отдельно)
# POSITIVE_PHRASES = [
#     "ищу аренду", "хочу арендовать", "ищу покупку", "хочу купить",
#     "ищу квартиру", "хочу квартиру", "ищу виллу", "хочу виллу",
#     "ищу коттедж", "хочу коттедж", "ищу кондоминиум", "хочу кондоминиум",
#     "looking for rent", "want to rent", "looking to buy", "want to buy",
#     "looking for apartment", "want apartment", "looking for villa", "want villa",
#     "looking for cottage", "want cottage", "looking for condominium", "want condominium"
# ]

# NEGATIVE_PHRASES = [
#     "доступно в аренду", "доступна аренда", "продается", "available for rent",
#     "for sale", "available to buy"
# ]

# def filter_message(message_data):
#     if not message_data or "text" not in message_data:
#         return False
#     text = message_data["text"].lower()
#     has_positive = any(phrase in text for phrase in POSITIVE_PHRASES)
#     has_negative = any(phrase in text for phrase in NEGATIVE_PHRASES)
#     return has_positive and not has_negative


async def filter_message(message_data):
    if not message_data or "text" not in message_data:
        return False

    text = message_data["text"].lower()

    positive_phrases = await get_keywords_by_type("positive")
    negative_phrases = await get_keywords_by_type("negative")

    has_positive = any(phrase in text for phrase in positive_phrases)
    has_negative = any(phrase in text for phrase in negative_phrases)

    return has_positive and not has_negative





async def mark_message_as_sent(message_id: int):
    from database import aiosqlite
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            UPDATE messages SET sent_to_group = 1 WHERE message_id = ?
        """, (message_id,))
        await db.commit()

async def was_message_sent(message_id: int):
    from database import aiosqlite
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT sent_to_group FROM messages WHERE message_id = ?
        """, (message_id,))
        result = await cursor.fetchone()
        return result and result[0] == 1

async def send_to_supergroup_topic(message_id: int):
    message_data = await get_message_by_id(message_id)
    if not message_data:
        logger.info(f"[group_sender] No message found with ID {message_id}")
        return

    if await was_message_sent(message_id):
        logger.info(f"[group_sender] Message {message_id} already sent. Skipping.")
        return

    # Формируем текст
    chat_id = message_data.get("chat_id")
    entity = await client.get_entity(PeerChannel(chat_id))
    title = getattr(entity, "title", None)
    chatname = getattr(entity, "username", None)
    link = f"https://t.me/{chatname}" if chatname else ""
    first_name = message_data.get("first_name", "Без имени")
    username = message_data.get("username")
    text = message_data.get("text", "")
    original_message_id = message_data.get("original_message_id")

    # Формируем ссылку на оригинальное сообщение
    if chatname:
        # Публичный канал
        message_link = f"https://t.me/{chatname}/{original_message_id}"
    else:
        # Приватный канал или супергруппа
        channel_id = str(chat_id).replace("-100", "")
        message_link = f"https://t.me/c/{channel_id}/{original_message_id}"
    
    # Форматированное сообщение
    formatted = (
        f"<b>Чат:</b> <b>{title}</b> <code>{chat_id}</code> — <a href='{link}'>ссылка</a>\n"
        f"<b>Имя:</b> {first_name}\n"
        f"<b>Юзернейм:</b> @{username if username else 'не указан'}\n\n"
        f"{text}\n"
        f"<b>🔗 Ссылка на сообщение:</b> <a href='{message_link}'>перейти</a>"
    )

    try:
        await bot.send_message(
            chat_id=SUPERGROUP_ID,
            message_thread_id=TOPIC_ID,
            text=formatted
        )
        await mark_message_as_sent(message_id)
        logger.info(f"[group_sender] Message {message_id} sent successfully.")
    except Exception as e:
        logger.info(f"[group_sender] Failed to send message {message_id}: {e}")
