import logging
from telethon import TelegramClient
from dotenv import load_dotenv
import os
import sys

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

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


async def main():
    client = TelegramClient("parser", API_ID, API_HASH)
    await client.start()
    logger.info("Successfully connected!")
    await client.disconnect()

import asyncio
asyncio.run(main())