import logging
import os
import sys
from telethon import TelegramClient
from telethon.tl.types import User
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PhoneMigrateError
from dotenv import load_dotenv


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