import time
time.sleep(15)

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
from pymorphy3 import MorphAnalyzer

from receiver import app
from client_instance import client
from dotenv import load_dotenv
from states import ChatStates, KeywordStates, KeywordLemmaState
from parser import get_entity_or_fail, start_client, stop_client, send_test_message
from database import init_db, add_user_chat, delete_user_chat, is_user_chat_exists, get_user_chats, get_all_tracked_chats
from database import add_keywords, delete_keyword, get_user_keywords_by_type, get_all_keywords_by_type
from database import add_intent_keywords_to_db
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

# Создаём экземпляр MorphAnalyzer для лемматизации
morph = MorphAnalyzer()

def lemmatize_word(word):
    # Лемматизация слова с использованием pymorphy2
    return morph.parse(word)[0].normal_form




# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    if user_id in ADMINS:
        await message.answer("Привет, админ! 👑\nТы получил доступ к административному интерфейсу.")
        # Здесь будет логика для админов
        await admin_logic_start(message, first_name)
    else:
        await message.answer(
            "Привет! 🤖\nДобро пожаловать в сервис парсинга телеграмм чатов на интересующие вас тематики.\n"
            "На данный момент сервис находится в стадии тестирования.\n"
            "Для более подробной информации можете обратиться к разработчику @CryptoSamara")
        # Здесь будет логика для обычных пользователей


async def admin_logic_start(message: Message, first_name: str):

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


@dp.callback_query(F.data == "back_admin_logic_start")
async def back_admin_logic_start(callback_query: CallbackQuery):
    try:
        # Попытка удалить сообщение
        await callback_query.message.delete()
    except Exception as e:
        # Логируем ошибку, если не удалось удалить сообщение
        logger.error(f"Ошибка при удалении сообщения: {str(e)}")

    # Получаем имя пользователя для правильного отображения
    first_name = callback_query.from_user.first_name
    
    # Перезапускаем логику с именем пользователя
    await admin_logic_start(callback_query.message, first_name)



@dp.callback_query(F.data == "working_chats")
async def working_chats(callback_query: CallbackQuery, state: FSMContext):
    first_name = callback_query.from_user.first_name

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить чат", callback_data="add_chat"),
            InlineKeyboardButton(text="➖ Удалить чат", callback_data="remove_chat")
        ],
        [InlineKeyboardButton(text="📋 Мои чаты", callback_data="list_chats")],
        [InlineKeyboardButton(text="📋 Все подключенные чаты", callback_data="list_all_chats")],
        [InlineKeyboardButton(text="⬅️ Незад", callback_data="back_admin_logic_start")]
    ])

    # Формируем сообщение
    text = (
        f"Итак, <b>{first_name}</b>!\n"
        "На данный момент функционал по работе с чатами следующий:\n\n"
        "• Добавление или удаление чата, из которого необходимо парсить сообщения.\n"
        "• Просмотр списка чатов, которые ты добавил лично\n"
        "• Просмотр всего списка чатов, которые были добавлены тобой или другими администраторами данного бота-парсера."
    )

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "working_keywords")
async def working_keywords(callback_query: CallbackQuery, state: FSMContext):
    first_name = callback_query.from_user.first_name

    # Создаём инлайн-кнопки для выбора парсинга
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Классический парсинг", callback_data="working_keywords_classic"),
            InlineKeyboardButton(text="Умный парсинг", callback_data="working_keywords_lemma")
        ],
        [InlineKeyboardButton(text="⬅️ Незад", callback_data="back_admin_logic_start")]
    ])

    # Формируем сообщение с пояснением
    text = (
        f"<b>{first_name}</b>!\n\n"
        "Выберите тип парсинга ключевых слов:\n\n"
        "Вы можете использовать оба варианта парсинга. Сначала будет производиться поиск по классическому парсингу с точным совпадением слов и фраз. А потом будет включаться умный парсинг.\n\n"
        "🔍 <b>Классический парсинг</b> — будет работать по точному совпадению ключевых слов.\n"
        "💡 <b>Умный парсинг</b> — будет учитывать лемматизацию и отбор похожих слов для более гибкой фильтрации.\n"
    )

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard)


# Обработчик для Классического парсинга (точное совпадение)
@dp.callback_query(F.data == "working_keywords_classic")
async def working_keywords(callback_query: CallbackQuery, state: FSMContext):
    first_name = callback_query.from_user.first_name

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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data= "working_keywords")]
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

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard)


# Обработчик для Умного парсинга (с лемматизацией и похожими словами)
@dp.callback_query(F.data == "working_keywords_lemma")
async def working_keywords_lemma(callback_query: CallbackQuery, state: FSMContext):
    first_name = callback_query.from_user.first_name

    # Создаём инлайн-кнопки для работы с ключевыми словами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅➕ Намерение", callback_data="add_intent"),
            InlineKeyboardButton(text="❌➖ Намерение", callback_data="remove_intent")
        ],
        [
            InlineKeyboardButton(text="✅➕ Объект", callback_data="add_object"),
            InlineKeyboardButton(text="❌➖ Объект", callback_data="remove_object")
        ],
        [
            InlineKeyboardButton(text="✅➕ Район", callback_data="add_region"),
            InlineKeyboardButton(text="❌➖ Район", callback_data="remove_region")
        ],
        [
            InlineKeyboardButton(text="✅➕ Пляж", callback_data="add_beach"),
            InlineKeyboardButton(text="❌➖ Пляж", callback_data="remove_beach")
        ],
        [
            InlineKeyboardButton(text="✅➕ Спальни", callback_data="add_bedrooms"),
            InlineKeyboardButton(text="❌➖ Спальни", callback_data="remove_bedrooms")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data= "working_keywords")]
    ])

    # Формируем сообщение для умного парсинга
    text = (
        f"<b>{first_name}</b>!\n\n"
        "Ты в разделе умного парсинга ключевых слов. Здесь бот будет искать подходящие сообщения на основе лемматизации и поиска похожих слов.\n\n"
        "Умный парсинг поможет точно определить, что именно ты ищешь, с учётом всех нюансов в тексте.\n"
        "С помощью этого метода бот будет отслеживать слова в разных формах и учитывать их синонимы.\n\n"
        "Что ты можешь сделать:\n\n"
        "🔑 **Добавить ключевые слова:**\n"
        "• Ты можешь добавлять ключевые слова или фразы для разных категорий, например:\n"
        "  - **Намерение**: покупка, аренда, съём, покупаю и т.д.\n"
        "  - **Объект**: квартира, дом, кондоминиум и другие виды недвижимости.\n\n"
        "✔️ Если сообщение содержит ключевое слово из **Намерения** (например, 'арендую') и из **Объекта** (например, 'квартира'), оно будет подходящим для обработки.\n"
        "Эти два параметра необходимы для того, чтобы бот точно понял твой запрос и мог его обработать.\n\n"
        "🔍 **Дополнительный отбор:**\n"
        "• Ты можешь добавить и другие параметры для более точного отбора. Например,:\n"
        "  - **Районы**: Паттайя, Пхукет и т.д.\n"
        "  - **Пляжи**: Патонг, Ката и другие пляжи Тайланда.\n"
        "  - **Количество спален**: 1 спальня, 2 спальни и т.д.\n"
        "• Эти параметры будут использоваться, если они есть в базе данных и если ты хочешь более точную фильтрацию.\n\n"
        "❗ **Удаление ключевых слов:**\n"
        "• Ты можешь удалить ключевые слова или фразы, если они больше не актуальны или были ошибочно добавлены. Удаление происходит по одному слову или фразе за раз.\n\n"
        "Это мощный инструмент для более точного поиска недвижимости по твоим запросам!"
    )

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard)



@dp.callback_query(F.data == "add_chat")
async def handle_add_chat(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("✏️ Пришлите username (@имячата) или ссылку на Telegram-чат, который вы хотите добавить.")
    await state.set_state(ChatStates.waiting_for_chat_input)

@dp.message(ChatStates.waiting_for_chat_input)
async def process_chat_input(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    user_id = message.from_user.id

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить еще", callback_data="add_chat")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_chats")]
    ])
    
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

    await message.answer(f"✅ Чат <b>@{username}</b> добавлен для парсинга.", reply_markup=keyboard)
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
async def handle_remove_chat(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer("✏️ Пришлите username (@имячата) или ссылку на Telegram-чат, который вы хотите удалить.")
    await state.set_state(ChatStates.waiting_for_chat_delete)

@dp.message(ChatStates.waiting_for_chat_delete)
async def process_chat_delete(message: Message, state: FSMContext):
    raw_input = message.text.strip()
    user_id = message.from_user.id

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➖ Удалить еще", callback_data="remove_chat")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_chats")]
    ])
    
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
async def list_user_chats(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    chats = await get_user_chats(user_id)

    if not chats:
        await callback_query.message.answer("У тебя пока нет добавленных чатов.")
        return

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="working_chats")]
    ])
    
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

    await callback_query.message.delete()
    await callback_query.message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)


@dp.callback_query(F.data == "list_all_chats")
async def list_all_chats(callback_query: types.CallbackQuery):
    chats = await get_all_tracked_chats()

    if not chats:
        await callback_query.message.answer("Нет добавленных чатов.")
        return

        # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="working_chats")]
    ])
    
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

    await callback_query.message.delete()
    await callback_query.message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)



@dp.callback_query(F.data == "add_keywords")
async def handle_add_keywords(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
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
async def handle_remove_keywords(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
        "✂️ Пришли ключевое слово или фразу, которую ты хочешь удалить из отслеживания.\n\n"
        "Удаление возможно только по одному слову или фразе за раз."
    )
    await state.set_state(KeywordStates.waiting_for_keyword_deletion)


@dp.message(KeywordStates.waiting_for_keyword_deletion)
async def process_keyword_deletion(message: Message, state: FSMContext):
    user_id = message.from_user.id
    keyword = message.text.strip()

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➖ Удалить еще", callback_data="remove_keywords")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
    ])
    
    if not keyword:
        await message.answer("⚠️ Сообщение пустое. Введи ключевое слово или фразу, которую нужно удалить.")
        return

    removed = await delete_keyword(user_id, keyword)

    if removed:
        await message.answer(f"🗑️ Ключевое слово <code>{keyword}</code> успешно удалено.", reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(f"❌ Ключевое слово <code>{keyword}</code> не найдено в списке.", parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "list_keywords")
async def handle_list_keywords(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    keywords = await get_user_keywords_by_type(user_id, keyword_type="positive")

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords")]
    ])
    
    if not keywords:
        await callback_query.message.answer("🔍 У тебя пока нет добавленных <b>положительных</b> ключевых слов.")
        return

    text = "🔑 Твои <b>положительные</b> ключевые слова:\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "list_all_keywords")
async def handle_list_all_keywords(callback_query: CallbackQuery):
    keywords = await get_all_keywords_by_type("positive")

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords")]
    ])
    
    if not keywords:
        await callback_query.message.answer("🔍 Пока ни один админ не добавил <b>положительные</b> ключевые слова.")
        return

    text = "🔑 Все <b>положительные</b> ключевые слова (всех админов):\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")



@dp.callback_query(F.data == "add_negative_keywords")
async def ask_negative_keywords(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
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

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌➕ Добавить еще", callback_data="add_negative_keywords")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
    ])
    
    if not raw_input:
        await message.answer("⚠️ Сообщение пустое. Пожалуйста, отправь хотя бы одно ключевое слово.")
        return

    added = await add_keywords(user_id, raw_input, is_negative=True)

    if not added:
        await message.answer("⚠️ Ни одного ключевого слова не было добавлено.")
    else:
        formatted = "\n".join(f"• <code>{kw}</code>" for kw in added)
        await message.answer(f"🚫 Добавлены следующие <b>негативные</b> ключевые слова:\n\n{formatted}", reply_markup=keyboard, parse_mode="HTML")

    await state.clear()


@dp.callback_query(F.data == "remove_negative_keywords")
async def handle_remove_negative_keywords(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
        "✂️ Пришли <b>негативное</b> ключевое слово или фразу, которую ты хочешь удалить из отслеживания.\n\n"
        "Удаление возможно только по одному слову или фразе за раз."
    )
    await state.set_state(KeywordStates.waiting_for_negative_keyword_deletion)


@dp.message(KeywordStates.waiting_for_negative_keyword_deletion)
async def process_keyword_negative_deletion(message: Message, state: FSMContext):
    user_id = message.from_user.id
    keyword = message.text.strip()

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌➖ Удалить еще", callback_data="remove_negative_keywords")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
    ])
    
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
async def handle_list_negative_keywords(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    keywords = await get_user_keywords_by_type(user_id, keyword_type="negative")

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
    ])
    
    if not keywords:
        await callback_query.message.answer("🔍 У тебя пока нет добавленных <b>негативных</b> ключевых слов.")
        return

    text = "🔑 Твои <b>негативные</b> ключевые слова:\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "list_all_negative_keywords")
async def handle_list_all_negative_keywords(callback_query: CallbackQuery):
    keywords = await get_all_keywords_by_type("negative")

    # Создаём инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="working_keywords_classic")]
    ])
    
    if not keywords:
        await callback_query.message.answer("🔍 Пока ни один админ не добавил <b>негативные</b> ключевые слова.")
        return

    text = "🔑 Все <b>негативные</b> ключевые слова (всех админов):\n\n"
    for i, kw in enumerate(keywords, start=1):
        text += f"{i}. <code>{kw}</code>\n"

    await callback_query.message.delete()
    await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")



# === Логика работы "умного парсинга" в боте парсере ===

# Функция добавления ключевого слова категории "Намерение"
@dp.callback_query(F.data == "add_intent")
async def add_intent(callback: CallbackQuery, state: FSMContext):
    # Устанавливаем состояние ожидания для ввода ключевого слова
    await state.set_state(KeywordLemmaState.keywords_lemma_intent)

    # Просим пользователя ввести одно или несколько ключевых слов через запятую или новую строку
    await callback.message.answer(
        "✏️ Пришли ключевые слова или фразы, которые ты хочешь добавить в категорию 'Намерение'.\n\n"
        "Можно несколько:\n"
        "• Через запятую → `куплю, арендую, ищу`\n"
        "• Или с новой строки:\n`сниму\nаренду`"
    )

@dp.message(KeywordLemmaState.keywords_lemma_intent)
async def process_intent_keywords(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_input = message.text.strip()

    if not raw_input:
        await message.answer("⚠️ Сообщение пустое. Пожалуйста, отправь хотя бы одно ключевое слово.")
        return

    # Разделяем слова по запятой или новой строке
    keywords = [kw.strip() for kw in raw_input.replace("\n", ",").split(",")]

    # Передаем исходные ключевые слова в функцию записи в базу
    added_keywords = await add_intent_keywords_to_db(user_id, keywords)

    if added_keywords:
        formatted = "\n".join(f"• <code>{kw}</code>" for kw in added_keywords)
        await message.answer(f"✅ Добавлены следующие ключевые слова в категорию 'Намерение':\n\n{formatted}")
    else:
        await message.answer("⚠️ Не удалось добавить ключевые слова. Возможно, они были пустыми.")
    
    # Очищаем состояние
    await state.clear()









# === Логика работы основного запуска бота парсера ===

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
