import os
import glob
import json
import time
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from telethon import TelegramClient
from telethon.errors import FloodWaitError, UserDeactivatedBanError, AuthKeyUnregisteredError
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import (
    InputReportReasonSpam,
    InputReportReasonViolence,
    InputReportReasonPornography,
    InputReportReasonFake,
    InputReportReasonOther
)

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "9151197978:AAH1zr2r16q5fc680nWf7iyNqX1NPb1g0us"
API_ID = 2040  # Стандартный API_ID Telegram Desktop
API_HASH = "b18441a1ff607e10a989891a5462e627"
ADMIN_ID = 1478278491  # Твой Telegram ID

BASE_DIR = r"C:\Users\zahan\OneDrive\Desktop\reporter_bot"
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
BANNER_PATH = os.path.join(BASE_DIR, "banner.jpg")  # Картинка для приветствия
SUBS_FILE = os.path.join(BASE_DIR, "subs.json")
CHANNELS_FILE = os.path.join(BASE_DIR, "channels.json")

# Ссылка на твой аккаунт для кнопки покупки подписки
ADMIN_CONTACT_URL = "https://t.me/prestanniy"

# Твои 2 канала для обязательной подписки
DEFAULT_CHANNELS = [
    {
        "title": "📢 Канал #1",
        "url": "https://t.me/yourserov",
        "chat_id": None  # Привязывается через админ-панель или вписывается вручную (-1003982772571)
    },
    {
        "title": "📢 Канал #2",
        "url": "https://t.me/perexodhorserova",
        "chat_id": None  # Привязывается через админ-панель или вписывается вручную (-1004309785427)
    }
]
# ================================================

os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

REASONS = {
    "spam": ("Спам", InputReportReasonSpam()),
    "fake": ("Фейк / Мошенничество", InputReportReasonFake()),
    "violence": ("Насилие", InputReportReasonViolence()),
    "porn": ("Порнография", InputReportReasonPornography()),
    "other": ("Другое нарушение", InputReportReasonOther()),
}

class BotStates(StatesGroup):
    waiting_for_target = State()
    waiting_for_reason = State()
    waiting_for_sub_input = State()
    waiting_for_channel_1 = State()
    waiting_for_channel_2 = State()

# ================= РАБОТА С БАЗОЙ КАНАЛОВ И ПОДПИСОК =================
def load_channels() -> list:
    if not os.path.exists(CHANNELS_FILE):
        save_channels(DEFAULT_CHANNELS)
        return DEFAULT_CHANNELS
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CHANNELS

def save_channels(channels: list):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=4, ensure_ascii=False)

def load_subs() -> dict:
    if not os.path.exists(SUBS_FILE):
        return {}
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_subs(subs: dict):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, indent=4)

def has_active_sub(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    subs = load_subs()
    return subs.get(str(user_id), 0) > time.time()

def get_sub_status_text(user_id: int) -> str:
    if user_id == ADMIN_ID:
        return "👑 Администратор (Безлимит)"
    subs = load_subs()
    exp_time = subs.get(str(user_id), 0)
    if exp_time > time.time():
        dt = datetime.fromtimestamp(exp_time).strftime("%d.%m.%Y %H:%M")
        return f"✅ Активна (до {dt})"
    return "❌ Отсутствует"

# ================= ПРОВЕРКА ПОДПИСКИ НА 2 КАНАЛА =================
async def check_user_channels(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    channels = load_channels()
    for ch in channels:
        chat_id = ch.get("chat_id")
        if not chat_id:
            continue
        try:
            member = await bot.get_chat_member(chat_id=int(chat_id), user_id=user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception as e:
            print(f"[!] Ошибка проверки канала {chat_id}: {e} (Убедись, что бот админ в канале!)")
            continue
    return True

# ================= ОТПРАВКА МЕНЮ С КАРТИНКОЙ =================
async def send_or_edit_menu(event: Message | CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup):
    has_banner = os.path.exists(BANNER_PATH)

    if isinstance(event, Message):
        if has_banner:
            photo = FSInputFile(BANNER_PATH)
            await event.answer_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await event.answer(text=text, reply_markup=reply_markup, parse_mode="Markdown")

    elif isinstance(event, CallbackQuery):
        try:
            if event.message.photo:
                await event.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                if has_banner:
                    await event.message.delete()
                    photo = FSInputFile(BANNER_PATH)
                    await event.message.answer_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await event.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            pass

# ================= КЛАВИАТУРЫ =================
def get_channel_sub_kb() -> InlineKeyboardMarkup:
    channels = load_channels()
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=ch["title"], url=ch["url"])])
    buttons.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_channel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🚀 Отправить жалобу", callback_data="menu:report")],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
            InlineKeyboardButton(text="💎 Купить подписку", callback_data="menu:buy")
        ]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu:home")]
    ])

def get_reasons_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"reason:{key}")]
        for key, (label, _) in REASONS.items()
    ]
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_welcome_text(user_id: int, first_name: str) -> str:
    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    return (
        f"👋 Привет, **{first_name}**!\n\n"
        f"🤖 Добро пожаловать в панель управления.\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 Твой ID: `{user_id}`\n"
        f"💎 Подписка: **{get_sub_status_text(user_id)}**\n"
        f"📂 Активных сессий: **{len(session_files)}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Выбери нужное действие ниже:"
    )

# ================= ОСНОВНЫЕ ХЭНДЛЕРЫ =================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if not await check_user_channels(message.from_user.id):
        await send_or_edit_menu(
            message,
            "⚠️ **Доступ закрыт!**\n\n"
            "Для использования бота подпишись на оба наших канала по кнопкам ниже, "
            "а затем нажми **«✅ Проверить подписку»**:",
            get_channel_sub_kb()
        )
        return

    await send_or_edit_menu(
        message,
        get_welcome_text(message.from_user.id, message.from_user.first_name),
        get_main_menu_kb(message.from_user.id)
    )

@dp.callback_query(F.data == "check_channel")
async def cb_check_channel(callback: CallbackQuery):
    if await check_user_channels(callback.from_user.id):
        await callback.answer("✅ Подписка на каналы подтверждена!")
        await send_or_edit_menu(
            callback,
            get_welcome_text(callback.from_user.id, callback.from_user.first_name),
            get_main_menu_kb(callback.from_user.id)
        )
    else:
        await callback.answer("❌ Ты подписался не на все каналы!", show_alert=True)

@dp.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not await check_user_channels(callback.from_user.id):
        await send_or_edit_menu(
            callback,
            "⚠️ **Для продолжения работы подпишись на наши каналы:**",
            get_channel_sub_kb()
        )
        return

    await send_or_edit_menu(
        callback,
        get_welcome_text(callback.from_user.id, callback.from_user.first_name),
        get_main_menu_kb(callback.from_user.id)
    )

@dp.callback_query(F.data == "menu:profile")
async def cb_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    text = (
        f"👤 **Личный профиль**\n\n"
        f"🔹 Имя: {callback.from_user.first_name}\n"
        f"🔹 ID: `{uid}`\n"
        f"🔹 Подписка: **{get_sub_status_text(uid)}**"
    )
    await send_or_edit_menu(callback, text, get_back_kb())

@dp.callback_query(F.data == "menu:buy")
async def cb_buy(callback: CallbackQuery):
    text = (
        "💎 **Приобретение подписки**\n\n"
        "Подписка открывает полный доступ к отправке жалоб через сессии.\n\n"
        "📅 **Тарифы:**\n"
        "• 7 дней — 150 ₽\n"
        "• 30 дней — 400 ₽\n"
        "• Навсегда — 900 ₽\n\n"
        f"Для покупки напиши администратору и укажи свой ID: `{callback.from_user.id}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать администратору", url=ADMIN_CONTACT_URL)],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu:home")]
    ])
    await send_or_edit_menu(callback, text, kb)

# ================= АДМИН-ПАНЕЛЬ И ПРИВЯЗКА КАНАЛОВ =================
@dp.callback_query(F.data == "menu:admin")
async def cb_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    subs = load_subs()
    active_subs = sum(1 for exp in subs.values() if exp > time.time())
    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    channels = load_channels()

    ch1_status = f"`{channels[0]['chat_id']}`" if channels[0].get("chat_id") else "❌ Не привязан"
    ch2_status = f"`{channels[1]['chat_id']}`" if channels[1].get("chat_id") else "❌ Не привязан"

    text = (
        f"👑 **Панель администратора**\n\n"
        f"📂 Сессий в базе: **{len(session_files)}**\n"
        f"👥 Активных подписок: **{active_subs}**\n\n"
        f"📢 **Статус проверки каналов:**\n"
        f"• Канал 1: {ch1_status}\n"
        f"• Канал 2: {ch2_status}\n\n"
        f"**Быстрые команды:**\n"
        f"• `/givesub ID ДНИ` — выдать подписку\n"
        f"• `/removesub ID` — забрать подписку"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin:give_sub")],
        [InlineKeyboardButton(text="🔗 Привязать ID обоих каналов", callback_data="admin:bind_channels")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu:home")]
    ])
    await send_or_edit_menu(callback, text, kb)

@dp.callback_query(F.data == "admin:bind_channels")
async def cb_bind_channels(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await send_or_edit_menu(
        callback,
        "🔗 **Привязка Канала #1** (`https://t.me/+T0bekcNuUsZhMWNi`)\n\n"
        "1. Добавь этого бота в **Администраторы** первого канала.\n"
        "2. **Перешли сюда любое сообщение** из первого канала (или отправь его ID вида `-100...` текстом):",
        get_back_kb()
    )
    await state.set_state(BotStates.waiting_for_channel_1)

@dp.message(BotStates.waiting_for_channel_1)
async def process_channel_1(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    chat_id = None
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
    elif message.text and message.text.strip().lstrip("-").isdigit():
        chat_id = int(message.text.strip())

    if not chat_id:
        await message.answer("❌ Перешли пост из первого канала или отправь его числовой ID (начинается с `-100`).")
        return

    channels = load_channels()
    channels[0]["chat_id"] = chat_id
    save_channels(channels)

    await message.answer(
        f"✅ Канал #1 привязан (`{chat_id}`)!\n\n"
        f"🔗 Теперь **перешли сюда любое сообщение из Канала #2** (`https://t.me/+QwbRY3HlS-U3ZWVl`) "
        f"или отправь его ID (не забудь также добавить бота в админы второго канала):",
        parse_mode="Markdown"
    )
    await state.set_state(BotStates.waiting_for_channel_2)

@dp.message(BotStates.waiting_for_channel_2)
async def process_channel_2(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    chat_id = None
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
    elif message.text and message.text.strip().lstrip("-").isdigit():
        chat_id = int(message.text.strip())

    if not chat_id:
        await message.answer("❌ Перешли пост из второго канала или отправь его числовой ID (начинается с `-100`).")
        return

    channels = load_channels()
    channels[1]["chat_id"] = chat_id
    save_channels(channels)
    await state.clear()

    await send_or_edit_menu(
        message,
        f"✅ **Оба канала успешно привязаны!**\nТеперь бот строго проверяет подписку на оба канала.",
        get_main_menu_kb(message.from_user.id)
    )

@dp.callback_query(F.data == "admin:give_sub")
async def cb_admin_give_sub(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await send_or_edit_menu(
        callback,
        "✏️ Введи ID пользователя и количество дней через пробел\nПример: `123456789 30`",
        get_back_kb()
    )
    await state.set_state(BotStates.waiting_for_sub_input)

@dp.message(BotStates.waiting_for_sub_input)
async def process_sub_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("❌ Неверный формат. Отправь: `ID ДНИ` (например: `123456789 30`)", parse_mode="Markdown")
        return

    target_id, days = parts[0], int(parts[1])
    subs = load_subs()
    subs[target_id] = time.time() + (days * 86400)
    save_subs(subs)
    await state.clear()
    await send_or_edit_menu(
        message,
        f"✅ Пользователю `{target_id}` выдана подписка на **{days}** дн.",
        get_main_menu_kb(message.from_user.id)
    )

@dp.message(Command("givesub"))
async def cmd_givesub(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Использование: `/givesub ID ДНИ`", parse_mode="Markdown")
        return
    target_id, days = parts[1], int(parts[2])
    subs = load_subs()
    subs[target_id] = time.time() + (days * 86400)
    save_subs(subs)
    await message.answer(f"✅ Подписка для `{target_id}` активирована на {days} дн.", parse_mode="Markdown")

@dp.message(Command("removesub"))
async def cmd_removesub(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: `/removesub ID`", parse_mode="Markdown")
        return
    target_id = parts[1]
    subs = load_subs()
    subs.pop(target_id, None)
    save_subs(subs)
    await message.answer(f"🗑 Подписка у пользователя `{target_id}` отключена.", parse_mode="Markdown")

# ================= ОТПРАВКА ЖАЛОБ ЧЕРЕЗ СЕССИИ =================
def create_client_from_session(session_path: str) -> TelegramClient:
    base_name = os.path.splitext(session_path)[0]
    json_path = f"{base_name}.json"
    api_id = API_ID
    api_hash = API_HASH
    device_model = "Desktop"
    system_version = "Windows 10"
    app_version = "4.16.8 x64"

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                api_id = data.get("app_id") or data.get("api_id") or API_ID
                api_hash = data.get("app_hash") or data.get("api_hash") or API_HASH
                device_model = data.get("device") or data.get("device_model") or device_model
                system_version = data.get("sdk") or data.get("system_version") or system_version
                app_version = data.get("app_version") or app_version
        except Exception:
            pass

    return TelegramClient(
        base_name,
        api_id=int(api_id),
        api_hash=str(api_hash),
        device_model=device_model,
        system_version=system_version,
        app_version=app_version
    )

@dp.callback_query(F.data == "menu:report")
async def cb_start_report(callback: CallbackQuery, state: FSMContext):
    if not await check_user_channels(callback.from_user.id):
        await callback.answer("❌ Сначала подпишись на наши каналы!", show_alert=True)
        return
    if not has_active_sub(callback.from_user.id):
        await callback.answer("❌ У тебя нет активной подписки! Приобрети её в меню.", show_alert=True)
        return

    await send_or_edit_menu(
        callback,
        "🎯 **Отправь `@username` или ссылку `https://t.me/...` на аккаунт или канал:**",
        get_back_kb()
    )
    await state.set_state(BotStates.waiting_for_target)

@dp.message(BotStates.waiting_for_target)
async def process_target(message: Message, state: FSMContext):
    if not has_active_sub(message.from_user.id):
        return

    target = message.text.strip()
    if "t.me/" in target:
        target = target.split("t.me/")[-1].split("/")[0].split("?")[0]
    if not target.startswith("@") and not target.startswith("+"):
        target = f"@{target}"

    await state.update_data(target=target)
    await send_or_edit_menu(
        message,
        f"🎯 Цель: `{target}`\nВыбери причину жалобы:",
        get_reasons_kb()
    )
    await state.set_state(BotStates.waiting_for_reason)

@dp.callback_query(BotStates.waiting_for_reason, F.data.startswith("reason:"))
async def process_reason(callback: CallbackQuery, state: FSMContext):
    if not has_active_sub(callback.from_user.id):
        return

    reason_key = callback.data.split(":")[1]
    reason_label, reason_obj = REASONS[reason_key]
    data = await state.get_data()
    target = data["target"]
    await state.clear()

    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    if not session_files:
        await send_or_edit_menu(
            callback,
            "❌ В папке `sessions/` нет ни одного `.session` файла.",
            get_back_kb()
        )
        return

    await send_or_edit_menu(
        callback,
        f"⏳ **Начинаю отправку жалоб...**\n\n"
        f"🎯 Цель: `{target}`\n"
        f"📌 Причина: **{reason_label}**\n"
        f"📂 Всего сессий: **{len(session_files)}**",
        InlineKeyboardMarkup(inline_keyboard=[])
    )

    success_count = 0
    fail_count = 0
    dead_sessions = 0

    for session_path in session_files:
        client = create_client_from_session(session_path)

        try:
            await client.connect()
            if not await client.is_user_authorized():
                dead_sessions += 1
                await client.disconnect()
                continue

            entity = await client.get_input_entity(target)

            await client(ReportPeerRequest(
                peer=entity,
                reason=reason_obj,
                message="Systematic violation of Telegram Terms of Service and spam activity."
            ))
            success_count += 1

        except (UserDeactivatedBanError, AuthKeyUnregisteredError):
            dead_sessions += 1
        except FloodWaitError as e:
            print(f"[FloodWait] Ожидание {e.seconds} сек.")
            fail_count += 1
        except Exception as e:
            print(f"[Ошибка] {session_path}: {e}")
            fail_count += 1
        finally:
            await client.disconnect()

        await asyncio.sleep(2.5)

    await send_or_edit_menu(
        callback,
        f"✅ **Отправка завершена!**\n\n"
        f"🎯 Цель: `{target}`\n"
        f"📌 Причина: {reason_label}\n"
        f"✔️ Успешно отправлено: **{success_count}**\n"
        f"⚠️ Ошибок (не найден пир / лимит): **{fail_count}**\n"
        f"💀 Невалидных сессий: **{dead_sessions}**",
        get_back_kb()
    )

async def main():
    print("Бот запущен на ПК...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())