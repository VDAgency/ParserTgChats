import logging
import aiosqlite
import os
import sys
from dotenv import load_dotenv
import time

# Загрузка переменных окружения
load_dotenv()

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
        
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN sent_to_group INTEGER NOT NULL DEFAULT 0")
        except Exception as e:
            # колонка уже есть — игнорируем
            logger.info(f"[init_db] Колонка sent_to_group уже существует или не может быть добавлена: {e}")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, chat_id)
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


# Добавление нового чата для пользователя
async def add_user_chat(user_id, chat_id):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_chats (user_id, chat_id)
            VALUES (?, ?)
        """, (user_id, chat_id))
        await db.commit()

# Удаление чата для пользователя
async def delete_user_chat(user_id: int, chat_id: int):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        await db.commit()

# Получение всех чатов, связанных с пользователем
async def get_user_chats(user_id: int):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT chat_id FROM user_chats WHERE user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

# Проверяет наличие записи в таблице user_chats для заданного пользователя и чата.
# Используется, чтобы избежать дублирующей вставки или убедиться, что чат можно удалить.
# Возвращает True, если такая запись существует, иначе False.
async def is_user_chat_exists(user_id, chat_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT 1 FROM user_chats WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        result = await cursor.fetchone()
        return result is not None

# Получить все уникальные chat_id, которые кто-то добавил
async def get_all_tracked_chats():
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT DISTINCT chat_id FROM user_chats")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
    

# Инициализация базы данных при запуске
if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
