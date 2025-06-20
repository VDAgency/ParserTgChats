from telethon import TelegramClient
from dotenv import load_dotenv
import os

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

async def main():
    client = TelegramClient("parser", API_ID, API_HASH)
    await client.start()
    print("Successfully connected!")
    await client.disconnect()

import asyncio
asyncio.run(main())