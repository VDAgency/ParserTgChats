import asyncio
import logging
import os
import sys
import uvicorn
from bot_instance import bot
from aiogram import Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from telethon.tl.types import PeerChannel, PeerChat
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import UserAlreadyParticipantError, FloodWaitError
from telethon.errors import ChannelInvalidError, ChannelPrivateError, ChannelPublicGroupNaError

from receiver import app
from client_instance import client
from dotenv import load_dotenv
from states import ChatStates, KeywordStates
from parser import get_entity_or_fail, start_client, stop_client, send_test_message
from database import init_db, add_user_chat, delete_user_chat, is_user_chat_exists, get_user_chats, get_all_tracked_chats
from database import add_keywords, delete_keyword, get_user_keywords_by_type, get_all_keywords_by_type
from receiver import check_health


# Загружаем .env
load_dotenv()
ADMINS = list(map(int, os.getenv("ADMINS", "").split(",")))

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

# Создаем экземпляры бота и диспетчера
dp = Dispatcher()


# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    if user_id in ADMINS:
        await message.answer("Привет, админ! 👑\nТы получил доступ к административному интерфейсу.")
        # Здесь будет логика для админов
        await admin_logic_start(message)
    else:
        await message.answer(
            "Привет! 🤖\nДобро пожаловать в сервис парсинга телеграмм чатов на интересующие вас тематики.\n"
            "На данный момент сервис находится в стадии тестирования.\n"
            "Для более подробной информации можете обратиться к разработчику @CryptoSamara")
        # Здесь будет логика для обычных пользователей


async def admin_logic_start(message: Message):
    first_name = message.from_user.first_name

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Работа с чатами", callback_data="working_chats")],
        [InlineKeyboardButton(text="🔑 Ключевые слова", callback_data="working_keywords")]
    ])

    # Формируем сообщение
    text = (
        f"Привет, <b>{first_name}</b>!\n"
        "На сегодняшний день функционал данного бота-парсера следующий:\n\n"
        "1. Можно добавлять и удалять чаты, из которых необходимо парсить сообщения.\n"
        "Также можно просматривать добавленные чаты.\n\n"
        "2. Можно добавлять и удалять ключевые слова, по которым парсер фильтрует сообщения.\n"
        "Эти сообщения будут пересылаться в группу для дальнейшей работы.\n"
        "Можно просмотреть список текущих ключевых слов и управлять ими."
    )

    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "working_chats")
async def working_chats(callback: CallbackQuery, state: FSMContext):
    first_name = callback.from_user.first_name

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat"),
            InlineKeyboardButton(text="➖ Удалить чат", callback_data="remove_chat")
        ],
        [InlineKeyboardButton(text="📋 Мои чаты", callback_data="list_chats")],
        [InlineKeyboardButton(text="📋 Все подключенные чаты", callback_data="list_all_chats")]
    ])

    # Формируем сообщение
    text = (
        f"Итак, <b>{first_name}</b>!\n"
        "На данный момент функционал по работе с чатами следующий:\n\n"
        "• Добавление или удаление чата, из которого необходимо парсить сообщения.\n"
        "• Просмотр списка чатов, которые ты добавил лично\n"
        "• Просмотр всего списка чатов, которые были добавлены тобой или другими администраторами данного бота-парсера."
    )

    await callback.message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "working_keywords")
async def working_keywords(callback: CallbackQuery, state: FSMContext):
    first_name = callback.from_user.first_name

    # Создаём инлайн-кнопки (две колонки)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅➕ Позитивные", callback_data="add_keywords"),
            InlineKeyboardButton(text="❌➕ Негативные", callback_data="add_negative_keywords")
        ],
        [
            InlineKeyboardButton(text="✅📋 Список позитивных", callback_data="list_keywords"),
            InlineKeyboardButton(text="❌📋 Список негативных", callback_data="list_negative_keywords")
        ],
        [
            InlineKeyboardButton(text="✅📋 Все позитивные (всех)", callback_data="list_all_keywords"),
            InlineKeyboardButton(text="❌📋 Все негативные (всех)", callback_data="list_all_negative_keywords")
        ],
        [
            InlineKeyboardButton(text="✅➖ Удалить позитивные", callback_data="remove_keywords"),
            InlineKeyboardButton(text="❌➖ Удалить негативные", callback_data="remove_negative_keywords")
        ],
    ])

    # Формируем сообщение
    text = (
        f"<b>{first_name}</b>!\n"
        "В данном разделе ты можешь работать с ключевыми словами:\n\n"
        "✅ <b>Позитивные</b> — по которым бот будет ловить сообщения.\n"
        "❌ <b>Негативные</b> — при их наличии в тексте бот пропустит сообщение.\n\n"
        "Ты можешь:\n"
        "• Добавить ключевое слово, или добавить сразу несколько ключевых слов или фраз, "
        "разделив их запятой или абзацем, начав с новой строки.\n"
        "• Удалить ключевое слово или фразу из списка ключевых слов, но удаление возможно только по одному слову "
        "или одной фразе из нескольких слов.\n"
    )

    await callback.message.answer(text, reply_markup=keyboard)



@dp.callback_query(F.data == "add_chat")
async def handle_add_chat(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Пришлите username (@имячата) или ссылку на Telegram-чат, который вы хотите добавить.")
    await state.set_state(ChatStates.waiting_for_chat_input)

@dp.message(ChatStates.waiting_for_chat_input)
async def process_chat_input(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    user_id = message.from_user.id

    # Парсим username
    if "t.me/" in raw_input:
        username = raw_input.split("t.me/")[-1].replace("/", "").strip()
    elif raw_input.startswith("@"):
        username = raw_input[1:]
    else:
        await message.answer("⚠️ Пожалуйста, пришлите корректный username (@имя) или ссылку.")
        return

    # Получаем chat_id через Telethon userbot
    try:
        entity = await get_entity_or_fail(username)
        chat_id = entity.id
    except Exception as e:
        logger.error(f"Ошибка при получении entity для @{username}: {e}")
        await message.answer(f"❌ Не удалось найти чат по имени @{username}.\nОшибка: {str(e)}")
        return

    # 👉 Пробуем вступить в группу перед записью в базу
    joined = await join_channel_if_needed(username)
    if not joined:
        await message.answer(f"❌ Не удалось присоединиться к @{username}. Убедитесь, что это открытая группа.")
        return
    
    # Сохраняем в базу
    await add_user_chat(user_id=user_id, chat_id=chat_id)

    await message.answer(f"✅ Чат <b>@{username}</b> добавлен для парсинга.")
    await state.clear()


async def join_channel_if_needed(username: str) -> bool:
    """
    Присоединяет юзер-бота к публичному каналу/группе, если он ещё не состоит в нём.
    :param username: Имя канала без @
    :return: True если успешно присоединился или уже состоит, False если ошибка
    """
    try:
        await client(JoinChannelRequest(username))
        logging.info(f"✅ Юзербот вступил в @{username}")
        return True

    except UserAlreadyParticipantError:
        logging.info(f"ℹ️ Юзербот уже состоит в @{username}")
        return True

    except FloodWaitError as e:
        logging.warning(f"⏳ FloodWaitError: нужно подождать {e.seconds} секунд перед вступлением в @{username}")
        await asyncio.sleep(e.seconds + 1)  # на всякий случай +1 секунда
        try:
            await client(JoinChannelRequest(username))
            logging.info(f"✅ Повторная попытка успешна. Юзербот вступил в @{username}")
            return True
        except Exception as retry_error:
            logging.error(f"❌ Ошибка при повторной попытке вступить в @{username}: {retry_error}")
            return False

    except Exception as e:
        logging.warning(f"❌ Не удалось вступить в @{username}: {e}")
        return False



@dp.callback_query(F.data == "remove_chat")
async def handle_remove_chat(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Пришлите username (@имячата) или ссылку на Telegram-чат, который вы хотите удалить.")
    await state.set_state(ChatStates.waiting_for_chat_delete)

@dp.message(ChatStates.waiting_for_chat_delete)
async def process_chat_delete(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    user_id = message.from_user.id

    if "t.me/" in raw_input:
        username = raw_input.split("t.me/")[-1].replace("/", "").strip()
    elif raw_input.startswith("@"):
        username = raw_input[1:]
    else:
        await message.answer("⚠️ Пожалуйста, пришлите корректный username (@имя) или ссылку.")
        return

    try:
        entity = await get_entity_or_fail(username)
        chat_id = entity.id
    except Exception as e:
        await message.answer(f"❌ Не удалось найти чат по имени @{username}.\nОшибка: {str(e)}")
        return

    exists = await is_user_chat_exists(user_id, chat_id)
    if not exists:
        await message.answer(f"ℹ️ Чат @{username} не найден в вашем списке.")
        await state.clear()
        return

    await delete_user_chat(user_id, chat_id)
    await message.answer(f"✅ Чат @{username} успешно удалён из вашего списка.")
    await state.clear()


@dp.callback_query(F.data == "list_chats")
async def list_user_chats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chats = await get_user_chats(user_id)

    if not chats:
        await callback.message.answer("У тебя пока нет добавленных чатов.")
        return

    text = "<b>📋 Список добавленных чатов:</b>\n\n"

    for i, chat_id in enumerate(chats, start=1):
        try:
            entity = await client.get_entity(PeerChannel(chat_id))
            title = getattr(entity, "title", None)
            username = getattr(entity, "username", None)
            link = f"https://t.me/{username}" if username else ""
        except (ChannelInvalidError, ChannelPrivateError, ChannelPublicGroupNaError):
            title = "❌ Чат недоступен"
            link = ""
        except Exception as e:
            title = f"⚠️ Ошибка: {str(e)}"
            link = ""

        # Формируем строку для каждого чата
        if link:
            text += f"{i}. <b>{title}</b> — <a href='{link}'>ссылка</a>\n"
        else:
            text += f"{i}. <b>{title}</b> (ID: <code>{chat_id}</code>)\n"

    await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@dp.callback_query(F.data == "list_all_chats")
async def list_all_chats(callback: types.CallbackQuery):
    chats = await get_all_tracked_chats()

    if not chats:
        await callback.message.answer("Нет добавленных чатов.")
        return

    text = "<b>Список всех добавленных чатов:</b>\n\n"
    for i, chat_id in enumerate(chats, start=1):
        try:
            entity = await client.get_entity(PeerChannel(chat_id))
            title = getattr(entity, "title", None)
            username = getattr(entity, "username", None)
            link = f"https://t.me/{username}" if username else ""
        except (ChannelInvalidError, ChannelPrivateError, ChannelPublicGroupNaError):
            title = "❌ Чат недоступен"
            link = ""
        except Exception as e:
            title = f"⚠️ Ошибка: {str(e)}"
            link = ""

        if link:
            text += f"{i}. <b>{title}</b> — <a href='{link}'>ссылка</a>\n"
        else:
            text += f"{i}. <b>{title}</b> (ID: <code>{chat_id}</code>)\n"

    await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)



@dp.callback_query(F.data == "add_keywords")
async def handle_add_keywords(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Пришли ключевые слова или фразы, которые ты хочешь добавить.\n\n"
        "Можно сразу несколько:\n"
        "• через запятую → `окна, пластиковые окна`\n"
        "• или с новой строки:\n`доставка\nмонтаж`\n\n"
        "Все они будут добавлены в базу для отслеживания.",
        parse_mode="Markdown"
    )
    await state.set_state(KeywordStates.waiting_for_keywords_input)


@dp.message(KeywordStates.waiting_for_keywords_input)
async def process_keywords_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_input = message.text.strip()

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить еще", callback_data="add_keywords")],
        [InlineKeyboardButton(text="Назад", callback_data="working_keywords")]
    ])
    
    if not raw_input:
        await message.answer("⚠️ Сообщение пустое. Пожалуйста, отправь хотя бы одно ключевое слово.")
        return

    added = await add_keywords(user_id, raw_input, is_negative=False)

    if not added:
        await message.answer("⚠️ Не удалось добавить ключевые слова. Возможно, все строки были пустыми.")
    else:
        formatted = "\n".join(f"• <code>{kw}</code>" for kw in added)
        await message.answer(f"✅ Добавлены следующие ключевые слова:\n\n{formatted}", reply_markup=keyboard, parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "remove_keywords")
async def handle_remove_keywords(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✂️ Пришли ключевое слово или фразу, которую ты хочешь удалить из отслеживания.\n\n"
        "Удаление возможно только по одному слову или фразе за раз."
    )
    await state.set_state(KeywordStates.waiting_for_keyword_deletion)


@dp.message(KeywordStates.waiting_for_keyword_deletion)
async def process_keyword_deletion(message: Message, state: FSMContext):
    user_id = message.from_user.id
    keyword = message.text.strip()

    if not keyword:
        await message.answer("⚠️ Введи ключевое слово или фразу, которую нужно удалить.")
        return

    removed = await delete_keyword(user_id, keyword)

    if removed:
        await message.answer(f"🗑️ Ключевое слово <code>{keyword}</code> успешно удалено.", parse_mode="HTML")
    else:
        await message.answer(f"❌ Ключевое слово <code>{keyword}</code> не найдено в списке.", parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "list_keywords")
async def handle_list_keywords(callback: CallbackQuery):
    user_id = callback.from_user.id
    keywords = await get_user_keywords_by_type(user_id, keyword_type="positive")

    if not keywords:
        await callback.message.answer("🔍 У тебя пока нет добавленных <b>положительных</b> ключевых слов.")
        return

    text = "🔑 Твои <b>положительные</b> ключевые слова:\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "list_all_keywords")
async def handle_list_all_keywords(callback: CallbackQuery):
    keywords = await get_all_keywords_by_type("positive")

    if not keywords:
        await callback.message.answer("🔍 Пока ни один админ не добавил <b>положительные</b> ключевые слова.")
        return

    text = "🔑 Все <b>положительные</b> ключевые слова (всех админов):\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback.message.answer(text, parse_mode="HTML")



@dp.callback_query(F.data == "add_negative_keywords")
async def ask_negative_keywords(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Введите <b>негативные</b> ключевые слова или фразы.\n\n"
        "Можно несколько:\n"
        "• через запятую → <code>сдаётся, продаётся</code>\n"
        "• или с новой строки:\n<code>в наличии\nв аренду</code>",
        parse_mode="HTML"
    )
    await state.set_state(KeywordStates.waiting_for_negative_keywords)


@dp.message(KeywordStates.waiting_for_negative_keywords)
async def save_negative_keywords(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_input = message.text.strip()

    if not raw_input:
        await message.answer("⚠️ Сообщение пустое. Пожалуйста, отправь хотя бы одно ключевое слово.")
        return

    added = await add_keywords(user_id, raw_input, is_negative=True)

    if not added:
        await message.answer("⚠️ Ни одного ключевого слова не было добавлено.")
    else:
        formatted = "\n".join(f"• <code>{kw}</code>" for kw in added)
        await message.answer(f"🚫 Добавлены следующие <b>негативные</b> ключевые слова:\n\n{formatted}", parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "remove_negative_keywords")
async def handle_remove_negative_keywords(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✂️ Пришли <b>негативное</b> ключевое слово или фразу, которую ты хочешь удалить из отслеживания.\n\n"
        "Удаление возможно только по одному слову или фразе за раз."
    )
    await state.set_state(KeywordStates.waiting_for_negative_keyword_deletion)


@dp.message(KeywordStates.waiting_for_negative_keyword_deletion)
async def process_keyword_negative_deletion(message: Message, state: FSMContext):
    user_id = message.from_user.id
    keyword = message.text.strip()

    if not keyword:
        await message.answer("⚠️ Введи <b>негативное</b> ключевое слово или фразу, которую нужно удалить.")
        return

    removed = await delete_keyword(user_id, keyword)

    if removed:
        await message.answer(f"🗑️ Ключевое слово <code>{keyword}</code> успешно удалено.", parse_mode="HTML")
    else:
        await message.answer(f"❌ Ключевое слово <code>{keyword}</code> не найдено в списке.", parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "list_negative_keywords")
async def handle_list_negative_keywords(callback: CallbackQuery):
    user_id = callback.from_user.id
    keywords = await get_user_keywords_by_type(user_id, keyword_type="negative")

    if not keywords:
        await callback.message.answer("🔍 У тебя пока нет добавленных <b>негативных</b> ключевых слов.")
        return

    text = "🔑 Твои <b>негативные</b> ключевые слова:\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "list_all_negative_keywords")
async def handle_list_all_negative_keywords(callback: CallbackQuery):
    keywords = await get_all_keywords_by_type("negative")

    if not keywords:
        await callback.message.answer("🔍 Пока ни один админ не добавил <b>негативные</b> ключевые слова.")
        return

    text = "🔑 Все <b>положительные</b> ключевые слова (всех админов):\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback.message.answer(text, parse_mode="HTML")



# Функция для запуска FastAPI
async def run_fastapi():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

# Функция запуска бота
async def main():
    
    await start_client()
    await send_test_message()
    
    # Запускаем polling бота и парсер параллельно
    polling_task = asyncio.create_task(dp.start_polling(bot))
    # parsing_task = asyncio.create_task(parse_loop())

    # Запускаем FastAPI сервер в отдельной задаче
    fastapi_task = asyncio.create_task(run_fastapi())
    
    # Запускаем периодическую проверку сервера
    # health_task = asyncio.create_task(check_health())
    
    try:
        # Ожидаем завершения polling_task (пока бот жив)
        await polling_task
    except asyncio.CancelledError:
        # Когда бот остановится, останавливаем парсер, сервер и клиента
        # parsing_task.cancel()
        fastapi_task.cancel()
        # health_task.cancel()
        await stop_client()
        raise

async def app_start():
    await init_db()
    await main()

if __name__ == "__main__":
    import asyncio
    asyncio.run(app_start())
