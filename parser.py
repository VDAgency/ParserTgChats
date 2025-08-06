import logging
from telethon import events
from telethon import TelegramClient
from telethon.tl.types import User
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
        logger.debug("Fetching tracked chat list from database.")
        chat_list = await get_all_tracked_chats()  # Получаем актуальный список чатов из базы
        logger.debug(f"Tracked chat list: {chat_list}")

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
        await mark_message_as_processed(message.id)
        return  # Прерываем выполнение функции
                    
    # Сохраняем новое сообщение в базу
    await save_message(**message_data)
    logger.info(f"{datetime.now()}: Saved message {message.id} from chat {event.chat_id}")
                    
    # Вызываем функцию обработки и отправки сообщения в супер группу
    await send_to_supergroup_topic(message.id)
                    
    await mark_message_as_processed(message.id)
                    
    # Вызываем функцию обработки и отправки вебхука
    # await process_and_send_webhook(message.id)
    
    
    # # Пример фильтрации по ключевым словам
    # if await check_keywords_match(message.text):
    #     logger.info(f"Processing message {message.id} from chat {event.chat_id}")
    #     await save_message(message)  # Сохраняем сообщение в базу
    #     await send_to_supergroup_topic(message.id)  # Дополнительная обработка, например, отправка в супергруппу



# async def parse_chat(chat_id, start_date=None):
#     try:
#         # Устанавливаем start_date как текущую дату и время
#         if not start_date:
#             start_date = datetime.now()  # Начинаем с текущего момента

#         messages_processed = 0
#         while True:
#             try:
#                 # Получаем сообщения из чата, начиная с start_date
#                 async for message in client.iter_messages(chat_id, offset_date=start_date, limit=100):
#                     # Проверяем, активна ли сессия
#                     if not await check_session():
#                         if not await reconnect():
#                             return  # Выход, если не удалось переподключиться
#                     # Проверяем, было ли сообщение уже обработано
#                     if await is_message_processed(message.id):
#                         logger.info(f"{datetime.now()}: Reached processed message {message.id} in chat {chat_id}. Stopping. | Достигнуто обработанное сообщение {message.id} в чате {chat_id}. Остановка парсинга.")
#                         return  # Завершаем работу, как только нашли обработанное сообщение

#                     # Получаем информацию о чате и отправителе
#                     chat = await message.get_chat()
#                     sender = await message.get_sender()
                    
#                     # Кэшируем сущность отправителя для получения access_hash
#                     if sender and isinstance(sender, User):
#                         try:
#                             sender_entity = await client.get_entity(sender.id)
#                             logger.info(f"Cached entity for {sender.id} with access_hash: {sender_entity.access_hash}")
#                             logger.info(f"Full sender entity data: {vars(sender_entity)}")
#                         except ValueError as ve:
#                             logger.warning(f"Could not fully resolve sender {sender.id} entity: {str(ve)}")
#                             logger.info(f"Partial sender data: {vars(sender) if hasattr(sender, '__dict__') else str(sender)}")
#                         except Exception as e:
#                             logger.error(f"Unexpected error resolving sender {sender.id}: {str(e)}", exc_info=True)
#                             logger.info(f"Partial sender data: {vars(sender) if hasattr(sender, '__dict__') else str(sender)}")

#                     # Безопасное извлечение имени и юзернейма
#                     if sender and isinstance(sender, User):
#                         first_name = sender.first_name
#                         username = sender.username
#                         sender_id = sender.id
#                     else:
#                         first_name = None
#                         username = None
#                         sender_id = sender.id if sender else None
                    
#                     # Преобразуем время сообщения в нужный формат
#                     message_timestamp = message.date.timestamp()
#                     message_data = {
#                         "update_id": 0,
#                         "message_id": message.id,
#                         "chat_id": chat.id,
#                         "chat_type": chat.type if hasattr(chat, "type") else "unknown",
#                         "sender_id": sender_id,
#                         "first_name": first_name,
#                         "username": username,
#                         "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message_timestamp)),
#                         "text": message.text if message.text else "",
#                     }
                    
#                     # ⛔ Пропускаем все, кроме текстовых сообщений
#                     if not message.text or not message.text.strip():
#                         logger.info(f"{datetime.now()}: Пропущено сообщение {message.id} без текста из чата {chat_id}")
#                         continue
                    
#                     # ⛔ Пропускаем, если нет ключевых слов
#                     if not await check_keywords_match(message.text):
#                         logger.info(f"{datetime.now()}: Пропущено сообщение {message.id} — нет ключевых слов.")
#                         await mark_message_as_processed(message.id)
#                         continue
                    
#                     # Сохраняем новое сообщение в базу
#                     await save_message(**message_data)
#                     logger.info(f"{datetime.now()}: Saved message {message.id} from chat {chat_id}")
                    
#                     # Вызываем функцию обработки и отправки сообщения в супер группу
#                     await send_to_supergroup_topic(message.id)
                    
#                     await mark_message_as_processed(message.id)
                    
#                     # Вызываем функцию обработки и отправки вебхука
#                     # await process_and_send_webhook(message.id)
                    
#                     messages_processed += 1  # Счетчик для отладки
#                     await asyncio.sleep(random.uniform(1, 5))  # Случайная задержка для имитации человека

#                 # Если дошли сюда, значит, в текущем запросе не нашли обработанное сообщение
#                 # Устанавливаем start_date на дату последнего обработанного сообщения минус 1 секунда
#                 if messages_processed > 0:
#                     last_message_date = datetime.strptime(message_data["date"], "%Y-%m-%d %H:%M:%S")
#                     start_date = last_message_date - timedelta(seconds=1)
#                     logger.info(f"{datetime.now()}: Processed {messages_processed} messages. Continuing with start_date={start_date}")
#                 else:
#                     logger.info(f"{datetime.now()}: No new messages found in chat {chat_id}. Stopping. | В чате {chat_id} не найдено новых сообщений. Остановка.")
#                     break  # Если новых сообщений нет, выходим
#             except FloodWaitError as e:
#                 logger.info(f"{datetime.now()}: Flood wait detected for chat {chat_id}. Waiting for {e.seconds} seconds.")
#                 await asyncio.sleep(e.seconds)
#                 continue  # Продолжаем после ожидания
#             except PhoneMigrateError as e:
#                 logger.info(f"{datetime.now()}: Phone migrated to DC {e.dc_id}. Reconnecting...")
#                 await client.session.set_dc(e.dc_id, API_ID, API_HASH)
#                 await reconnect()
#                 continue  # Продолжаем после переподключения
#     except ValueError as e:
#         logger.info(f"{datetime.now()}: Error parsing chat {chat_id}: {str(e)}. Skipping this chat.")
#     except Exception as e:
#         logger.info(f"{datetime.now()}: Unexpected error parsing chat {chat_id}: {str(e)}. Skipping this chat.")

# Экспортируем клиент и функции
__all__ = ['client', 'start_client', 'stop_client', 'get_entity_or_fail']



# async def parse_loop():
#     while True:
#         chat_ids = await get_all_tracked_chats()
#         if not chat_ids:
#             logger.info("Нет чатов для парсинга. Ожидаем 60 секунд...")
#             await asyncio.sleep(60)
#             continue

#         for chat_id in chat_ids:
#             if not await check_session():
#                 if not await reconnect():
#                     logger.info("Не удалось переподключиться. Останавливаем парсинг.")
#                     return
#             try:
#                 logger.info(f"Начинаем парсинг чата {chat_id}")
#                 await parse_chat(chat_id)
#                 await asyncio.sleep(random.uniform(3, 6))  # Задержка между чатами
#             except Exception as e:
#                 logger.info(f"Ошибка при парсинге чата {chat_id}: {str(e)}")
#                 continue

#         logger.info("Цикл парсинга завершён. Ожидаем перед следующим циклом.")
#         await asyncio.sleep(60)  # Задержка между полными циклами


