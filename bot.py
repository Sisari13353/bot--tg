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
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
ADMIN_ID = 8697016918

# Автоматическое определение пути к папке проекта на диске D
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
SUBS_FILE = os.path.join(BASE_DIR, "subs.json")

# Твои каналы (ссылки на подписку)
CHANNEL_1_URL = "https://t.me/+T0bekcNuUsZhMWNi"
CHANNEL_2_URL = "https://t.me/+QwbRY3HlS-U3ZWVl"

# Контакт администратора для покупки
ADMIN_CONTACT_URL = "https://t.me/tgsteclov"
# ================================================

os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Поиск файла баннера (jpg, png, jpeg) в папке проекта
def get_banner_file_path() -> str | None:
    for ext in [".jpg", ".png", ".jpeg"]:
        path = os.path.join(BASE_DIR, f"banner{ext}")
        if os.path.exists(path):
            return path
    return None

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

# ================= РАБОТА С ПОДПИСКАМИ =================
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

# ================= ОТРИСОВКА МЕНЮ С ФОТО =================
async def send_or_edit_menu(event: Message | CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup):
    banner_path = get_banner_file_path()

    if isinstance(event, Message):
        if banner_path:
            try:
                photo = FSInputFile(banner_path)
                await event.answer_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                return
            except Exception as e:
                print(f"[!] Ошибка отправки фото: {e}")
        await event.answer(text=text, reply_markup=reply_markup, parse_mode="Markdown")

    elif isinstance(event, CallbackQuery):
        try:
            if event.message.photo:
                await event.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                if banner_path:
                    await event.message.delete()
                    photo = FSInputFile(banner_path)
                    await event.message.answer_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await event.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            pass

# ================= КЛАВИАТУРЫ =================
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

def get_channel_links_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на Канал #1", url=CHANNEL_1_URL)],
        [InlineKeyboardButton(text="📢 Подписаться на Канал #2", url=CHANNEL_2_URL)],
        [InlineKeyboardButton(text="✅ Я подписался (Продолжить)", callback_data="channels_done")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu:home")]
    ])

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
        f"📂 Доступно сессий: **{len(session_files)}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Выбери необходимое действие ниже:"
    )

# ================= ХЭНДЛЕРЫ =================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await send_or_edit_menu(
        message,
        get_welcome_text(message.from_user.id, message.from_user.first_name),
        get_main_menu_kb(message.from_user.id)
    )

@dp.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
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

# ================= ЭКРАН ПОДПИСКИ НА КАНАЛЫ =================
@dp.callback_query(F.data == "menu:report")
async def cb_report_click(callback: CallbackQuery, state: FSMContext):
    if not has_active_sub(callback.from_user.id):
        await callback.answer("❌ У тебя нет активной подписки! Купи её в профиле.", show_alert=True)
        return

    # Выводим плашку с каналами
    text = (
        "📢 **Обязательная подписка на наши каналы!**\n\n"
        "Для использования инструмента подпишись на каналы ниже, "
        "после чего нажми кнопку **«✅ Я подписался (Продолжить)»**:"
    )
    await send_or_edit_menu(callback, text, get_channel_links_kb())

@dp.callback_query(F.data == "channels_done")
async def cb_channels_done(callback: CallbackQuery, state: FSMContext):
    if not has_active_sub(callback.from_user.id):
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return

    await send_or_edit_menu(
        callback,
        "🎯 **Отправь `@username` или ссылку `https://t.me/...` на аккаунт или канал:**",
        get_back_kb()
    )
    await state.set_state(BotStates.waiting_for_target)

# ================= АДМИН-ПАНЕЛЬ =================
@dp.callback_query(F.data == "menu:admin")
async def cb_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    subs = load_subs()
    active_subs = sum(1 for exp in subs.values() if exp > time.time())
    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))

    text = (
        f"👑 **Панель администратора**\n\n"
        f"📂 Сессий в папке: **{len(session_files)}**\n"
        f"👥 Активных пользователей: **{active_subs}**\n\n"
        f"**Команды:**\n"
        f"• `/givesub ID ДНИ` — выдать доступ\n"
        f"• `/removesub ID` — отозвать доступ"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin:give_sub")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu:home")]
    ])
    await send_or_edit_menu(callback, text, kb)

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
        await message.answer("❌ Формат: `ID ДНИ` (например: `123456789 30`)", parse_mode="Markdown")
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
        await message.answer("Формат: `/givesub ID ДНИ`", parse_mode="Markdown")
        return
    target_id, days = parts[1], int(parts[2])
    subs = load_subs()
    subs[target_id] = time.time() + (days * 86400)
    save_subs(subs)
    await message.answer(f"✅ Доступ выдан для `{target_id}` на {days} дн.", parse_mode="Markdown")

@dp.message(Command("removesub"))
async def cmd_removesub(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: `/removesub ID`", parse_mode="Markdown")
        return
    target_id = parts[1]
    subs = load_subs()
    subs.pop(target_id, None)
    save_subs(subs)
    await message.answer(f"🗑 Подписка у `{target_id}` аннулирована.", parse_mode="Markdown")

# ================= ОБРАБОТКА ЦЕЛИ И ОТПРАВКА =================
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
            "❌ В папке `sessions/` на диске D нет ни одного `.session` файла.",
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
        session_name = os.path.splitext(session_path)[0]
        client = TelegramClient(session_name, API_ID, API_HASH)

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
            print(f"[FloodWait] Лимит ожидания: {e.seconds} сек.")
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
        f"⚠️ Ошибок / лимит: **{fail_count}**\n"
        f"💀 Невалидных сессий: **{dead_sessions}**",
        get_back_kb()
    )

# ================= ЗАПУСК =================
async def main():
    banner = get_banner_file_path()
    if banner:
        print(f"[OK] Картинка баннера обнаружена: {banner}")
    else:
        print(f"[!] Файл banner (.jpg/.png) НЕ найден в папке: {BASE_DIR}")

    print(f"[OK] Папка с сессиями: {SESSIONS_DIR}")
    print("Бот успешно запущен на диске D...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())