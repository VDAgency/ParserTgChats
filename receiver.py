import os
import sys
import logging
import asyncio
import aiohttp
import aiosqlite
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio
from client_instance import client
from parser import start_client, stop_client, get_entity_or_fail


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


# Загрузка переменных окружения
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")

# Инициализация FastAPI
app = FastAPI()

# Запускаем клиент Telethon при старте FastAPI
@app.on_event("startup")
async def startup_event():
    await start_client()
    logger.info("✅ Telethon client connected")

# Закрываем клиент Telethon при завершении работы
@app.on_event("shutdown")
async def shutdown_event():
    await stop_client()
    logger.info("🛑 Telethon client disconnected")

# Структура входящих данных от Make
class MessageData(BaseModel):
    sender_id: int
    message_text: str

@app.get("/")
async def root():
    return {"message": "ParserTgChats is running!"}

# Эндпоинт для проверки здоровья
@app.get("/health")
async def health_check():
    try:
        # Проверка подключения к базе данных
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("SELECT 1")  # Простой запрос для проверки
        logger.info("Database connection is healthy")

        # Проверка статуса клиента Telethon
        if client.is_connected():
            me = await client.get_me()
            if me:
                logger.info("Telethon client is connected and authenticated")
            else:
                logger.warning("Telethon client is connected but not authenticated")
                return {"status": "unhealthy", "details": "Telethon not authenticated"}
        else:
            logger.warning("Telethon client is not connected")
            return {"status": "unhealthy", "details": "Telethon not connected"}

        # Если все проверки прошли
        return {"status": "healthy"}

    except aiosqlite.Error as db_error:
        logger.error(f"Database health check failed: {str(db_error)}")
        return {"status": "unhealthy", "details": str(db_error)}
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return {"status": "unhealthy", "details": str(e)}


# Фоновый процесс для периодической проверки
async def check_health():
    while True:
        try:
            # Проверка подключения к базе данных
            async with aiosqlite.connect("bot.db") as db:
                await db.execute("SELECT 1")
                logger.info("Database connection is healthy")

            # Проверка статуса клиента Telethon
            if client.is_connected():
                me = await client.get_me()
                if me:
                    logger.info("Telethon client is connected and authenticated")
                else:
                    logger.warning("Telethon client is connected but not authenticated")
            else:
                logger.warning("Telethon client is not connected")

            # Отправка запроса к серверу для поддержания активности
            render_url = os.environ.get("RENDER_EXTERNAL_URL")
            if render_url:
                async with aiohttp.ClientSession() as session:
                    url = f"https://{render_url}/health"
                    logger.info(f"Sending health check request to: {url}")
                    async with session.get(url) as response:
                        if response.status == 200:
                            logger.info("Server health check passed")
                        else:
                            logger.warning(f"Server health check failed with status {response.status}")
            else:
                logger.warning("RENDER_EXTERNAL_URL is not set, skipping server health check")

            logger.info("Periodic health check passed")

        except aiosqlite.Error as db_error:
            logger.error(f"Database health check failed: {str(db_error)}")
        except Exception as e:
            logger.error(f"Health check error: {str(e)}")

        await asyncio.sleep(300)  # 5 минут



@app.post("/send_message")
async def send_message(data: MessageData):
    try:
        entity = await client.get_entity(data.sender_id)
        await client.send_message(entity, data.message_text)
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "details": str(e)}