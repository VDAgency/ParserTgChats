import aiosqlite
import os
from dotenv import load_dotenv
import time

# Загрузка переменных окружения
load_dotenv()

async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                update_id INTEGER,
                message_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                chat_type TEXT,
                sender_id INTEGER,
                first_name TEXT,
                username TEXT,
                date TEXT,
                text TEXT,
                parsed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def save_message(update_id, message_id, chat_id, chat_type, sender_id, first_name, username, date, text):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT OR IGNORE INTO messages (update_id, message_id, chat_id, chat_type, sender_id, first_name, username, date, text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (update_id, message_id, chat_id, chat_type, sender_id, first_name, username, date, text))
        await db.commit()

async def is_message_processed(message_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE message_id = ?", (message_id,))
        count = await cursor.fetchone()
        return count[0] > 0

async def get_last_parsed_date(chat_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT MAX(date) FROM messages WHERE chat_id = ?", (chat_id,))
        result = await cursor.fetchone()
        return result[0] if result[0] else None

async def get_unprocessed_messages():
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT * FROM messages WHERE processed IS NULL")
        return await cursor.fetchall()

# Новая функция для чтения сообщения по message_id
async def get_message_by_id(message_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT update_id, message_id, chat_id, chat_type, sender_id, first_name, username, date, text
            FROM messages WHERE message_id = ?
        """, (message_id,))
        result = await cursor.fetchone()
        if result:
            return {
                "update_id": result[0],
                "message_id": result[1],
                "chat_id": result[2],
                "chat_type": result[3],
                "sender_id": result[4],
                "first_name": result[5],
                "username": result[6],
                "date": result[7],
                "text": result[8],
            }
        return None

# Инициализация базы данных при запуске
if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
