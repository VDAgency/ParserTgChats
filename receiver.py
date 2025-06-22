import logging
import os
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from telethon import TelegramClient
import asyncio
from parser import client, start_client, stop_client, get_entity_or_fail


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),  # Логи в файл
        logging.StreamHandler()  # Логи в консоль
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

# async def ensure_entity_known(sender_id: int, common_chat_id: int):
#     logger.info(f"Checking if entity {sender_id} is known in common chat {common_chat_id}")
#     try:
#         # Получаем сущность общего чата
#         chat_entity = await get_entity_or_fail(common_chat_id)
#         # Получаем список участников
#         participants = await client.get_participants(chat_entity, limit=200)  # Ограничиваем для тестов
#         for participant in participants:
#             if participant.id == sender_id:
#                 logger.info(f"Entity {sender_id} found in participants")
#                 return True
#         logger.warning(f"Entity {sender_id} not found in participants of chat {common_chat_id}")
#         return False
#     except Exception as e:
#         logger.error(f"Error fetching participants: {str(e)}", exc_info=True)
#         return False

# @app.post("/send_message")
# async def send_message(data: MessageData):
#     logger.debug(f"Received request with data: {data}")
    
#     try:
#         Проверяем, известна ли сущность
#         if not await ensure_entity_known(data.sender_id, data.common_chat_id):
#             logger.error(f"Cannot resolve entity {data.sender_id} even after checking participants")
#             return {"status": "error", "details": f"Could not resolve entity {data.sender_id}. Ensure the user is in the common chat."}
        
#         logger.info(f"Attempting to resolve entity for sender_id: {data.sender_id}")
#         entity = await get_entity_or_fail(data.sender_id)
#         logger.debug(f"Entity resolved successfully: {entity}")
        
#         logger.info(f"Sending message '{data.message_text}' to {data.sender_id}")
#         await client.send_message(entity, data.message_text)
#         logger.debug(f"Message sent successfully to {data.sender_id}")
        
#         response = {"status": "sent", "to": data.sender_id, "text": data.message_text}
#         logger.info(f"Returning response: {response}")
#         return response
#     except ValueError as ve:
#         logger.error(f"ValueError during entity resolution: {str(ve)}")
#         response = {
#             "status": "error",
#             "details": f"{str(ve)}. Ensure {data.sender_id} is accessible via common chat."
#         }
#         logger.info(f"Returning error response: {response}")
#         return response
#     except Exception as e:
#         logger.error(f"Unexpected error during message sending: {str(e)}", exc_info=True)
#         response = {"status": "error", "details": str(e)}
#         logger.info(f"Returning error response: {response}")
#         return response

@app.post("/send_message")
async def send_message(data: MessageData):
    try:
        entity = await client.get_entity(data.sender_id)
        await client.send_message(entity, data.message_text)
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "details": str(e)}