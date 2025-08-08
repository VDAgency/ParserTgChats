import logging
import aiosqlite
import os
import sys
from pymorphy3 import MorphAnalyzer
from dotenv import load_dotenv
import time

# Загрузка переменных окружения
load_dotenv()

# Создаём экземпляр MorphAnalyzer для лемматизации
morph = MorphAnalyzer()

def lemmatize_word(word):
    # Лемматизация слова с использованием pymorphy2
    return morph.parse(word)[0].normal_form


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
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN original_message_id INTEGER")
        except Exception as e:
            logger.info(f"[init_db] Колонка original_message_id уже существует или не может быть добавлена: {e}")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, chat_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                is_negative INTEGER DEFAULT 0,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, keyword)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS keywords_lemma (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                word TEXT NOT NULL,
                lemma TEXT NOT NULL,
                extra_info TEXT DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()


async def save_message(
        update_id, message_id, chat_id, chat_type,
        sender_id, first_name, username, date, text, original_message_id=None
    ):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT OR IGNORE INTO messages (
                update_id, message_id, chat_id, chat_type,
                sender_id, first_name, username, date, text, original_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            update_id, message_id, chat_id, chat_type,
            sender_id, first_name, username, date, text, original_message_id
        ))
        await db.commit()

async def is_message_processed(message_id):
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,))
        return await cursor.fetchone() is not None

async def mark_message_as_processed(message_id):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)", (message_id,))
        await db.commit()

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
            SELECT update_id, message_id, chat_id, chat_type, sender_id, first_name, username, date, text, original_message_id
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
                "original_message_id": result[9],
            }
        return None


# # Добавление нового чата для пользователя
# async def add_user_chat(user_id, chat_id):
#     async with aiosqlite.connect("bot.db") as db:
#         await db.execute("""
#             INSERT OR IGNORE INTO user_chats (user_id, chat_id)
#             VALUES (?, ?)
#         """, (user_id, chat_id))
#         await db.commit()


# Функция для добавления чата в базу данных с учётом префикса для супергрупп/каналов
async def add_user_chat(user_id, chat_id):
    # Если это канал или супергруппа, добавляем префикс '-100'
    if chat_id > 0:  # Для чатов с положительным chat_id (обычно это личные чаты), ничего не меняем
        chat_id = f"-100{chat_id}"  # Добавляем префикс для супергрупп и каналов
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_chats (user_id, chat_id)
            VALUES (?, ?)
        """, (user_id, chat_id))
        await db.commit()
    logger.info(f"Chat {chat_id} added to database for user {user_id}.")


# Удаление чата для пользователя с учётом префикса для супергрупп и каналов
async def delete_user_chat(user_id: int, chat_id: int):
    # Если chat_id не начинается с '-100', добавляем префикс
    if not str(chat_id).startswith('-100'):
        chat_id = f"-100{chat_id}"

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        await db.commit()

    logger.info(f"Chat {chat_id} deleted from database for user {user_id}.")


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
    # Если чат не начинается с "-100", добавляем этот префикс (для супергрупп и каналов)
    if not str(chat_id).startswith('-100'):
        chat_id = f"-100{chat_id}"
    
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




# Функция добавления ключевых слов (по одному или списком)
async def add_keywords(user_id: int, raw_text: str, is_negative: bool = False) -> list[str]:
    """
    Добавляет ключевые слова или фразы, разделённые запятыми или переносами строк.
    Возвращает список добавленных (уникальных) ключевых слов.
    """
    candidates = [word.strip() for part in raw_text.split("\n") for word in part.split(",")]
    keywords = list({kw.lower() for kw in candidates if kw})

    if not keywords:
        return []

    added = []
    async with aiosqlite.connect("bot.db") as db:
        for kw in keywords:
            try:
                await db.execute(
                    "INSERT INTO keywords (user_id, keyword, is_negative) VALUES (?, ?, ?)",
                    (user_id, kw, int(is_negative))
                )
                added.append(kw)
            except aiosqlite.IntegrityError:
                continue
        await db.commit()

    return added


# Функция удаления ключевого слова
async def delete_keyword(user_id: int, keyword: str) -> bool:
    """
    Удаляет ключевое слово. Возвращает True, если что-то было удалено.
    """
    kw = keyword.strip().lower()
    if not kw:
        return False

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            DELETE FROM keywords WHERE user_id = ? AND keyword = ?
        """, (user_id, kw))
        await db.commit()
        return cursor.rowcount > 0


# # Функция получения всех ключевых слов пользователя
# async def get_user_keywords(user_id: int) -> list[str]:
#     async with aiosqlite.connect("bot.db") as db:
#         cursor = await db.execute("""
#             SELECT keyword FROM keywords WHERE user_id = ? ORDER BY added_at DESC
#         """, (user_id,))
#         rows = await cursor.fetchall()
#         return [row[0] for row in rows]


# Функция получения позитивных и негативных ключевых слов и фраз пользователя
async def get_user_keywords_by_type(user_id: int, keyword_type: str) -> list[str]:
    is_negative = 1 if keyword_type == "negative" else 0
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT keyword FROM keywords
            WHERE user_id = ? AND is_negative = ?
            ORDER BY added_at DESC
        """, (user_id, is_negative))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# Функция получения всех ключевых слов парсинга
async def get_all_keywords() -> list[str]:
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("SELECT DISTINCT keyword FROM keywords")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# Получение всех ключевых слов (от всех админов) по типу: "positive" или "negative"
async def get_all_keywords_by_type(keyword_type: str) -> list[str]:
    is_negative = 1 if keyword_type == "negative" else 0
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT DISTINCT keyword FROM keywords
            WHERE is_negative = ?
            ORDER BY added_at DESC
        """, (is_negative,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]




# Функция для получения всех ключевых слов для сравнения при сохранении
async def check_keywords_match(text: str) -> bool:
    if not text:
        return False

    text_lower = text.lower()

    # Получаем списки
    positive_keywords = await get_keywords_by_type(is_negative=False)
    negative_keywords = await get_keywords_by_type(is_negative=True)

    # Проверяем наличие позитивных фраз
    has_positive = any(keyword in text_lower for keyword in positive_keywords)

    # Если позитивных нет — сразу False
    if not has_positive:
        return False

    # Если есть негативные — отклоняем
    has_negative = any(keyword in text_lower for keyword in negative_keywords)
    if has_negative:
        return False

    return True


# Функция получения позитивных и негативных ключевых слов и фраз
async def get_keywords_by_type(is_negative: bool) -> list[str]:
    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute(
            "SELECT DISTINCT LOWER(keyword) FROM keywords WHERE is_negative = ?",
            (1 if is_negative else 0,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]











# async def add_intent_keywords_to_db(user_id, keywords):
#     async with aiosqlite.connect("bot.db") as db:
#         added_keywords = []
#         failed_keywords = []

#         # Максимальное количество попыток для каждой вставки
#         max_retries = 3

#         for keyword in keywords:
#             retries = 0
#             success = False

#             # Проверяем, существует ли слово в базе
#             existing_keywords = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("intent",))
#             existing_keywords = await existing_keywords.fetchall()
#             existing_keywords = [kw[0] for kw in existing_keywords]

#             if keyword in existing_keywords:
#                 logger.info(f"Keyword '{keyword}' already exists in the database.")
#                 failed_keywords.append(keyword)
#                 continue  # Пропускаем это слово, если оно уже существует

#             # Лемматизируем слово для записи в графу 'lemma'
#             lemmatized_keyword = lemmatize_word(keyword)

#             # Пробуем записать слово в базу с до 3-х попыток
#             while retries < max_retries and not success:
#                 try:
#                     # Вставляем слово в базу данных
#                     await db.execute("""
#                         INSERT INTO keywords_lemma (category, word, lemma)
#                         VALUES (?, ?, ?)
#                     """, ("intent", keyword, lemmatized_keyword))

#                     # Если вставка прошла успешно
#                     success = True
#                     added_keywords.append(keyword)

#                 except Exception as e:
#                     retries += 1
#                     logger.error(f"Error adding keyword '{keyword}': {str(e)}. Retry {retries}/{max_retries}.")
#                     if retries == max_retries:
#                         logger.error(f"Failed to add keyword '{keyword}' after {max_retries} attempts.")
#                         failed_keywords.append(keyword)
#                         break
#                     await asyncio.sleep(2)  # Ожидаем перед повторной попыткой

#         await db.commit()

#         # Если есть добавленные ключевые слова, отправляем сообщение
#         if added_keywords:
#             formatted_added = "\n".join(f"• <code>{kw}</code>" for kw in added_keywords)
#             logger.info(f"Added keywords: {formatted_added}")

#         # Если есть неудачные ключевые слова, сообщаем о них
#         if failed_keywords:
#             formatted_failed = "\n".join(f"• <code>{kw}</code>" for kw in failed_keywords)
#             logger.info(f"Failed to add keywords: {formatted_failed}")
#             return None, failed_keywords

#         return added_keywords, failed_keywords


# === Функции добавления ключевых слов умного парсинга в базу данных ===

async def add_intent_keywords_to_db(user_id, keywords):
    async with aiosqlite.connect("bot.db") as db:
        added_keywords = []
        already_existing = []

        # Получаем все существующие слова в категории intent
        existing = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("intent",))
        existing_words = {row[0].strip().lower() for row in await existing.fetchall()}

        # Определим какие слова уже есть
        for keyword in keywords:
            keyword_lower = keyword.strip().lower()
            if keyword_lower in existing_words:
                already_existing.append(keyword)

        # Если все слова уже существуют — сразу выходим
        if len(already_existing) == len(keywords):
            return [], already_existing

        # Добавим только те, которых ещё нет
        for keyword in keywords:
            if keyword in already_existing:
                continue

            keyword_cleaned = keyword.strip().lower()
            lemmatized = lemmatize_word(keyword_cleaned).lower()  # <- нормализуем лемму

            try:
                await db.execute("""
                    INSERT INTO keywords_lemma (category, word, lemma)
                    VALUES (?, ?, ?)
                """, ("intent", keyword_cleaned, lemmatized))  # <- сохраняем в нижнем регистре
                added_keywords.append(keyword)
            except Exception as e:
                logging.error(f"[add_intent_keywords_to_db] Ошибка при добавлении '{keyword}': {str(e)}")
                already_existing.append(keyword)

        await db.commit()
        return added_keywords, already_existing


async def add_object_keywords_to_db(user_id, keywords):
    async with aiosqlite.connect("bot.db") as db:
        added_keywords = []
        already_existing = []

        # Получаем все существующие слова в категории 'object'
        existing = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("object",))
        existing_words = {row[0].strip().lower() for row in await existing.fetchall()}

        # Определим какие слова уже есть
        for keyword in keywords:
            keyword_lower = keyword.strip().lower()
            if keyword_lower in existing_words:
                already_existing.append(keyword)

        # Если все слова уже существуют — сразу выходим
        if len(already_existing) == len(keywords):
            return [], already_existing

        # Добавим только те, которых ещё нет
        for keyword in keywords:
            if keyword in already_existing:
                continue

            keyword_cleaned = keyword.strip().lower()
            lemmatized = lemmatize_word(keyword_cleaned).lower()

            try:
                await db.execute("""
                    INSERT INTO keywords_lemma (category, word, lemma)
                    VALUES (?, ?, ?)
                """, ("object", keyword_cleaned, lemmatized))
                added_keywords.append(keyword)
            except Exception as e:
                logging.error(f"[add_object_keywords_to_db] Ошибка при добавлении '{keyword}': {str(e)}")
                already_existing.append(keyword)

        await db.commit()
        return added_keywords, already_existing


async def add_region_keywords_to_db(user_id, keywords):
    async with aiosqlite.connect("bot.db") as db:
        added_keywords = []
        already_existing = []

        # Получаем все существующие слова в категории 'region'
        existing = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("region",))
        existing_words = {row[0].strip().lower() for row in await existing.fetchall()}

        # Определим какие слова уже есть
        for keyword in keywords:
            keyword_lower = keyword.strip().lower()
            if keyword_lower in existing_words:
                already_existing.append(keyword)

        # Если все слова уже существуют — сразу выходим
        if len(already_existing) == len(keywords):
            return [], already_existing

        # Добавим только те, которых ещё нет
        for keyword in keywords:
            if keyword in already_existing:
                continue

            keyword_cleaned = keyword.strip().lower()
            lemmatized = lemmatize_word(keyword_cleaned).lower()

            try:
                await db.execute("""
                    INSERT INTO keywords_lemma (category, word, lemma)
                    VALUES (?, ?, ?)
                """, ("region", keyword_cleaned, lemmatized))
                added_keywords.append(keyword)
            except Exception as e:
                logging.error(f"[add_region_keywords_to_db] Ошибка при добавлении '{keyword}': {str(e)}")
                already_existing.append(keyword)

        await db.commit()
        return added_keywords, already_existing


async def add_beach_keywords_to_db(user_id, keywords):
    async with aiosqlite.connect("bot.db") as db:
        added_keywords = []
        already_existing = []

        # Получаем все существующие слова в категории 'beach'
        existing = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("beach",))
        existing_words = {row[0].strip().lower() for row in await existing.fetchall()}

        # Определим какие слова уже есть
        for keyword in keywords:
            keyword_lower = keyword.strip().lower()
            if keyword_lower in existing_words:
                already_existing.append(keyword)

        # Если все слова уже существуют — сразу выходим
        if len(already_existing) == len(keywords):
            return [], already_existing

        # Добавим только те, которых ещё нет
        for keyword in keywords:
            if keyword in already_existing:
                continue

            keyword_cleaned = keyword.strip().lower()
            lemmatized = lemmatize_word(keyword_cleaned).lower()

            try:
                await db.execute("""
                    INSERT INTO keywords_lemma (category, word, lemma)
                    VALUES (?, ?, ?)
                """, ("beach", keyword_cleaned, lemmatized))
                added_keywords.append(keyword)
            except Exception as e:
                logging.error(f"[add_beach_keywords_to_db] Ошибка при добавлении '{keyword}': {str(e)}")
                already_existing.append(keyword)

        await db.commit()
        return added_keywords, already_existing


async def add_bedrooms_keywords_to_db(user_id, keywords):
    async with aiosqlite.connect("bot.db") as db:
        added_keywords = []
        already_existing = []

        # Получаем все существующие слова в категории 'bedrooms'
        existing = await db.execute("SELECT word FROM keywords_lemma WHERE category = ?", ("bedrooms",))
        existing_words = {row[0].strip().lower() for row in await existing.fetchall()}

        # Определим какие слова уже есть
        for keyword in keywords:
            keyword_lower = keyword.strip().lower()
            if keyword_lower in existing_words:
                already_existing.append(keyword)

        # Если все слова уже существуют — сразу выходим
        if len(already_existing) == len(keywords):
            return [], already_existing

        # Добавим только те, которых ещё нет
        for keyword in keywords:
            if keyword in already_existing:
                continue

            keyword_cleaned = keyword.strip().lower()
            lemmatized = lemmatize_word(keyword_cleaned).lower()

            try:
                await db.execute("""
                    INSERT INTO keywords_lemma (category, word, lemma)
                    VALUES (?, ?, ?)
                """, ("bedrooms", keyword_cleaned, lemmatized))
                added_keywords.append(keyword)
            except Exception as e:
                logging.error(f"[add_bedrooms_keywords_to_db] Ошибка при добавлении '{keyword}': {str(e)}")
                already_existing.append(keyword)

        await db.commit()
        return added_keywords, already_existing



# === Функции удаления ключевых слов умного парсинга в базу данных ===

async def delete_intent_keyword_from_db(user_id: int, keyword: str) -> bool:
    keyword = keyword.strip().lower()  # Приводим входное слово к нижнему регистру

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id FROM keywords_lemma
            WHERE category = ? AND lower(word) = ?
        """, ("intent", keyword))
        row = await cursor.fetchone()
        print(f"Searching for keyword: {keyword}, row found: {row}")
        
        if row:
            await db.execute("DELETE FROM keywords_lemma WHERE id = ?", (row[0],))
            await db.commit()
            return True

        return False

async def delete_object_keyword_from_db(user_id: int, keyword: str) -> bool:
    keyword = keyword.strip().lower()

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id FROM keywords_lemma
            WHERE category = ? AND lower(word) = ?
        """, ("object", keyword))
        row = await cursor.fetchone()
        print(f"[OBJECT] Searching for keyword: {keyword}, row found: {row}")

        if row:
            await db.execute("DELETE FROM keywords_lemma WHERE id = ?", (row[0],))
            await db.commit()
            return True

        return False


async def delete_region_keyword_from_db(user_id: int, keyword: str) -> bool:
    keyword = keyword.strip().lower()

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id FROM keywords_lemma
            WHERE category = ? AND lower(word) = ?
        """, ("region", keyword))
        row = await cursor.fetchone()
        print(f"[REGION] Searching for keyword: {keyword}, row found: {row}")

        if row:
            await db.execute("DELETE FROM keywords_lemma WHERE id = ?", (row[0],))
            await db.commit()
            return True

        return False


async def delete_beach_keyword_from_db(user_id: int, keyword: str) -> bool:
    keyword = keyword.strip().lower()

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id FROM keywords_lemma
            WHERE category = ? AND lower(word) = ?
        """, ("beach", keyword))
        row = await cursor.fetchone()
        print(f"[BEACH] Searching for keyword: {keyword}, row found: {row}")

        if row:
            await db.execute("DELETE FROM keywords_lemma WHERE id = ?", (row[0],))
            await db.commit()
            return True

        return False


async def delete_bedrooms_keyword_from_db(user_id: int, keyword: str) -> bool:
    keyword = keyword.strip().lower()

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute("""
            SELECT id FROM keywords_lemma
            WHERE category = ? AND lower(word) = ?
        """, ("bedrooms", keyword))
        row = await cursor.fetchone()
        print(f"[BEDROOMS] Searching for keyword: {keyword}, row found: {row}")

        if row:
            await db.execute("DELETE FROM keywords_lemma WHERE id = ?", (row[0],))
            await db.commit()
            return True

        return False





# Инициализация базы данных при запуске
if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
