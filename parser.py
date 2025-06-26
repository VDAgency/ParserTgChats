import logging
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
from database import save_message, is_message_processed, get_last_parsed_date, get_all_tracked_chats
from webhook_processor import process_and_send_webhook
from group_sender import send_to_supergroup_topic


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


async def parse_chat(chat_id, start_date=None):
    try:
        # Устанавливаем start_date как текущую дату и время
        if not start_date:
            start_date = datetime.now()  # Начинаем с текущего момента

        messages_processed = 0
        while True:
            try:
                # Получаем сообщения из чата, начиная с start_date
                async for message in client.iter_messages(chat_id, offset_date=start_date, limit=100):
                    # Проверяем, активна ли сессия
                    if not await check_session():
                        if not await reconnect():
                            return  # Выход, если не удалось переподключиться
                    # Проверяем, было ли сообщение уже обработано
                    if await is_message_processed(message.id):
                        logger.info(f"{datetime.now()}: Reached processed message {message.id} in chat {chat_id}. Stopping. | Достигнуто обработанное сообщение {message.id} в чате {chat_id}. Остановка парсинга.")
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

                    # Преобразуем время сообщения в нужный формат
                    message_timestamp = message.date.timestamp()
                    message_data = {
                        "update_id": 0,
                        "message_id": message.id,
                        "chat_id": chat.id,
                        "chat_type": chat.type if hasattr(chat, "type") else "unknown",
                        "sender_id": sender.id if sender else None,
                        "first_name": sender.first_name if sender else None,
                        "username": sender.username if sender else None,
                        "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message_timestamp)),
                        "text": message.text if message.text else "",
                    }

                    # Сохраняем новое сообщение в базу
                    await save_message(**message_data)
                    logger.info(f"{datetime.now()}: Saved message {message.id} from chat {chat_id}")
                    
                    # Вызываем функцию обработки и отправки сообщения в супер группу
                    await send_to_supergroup_topic(message.id)
                    
                    # Вызываем функцию обработки и отправки вебхука
                    await process_and_send_webhook(message.id)
                    
                    messages_processed += 1  # Счетчик для отладки
                    await asyncio.sleep(random.uniform(1, 3))  # Случайная задержка для имитации человека

                # Если дошли сюда, значит, в текущем запросе не нашли обработанное сообщение
                # Устанавливаем start_date на дату последнего обработанного сообщения минус 1 секунда
                if messages_processed > 0:
                    last_message_date = datetime.strptime(message_data["date"], "%Y-%m-%d %H:%M:%S")
                    start_date = last_message_date - timedelta(seconds=1)
                    logger.info(f"{datetime.now()}: Processed {messages_processed} messages. Continuing with start_date={start_date}")
                else:
                    logger.info(f"{datetime.now()}: No new messages found in chat {chat_id}. Stopping. | В чате {chat_id} не найдено новых сообщений. Остановка.")
                    break  # Если новых сообщений нет, выходим
            except FloodWaitError as e:
                logger.info(f"{datetime.now()}: Flood wait detected for chat {chat_id}. Waiting for {e.seconds} seconds.")
                await asyncio.sleep(e.seconds)
                continue  # Продолжаем после ожидания
            except PhoneMigrateError as e:
                logger.info(f"{datetime.now()}: Phone migrated to DC {e.dc_id}. Reconnecting...")
                await client.session.set_dc(e.dc_id, API_ID, API_HASH)
                await reconnect()
                continue  # Продолжаем после переподключения
    except ValueError as e:
        logger.info(f"{datetime.now()}: Error parsing chat {chat_id}: {str(e)}. Skipping this chat.")
    except Exception as e:
        logger.info(f"{datetime.now()}: Unexpected error parsing chat {chat_id}: {str(e)}. Skipping this chat.")

# Экспортируем клиент и функции
__all__ = ['client', 'start_client', 'stop_client', 'get_entity_or_fail']


# async def parse_loop():
#     while True:
#         for chat_id in CHAT_IDS:
#             if not await check_session():
#                 if not await reconnect():
#                     logger.info("Failed to reconnect, stopping parse loop")
#                     return
#             await parse_chat(chat_id)
#             await asyncio.sleep(random.uniform(5, 15))
#         await asyncio.sleep(60)  # Задержка между циклами

async def parse_loop():
    while True:
        chat_ids = await get_all_tracked_chats()
        if not chat_ids:
            logger.info("Нет чатов для парсинга. Ожидаем 60 секунд...")
            await asyncio.sleep(60)
            continue

        for chat_id in chat_ids:
            if not await check_session():
                if not await reconnect():
                    logger.info("Не удалось переподключиться. Останавливаем парсинг.")
                    return
            try:
                logger.info(f"Начинаем парсинг чата {chat_id}")
                await parse_chat(chat_id)
                await asyncio.sleep(random.uniform(3, 6))  # Задержка между чатами
            except Exception as e:
                logger.info(f"Ошибка при парсинге чата {chat_id}: {str(e)}")
                continue

        logger.info("Цикл парсинга завершён. Ожидаем перед следующим циклом.")
        await asyncio.sleep(60)  # Задержка между полными циклами

# async def main():
#     try:
#         await start_client()
        
#         await send_test_message()

#         for chat_id in CHAT_IDS:
#             if not await check_session():
#                 if not await reconnect():
#                     return
#             logger.info(f"{datetime.now()}: Parsing chat {chat_id}")
#             await parse_chat(chat_id)
#             await asyncio.sleep(random.uniform(5, 15))  # Задержка между чатами
#     except Exception as e:
#         logger.info(f"{datetime.now()}: Error in main: {str(e)}")
#     finally:
#         await stop_client()

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())

