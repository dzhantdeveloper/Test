#!/usr/bin/env python3
"""
Dzhant Shop Bot — единый файл.
Python 3.11+. При первом запуске сам ставит зависимости и спрашивает
TOKEN бота и пароль администратора.

Раздел "Накрутка" работает через TwiBoost API (https://twiboost.com/api/v2).
Ключ TwiBoost задаётся в админ-панели (/panel -> TwiBoost API).
"""

import sys
import subprocess
import importlib.util


def ensure_dependencies():
    required = {"aiogram": "aiogram>=3.4,<4", "requests": "requests>=2.31"}
    missing = []
    for module_name, pip_spec in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_spec)
    if missing:
        print("Устанавливаю недостающие зависимости:", ", ".join(missing), flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("Зависимости установлены.\n", flush=True)


ensure_dependencies()

import asyncio
import json
import os
import hashlib
import getpass
import logging
import time
import random
import string

import requests

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ─────────────────────────────────────────────
#  ПУТИ / КОНСТАНТЫ
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SERVICES_PATH = os.path.join(BASE_DIR, "smm_services.json")
CATEGORIES_PATH = os.path.join(BASE_DIR, "smm_categories.json")
ORDERS_PATH = os.path.join(BASE_DIR, "smm_orders.json")
STATS_PATH = os.path.join(BASE_DIR, "stats.json")
USERS_PATH = os.path.join(BASE_DIR, "users.json")
PROMOCODES_PATH = os.path.join(BASE_DIR, "promocodes.json")
TOPUPS_PATH = os.path.join(BASE_DIR, "topups.json")

SHOP_NAME = "Dzhant Shop"
TWIBOOST_API_URL = "https://twiboost.com/api/v2"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"
ORDER_CHECK_INTERVAL = 180  # сек, как часто проверять статусы активных заказов
TOPUP_CHECK_INTERVAL = 20  # сек, как часто проверять неоплаченные счета CryptoBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dzhant_shop")

router = Router()


# ─────────────────────────────────────────────
#  ХРАНИЛИЩЕ (простые json-файлы)
# ─────────────────────────────────────────────
def _load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config() -> dict:
    return _load_json(CONFIG_PATH, {})


def save_config(cfg: dict) -> None:
    _save_json(CONFIG_PATH, cfg)


def load_services() -> dict:
    return _load_json(SERVICES_PATH, {})


def save_services(data: dict) -> None:
    _save_json(SERVICES_PATH, data)


def load_categories() -> list:
    """Список категорий услуг (например Telegram, Youtube).
    Это чисто пользовательская сущность для удобной навигации в боте —
    на работу с TwiBoost никак не влияет."""
    return _load_json(CATEGORIES_PATH, [])


def save_categories(data: list) -> None:
    _save_json(CATEGORIES_PATH, data)


def add_category(name: str) -> None:
    categories = load_categories()
    if name not in categories:
        categories.append(name)
        save_categories(categories)


def load_orders() -> list:
    return _load_json(ORDERS_PATH, [])


def save_orders(data: list) -> None:
    _save_json(ORDERS_PATH, data)


def load_stats() -> dict:
    return _load_json(STATS_PATH, {"started_users": []})


def save_stats(data: dict) -> None:
    _save_json(STATS_PATH, data)


def register_start(user_id: int) -> None:
    stats = load_stats()
    if user_id not in stats["started_users"]:
        stats["started_users"].append(user_id)
        save_stats(stats)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────
#  ПОЛЬЗОВАТЕЛИ / БАЛАНС
# ─────────────────────────────────────────────
def load_users() -> dict:
    return _load_json(USERS_PATH, {})


def save_users(data: dict) -> None:
    _save_json(USERS_PATH, data)


def get_user(user_id: int) -> dict:
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {"balance": 0.0, "promocodes_used": []}
        save_users(users)
    return users[key]


def get_balance(user_id: int) -> float:
    return float(get_user(user_id).get("balance", 0.0))


def add_balance(user_id: int, amount: float) -> float:
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {"balance": 0.0, "promocodes_used": []}
    users[key]["balance"] = round(float(users[key].get("balance", 0.0)) + amount, 2)
    save_users(users)
    return users[key]["balance"]


def deduct_balance(user_id: int, amount: float) -> bool:
    """Списывает сумму с баланса, если средств достаточно. Возвращает успех."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {"balance": 0.0, "promocodes_used": []}
    current = float(users[key].get("balance", 0.0))
    if current < amount:
        return False
    users[key]["balance"] = round(current - amount, 2)
    save_users(users)
    return True


# ─────────────────────────────────────────────
#  ПРОМОКОДЫ
# ─────────────────────────────────────────────
def load_promocodes() -> dict:
    return _load_json(PROMOCODES_PATH, {})


def save_promocodes(data: dict) -> None:
    _save_json(PROMOCODES_PATH, data)


def generate_promo_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    promos = load_promocodes()
    while True:
        code = "".join(random.choice(alphabet) for _ in range(length))
        if code not in promos:
            return code


def create_promocode(code: str, amount: float, max_activations: int = 1) -> None:
    promos = load_promocodes()
    promos[code] = {
        "amount": amount,
        "max_activations": max_activations,
        "activations_used": 0,
        "used_by": [],
        "created_at": int(time.time()),
    }
    save_promocodes(promos)


def redeem_promocode(code: str, user_id: int):
    """Возвращает (успех: bool, сообщение/сумма)."""
    promos = load_promocodes()
    entry = promos.get(code)
    if not entry:
        return False, "Промокод не найден."

    # Совместимость со старым форматом промокодов (used: bool)
    if "max_activations" not in entry:
        entry["max_activations"] = 1
        entry["activations_used"] = 1 if entry.get("used") else 0
        entry["used_by"] = [entry["used_by"]] if entry.get("used_by") else []

    if user_id in entry.get("used_by", []):
        return False, "Вы уже активировали этот промокод."

    if entry.get("activations_used", 0) >= entry.get("max_activations", 1):
        return False, "У этого промокода закончились активации."

    entry["activations_used"] = entry.get("activations_used", 0) + 1
    entry.setdefault("used_by", []).append(user_id)
    entry["used_at"] = int(time.time())
    promos[code] = entry
    save_promocodes(promos)

    new_balance = add_balance(user_id, float(entry["amount"]))
    users = load_users()
    users[str(user_id)].setdefault("promocodes_used", []).append(code)
    save_users(users)

    return True, {"amount": entry["amount"], "balance": new_balance}


# ─────────────────────────────────────────────
#  ПОПОЛНЕНИЯ БАЛАНСА (CryptoBot)
# ─────────────────────────────────────────────
def load_topups() -> dict:
    return _load_json(TOPUPS_PATH, {})


def save_topups(data: dict) -> None:
    _save_json(TOPUPS_PATH, data)


def create_topup(invoice_id: str, user_id: int, amount: float) -> None:
    topups = load_topups()
    topups[str(invoice_id)] = {
        "user_id": user_id,
        "amount": amount,
        "status": "active",
        "created_at": int(time.time()),
    }
    save_topups(topups)


def mark_topup_paid(invoice_id: str) -> bool:
    """Помечает счёт оплаченным и начисляет баланс. Возвращает True при первом
    успешном зачислении (защита от повторного начисления)."""
    topups = load_topups()
    entry = topups.get(str(invoice_id))
    if not entry or entry.get("status") == "paid":
        return False
    entry["status"] = "paid"
    entry["paid_at"] = int(time.time())
    topups[str(invoice_id)] = entry
    save_topups(topups)
    add_balance(entry["user_id"], float(entry["amount"]))
    return True


# ─────────────────────────────────────────────
#  TWIBOOST API
# ─────────────────────────────────────────────
class TwiBoostApi:
    @staticmethod
    def _post(key: str, data: dict):
        payload = {"key": key, **data}
        try:
            r = requests.post(TWIBOOST_API_URL, data=payload, timeout=20)
            return r.json()
        except Exception as ex:
            logger.error(f"TwiBoost API error: {ex}")
            return None

    @staticmethod
    def get_services(key: str) -> list:
        res = TwiBoostApi._post(key, {"action": "services"})
        return res if isinstance(res, list) else []

    @staticmethod
    def get_balance(key: str):
        res = TwiBoostApi._post(key, {"action": "balance"})
        if isinstance(res, dict) and "balance" in res:
            try:
                return float(res["balance"]), res.get("currency", "USD")
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def add_order(key: str, service_id, link: str, quantity: int):
        return TwiBoostApi._post(key, {
            "action": "add",
            "service": service_id,
            "link": link,
            "quantity": quantity,
        })

    @staticmethod
    def get_status(key: str, order_id):
        return TwiBoostApi._post(key, {"action": "status", "order": order_id})


# ─────────────────────────────────────────────
#  CRYPTOBOT API (Crypto Pay) — пополнение баланса
#  Документация: https://help.crypt.bot/crypto-pay-api
# ─────────────────────────────────────────────
class CryptoBotApi:
    @staticmethod
    def _request(token: str, method: str, params: dict | None = None):
        headers = {"Crypto-Pay-API-Token": token}
        try:
            r = requests.post(f"{CRYPTOBOT_API_URL}/{method}", headers=headers, json=params or {}, timeout=20)
            data = r.json()
            if data.get("ok"):
                return data.get("result")
            logger.warning(f"CryptoBot API error [{method}]: {data.get('error')}")
            return None
        except Exception as ex:
            logger.error(f"CryptoBot API request failed [{method}]: {ex}")
            return None

    @staticmethod
    def check_token(token: str):
        """Проверка токена — возвращает данные приложения CryptoBot или None."""
        return CryptoBotApi._request(token, "getMe")

    @staticmethod
    def create_invoice(token: str, amount: float, payload: str, description: str = ""):
        params = {
            "currency_type": "fiat",
            "fiat": "RUB",
            "amount": f"{amount:.2f}",
            "description": description or "Пополнение баланса",
            "payload": payload,
            "expires_in": 3600,
        }
        return CryptoBotApi._request(token, "createInvoice", params)

    @staticmethod
    def get_invoice(token: str, invoice_id):
        result = CryptoBotApi._request(token, "getInvoices", {"invoice_ids": str(invoice_id)})
        if isinstance(result, dict):
            items = result.get("items", [])
            return items[0] if items else None
        return None

    @staticmethod
    def get_active_invoices(token: str):
        result = CryptoBotApi._request(token, "getInvoices", {"status": "active"})
        if isinstance(result, dict):
            return result.get("items", [])
        return []


# ─────────────────────────────────────────────
#  FSM СОСТОЯНИЯ
# ─────────────────────────────────────────────
class AdminAuth(StatesGroup):
    waiting_password = State()


class AdminFlow(StatesGroup):
    waiting_api_key = State()
    waiting_new_category_name = State()
    waiting_new_service_name = State()
    waiting_new_service_description = State()
    waiting_new_service_tbid = State()
    waiting_new_service_price = State()
    waiting_promo_custom_code = State()
    waiting_promo_amount = State()
    waiting_promo_activations = State()
    waiting_cryptobot_token = State()


class OrderFlow(StatesGroup):
    waiting_quantity = State()
    waiting_link = State()


class ProfileFlow(StatesGroup):
    waiting_promo_code = State()
    waiting_topup_amount = State()


# ─────────────────────────────────────────────
#  КЛАВИАТУРЫ (инлайн)
# ─────────────────────────────────────────────
def main_menu_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🛠 Услуги", callback_data="menu_uslugi")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="ℹ️ О магазине", callback_data="menu_about")],
    ]
    if user_id is not None:
        cfg = load_config()
        if user_id in cfg.get("admin_ids", []):
            kb.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="adm_open_from_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def uslugi_menu_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🚀 Накрутка", callback_data="uslugi_nakrutka")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def nakrutka_categories_kb() -> InlineKeyboardMarkup:
    """Категории (сервисы вроде Telegram, Youtube) — показываем только те,
    под которыми реально есть хотя бы один лот."""
    services = load_services()
    used_categories = {svc.get("category", "Без категории") for svc in services.values()}
    categories = [c for c in load_categories() if c in used_categories]
    # На случай, если у лота стоит категория, которой почему-то нет в списке категорий
    for c in used_categories:
        if c not in categories:
            categories.append(c)

    rows = [
        [InlineKeyboardButton(text=cat, callback_data=f"nkcat_{cat}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nakrutka_services_kb(category: str) -> InlineKeyboardMarkup:
    services = load_services()
    rows = []
    for svc_id, svc in services.items():
        if svc.get("category", "Без категории") != category:
            continue
        rows.append([InlineKeyboardButton(
            text=f"{svc['name']} — {svc['price']} ₽/шт",
            callback_data=f"svc_{svc_id}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="uslugi_nakrutka")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(callback_data="back_main", text="⬅️ Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="🚀 Услуги", callback_data="adm_uslugi")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_addpromo")],
        [InlineKeyboardButton(text="🎫 Активные промокоды", callback_data="adm_active_promos")],
        [InlineKeyboardButton(text="💳 Способы оплаты", callback_data="adm_payments")],
        [InlineKeyboardButton(text="⚙️ Конфиг", callback_data="adm_config")],
        [InlineKeyboardButton(text="🚪 Выход", callback_data="adm_exit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_payments_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    has_token = bool(cfg.get("cryptobot_token"))
    enabled = cfg.get("cryptobot_enabled", False)
    token_status = "✅ подключён" if has_token else "❌ не подключён"
    toggle_text = "🔴 Выключить CryptoBot" if enabled else "🟢 Включить CryptoBot"
    kb = [
        [InlineKeyboardButton(text=f"🔑 CryptoBot API ({token_status})", callback_data="adm_cryptobot_setkey")],
    ]
    if has_token:
        kb.append([InlineKeyboardButton(text=toggle_text, callback_data="adm_cryptobot_toggle")])
    kb.append([InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_uslugi_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    key_status = "✅ подключён" if cfg.get("twiboost_api_key") else "❌ не подключён"
    kb = [
        [InlineKeyboardButton(text=f"🔑 TwiBoost API ({key_status})", callback_data="adm_setkey")],
        [InlineKeyboardButton(text="🗂 Сервисы", callback_data="adm_categories")],
        [InlineKeyboardButton(text="📦 Лоты", callback_data="adm_services")],
        [InlineKeyboardButton(text="🧾 Заказы", callback_data="adm_orders")],
        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_categories_kb() -> InlineKeyboardMarkup:
    categories = load_categories()
    rows = []
    for cat in categories:
        rows.append([
            InlineKeyboardButton(text=cat, callback_data="noop"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_delcat_{cat}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить сервис", callback_data="adm_addcat_direct")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Услуги", callback_data="adm_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_config_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    locked = cfg.get("panel_locked", False)
    lock_text = "🔓 Разрешить вход в /panel" if locked else "🔒 Запретить вход в /panel"
    kb = [
        [InlineKeyboardButton(text=lock_text, callback_data="adm_toggle_lock")],
        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_promo_type_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🎲 Сгенерировать код", callback_data="adm_promo_gen")],
        [InlineKeyboardButton(text="✏️ Ввести свой код", callback_data="adm_promo_manual")],
        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_services_kb() -> InlineKeyboardMarkup:
    services = load_services()
    rows = []
    for svc_id, svc in services.items():
        cat = svc.get("category", "Без категории")
        rows.append([
            InlineKeyboardButton(text=f"[{cat}] {svc['name']}", callback_data=f"adm_svc_{svc_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_delsvc_{svc_id}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить услугу", callback_data="adm_addsvc")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Услуги", callback_data="adm_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─────────────────────────────────────────────
#  СТАРТ / ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    register_start(message.from_user.id)
    await message.answer(
        f"Добро пожаловать в <b>{SHOP_NAME}</b>! 🛒\n\n"
        "Это тестовая версия магазина. Выберите раздел ниже 👇",
        reply_markup=main_menu_kb(message.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        f"<b>{SHOP_NAME}</b> — главное меню:",
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "menu_profile")
async def cb_profile(call: CallbackQuery):
    user = call.from_user
    balance = get_balance(user.id)
    cfg = load_config()
    rows = []
    if cfg.get("cryptobot_token") and cfg.get("cryptobot_enabled"):
        rows.append([InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup")])
    rows.append([InlineKeyboardButton(text="🎟 Промокод", callback_data="profile_promo")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await call.message.edit_text(
        "👤 <b>Ваш профиль</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.full_name}\n"
        f"Username: @{user.username if user.username else '—'}\n"
        f"💰 Баланс: <b>{balance} ₽</b>\n\n"
        "Есть промокод? Активируйте его кнопкой ниже.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "profile_promo")
async def cb_profile_promo(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileFlow.waiting_promo_code)
    await call.message.edit_text(
        "🎟 Пришлите промокод, чтобы активировать его:",
        reply_markup=back_kb("menu_profile"),
    )
    await call.answer()


@router.message(ProfileFlow.waiting_promo_code)
async def profile_get_promo_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("Пришлите текст промокода:")
        return

    await state.clear()
    ok, result = redeem_promocode(code, message.from_user.id)
    if not ok:
        await message.answer(f"❌ {result}", reply_markup=back_kb("menu_profile"))
        return

    await message.answer(
        f"✅ Промокод активирован!\n"
        f"Начислено: <b>{result['amount']} ₽</b>\n"
        f"Текущий баланс: <b>{result['balance']} ₽</b>",
        reply_markup=back_kb("menu_profile"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "profile_topup")
async def cb_profile_topup(call: CallbackQuery, state: FSMContext):
    cfg = load_config()
    if not (cfg.get("cryptobot_token") and cfg.get("cryptobot_enabled")):
        await call.answer("Пополнение баланса временно недоступно.", show_alert=True)
        return
    await state.set_state(ProfileFlow.waiting_topup_amount)
    await call.message.edit_text(
        "💰 <b>Пополнение баланса</b>\n\nВведите сумму пополнения в рублях (например 500):",
        reply_markup=back_kb("menu_profile", "❌ Отмена"),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(ProfileFlow.waiting_topup_amount)
async def profile_get_topup_amount(message: Message, state: FSMContext):
    try:
        amount = float((message.text or "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 500. Введите сумму:")
        return

    await state.clear()
    cfg = load_config()
    token = cfg.get("cryptobot_token")
    if not (token and cfg.get("cryptobot_enabled")):
        await message.answer("Пополнение баланса временно недоступно.", reply_markup=back_kb("menu_profile"))
        return

    wait_msg = await message.answer("⏳ Создаю счёт на оплату...")
    payload = f"topup:{message.from_user.id}:{int(time.time())}"
    invoice = CryptoBotApi.create_invoice(token, amount, payload, f"Пополнение баланса {SHOP_NAME}")
    await wait_msg.delete()

    if not invoice or "invoice_id" not in invoice:
        await message.answer(
            "❌ Не удалось создать счёт. Попробуйте позже.",
            reply_markup=back_kb("menu_profile"),
        )
        return

    create_topup(invoice["invoice_id"], message.from_user.id, amount)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=invoice["pay_url"])],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"topup_check_{invoice['invoice_id']}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_profile")],
    ])
    await message.answer(
        f"💰 <b>Счёт создан</b>\n\n"
        f"Сумма: <b>{amount} ₽</b>\n\n"
        "Нажмите «Оплатить», чтобы перейти к оплате в CryptoBot. "
        "После оплаты баланс пополнится автоматически — можно также нажать «Проверить оплату».",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("topup_check_"))
async def cb_topup_check(call: CallbackQuery):
    invoice_id = call.data.removeprefix("topup_check_")
    cfg = load_config()
    token = cfg.get("cryptobot_token")
    if not token:
        await call.answer("Оплата недоступна.", show_alert=True)
        return

    invoice = CryptoBotApi.get_invoice(token, invoice_id)
    if not invoice:
        await call.answer("Не удалось проверить статус. Попробуйте позже.", show_alert=True)
        return

    if invoice.get("status") == "paid":
        credited = mark_topup_paid(invoice_id)
        balance = get_balance(call.from_user.id)
        if credited:
            await call.message.edit_text(
                f"✅ Оплата получена! Баланс пополнен.\n💰 Текущий баланс: <b>{balance} ₽</b>",
                reply_markup=back_kb("menu_profile"),
                parse_mode="HTML",
            )
        else:
            await call.message.edit_text(
                f"✅ Этот счёт уже был зачислен ранее.\n💰 Текущий баланс: <b>{balance} ₽</b>",
                reply_markup=back_kb("menu_profile"),
                parse_mode="HTML",
            )
        await call.answer()
    else:
        await call.answer("Оплата ещё не поступила. Попробуйте немного позже.", show_alert=True)


@router.callback_query(F.data == "menu_about")
async def cb_about(call: CallbackQuery):
    await call.message.edit_text(
        f"ℹ️ <b>{SHOP_NAME}</b>\n\n"
        "Тестовая версия магазина в Telegram.\n"
        "Есть раздел «Накрутка» — заказ выполняется автоматически через TwiBoost.",
        reply_markup=back_kb(),
        parse_mode="HTML",
    )
    await call.answer()


# ─────────────────────────────────────────────
#  УСЛУГИ / НАКРУТКА (покупатель)
# ─────────────────────────────────────────────
@router.callback_query(F.data == "menu_uslugi")
async def cb_menu_uslugi(call: CallbackQuery):
    await call.message.edit_text(
        "🛠 <b>Услуги</b>\n\nВыберите раздел:",
        reply_markup=uslugi_menu_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "uslugi_nakrutka")
async def cb_uslugi_nakrutka(call: CallbackQuery):
    services = load_services()
    if not services:
        await call.message.edit_text(
            "🚀 <b>Накрутка</b>\n\n"
            "Пока нет ни одного активного предложения. Загляните позже.",
            reply_markup=back_kb("menu_uslugi"),
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            "🚀 <b>Накрутка</b>\n\nВыберите сервис:",
            reply_markup=nakrutka_categories_kb(),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data.startswith("nkcat_"))
async def cb_nakrutka_category(call: CallbackQuery):
    category = call.data.removeprefix("nkcat_")
    await call.message.edit_text(
        f"🚀 <b>Накрутка — {category}</b>\n\nВыберите услугу:",
        reply_markup=nakrutka_services_kb(category),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("svc_"))
async def cb_service_info(call: CallbackQuery, state: FSMContext):
    svc_id = call.data.removeprefix("svc_")
    services = load_services()
    svc = services.get(svc_id)
    if not svc:
        await call.answer("Услуга больше не доступна", show_alert=True)
        return

    await state.update_data(svc_id=svc_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Заказать", callback_data=f"order_{svc_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="uslugi_nakrutka")],
    ])
    description = svc.get("description") or "—"
    await call.message.edit_text(
        f"📦 <b>{svc['name']}</b>\n\n"
        f"📝 {description}\n\n"
        f"💰 Цена: <b>{svc['price']} ₽</b> за 1 шт.\n"
        f"📉 Мин. заказ: {svc['min']}\n"
        f"📈 Макс. заказ: {svc['max']}\n\n"
        "Нажмите «Заказать», чтобы указать количество и ссылку.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("order_"))
async def cb_order_start(call: CallbackQuery, state: FSMContext):
    svc_id = call.data.removeprefix("order_")
    services = load_services()
    svc = services.get(svc_id)
    if not svc:
        await call.answer("Услуга больше не доступна", show_alert=True)
        return

    await state.update_data(svc_id=svc_id)
    await state.set_state(OrderFlow.waiting_quantity)
    await call.message.edit_text(
        f"📦 {svc['name']}\n\n"
        f"Введите количество (от {svc['min']} до {svc['max']}):",
    )
    await call.answer()


@router.message(OrderFlow.waiting_quantity)
async def order_get_quantity(message: Message, state: FSMContext):
    data = await state.get_data()
    services = load_services()
    svc = services.get(data.get("svc_id"))
    if not svc:
        await state.clear()
        await message.answer("Услуга больше не доступна.", reply_markup=main_menu_kb(message.from_user.id))
        return

    if not message.text or not message.text.strip().isdigit():
        await message.answer("Нужно ввести число. Попробуйте ещё раз:")
        return

    qty = int(message.text.strip())
    if qty < svc["min"] or qty > svc["max"]:
        await message.answer(f"Количество должно быть от {svc['min']} до {svc['max']}. Попробуйте ещё раз:")
        return

    await state.update_data(quantity=qty)
    await state.set_state(OrderFlow.waiting_link)
    await message.answer("Теперь пришлите ссылку на объект накрутки (страница/пост/канал и т.д.):")


@router.message(OrderFlow.waiting_link)
async def order_get_link(message: Message, state: FSMContext):
    link = (message.text or "").strip()
    if not link.startswith("http"):
        await message.answer("Похоже, это не ссылка. Пришлите корректную ссылку (начинается с http/https):")
        return

    data = await state.get_data()
    services = load_services()
    svc = services.get(data.get("svc_id"))
    if not svc:
        await state.clear()
        await message.answer("Услуга больше не доступна.", reply_markup=main_menu_kb(message.from_user.id))
        return

    qty = data["quantity"]
    total = round(qty * svc["price"], 2)
    await state.update_data(link=link)

    balance = get_balance(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="confirm_order")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_main")],
    ])
    await message.answer(
        "📋 <b>Подтверждение заказа</b>\n\n"
        f"Услуга: {svc['name']}\n"
        f"Количество: {qty}\n"
        f"Ссылка: {link}\n"
        f"Итого: <b>{total} ₽</b>\n\n"
        f"💳 С баланса спишется: <b>{total} ₽</b>\n"
        f"💰 Текущий баланс: <b>{balance} ₽</b>\n\n"
        "Подтвердите оформление:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "confirm_order")
async def cb_confirm_order(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    services = load_services()
    svc = services.get(data.get("svc_id"))
    cfg = load_config()
    api_key = cfg.get("twiboost_api_key")

    if not svc or not api_key:
        await call.message.edit_text("⚠️ Заказ невозможен: услуга или API-ключ недоступны.", reply_markup=back_kb())
        await state.clear()
        await call.answer()
        return

    qty = data["quantity"]
    link = data["link"]
    total = round(qty * svc["price"], 2)

    if get_balance(call.from_user.id) < total:
        await call.message.edit_text(
            f"❌ Недостаточно средств на балансе.\n"
            f"Нужно: <b>{total} ₽</b>, доступно: <b>{get_balance(call.from_user.id)} ₽</b>.\n"
            "Пополните баланс промокодом в разделе «Профиль».",
            reply_markup=back_kb(),
            parse_mode="HTML",
        )
        await state.clear()
        await call.answer()
        return

    result = TwiBoostApi.add_order(api_key, svc["tb_id"], link, qty)
    if not result or "order" not in result:
        error_text = result.get("error") if isinstance(result, dict) else "неизвестная ошибка"
        await call.message.edit_text(
            f"❌ Не удалось создать заказ в TwiBoost.\nОшибка: {error_text}\n\nСредства не списывались.",
            reply_markup=back_kb(),
        )
        await state.clear()
        await call.answer()
        return

    # Списываем средства только после успешного создания заказа в TwiBoost
    if not deduct_balance(call.from_user.id, total):
        await call.message.edit_text(
            "❌ Недостаточно средств на балансе. Заказ отменён.",
            reply_markup=back_kb(),
        )
        await state.clear()
        await call.answer()
        return

    orders = load_orders()
    local_id = len(orders) + 1
    orders.append({
        "local_id": local_id,
        "tb_order_id": result["order"],
        "user_id": call.from_user.id,
        "username": call.from_user.username,
        "service_name": svc["name"],
        "quantity": qty,
        "link": link,
        "price": round(qty * svc["price"], 2),
        "status": "Pending",
        "created_at": int(time.time()),
    })
    save_orders(orders)
    await state.clear()

    new_balance = get_balance(call.from_user.id)
    await call.message.edit_text(
        f"✅ <b>Заказ #{local_id} оформлен!</b>\n\n"
        f"Услуга: {svc['name']}\n"
        f"Количество: {qty}\n"
        f"Статус: обрабатывается\n\n"
        f"💳 Списано с баланса: <b>{total} ₽</b>\n"
        f"💰 Остаток на балансе: <b>{new_balance} ₽</b>\n\n"
        "Мы уведомим вас, когда заказ будет выполнен.",
        reply_markup=back_kb(),
        parse_mode="HTML",
    )
    await call.answer()


# ─────────────────────────────────────────────
#  АДМИН-ПАНЕЛЬ
# ─────────────────────────────────────────────
# Команда /panel сознательно не добавляется в меню команд бота (BotFather),
# обычные пользователи её не увидят в интерфейсе Telegram.
@router.message(Command("panel"))
async def cmd_panel(message: Message, state: FSMContext):
    cfg = load_config()
    admin_ids = cfg.get("admin_ids", [])

    if admin_ids and message.from_user.id in admin_ids:
        await message.answer("🛠 <b>Админ-панель Dzhant Shop</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")
        return

    # Если вход в панель заблокирован — полностью игнорируем всех, кроме админов
    if cfg.get("panel_locked", False):
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

    # Если пока вводили пароль, панель успели заблокировать — игнорируем
    if cfg.get("panel_locked", False):
        await state.clear()
        return

    if entered and hash_password(entered) == cfg.get("admin_password_hash"):
        # Первый успешный ввод пароля — пользователь навсегда получает статус Admin,
        # пароль больше не потребуется.
        admin_ids = cfg.get("admin_ids", [])
        if message.from_user.id not in admin_ids:
            admin_ids.append(message.from_user.id)
            cfg["admin_ids"] = admin_ids
            save_config(cfg)

        await message.answer("✅ Пароль верный. Вам присвоен статус Admin — пароль больше не понадобится.")
        await message.answer("🛠 <b>Админ-панель Dzhant Shop</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")
    else:
        await message.answer("❌ Неверный пароль.")
    await state.clear()


@router.callback_query(F.data == "adm_open_from_menu")
async def cb_adm_open_from_menu(call: CallbackQuery):
    cfg = load_config()
    if call.from_user.id not in cfg.get("admin_ids", []):
        await call.answer("Доступ запрещён.", show_alert=True)
        return
    await call.message.edit_text(
        "🛠 <b>Админ-панель Dzhant Shop</b>", reply_markup=admin_panel_kb(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "adm_back")
async def cb_adm_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🛠 <b>Админ-панель Dzhant Shop</b>", reply_markup=admin_panel_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "adm_exit")
async def cb_adm_exit(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        f"<b>{SHOP_NAME}</b> — главное меню:",
        reply_markup=main_menu_kb(call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: CallbackQuery):
    stats = load_stats()
    total_started = len(stats.get("started_users", []))
    orders = load_orders()
    await call.message.edit_text(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего нажали /start: <b>{total_started}</b>\n"
        f"🧾 Всего заказов Услуги: <b>{len(orders)}</b>",
        reply_markup=back_kb("adm_back", "⬅️ В админ-панель"),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_uslugi")
async def cb_adm_uslugi(call: CallbackQuery):
    cfg = load_config()
    key = cfg.get("twiboost_api_key")
    if key:
        balance = TwiBoostApi.get_balance(key)
        bal_txt = f"{balance[0]} {balance[1]}" if balance else "н/д"
        status = f"✅ Подключён · Баланс: <b>{bal_txt}</b>"
    else:
        status = "❌ Не подключён"

    services = load_services()
    orders = load_orders()
    await call.message.edit_text(
        "🚀 <b>Управление услугами</b>\n\n"
        f"🔑 TwiBoost: {status}\n"
        f"📦 Лотов: <b>{len(services)}</b>\n"
        f"🧾 Заказов: <b>{len(orders)}</b>\n\n"
        "Выберите раздел:",
        reply_markup=admin_uslugi_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_payments")
async def cb_adm_payments(call: CallbackQuery):
    cfg = load_config()
    has_token = bool(cfg.get("cryptobot_token"))
    enabled = cfg.get("cryptobot_enabled", False)
    if has_token and enabled:
        status = "✅ CryptoBot подключён и включён"
    elif has_token and not enabled:
        status = "⏸ CryptoBot подключён, но выключен"
    else:
        status = "❌ CryptoBot не подключён"
    await call.message.edit_text(
        f"💳 <b>Способы оплаты</b>\n\n{status}\n\n"
        "CryptoBot — приём оплаты через криптовалюту (@CryptoBot в Telegram). "
        "Получите API-токен: @CryptoBot → Crypto Pay → Create App.",
        reply_markup=admin_payments_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_cryptobot_setkey")
async def cb_adm_cryptobot_setkey(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.waiting_cryptobot_token)
    await call.message.edit_text(
        "🔑 <b>CryptoBot API</b>\n\n"
        "Откройте @CryptoBot в Telegram → Crypto Pay → Create App, "
        "скопируйте API-токен и пришлите его сюда:",
        reply_markup=back_kb("adm_payments", "❌ Отмена"),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminFlow.waiting_cryptobot_token)
async def adm_get_cryptobot_token(message: Message, state: FSMContext):
    token = (message.text or "").strip()
    await state.clear()

    wait_msg = await message.answer("⏳ Проверяю токен CryptoBot...")
    app_info = CryptoBotApi.check_token(token)
    await wait_msg.delete()

    if app_info is None:
        await message.answer(
            "❌ Неверный токен или CryptoBot недоступен. Проверьте токен и попробуйте снова.",
            reply_markup=admin_payments_kb(),
        )
        return

    cfg = load_config()
    cfg["cryptobot_token"] = token
    cfg["cryptobot_enabled"] = True
    save_config(cfg)

    app_name = app_info.get("name", "CryptoBot App")
    await message.answer(
        f"✅ CryptoBot подключён и включён!\nПриложение: <b>{app_name}</b>",
        reply_markup=admin_payments_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm_cryptobot_toggle")
async def cb_adm_cryptobot_toggle(call: CallbackQuery):
    cfg = load_config()
    if not cfg.get("cryptobot_token"):
        await call.answer("Сначала подключите CryptoBot API токен.", show_alert=True)
        return
    cfg["cryptobot_enabled"] = not cfg.get("cryptobot_enabled", False)
    save_config(cfg)
    enabled = cfg["cryptobot_enabled"]
    status = "✅ CryptoBot подключён и включён" if enabled else "⏸ CryptoBot подключён, но выключен"
    await call.message.edit_text(
        f"💳 <b>Способы оплаты</b>\n\n{status}",
        reply_markup=admin_payments_kb(),
        parse_mode="HTML",
    )
    await call.answer("Оплата включена" if enabled else "Оплата выключена")


@router.callback_query(F.data == "adm_config")
async def cb_adm_config(call: CallbackQuery):
    cfg = load_config()
    locked = cfg.get("panel_locked", False)
    status = "🔒 Вход в /panel закрыт для всех, кроме админов" if locked else "🔓 Вход в /panel открыт (по паролю)"
    await call.message.edit_text(
        f"⚙️ <b>Конфиг</b>\n\n{status}",
        reply_markup=admin_config_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_toggle_lock")
async def cb_adm_toggle_lock(call: CallbackQuery):
    cfg = load_config()
    cfg["panel_locked"] = not cfg.get("panel_locked", False)
    save_config(cfg)
    locked = cfg["panel_locked"]
    status = "🔒 Вход в /panel закрыт для всех, кроме админов" if locked else "🔓 Вход в /panel открыт (по паролю)"
    await call.message.edit_text(
        f"⚙️ <b>Конфиг</b>\n\n{status}",
        reply_markup=admin_config_kb(),
        parse_mode="HTML",
    )
    await call.answer("Настройка обновлена" if locked else "Настройка снята")


# ─────────────────────────────────────────────
#  АДМИН-ПАНЕЛЬ: ПРОМОКОДЫ
# ─────────────────────────────────────────────
@router.callback_query(F.data == "adm_addpromo")
async def cb_adm_addpromo(call: CallbackQuery):
    await call.message.edit_text(
        "🎟 <b>Создать промокод</b>\n\nВыберите способ создания кода:",
        reply_markup=admin_promo_type_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_active_promos")
async def cb_adm_active_promos(call: CallbackQuery):
    promos = load_promocodes()
    lines = ["🎫 <b>Активные промокоды</b>\n"]
    active = []
    for code, entry in promos.items():
        max_act = entry.get("max_activations", 1)
        used_act = entry.get("activations_used", 1 if entry.get("used") else 0)
        if used_act < max_act:
            active.append((code, entry, used_act, max_act))

    if not active:
        lines.append("Нет ни одного действующего промокода.")
    else:
        for code, entry, used_act, max_act in active:
            lines.append(
                f"<code>{code}</code> — {entry['amount']} ₽ · использован {used_act}/{max_act}"
            )
    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_kb("adm_back", "⬅️ В админ-панель"),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_promo_gen")
async def cb_adm_promo_gen(call: CallbackQuery, state: FSMContext):
    code = generate_promo_code()
    await state.update_data(promo_code=code)
    await state.set_state(AdminFlow.waiting_promo_amount)
    await call.message.edit_text(
        f"🎲 Сгенерирован код: <code>{code}</code>\n\n"
        "Теперь введите сумму, на которую будет активирован промокод (в рублях):",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_promo_manual")
async def cb_adm_promo_manual(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.waiting_promo_custom_code)
    await call.message.edit_text("✏️ Пришлите текст своего промокода (например SALE2026):")
    await call.answer()


@router.message(AdminFlow.waiting_promo_custom_code)
async def adm_get_promo_custom_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("Код не может быть пустым. Пришлите текст промокода:")
        return

    promos = load_promocodes()
    if code in promos:
        await message.answer("Такой промокод уже существует. Придумайте другой:")
        return

    await state.update_data(promo_code=code)
    await state.set_state(AdminFlow.waiting_promo_amount)
    await message.answer(
        f"Код: <code>{code}</code>\n\nТеперь введите сумму, на которую будет активирован промокод (в рублях):",
        parse_mode="HTML",
    )


@router.message(AdminFlow.waiting_promo_amount)
async def adm_get_promo_amount(message: Message, state: FSMContext):
    try:
        amount = float((message.text or "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 100. Введите сумму:")
        return

    await state.update_data(promo_amount=amount)
    await state.set_state(AdminFlow.waiting_promo_activations)
    await message.answer(
        "Сколько раз можно активировать этот промокод (разными пользователями)?\n"
        "Введите число, например 1 или 10:"
    )


@router.message(AdminFlow.waiting_promo_activations)
async def adm_get_promo_activations(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("Нужно положительное целое число. Введите количество активаций:")
        return

    max_activations = int(message.text.strip())
    data = await state.get_data()
    code = data.get("promo_code")
    amount = data.get("promo_amount")
    await state.clear()

    create_promocode(code, amount, max_activations)
    await message.answer(
        f"✅ Промокод создан!\n\n"
        f"Код: <code>{code}</code>\n"
        f"Сумма: <b>{amount} ₽</b>\n"
        f"Активаций: <b>{max_activations}</b>",
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )
@router.callback_query(F.data == "adm_setkey")
async def cb_adm_setkey(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.waiting_api_key)
    await call.message.edit_text(
        "🔑 <b>TwiBoost API</b>\n\n"
        "Пришлите API-ключ TwiBoost (личный кабинет twiboost.com → API):",
        reply_markup=back_kb("adm_uslugi", "❌ Отмена"),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminFlow.waiting_api_key)
async def adm_get_api_key(message: Message, state: FSMContext):
    key = (message.text or "").strip()
    await state.clear()

    wait_msg = await message.answer("⏳ Проверяю подключение к TwiBoost...")
    balance = TwiBoostApi.get_balance(key)
    await wait_msg.delete()

    if balance is None:
        await message.answer(
            "❌ Неверный API-ключ или TwiBoost недоступен.\n"
            "Проверьте ключ в профиле twiboost.com и попробуйте снова через 🚀 Услуги → 🔑 TwiBoost API.",
            reply_markup=admin_uslugi_kb(),
        )
        return

    cfg = load_config()
    cfg["twiboost_api_key"] = key
    save_config(cfg)

    await message.answer(
        f"✅ TwiBoost подключён!\nБаланс: <b>{balance[0]} {balance[1]}</b>",
        reply_markup=admin_uslugi_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm_services")
async def cb_adm_services(call: CallbackQuery):
    await call.message.edit_text(
        "📦 <b>Лоты</b>\n\nСписок активных предложений:",
        reply_markup=admin_services_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_delsvc_"))
async def cb_adm_delsvc(call: CallbackQuery):
    svc_id = call.data.removeprefix("adm_delsvc_")
    services = load_services()
    services.pop(svc_id, None)
    save_services(services)
    await call.message.edit_text(
        "📦 <b>Лоты</b>\n\nЛот удалён.",
        reply_markup=admin_services_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_categories")
async def cb_adm_categories(call: CallbackQuery):
    await call.message.edit_text(
        "🗂 <b>Сервисы</b>\n\n"
        "Это категории для удобной навигации покупателей (Telegram, YouTube и т.д.). "
        "На работу с TwiBoost они не влияют.",
        reply_markup=admin_categories_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "adm_addcat_direct")
async def cb_adm_addcat_direct(call: CallbackQuery, state: FSMContext):
    await state.update_data(direct=True)
    await state.set_state(AdminFlow.waiting_new_category_name)
    await call.message.edit_text(
        "✏️ Напишите название нового сервиса (например Telegram, YouTube и т.д.):",
        reply_markup=back_kb("adm_categories", "❌ Отмена"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_delcat_"))
async def cb_adm_delcat(call: CallbackQuery):
    category = call.data.removeprefix("adm_delcat_")
    categories = load_categories()
    if category in categories:
        categories.remove(category)
        save_categories(categories)
    await call.message.edit_text(
        "🗂 <b>Сервисы</b>\n\nСервис удалён из списка (лоты, привязанные к нему, остаются, "
        "но пока не будут показаны в категориях — привяжите их к другому сервису).",
        reply_markup=admin_categories_kb(),
        parse_mode="HTML",
    )
    await call.answer()


def category_choice_kb() -> InlineKeyboardMarkup:
    categories = load_categories()
    rows = [
        [InlineKeyboardButton(text=cat, callback_data=f"adm_cat_choose_{cat}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text="➕ Новый сервис", callback_data="adm_cat_new")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Услуги", callback_data="adm_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "adm_addsvc")
async def cb_adm_addsvc(call: CallbackQuery, state: FSMContext):
    cfg = load_config()
    if not cfg.get("twiboost_api_key"):
        await call.answer("Сначала задайте TwiBoost API ключ.", show_alert=True)
        return

    categories = load_categories()
    if not categories:
        # Ещё нет ни одного сервиса (категории) — просим создать первый
        await state.set_state(AdminFlow.waiting_new_category_name)
        await call.message.edit_text(
            "➕ <b>Новый лот</b>\n\n"
            "Пока нет ни одного сервиса. Напишите название сервиса "
            "(например Telegram, YouTube и т.д.):",
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            "➕ <b>Новый лот</b>\n\n"
            "Выберите сервис, к которому относится лот, или создайте новый:",
            reply_markup=category_choice_kb(),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data == "adm_cat_new")
async def cb_adm_cat_new(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.waiting_new_category_name)
    await call.message.edit_text(
        "✏️ Напишите название нового сервиса (например Telegram, YouTube и т.д.):",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_cat_choose_"))
async def cb_adm_cat_choose(call: CallbackQuery, state: FSMContext):
    category = call.data.removeprefix("adm_cat_choose_")
    await state.update_data(category=category)
    await state.set_state(AdminFlow.waiting_new_service_name)
    await call.message.edit_text(
        f"➕ <b>Новый лот · {category}</b>\n\nВведите название, которое увидят покупатели:",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminFlow.waiting_new_category_name)
async def adm_get_category_name(message: Message, state: FSMContext):
    category = (message.text or "").strip()
    if not category:
        await message.answer("Название не может быть пустым. Напишите название сервиса:")
        return

    add_category(category)
    data = await state.get_data()

    if data.get("direct"):
        # Прямое добавление сервиса из раздела "Сервисы" — не продолжаем в создание лота
        await state.clear()
        await message.answer(
            f"✅ Сервис «{category}» добавлен.",
            reply_markup=admin_categories_kb(),
        )
        return

    await state.update_data(category=category)
    await state.set_state(AdminFlow.waiting_new_service_name)
    await message.answer(
        f"✅ Сервис «{category}» добавлен.\n\n"
        "Теперь введите название лота, которое увидят покупатели:"
    )


@router.message(AdminFlow.waiting_new_service_name)
async def adm_get_svc_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название:")
        return
    await state.update_data(name=name)
    await state.set_state(AdminFlow.waiting_new_service_description)
    await message.answer("Теперь введите описание лота (покупатели увидят его в карточке):")


@router.message(AdminFlow.waiting_new_service_description)
async def adm_get_svc_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if not description:
        await message.answer("Описание не может быть пустым. Введите описание:")
        return
    await state.update_data(description=description)
    await state.set_state(AdminFlow.waiting_new_service_tbid)
    await message.answer(
        "Теперь укажите вид услуги — ID услуги из TwiBoost "
        "(число service_id из прайса TwiBoost):"
    )


@router.message(AdminFlow.waiting_new_service_tbid)
async def adm_get_svc_tbid(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Нужно число. Пришлите ID услуги TwiBoost:")
        return

    tb_id = int(message.text.strip())
    cfg = load_config()
    key = cfg.get("twiboost_api_key")

    wait_msg = await message.answer("⏳ Проверяю услугу в TwiBoost...")
    tb_services = TwiBoostApi.get_services(key)
    await wait_msg.delete()

    found = next((s for s in tb_services if int(s.get("service", -1)) == tb_id), None)
    if not found:
        await message.answer(f"❌ Услуга #{tb_id} не найдена в TwiBoost. Проверьте ID и попробуйте снова:")
        return

    await state.update_data(tb_id=tb_id, tb_min=int(found["min"]), tb_max=int(found["max"]))
    await state.set_state(AdminFlow.waiting_new_service_price)
    await message.answer(
        f"Найдено: <b>{found['name']}</b>\n"
        f"Мин: {found['min']}, Макс: {found['max']}\n\n"
        "Введите цену за 1 шт. в рублях (например 0.9):",
        parse_mode="HTML",
    )


@router.message(AdminFlow.waiting_new_service_price)
async def adm_get_svc_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Нужно число, например 0.9. Введите цену:")
        return

    data = await state.get_data()
    services = load_services()
    # Каждому лоту незаметно присваивается собственный сгенерированный ID,
    # чтобы связывать покупки в боте с конкретным предложением без путаницы.
    new_id = f"svc_{len(services) + 1}"
    services[new_id] = {
        "tb_id": data["tb_id"],
        "name": data["name"],
        "description": data.get("description", ""),
        "price": price,
        "min": data["tb_min"],
        "max": data["tb_max"],
        "category": data.get("category", "Без категории"),
    }
    save_services(services)
    await state.clear()
    await message.answer(
        f"✅ Лот «{data['name']}» добавлен в сервис «{data.get('category', 'Без категории')}».",
        reply_markup=admin_panel_kb(),
    )


@router.callback_query(F.data == "adm_orders")
async def cb_adm_orders(call: CallbackQuery):
    orders = load_orders()
    last = orders[-10:][::-1]
    if not last:
        text = "🧾 Заказов пока нет."
    else:
        lines = ["🧾 <b>Последние заказы</b>\n"]
        for o in last:
            lines.append(
                f"#{o['local_id']} · {o['service_name']} × {o['quantity']} · "
                f"{o['status']} · @{o.get('username') or o['user_id']}"
            )
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_kb("adm_uslugi", "⬅️ Назад в Услуги"), parse_mode="HTML")
    await call.answer()


# ─────────────────────────────────────────────
#  ФОНОВАЯ ПРОВЕРКА СТАТУСОВ ЗАКАЗОВ
# ─────────────────────────────────────────────
async def order_status_checker(bot: Bot):
    while True:
        try:
            cfg = load_config()
            key = cfg.get("twiboost_api_key")
            if key:
                orders = load_orders()
                changed = False
                for o in orders:
                    if o["status"] in ("Completed", "Canceled", "Cancelled"):
                        continue
                    result = TwiBoostApi.get_status(key, o["tb_order_id"])
                    if not result or "status" not in result:
                        continue
                    new_status = result["status"]
                    if new_status != o["status"]:
                        o["status"] = new_status
                        changed = True
                        try:
                            await bot.send_message(
                                o["user_id"],
                                f"📦 Заказ #{o['local_id']} ({o['service_name']})\n"
                                f"Новый статус: <b>{new_status}</b>",
                                parse_mode="HTML",
                            )
                        except Exception as ex:
                            logger.warning(f"Не удалось уведомить пользователя {o['user_id']}: {ex}")
                if changed:
                    save_orders(orders)
        except Exception as ex:
            logger.error(f"order_status_checker error: {ex}")
        await asyncio.sleep(ORDER_CHECK_INTERVAL)


async def topup_checker(bot: Bot):
    """Фоновая проверка неоплаченных счетов CryptoBot — как только оплата
    поступила, баланс пользователя пополняется автоматически."""
    while True:
        try:
            cfg = load_config()
            token = cfg.get("cryptobot_token")
            if token and cfg.get("cryptobot_enabled"):
                topups = load_topups()
                pending_ids = [
                    invoice_id for invoice_id, entry in topups.items()
                    if entry.get("status") != "paid"
                ]
                for invoice_id in pending_ids:
                    invoice = CryptoBotApi.get_invoice(token, invoice_id)
                    if not invoice:
                        continue
                    if invoice.get("status") == "paid":
                        credited = mark_topup_paid(invoice_id)
                        if credited:
                            entry = load_topups().get(invoice_id, {})
                            user_id = entry.get("user_id")
                            amount = entry.get("amount")
                            if user_id:
                                try:
                                    await bot.send_message(
                                        user_id,
                                        f"✅ Баланс пополнен на <b>{amount} ₽</b> (оплата через CryptoBot получена).",
                                        parse_mode="HTML",
                                    )
                                except Exception as ex:
                                    logger.warning(f"Не удалось уведомить пользователя {user_id}: {ex}")
        except Exception as ex:
            logger.error(f"topup_checker error: {ex}")
        await asyncio.sleep(TOPUP_CHECK_INTERVAL)


# ─────────────────────────────────────────────
#  FALLBACK: НЕРАСПОЗНАННЫЕ СООБЩЕНИЯ И КНОПКИ
#  Должны быть зарегистрированы ПОСЛЕДНИМИ — иначе перехватят
#  апдейты раньше нужных хендлеров.
# ─────────────────────────────────────────────
@router.callback_query()
async def fallback_callback(call: CallbackQuery, state: FSMContext):
    # Нажата кнопка от устаревшей/неизвестной клавиатуры — не оставляем
    # пользователя в подвисшем состоянии, а возвращаем в главное меню.
    await state.clear()
    try:
        await call.message.edit_text(
            f"<b>{SHOP_NAME}</b> — главное меню:",
            reply_markup=main_menu_kb(call.from_user.id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("Кнопка устарела, открыл главное меню", show_alert=False)


@router.message()
async def fallback_message(message: Message, state: FSMContext):
    # Любое сообщение, не попавшее ни под одну команду или активное состояние.
    await state.clear()
    await message.answer(
        "Не понял команду 🤔\nНажмите /start, чтобы открыть меню.",
        reply_markup=main_menu_kb(message.from_user.id),
    )


# ─────────────────────────────────────────────
#  ПЕРВЫЙ ЗАПУСК / MAIN
# ─────────────────────────────────────────────
def first_run_setup() -> dict:
    print("=== Первый запуск Dzhant Shop Bot ===", flush=True)
    print("Настройка выполняется один раз, данные сохранятся в config.json\n", flush=True)

    token = input("Введите TOKEN Telegram-бота (получить у @BotFather): ").strip()
    while not token:
        token = input("Токен не может быть пустым. Введите TOKEN: ").strip()

    print("\nТеперь задайте пароль для админ-панели (команда /panel).", flush=True)
    print("Пароль не отображается на экране при вводе.", flush=True)
    while True:
        password = getpass.getpass("Придумайте пароль администратора: ")
        password_confirm = getpass.getpass("Повторите пароль: ")
        if password and password == password_confirm:
            break
        print("Пароли не совпадают или пустые. Попробуйте снова.", flush=True)

    admin_id_raw = input(
        "\n(Необязательно) Ваш Telegram numeric ID для автодоступа к /panel без пароля "
        "(Enter — пропустить): "
    ).strip()

    cfg = {
        "token": token,
        "admin_password_hash": hash_password(password),
        "admin_ids": [int(admin_id_raw)] if admin_id_raw.isdigit() else [],
        "panel_locked": False,
    }
    save_config(cfg)
    print("\nНастройка завершена. Конфигурация сохранена в config.json", flush=True)
    print("Запускаю бота...\n", flush=True)
    return cfg


async def main():
    cfg = load_config()
    if not cfg.get("token") or not cfg.get("admin_password_hash"):
        cfg = first_run_setup()

    bot = Bot(token=cfg["token"])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(order_status_checker(bot))
    asyncio.create_task(topup_checker(bot))

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
