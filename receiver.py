import os
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio

# Загрузка переменных окружения
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# Инициализация FastAPI
app = FastAPI()

# Инициализация Telethon клиента
client = TelegramClient("Property", API_ID, API_HASH)

# Запускаем клиент Telethon при старте FastAPI
@app.on_event("startup")
async def startup_event():
    await client.start()
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

# Эндпоинт для приёма webhook-запросов
@app.post("/send_message")
async def send_message(data: MessageData):
    try:
        await client.send_message(data.sender_id, data.message_text)
        return {"status": "sent", "to": data.sender_id, "text": data.message_text}
    except Exception as e:
        return {"status": "error", "details": str(e)}
