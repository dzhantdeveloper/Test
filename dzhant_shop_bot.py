#!/usr/bin/env python3
"""
Dzhant Shop Bot — единый файл.
Python 3.11+. При первом запуске сам ставит зависимости и спрашивает
TOKEN бота и пароль администратора.
"""

import sys
import subprocess
import importlib.util


def ensure_dependencies():
    required = {"aiogram": "aiogram>=3.4,<4"}
    missing = []
    for module_name, pip_spec in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_spec)
    if missing:
        print("Устанавливаю недостающие зависимости:", ", ".join(missing))
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("Зависимости установлены.\n")


ensure_dependencies()

import asyncio
import json
import os
import hashlib
import getpass
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SHOP_NAME = "Dzhant Shop"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()


class AdminAuth(StatesGroup):
    waiting_password = State()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def first_run_setup() -> dict:
    print("=== Первый запуск Dzhant Shop Bot ===")
    print("Настройка выполняется один раз, данные сохранятся в config.json\n")

    token = input("Введите TOKEN Telegram-бота (получить у @BotFather): ").strip()
    while not token:
        token = input("Токен не может быть пустым. Введите TOKEN: ").strip()

    print("\nТеперь задайте пароль для админ-панели (команда /panel).")
    print("Пароль не отображается на экране при вводе.")
    while True:
        password = getpass.getpass("Придумайте пароль администратора: ")
        password_confirm = getpass.getpass("Повторите пароль: ")
        if password and password == password_confirm:
            break
        print("Пароли не совпадают или пустые. Попробуйте снова.")

    admin_id_raw = input(
        "\n(Необязательно) Ваш Telegram numeric ID для автодоступа к /panel без пароля "
        "(Enter — пропустить): "
    ).strip()

    cfg = {
        "token": token,
        "admin_password_hash": hash_password(password),
        "admin_ids": [int(admin_id_raw)] if admin_id_raw.isdigit() else [],
    }
    save_config(cfg)
    print("\nНастройка завершена. Конфигурация сохранена в config.json")
    print("Запускаю бота...\n")
    return cfg


def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🛍 Товары"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="ℹ️ О магазине")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Добро пожаловать в <b>{SHOP_NAME}</b>! 🛒\n\n"
        "Это тестовая версия магазина. Выберите раздел в меню ниже.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(F.text == "🛍 Товары")
async def show_products(message: Message):
    await message.answer(
        "📦 Раздел «Товары» пока в разработке.\n"
        "Здесь появится каталог с ценами и кнопками покупки."
    )


@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    user = message.from_user
    await message.answer(
        "👤 <b>Ваш профиль</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.full_name}\n"
        f"Username: @{user.username if user.username else '—'}\n\n"
        "Баланс и история заказов появятся здесь позже.",
        parse_mode="HTML",
    )


@router.message(F.text == "ℹ️ О магазине")
async def about_shop(message: Message):
    await message.answer(
        f"ℹ️ <b>{SHOP_NAME}</b>\n\n"
        "Это тестовая версия магазина в Telegram.\n"
        "Скоро здесь появится полноценный каталог, оплата и поддержка.",
        parse_mode="HTML",
    )


# Команда /panel сознательно НЕ добавляется в меню команд бота (BotFather),
# поэтому обычные пользователи её не увидят в интерфейсе Telegram.
@router.message(Command("panel"))
async def cmd_panel(message: Message, state: FSMContext):
    cfg = load_config()
    admin_ids = cfg.get("admin_ids", [])

    if admin_ids and message.from_user.id in admin_ids:
        await show_admin_panel(message)
        return

    await message.answer("Введите пароль администратора:")
    await state.set_state(AdminAuth.waiting_password)


@router.message(AdminAuth.waiting_password)
async def check_admin_password(message: Message, state: FSMContext):
    entered = message.text.strip() if message.text else ""

    try:
        await message.delete()
    except Exception:
        pass

    cfg = load_config()
    if entered and hash_password(entered) == cfg.get("admin_password_hash"):
        await message.answer("✅ Пароль верный. Добро пожаловать в админ-панель.")
        await show_admin_panel(message)
    else:
        await message.answer("❌ Неверный пароль.")
    await state.clear()


async def show_admin_panel(message: Message):
    await message.answer(
        "🛠 <b>Админ-панель Dzhant Shop</b>\n\n"
        "Здесь будут функции управления товарами, заказами и пользователями "
        "(в разработке).",
        parse_mode="HTML",
    )


async def main():
    cfg = load_config()
    if not cfg.get("token") or not cfg.get("admin_password_hash"):
        cfg = first_run_setup()

    bot = Bot(token=cfg["token"])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
