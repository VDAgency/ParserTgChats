from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneMigrateError
from datetime import datetime, timedelta
import time
import os
import asyncio
import random
from dotenv import load_dotenv
from database import save_message, is_message_processed, get_last_parsed_date
from webhook_processor import process_and_send_webhook


load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHAT_IDS = [int(chat_id.strip()) for chat_id in os.getenv("CHAT_IDS", "").split(",")]

client = TelegramClient(
    "Property",
    API_ID,
    API_HASH,
    device_model="Dell XPS 13",
    system_version="Windows 11",
    app_version="5.15.2 x64",
    lang_code="en",
    system_lang_code="en-US"
)

async def send_test_message():
    me = await client.get_me()
    my_user_id = me.id
    await client.send_message(my_user_id, "Bot activated successfully! This is a test message. | Бот успешно активирован! Это тестовое сообщение.")
    print(f"{datetime.now()}: Test message sent to yourself. | Тестовое сообщение, отправленное самому себе.")

async def check_session():
    try:
        me = await client.get_me()
        if not me:
            raise Exception("Session is invalid, attempting to reconnect.")
        return True
    except Exception as e:
        print(f"{datetime.now()}: Session check failed: {str(e)}")
        return False

async def reconnect(max_attempts=3, attempt=1):
    try:
        await client.disconnect()
        await client.connect()
        if not await client.is_user_authorized():
            print(f"{datetime.now()}: Reauthorization required. Please restart the script.")
            return False
        print(f"{datetime.now()}: Reconnected successfully (attempt {attempt}/{max_attempts}).")
        return True
    except Exception as e:
        if attempt < max_attempts:
            print(f"{datetime.now()}: Reconnection attempt {attempt}/{max_attempts} failed: {str(e)}. Retrying...")
            await asyncio.sleep(random.uniform(5, 10))
            return await reconnect(max_attempts, attempt + 1)
        print(f"{datetime.now()}: Max reconnection attempts reached. Stopping.")
        return False


async def parse_chat(chat_id, start_date=None):
    try:
        # Устанавливаем start_date как текущую дату и время
        if not start_date:
            start_date = datetime.now()  # Начинаем с текущего момента

        messages_processed = 0  # Счетчик для отладки (уже не ограничивает)
        while True:  # Цикл продолжается, пока не найдем обработанное сообщение
            try:
                # Получаем сообщения из чата, начиная с start_date
                async for message in client.iter_messages(chat_id, offset_date=start_date, limit=50):  # Лимит 50 для одного запроса
                    # Проверяем, активна ли сессия
                    if not await check_session():
                        if not await reconnect():
                            return  # Выход, если не удалось переподключиться
                    # Проверяем, было ли сообщение уже обработано
                    if await is_message_processed(message.id):
                        print(f"{datetime.now()}: Reached processed message {message.id} in chat {chat_id}. Stopping.")
                        return  # Завершаем работу, как только нашли обработанное сообщение

                    # Получаем информацию о чате и отправителе
                    chat = await message.get_chat()
                    sender = await message.get_sender()

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
                    print(f"{datetime.now()}: Saved message {message.id} from chat {chat_id}")
                    
                    # Вызываем функцию обработки и отправки вебхука
                    await process_and_send_webhook(message.id)
                    
                    messages_processed += 1  # Счетчик для отладки
                    await asyncio.sleep(random.uniform(1, 3))  # Случайная задержка для имитации человека

                # Если дошли сюда, значит, в текущем запросе не нашли обработанное сообщение
                # Устанавливаем start_date на дату последнего обработанного сообщения минус 1 секунда
                if messages_processed > 0:
                    last_message_date = datetime.strptime(message_data["date"], "%Y-%m-%d %H:%M:%S")
                    start_date = last_message_date - timedelta(seconds=1)
                    print(f"{datetime.now()}: Processed {messages_processed} messages. Continuing with start_date={start_date}")
                else:
                    print(f"{datetime.now()}: No new messages found in chat {chat_id}. Stopping. | В чате {chat_id} не найдено новых сообщений. Остановка.")
                    break  # Если новых сообщений нет, выходим
            except FloodWaitError as e:
                print(f"{datetime.now()}: Flood wait detected for chat {chat_id}. Waiting for {e.seconds} seconds.")
                await asyncio.sleep(e.seconds)
                continue  # Продолжаем после ожидания
            except PhoneMigrateError as e:
                print(f"{datetime.now()}: Phone migrated to DC {e.dc_id}. Reconnecting...")
                await client.session.set_dc(e.dc_id, API_ID, API_HASH)
                await reconnect()
                continue  # Продолжаем после переподключения
    except ValueError as e:
        print(f"{datetime.now()}: Error parsing chat {chat_id}: {str(e)}. Skipping this chat.")
    except Exception as e:
        print(f"{datetime.now()}: Unexpected error parsing chat {chat_id}: {str(e)}. Skipping this chat.")

async def main():
    try:
        await client.start()
        print(f"{datetime.now()}: Client started")

        await send_test_message()

        for chat_id in CHAT_IDS:
            if not await check_session():
                if not await reconnect():
                    return
            print(f"{datetime.now()}: Parsing chat {chat_id}")
            await parse_chat(chat_id)
            await asyncio.sleep(random.uniform(10, 30))  # Задержка между чатами
    except Exception as e:
        print(f"{datetime.now()}: Error in main: {str(e)}")
    finally:
        await client.disconnect()
        print(f"{datetime.now()}: Client disconnected")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

