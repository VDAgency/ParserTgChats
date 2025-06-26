import logging
import os
import sys
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio
from parser import client, start_client, stop_client, get_entity_or_fail


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
    return {"status": "healthy"}

@app.post("/send_message")
async def send_message(data: MessageData):
    try:
        entity = await client.get_entity(data.sender_id)
        await client.send_message(entity, data.message_text)
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "details": str(e)}