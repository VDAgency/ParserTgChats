import os
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio
from parser import client, start_client, stop_client

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
    await client.start(phone=PHONE)
    print("✅ Telethon client connected")

# Закрываем клиент Telethon при завершении работы
@app.on_event("shutdown")
async def shutdown_event():
    await client.disconnect()
    print("🛑 Telethon client disconnected")

# Структура входящих данных от Make
class MessageData(BaseModel):
    sender_id: int
    message_text: str

# Эндпоинт для проверки здоровья
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Эндпоинт для приёма webhook-запросов
@app.post("/send_message")
async def send_message(data: MessageData):
    try:
        await client.send_message(data.sender_id, data.message_text)
        return {"status": "sent", "to": data.sender_id, "text": data.message_text}
    except Exception as e:
        return {"status": "error", "details": str(e)}
