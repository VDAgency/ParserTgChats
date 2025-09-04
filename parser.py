import logging
from telethon import events
from telethon import TelegramClient
from telethon.tl.types import User, Message
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneMigrateError
from client_instance import client
from datetime import datetime, timedelta
import time
import os
import sys
import asyncio
import random
from dotenv import load_dotenv
from database import save_message, is_message_processed, get_last_parsed_date, get_all_tracked_chats, check_keywords_match, mark_message_as_processed
from webhook_processor import process_and_send_webhook
from group_sender import send_to_supergroup_topic
from smart_parser import smart_parse_message
from property_matcher import find_matching_properties, format_properties_message


# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHAT_IDS = [int(chat_id.strip()) for chat_id in os.getenv("CHAT_IDS", "").split(",")]
PHONE = os.getenv("PHONE")
MY_GROUP_ID = int(os.getenv("MY_GROUP_ID"))
MY_TOPIC_ID = int(os.getenv("MY_TOPIC_ID"))


TOPIC_CACHE = {}


# Функция для запуска клиента
async def start_client():
    logger.info(f"{datetime.now()}: ✅ We launch the Telethon client for the user bot. | Запускаем клиента Telethon для юзер-бота.")
    try:
        await client.connect()  # Убедимся, что соединение активно
        if not await client.is_user_authorized():
            await client.start(phone=PHONE)
        me = await client.get_me()
        logger.info(f"Authenticated as: {me.id} ({me.phone})")
        logger.info("✅ Telethon client connected")
    except Exception as e:
        logger.info(f"{datetime.now()}: Error starting client: {str(e)}")
        raise

# Функция для остановки клиента
async def stop_client():
    await client.disconnect()
    logger.info(f"{datetime.now()}: 🛑 Telethon client disconnected")


async def send_test_message():
    me = await client.get_me()
    my_user_id = me.id
    await client.send_message(my_user_id, "Bot activated successfully! This is a test message. | Бот успешно активирован! Это тестовое сообщение.")
    logger.info(f"{datetime.now()}: Test message sent to yourself. | Тестовое сообщение, отправленное самому себе.")


async def get_entity_or_fail(entity_id):
    try:
        entity = await client.get_entity(entity_id)  # Получает сущность по ID
        return entity
    except ValueError as e:
        raise Exception(f"Could not resolve entity {entity_id}: {str(e)}")


async def check_session():
    try:
        me = await client.get_me()
        if not me:
            raise Exception("Session is invalid, attempting to reconnect.")
        return True
    except Exception as e:
        logger.info(f"{datetime.now()}: Session check failed: {str(e)}")
        return False


async def reconnect(max_attempts=3, attempt=1):
    try:
        await client.disconnect()
        await client.connect()
        if not await client.is_user_authorized():
            logger.info(f"{datetime.now()}: Reauthorization required. Please restart the script.")
            return False
        logger.info(f"{datetime.now()}: Reconnected successfully (attempt {attempt}/{max_attempts}).")
        return True
    except Exception as e:
        if attempt < max_attempts:
            logger.info(f"{datetime.now()}: Reconnection attempt {attempt}/{max_attempts} failed: {str(e)}. Retrying...")
            await asyncio.sleep(random.uniform(5, 10))
            return await reconnect(max_attempts, attempt + 1)
        logger.info(f"{datetime.now()}: Max reconnection attempts reached. Stopping.")
        return False


@client.on(events.NewMessage)
async def handler(event):
    logger.debug(f"Received new message from chat {event.chat_id}: {event.message.text}")

    try:
        # Логирование получения списка чатов
        logger.debug("Fetching tracked chat list from database. | Извлечение отслеживаемого списка чатов из базы данных.")
        chat_list = await get_all_tracked_chats()  # Получаем актуальный список чатов из базы
        logger.debug(f"Tracked chat list: {chat_list} | Список отслеживаемых чатов: {chat_list}")

        # Добавляем префикс '-100' к chat_id, если это супергруппа/канал
        if event.chat_id not in chat_list:
            # Если префикса нет, добавляем его перед сравнением
            if event.chat_id not in chat_list and f"-100{event.chat_id}" in chat_list:
                logger.info(f"Message from chat {event.chat_id} is not in tracked chats, but adding '-100' prefix.")
                event.chat_id = f"-100{event.chat_id}"        
        
        # Проверка, если chat_id сообщения в нашем списке
        if event.chat_id not in chat_list:
            logger.info(f"Message from chat {event.chat_id} is not in tracked chats. Skipping.")
            return  # Пропускаем, если чат не в списке

        logger.info(f"Message from chat {event.chat_id} is in tracked chats. Processing message...")

        # Обработка сообщения
        await process_message(event)

    except Exception as e:
        logger.error(f"Error in handler for chat {event.chat_id}: {str(e)}", exc_info=True)




async def process_message(event):
    message = event.message
    
    # Проверяем, было ли сообщение уже обработано
    if await is_message_processed(message.id):
        logger.info(f"{datetime.now()}: Reached processed message {message.id} in chat {message.chat_id}. Stopping. | Достигнуто обработанное сообщение {message.id} в чате {message.chat_id}. Остановка парсинга.")
        return  # Завершаем работу, как только нашли обработанное сообщение
    
    # Получаем информацию о чате и отправителе
    chat = await message.get_chat()
    sender = await message.get_sender()
                    
    # Кэшируем сущность отправителя для получения access_hash
    if sender and isinstance(sender, User):
        try:
            sender_entity = await client.get_entity(sender.id)
            logger.info(f"Cached entity for {sender.id} with access_hash: {sender_entity.access_hash}")
            logger.info(f"Full sender entity data: {vars(sender_entity)}")
        except ValueError as ve:
            logger.warning(f"Could not fully resolve sender {sender.id} entity: {str(ve)}")
            logger.info(f"Partial sender data: {vars(sender) if hasattr(sender, '__dict__') else str(sender)}")
        except Exception as e:
            logger.error(f"Unexpected error resolving sender {sender.id}: {str(e)}", exc_info=True)
            logger.info(f"Partial sender data: {vars(sender) if hasattr(sender, '__dict__') else str(sender)}")

    # Безопасное извлечение имени и юзернейма
    if sender and isinstance(sender, User):
        first_name = sender.first_name
        username = sender.username
        sender_id = sender.id
    else:
        first_name = None
        username = None
        sender_id = sender.id if sender else None
    
    # Преобразуем время сообщения в нужный формат
    message_timestamp = message.date.timestamp()
    message_data = {
        "update_id": 0,
        "message_id": message.id,
        "chat_id": chat.id,
        "chat_type": chat.type if hasattr(chat, "type") else "unknown",
        "sender_id": sender_id,
        "first_name": first_name,
        "username": username,
        "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message_timestamp)),
        "text": message.text if message.text else "",
        "original_message_id": message.id,
    }
    
    # ⛔ Пропускаем все, кроме текстовых сообщений
    if not message.text or not message.text.strip():
        logger.info(f"{datetime.now()}: Пропущено сообщение {message.id} без текста из чата {message.chat_id}")
        return  # Пропускаем это сообщение, завершаем выполнение функции 
    
    # ⛔ Пропускаем, если нет ключевых слов
    if not await check_keywords_match(message.text):
        logger.info(f"{datetime.now()}: Пропущено сообщение {message.id} — нет ключевых слов.")
        if await smart_parse_message(message.id, message.text, message_data):
            await send_to_supergroup_topic(message.id)
            # запуск логики отбора объектов из гугл таблицы
            user_id = sender_id
            message_text = message.text
            df_results = await find_matching_properties(message_text)
            if not df_results.empty:
                reply_text = await format_properties_message(df_results)
                if reply_text:
                    await client.send_message(user_id, reply_text)
        else:
            await mark_message_as_processed(message.id)
        return  # Прерываем выполнение функции
                    
    # Сохраняем новое сообщение в базу
    await save_message(**message_data)
    logger.info(f"{datetime.now()}: Saved message {message.id} from chat {event.chat_id}")
                    
    # Вызываем функцию обработки и отправки сообщения в супер группу
    await send_to_supergroup_topic(message.id)
       
    # запуск логики отбора объектов из гугл таблицы
    user_id = sender_id
    message_text = message.text
    df_results = await find_matching_properties(message_text)
    if not df_results.empty:
        reply_text = await format_properties_message(df_results)
        if reply_text:
            await client.send_message(user_id, reply_text)
    
    # Отмечаем сообщение как обработанное
    await mark_message_as_processed(message.id)
    
                    
    # Вызываем функцию обработки и отправки вебхука
    # await process_and_send_webhook(message.id)
    
    
    # # Пример фильтрации по ключевым словам
    # if await check_keywords_match(message.text):
    #     logger.info(f"Processing message {message.id} from chat {event.chat_id}")
    #     await save_message(message)  # Сохраняем сообщение в базу
    #     await send_to_supergroup_topic(message.id)  # Дополнительная обработка, например, отправка в супергруппу


async def get_topic_title(client, chat_id: int, topic_id: int) -> str:
    """
    Возвращает название топика по его ID (с кэшем).
    """
    if (chat_id, topic_id) in TOPIC_CACHE:
        return TOPIC_CACHE[(chat_id, topic_id)]

    try:
        result = await client(GetForumTopicsRequest(
            channel=chat_id,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        for topic in result.topics:
            if topic.id == topic_id:
                TOPIC_CACHE[(chat_id, topic_id)] = topic.title
                return topic.title
    except Exception as e:
        logger.error(f"[PhotoID] Ошибка при получении названия топика {topic_id}: {e}")
    return f"Топик {topic_id}"


@client.on(events.NewMessage(chats=MY_GROUP_ID))
async def photo_id_handler(event: Message):
    """
    Ловим фото в супергруппе в конкретном топике и отвечаем ID фотографии + название топика.
    """
    try:
        topic_id = None
        if event.message.reply_to:
            topic_id = getattr(event.message.reply_to, "reply_to_msg_id", None)

        logger.info(f"[PhotoID] Получено сообщение, topic_id={topic_id}")

        if topic_id == MY_TOPIC_ID:
            if event.message.photo:
                photo_id = event.message.photo.id
                logger.info(f"[PhotoID] Найдено фото, id={photo_id}")

                # получаем название топика
                topic_title = await get_topic_title(client, MY_GROUP_ID, topic_id)

                # отправляем ответ
                await client.send_message(
                    MY_GROUP_ID,
                    f"📸 Фото сохранено в топике: *{topic_title}*\nID фотографии: `{photo_id}`",
                    reply_to=event.message.id,
                    parse_mode="markdown"
                )
        else:
            logger.info(f"[PhotoID] Топик не совпал (получили {topic_id}, ожидали {MY_TOPIC_ID})")

    except Exception as e:
        logger.exception(f"[PhotoID] Ошибка обработки: {e}")



__all__ = ['client', 'start_client', 'stop_client', 'get_entity_or_fail']



