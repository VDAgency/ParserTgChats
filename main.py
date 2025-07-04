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
from telethon.errors import ChannelInvalidError, ChannelPrivateError, ChannelPublicGroupNaError

from receiver import app
from client_instance import client
from dotenv import load_dotenv
from states import ChatStates
from parser import get_entity_or_fail, start_client, stop_client, parse_loop, send_test_message
from database import init_db, add_user_chat, delete_user_chat, is_user_chat_exists, get_user_chats, get_all_tracked_chats
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
        [InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat")],
        [InlineKeyboardButton(text="➖ Удалить чат", callback_data="remove_chat")],
        [InlineKeyboardButton(text="📋 Мои чаты", callback_data="list_chats")],
        [InlineKeyboardButton(text="📋 Все подключенные чаты", callback_data="list_all_chats")]
    ])

    # Формируем сообщение
    text = (
        f"Привет, <b>{first_name}</b>!\n"
        "На сегодняшний день весь функционал сводится к:\n\n"
        "• добавлению и удалению чата,\n"
        "из которого необходимо парсить сообщения."
    )

    await message.answer(text, reply_markup=keyboard)


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
        await message.answer(f"❌ Не удалось найти чат по имени @{username}.\nОшибка: {str(e)}")
        return

    # Сохраняем в базу
    await add_user_chat(user_id=user_id, chat_id=chat_id)

    await message.answer(f"✅ Чат <b>@{username}</b> добавлен для парсинга.")
    await state.clear()


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

    text = "<b>Список добавленных чатов:</b>\n\n"

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
    parsing_task = asyncio.create_task(parse_loop())

    # Запускаем FastAPI сервер в отдельной задаче
    fastapi_task = asyncio.create_task(run_fastapi())
    
    # Запускаем периодическую проверку сервера
    # health_task = asyncio.create_task(check_health())
    
    try:
        # Ожидаем завершения polling_task (пока бот жив)
        await polling_task
    except asyncio.CancelledError:
        # Когда бот остановится, останавливаем парсер, сервер и клиента
        parsing_task.cancel()
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
