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
import shutil

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
GC_CATEGORIES_PATH = os.path.join(BASE_DIR, "giftcard_categories.json")
GIFTCARDS_PATH = os.path.join(BASE_DIR, "giftcards.json")
RATES_PATH = os.path.join(BASE_DIR, "rates.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

SHOP_NAME = "Dzhant Shop"
TWIBOOST_API_URL = "https://twiboost.com/api/v2"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"
ORDER_CHECK_INTERVAL = 180  # сек, как часто проверять статусы активных заказов
TOPUP_CHECK_INTERVAL = 20  # сек, как часто проверять неоплаченные счета CryptoBot
RATES_UPDATE_INTERVAL = 3600  # сек, обновление курса валют раз в час
BACKUP_INTERVAL = 86400  # сек, автобэкап раз в сутки

# Валюты: рубль (базовая, в ней хранятся все цены и баланс) + доллар + все страны СНГ по отдельности
CURRENCIES = {
    "RUB": {"name": "Российский рубль", "symbol": "₽"},
    "USD": {"name": "Доллар США", "symbol": "$"},
    "UAH": {"name": "Украинская гривна", "symbol": "₴"},
    "KZT": {"name": "Казахстанский тенге", "symbol": "₸"},
    "BYN": {"name": "Белорусский рубль", "symbol": "Br"},
    "UZS": {"name": "Узбекский сум", "symbol": "so'm"},
    "AMD": {"name": "Армянский драм", "symbol": "֏"},
    "AZN": {"name": "Азербайджанский манат", "symbol": "₼"},
    "GEL": {"name": "Грузинский лари", "symbol": "₾"},
    "KGS": {"name": "Киргизский сом", "symbol": "с"},
    "TJS": {"name": "Таджикский сомони", "symbol": "SM"},
    "MDL": {"name": "Молдавский лей", "symbol": "L"},
    "TMT": {"name": "Туркменский манат", "symbol": "m"},
}

# Страны активации для гифт-карт: Global, США и все страны СНГ по отдельности
GIFTCARD_COUNTRIES = [
    "Global", "США", "Украина", "Казахстан", "Беларусь", "Узбекистан",
    "Армения", "Азербайджан", "Грузия", "Киргизия", "Таджикистан",
    "Молдова", "Туркменистан", "Россия",
]

LOG_PATH = os.path.join(BASE_DIR, "bot.log")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
# aiogram по умолчанию логирует каждое апдейт-событие целиком в консоль —
# это и есть тот самый "поток текста" при получении сообщений. Приглушаем.
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

logger = logging.getLogger("dzhant_shop")
logger.setLevel(logging.INFO)

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
# ─────────────────────────────────────────────
#  ГИФТ-КАРТЫ (склад ключей)
# ─────────────────────────────────────────────
def load_gc_categories() -> list:
    return _load_json(GC_CATEGORIES_PATH, [])


def save_gc_categories(data: list) -> None:
    _save_json(GC_CATEGORIES_PATH, data)


def add_gc_category(name: str) -> None:
    categories = load_gc_categories()
    if name not in categories:
        categories.append(name)
        save_gc_categories(categories)


def load_giftcards() -> dict:
    return _load_json(GIFTCARDS_PATH, {})


def save_giftcards(data: dict) -> None:
    _save_json(GIFTCARDS_PATH, data)


# ─────────────────────────────────────────────
#  КУРС ВАЛЮТ (обновляется раз в час фоновой задачей)
# ─────────────────────────────────────────────
def load_rates() -> dict:
    return _load_json(RATES_PATH, {"base": "RUB", "rates": {}, "updated_at": 0})


def save_rates(data: dict) -> None:
    _save_json(RATES_PATH, data)


def fetch_rates() -> bool:
    """Тянет актуальный курс валют (база — рубль) с бесплатного публичного API."""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/RUB", timeout=15)
        data = r.json()
        if data.get("result") == "success" and "rates" in data:
            save_rates({
                "base": "RUB",
                "rates": data["rates"],
                "updated_at": int(time.time()),
            })
            return True
    except Exception as ex:
        logger.error(f"Не удалось обновить курс валют: {ex}")
    return False


def convert_from_rub(amount_rub: float, currency: str) -> float:
    if currency == "RUB":
        return round(amount_rub, 2)
    rates = load_rates().get("rates", {})
    rate = rates.get(currency)
    if not rate:
        return round(amount_rub, 2)
    return round(amount_rub * rate, 2)


def get_user_currency(user_id: int) -> str:
    user = get_user(user_id)
    return user.get("currency", "RUB")


def set_user_currency(user_id: int, currency: str) -> None:
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {"balance": 0.0, "promocodes_used": []}
    users[key]["currency"] = currency
    save_users(users)


def fmt_price(amount_rub: float, user_id: int) -> str:
    """Форматирует сумму (хранится всегда в рублях) в валюту покупателя."""
    currency = get_user_currency(user_id)
    symbol = CURRENCIES.get(currency, CURRENCIES["RUB"])["symbol"]
    value = convert_from_rub(amount_rub, currency)
    return f"{value} {symbol}"


# ─────────────────────────────────────────────
#  АВТОБЭКАП ДАННЫХ
# ─────────────────────────────────────────────
def backup_data() -> str | None:
    """Копирует все json-файлы данных в /backups/backup_<дата_время>/."""
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest_dir = os.path.join(BACKUP_DIR, f"backup_{stamp}")
        os.makedirs(dest_dir, exist_ok=True)
        sources = [
            CONFIG_PATH, SERVICES_PATH, CATEGORIES_PATH, ORDERS_PATH,
            STATS_PATH, USERS_PATH, PROMOCODES_PATH, TOPUPS_PATH,
            GC_CATEGORIES_PATH, GIFTCARDS_PATH, RATES_PATH,
        ]
        for src in sources:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest_dir, os.path.basename(src)))
        return dest_dir
    except Exception as ex:
        logger.error(f"Ошибка автобэкапа: {ex}")
        return None


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
    waiting_gc_category_name = State()
    waiting_gc_name = State()
    waiting_gc_price = State()
    waiting_gc_key = State()


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
        [InlineKeyboardButton(text="🛍 Товары", callback_data="menu_uslugi")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="ℹ️ О магазине", callback_data="menu_about")],
    ]
    if user_id is not None:
        cfg = load_config()
        if user_id in cfg.get("admin_ids", []):
            kb.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="adm_open_from_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def pair_rows(buttons: list) -> list:
    """Раскладывает список кнопок по 2 в ряд (для более удобных клавиатур)."""
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])
    return rows


def uslugi_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="🚀 Накрутка", callback_data="uslugi_nakrutka"),
        InlineKeyboardButton(text="🎁 Гифт-карты", callback_data="menu_giftcards"),
    ]
    kb = pair_rows(buttons)
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
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

    buttons = [InlineKeyboardButton(text=cat, callback_data=f"nkcat_{cat}") for cat in categories]
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nakrutka_services_kb(category: str, user_id: int | None = None) -> InlineKeyboardMarkup:
    services = load_services()
    buttons = []
    for svc_id, svc in services.items():
        if svc.get("category", "Без категории") != category:
            continue
        price_str = fmt_price(svc["price"], user_id) if user_id else f"{svc['price']} ₽"
        buttons.append(InlineKeyboardButton(
            text=f"{svc['name']} — {price_str}/шт",
            callback_data=f"svc_{svc_id}",
        ))
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="uslugi_nakrutka")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(callback_data="back_main", text="⬅️ Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]])


def admin_panel_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton(text="🚀 Товары", callback_data="adm_uslugi"),
        InlineKeyboardButton(text="🎁 Гифт-карты", callback_data="adm_giftcards"),
        InlineKeyboardButton(text="🧾 Заказы", callback_data="adm_orders"),
        InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_addpromo"),
        InlineKeyboardButton(text="🎫 Активные промокоды", callback_data="adm_active_promos"),
        InlineKeyboardButton(text="💳 Способы оплаты", callback_data="adm_payments"),
        InlineKeyboardButton(text="⚙️ Конфиг", callback_data="adm_config"),
    ]
    kb = pair_rows(buttons)
    kb.append([InlineKeyboardButton(text="🚪 Выход", callback_data="adm_exit")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_payments_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    has_token = bool(cfg.get("cryptobot_token"))
    enabled = cfg.get("cryptobot_enabled", False)
    token_status = "✅ подключён" if has_token else "❌ не подключён"
    toggle_text = "🔴 Выключить" if enabled else "🟢 Включить"
    buttons = [InlineKeyboardButton(text=f"🔑 CryptoBot ({token_status})", callback_data="adm_cryptobot_setkey")]
    if has_token:
        buttons.append(InlineKeyboardButton(text=toggle_text, callback_data="adm_cryptobot_toggle"))
    kb = pair_rows(buttons)
    kb.append([InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_uslugi_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    key_status = "✅ подключён" if cfg.get("twiboost_api_key") else "❌ не подключён"
    buttons = [
        InlineKeyboardButton(text=f"🔑 TwiBoost API ({key_status})", callback_data="adm_setkey"),
        InlineKeyboardButton(text="🗂 Сервисы", callback_data="adm_categories"),
        InlineKeyboardButton(text="📦 Лоты", callback_data="adm_services"),
        InlineKeyboardButton(text="🧾 Заказы", callback_data="adm_orders"),
    ]
    kb = pair_rows(buttons)
    kb.append([InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")])
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
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Товары", callback_data="adm_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_config_kb() -> InlineKeyboardMarkup:
    cfg = load_config()
    locked = cfg.get("panel_locked", False)
    lock_text = "🔓 Разрешить /panel" if locked else "🔒 Запретить /panel"
    kb = [
        [InlineKeyboardButton(text=lock_text, callback_data="adm_toggle_lock")],
        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_promo_type_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🎲 Сгенерировать", callback_data="adm_promo_gen"),
            InlineKeyboardButton(text="✏️ Ввести свой", callback_data="adm_promo_manual"),
        ],
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
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Товары", callback_data="adm_uslugi")])
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
    buttons = []
    if cfg.get("cryptobot_token") and cfg.get("cryptobot_enabled"):
        buttons.append(InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="profile_topup"))
    buttons.append(InlineKeyboardButton(text="🎟 Промокод", callback_data="profile_promo"))
    buttons.append(InlineKeyboardButton(text="📋 Мои заказы", callback_data="profile_orders"))
    buttons.append(InlineKeyboardButton(text="⚙️ Настройки", callback_data="profile_settings"))
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await call.message.edit_text(
        "👤 <b>Ваш профиль</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.full_name}\n"
        f"Username: @{user.username if user.username else '—'}\n"
        f"💰 Баланс: <b>{fmt_price(balance, user.id)}</b>\n\n"
        "Есть промокод? Активируйте его кнопкой ниже.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "profile_orders")
async def cb_profile_orders(call: CallbackQuery):
    orders = load_orders()
    my_orders = [o for o in orders if o.get("user_id") == call.from_user.id]
    my_orders.sort(key=lambda o: o.get("created_at", 0), reverse=True)
    my_orders = my_orders[:15]

    if not my_orders:
        text = "📋 <b>Мои заказы</b>\n\nУ вас пока нет заказов."
    else:
        lines = ["📋 <b>Мои заказы</b> (последние 15)\n"]
        status_emoji = {
            "Pending": "⏳", "In progress": "🔄", "Processing": "🔄",
            "Completed": "✅", "Partial": "⚠️", "Canceled": "❌", "Cancelled": "❌",
        }
        for o in my_orders:
            emoji = status_emoji.get(o.get("status", "Pending"), "•")
            lines.append(
                f"{emoji} #{o['local_id']} · {o['service_name']} × {o['quantity']} — "
                f"{fmt_price(o['price'], call.from_user.id)} · {o.get('status', 'Pending')}"
            )
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_kb("menu_profile"), parse_mode="HTML")
    await call.answer()


def profile_currency_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{data['symbol']} {code}", callback_data=f"setcur_{code}")
        for code, data in CURRENCIES.items()
    ]
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "profile_settings")
async def cb_profile_settings(call: CallbackQuery):
    current = get_user_currency(call.from_user.id)
    cur_name = CURRENCIES.get(current, CURRENCIES["RUB"])["name"]
    await call.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"Текущая валюта отображения цен: <b>{cur_name}</b>\n\n"
        "Все расчёты внутри магазина ведутся в рублях, валюта ниже влияет "
        "только на то, как цены и баланс показываются вам.\n\n"
        "Выберите валюту:",
        reply_markup=profile_currency_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("setcur_"))
async def cb_set_currency(call: CallbackQuery):
    currency = call.data.removeprefix("setcur_")
    if currency not in CURRENCIES:
        await call.answer("Неизвестная валюта.", show_alert=True)
        return
    set_user_currency(call.from_user.id, currency)
    await call.answer(f"Валюта изменена на {currency}")
    await cb_profile_settings(call)


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
        f"Начислено: <b>{fmt_price(result['amount'], message.from_user.id)}</b>\n"
        f"Текущий баланс: <b>{fmt_price(result['balance'], message.from_user.id)}</b>",
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
        f"Сумма: <b>{amount} ₽</b> ({fmt_price(amount, message.from_user.id)})\n\n"
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
                f"✅ Оплата получена! Баланс пополнен.\n💰 Текущий баланс: <b>{fmt_price(balance, call.from_user.id)}</b>",
                reply_markup=back_kb("menu_profile"),
                parse_mode="HTML",
            )
        else:
            await call.message.edit_text(
                f"✅ Этот счёт уже был зачислен ранее.\n💰 Текущий баланс: <b>{fmt_price(balance, call.from_user.id)}</b>",
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
        "🛍 <b>Товары</b>\n\nВыберите раздел:",
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
        reply_markup=nakrutka_services_kb(category, call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


# ─────────────────────────────────────────────
#  ГИФТ-КАРТЫ (покупатель)
# ─────────────────────────────────────────────
def giftcard_categories_kb() -> InlineKeyboardMarkup:
    giftcards = load_giftcards()
    used_categories = {gc.get("category") for gc in giftcards.values()}
    categories = [c for c in load_gc_categories() if c in used_categories]
    buttons = [InlineKeyboardButton(text=cat, callback_data=f"gccat_{cat}") for cat in categories]
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_uslugi")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def giftcard_lots_kb(category: str, user_id: int) -> InlineKeyboardMarkup:
    giftcards = load_giftcards()
    buttons = []
    for gc_id, gc in giftcards.items():
        if gc.get("category") != category:
            continue
        stock = len(gc.get("keys", []))
        price_str = fmt_price(gc["price"], user_id)
        buttons.append(InlineKeyboardButton(
            text=f"{gc['name']} ({gc['country']}) — {price_str} · {stock} шт",
            callback_data=f"gclot_{gc_id}",
        ))
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_giftcards")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu_giftcards")
async def cb_menu_giftcards(call: CallbackQuery):
    giftcards = load_giftcards()
    if not giftcards:
        await call.message.edit_text(
            "🎁 <b>Гифт-карты</b>\n\nПока нет ни одной гифт-карты в продаже.",
            reply_markup=back_kb("menu_uslugi"),
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            "🎁 <b>Гифт-карты</b>\n\nВыберите сервис:",
            reply_markup=giftcard_categories_kb(),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data.startswith("gccat_"))
async def cb_gc_category(call: CallbackQuery):
    category = call.data.removeprefix("gccat_")
    await call.message.edit_text(
        f"🎁 <b>Гифт-карты — {category}</b>\n\nВыберите карту:",
        reply_markup=giftcard_lots_kb(category, call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("gclot_"))
async def cb_gc_lot_info(call: CallbackQuery):
    gc_id = call.data.removeprefix("gclot_")
    giftcards = load_giftcards()
    gc = giftcards.get(gc_id)
    if not gc:
        await call.answer("Карта больше не доступна", show_alert=True)
        return

    stock = len(gc.get("keys", []))
    kb_rows = []
    if stock > 0:
        kb_rows.append([InlineKeyboardButton(text="🛒 Купить", callback_data=f"gcbuy_{gc_id}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gccat_{gc['category']}")])

    await call.message.edit_text(
        f"🎁 <b>{gc['name']}</b>\n\n"
        f"🌍 Регион активации: {gc['country']}\n"
        f"💰 Цена: <b>{fmt_price(gc['price'], call.from_user.id)}</b>\n"
        f"📦 В наличии: <b>{stock} шт</b>\n\n"
        + ("Нажмите «Купить», чтобы получить ключ." if stock > 0 else "⚠️ Сейчас нет в наличии."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("gcbuy_"))
async def cb_gc_purchase(call: CallbackQuery):
    gc_id = call.data.removeprefix("gcbuy_")
    giftcards = load_giftcards()
    gc = giftcards.get(gc_id)
    if not gc or not gc.get("keys"):
        await call.answer("Карта закончилась или недоступна.", show_alert=True)
        return

    price = gc["price"]
    user_id = call.from_user.id
    if get_balance(user_id) < price:
        await call.answer("Недостаточно средств на балансе.", show_alert=True)
        return

    # Забираем ключ со склада и сразу сохраняем — чтобы никто другой не получил тот же ключ
    key = gc["keys"].pop(0)
    if not deduct_balance(user_id, price):
        gc["keys"].insert(0, key)  # средств не хватило — возвращаем ключ на склад
        save_giftcards(giftcards)
        await call.answer("Недостаточно средств на балансе.", show_alert=True)
        return

    gc.setdefault("sold", []).append({
        "user_id": user_id,
        "username": call.from_user.username,
        "key": key,
        "sold_at": int(time.time()),
    })
    save_giftcards(giftcards)

    new_balance = get_balance(user_id)
    await call.message.edit_text(
        f"✅ <b>Покупка успешна!</b>\n\n"
        f"🎁 {gc['name']} ({gc['country']})\n"
        f"🔑 Ваш ключ:\n<code>{key}</code>\n\n"
        f"💳 Списано: <b>{fmt_price(price, user_id)}</b>\n"
        f"💰 Остаток на балансе: <b>{fmt_price(new_balance, user_id)}</b>",
        reply_markup=back_kb("menu_giftcards"),
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
        f"💰 Цена: <b>{fmt_price(svc['price'], call.from_user.id)}</b> за 1 шт.\n"
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
    uid = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="confirm_order")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_main")],
    ])
    await message.answer(
        "📋 <b>Подтверждение заказа</b>\n\n"
        f"Услуга: {svc['name']}\n"
        f"Количество: {qty}\n"
        f"Ссылка: {link}\n"
        f"Итого: <b>{fmt_price(total, uid)}</b>\n\n"
        f"💳 С баланса спишется: <b>{fmt_price(total, uid)}</b>\n"
        f"💰 Текущий баланс: <b>{fmt_price(balance, uid)}</b>\n\n"
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
            f"Нужно: <b>{fmt_price(total, call.from_user.id)}</b>, "
            f"доступно: <b>{fmt_price(get_balance(call.from_user.id), call.from_user.id)}</b>.\n"
            "Пополните баланс в разделе «Профиль».",
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
        f"💳 Списано с баланса: <b>{fmt_price(total, call.from_user.id)}</b>\n"
        f"💰 Остаток на балансе: <b>{fmt_price(new_balance, call.from_user.id)}</b>\n\n"
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


def admin_giftcards_kb() -> InlineKeyboardMarkup:
    categories = load_gc_categories()
    giftcards = load_giftcards()
    rows = []
    for cat in categories:
        count = sum(1 for gc in giftcards.values() if gc.get("category") == cat)
        rows.append([
            InlineKeyboardButton(text=f"{cat} ({count})", callback_data=f"adm_gc_cat_{cat}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_gc_delcat_{cat}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить сервис", callback_data="adm_gc_addcat")])
    rows.append([InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_gc_lots_kb(category: str) -> InlineKeyboardMarkup:
    giftcards = load_giftcards()
    rows = []
    for gc_id, gc in giftcards.items():
        if gc.get("category") != category:
            continue
        stock = len(gc.get("keys", []))
        rows.append([InlineKeyboardButton(
            text=f"{gc['name']} ({gc['country']}) · {stock} шт",
            callback_data=f"adm_gclot_{gc_id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить лот", callback_data=f"adm_gc_addlot_{category}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в Гифт-карты", callback_data="adm_giftcards")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_gc_country_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=country, callback_data=f"adm_gccountry_{i}")
        for i, country in enumerate(GIFTCARD_COUNTRIES)
    ]
    rows = pair_rows(buttons)
    rows.append([InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_gc_lot_detail_kb(gc_id: str, category: str) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="➕ Добавить ключ", callback_data=f"adm_gc_addkey_{gc_id}"),
            InlineKeyboardButton(text="📦 Склад", callback_data=f"adm_gc_stock_{gc_id}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить лот", callback_data=f"adm_gc_dellot_{gc_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_gc_cat_{category}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "adm_giftcards")
async def cb_adm_giftcards(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>Гифт-карты</b>\n\n"
        "Сервисы (Steam, Xbox и т.д.) — внутри каждого можно создавать лоты со своим "
        "складом ключей.",
        reply_markup=admin_giftcards_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_gc_addcat")
async def cb_adm_gc_addcat(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.waiting_gc_category_name)
    await call.message.edit_text(
        "✏️ Напишите название сервиса гифт-карт (например Steam, Xbox, PlayStation и т.д.):",
        reply_markup=back_kb("adm_giftcards", "❌ Отмена"),
    )
    await call.answer()


@router.message(AdminFlow.waiting_gc_category_name)
async def adm_get_gc_category_name(message: Message, state: FSMContext):
    category = (message.text or "").strip()
    if not category:
        await message.answer("Название не может быть пустым. Напишите название сервиса:")
        return
    add_gc_category(category)
    await state.clear()
    await message.answer(f"✅ Сервис «{category}» добавлен.", reply_markup=admin_giftcards_kb())


@router.callback_query(F.data.startswith("adm_gc_delcat_"))
async def cb_adm_gc_delcat(call: CallbackQuery):
    category = call.data.removeprefix("adm_gc_delcat_")
    categories = load_gc_categories()
    if category in categories:
        categories.remove(category)
        save_gc_categories(categories)
    await call.message.edit_text(
        "🎁 <b>Гифт-карты</b>\n\nСервис удалён из списка (лоты внутри него остаются, "
        "но не будут показаны, пока не привяжете их к другому сервису).",
        reply_markup=admin_giftcards_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_gc_cat_"))
async def cb_adm_gc_cat(call: CallbackQuery):
    category = call.data.removeprefix("adm_gc_cat_")
    await call.message.edit_text(
        f"🎁 <b>Гифт-карты — {category}</b>\n\nЛоты:",
        reply_markup=admin_gc_lots_kb(category),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_gc_addlot_"))
async def cb_adm_gc_addlot(call: CallbackQuery, state: FSMContext):
    category = call.data.removeprefix("adm_gc_addlot_")
    await state.update_data(gc_category=category)
    await state.set_state(AdminFlow.waiting_gc_name)
    await call.message.edit_text(
        f"➕ <b>Новый лот · {category}</b>\n\nВведите название, которое увидят покупатели "
        "(например «Steam Wallet 500₽»):",
        reply_markup=back_kb(f"adm_gc_cat_{category}", "❌ Отмена"),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminFlow.waiting_gc_name)
async def adm_get_gc_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название лота:")
        return
    await state.update_data(gc_name=name)
    await message.answer(
        "Выберите страну активации:",
        reply_markup=admin_gc_country_kb(),
    )


@router.callback_query(F.data.startswith("adm_gccountry_"))
async def cb_adm_gc_country(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.removeprefix("adm_gccountry_"))
    country = GIFTCARD_COUNTRIES[idx]
    await state.update_data(gc_country=country)
    await state.set_state(AdminFlow.waiting_gc_price)
    await call.message.edit_text(f"Страна: <b>{country}</b>\n\nВведите цену за 1 ключ в рублях:", parse_mode="HTML")
    await call.answer()


@router.message(AdminFlow.waiting_gc_price)
async def adm_get_gc_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 500. Введите цену:")
        return

    data = await state.get_data()
    category = data["gc_category"]
    giftcards = load_giftcards()
    new_id = f"gc_{len(giftcards) + 1}_{int(time.time())}"
    giftcards[new_id] = {
        "category": category,
        "name": data["gc_name"],
        "country": data["gc_country"],
        "price": price,
        "keys": [],
        "sold": [],
    }
    save_giftcards(giftcards)
    await state.clear()
    await message.answer(
        f"✅ Лот «{data['gc_name']}» добавлен в «{category}».\n\n"
        "Теперь добавьте ключи через карточку лота (кнопка «➕ Добавить ключ»).",
        reply_markup=admin_gc_lots_kb(category),
    )


@router.callback_query(F.data.startswith("adm_gclot_"))
async def cb_adm_gclot(call: CallbackQuery):
    gc_id = call.data.removeprefix("adm_gclot_")
    giftcards = load_giftcards()
    gc = giftcards.get(gc_id)
    if not gc:
        await call.answer("Лот не найден.", show_alert=True)
        return
    stock = len(gc.get("keys", []))
    sold_count = len(gc.get("sold", []))
    await call.message.edit_text(
        f"🎁 <b>{gc['name']}</b>\n\n"
        f"Сервис: {gc['category']}\n"
        f"🌍 Страна: {gc['country']}\n"
        f"💰 Цена: {gc['price']} ₽\n"
        f"📦 В наличии: <b>{stock} шт</b>\n"
        f"🛒 Продано: {sold_count} шт",
        reply_markup=admin_gc_lot_detail_kb(gc_id, gc["category"]),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_gc_addkey_"))
async def cb_adm_gc_addkey(call: CallbackQuery, state: FSMContext):
    gc_id = call.data.removeprefix("adm_gc_addkey_")
    giftcards = load_giftcards()
    if gc_id not in giftcards:
        await call.answer("Лот не найден.", show_alert=True)
        return
    await state.update_data(gc_id=gc_id)
    await state.set_state(AdminFlow.waiting_gc_key)
    await call.message.edit_text(
        "🔑 Пришлите ключ(и) для склада.\n"
        "Можно несколько сразу — каждый ключ с новой строки.",
        reply_markup=back_kb(f"adm_gclot_{gc_id}", "❌ Отмена"),
    )
    await call.answer()


@router.message(AdminFlow.waiting_gc_key)
async def adm_get_gc_key(message: Message, state: FSMContext):
    data = await state.get_data()
    gc_id = data.get("gc_id")
    giftcards = load_giftcards()
    gc = giftcards.get(gc_id)
    if not gc:
        await state.clear()
        await message.answer("Лот больше не существует.", reply_markup=admin_giftcards_kb())
        return

    keys = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not keys:
        await message.answer("Не нашёл ни одного ключа. Пришлите ключ(и), каждый с новой строки:")
        return

    gc.setdefault("keys", []).extend(keys)
    save_giftcards(giftcards)
    await state.clear()
    await message.answer(
        f"✅ Добавлено ключей: <b>{len(keys)}</b>\n📦 Всего на складе: <b>{len(gc['keys'])} шт</b>",
        reply_markup=admin_gc_lot_detail_kb(gc_id, gc["category"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_gc_stock_"))
async def cb_adm_gc_stock(call: CallbackQuery):
    gc_id = call.data.removeprefix("adm_gc_stock_")
    giftcards = load_giftcards()
    gc = giftcards.get(gc_id)
    if not gc:
        await call.answer("Лот не найден.", show_alert=True)
        return
    keys = gc.get("keys", [])
    if not keys:
        text = f"📦 <b>Склад · {gc['name']}</b>\n\nКлючей нет."
    else:
        shown = keys[:50]
        lines = "\n".join(f"<code>{k}</code>" for k in shown)
        text = f"📦 <b>Склад · {gc['name']}</b>\n\nВсего: {len(keys)} шт\n\n{lines}"
        if len(keys) > 50:
            text += f"\n\n… и ещё {len(keys) - 50} шт"
    await call.message.edit_text(
        text,
        reply_markup=back_kb(f"adm_gclot_{gc_id}", "⬅️ Назад"),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_gc_dellot_"))
async def cb_adm_gc_dellot(call: CallbackQuery):
    gc_id = call.data.removeprefix("adm_gc_dellot_")
    giftcards = load_giftcards()
    gc = giftcards.pop(gc_id, None)
    save_giftcards(giftcards)
    category = gc["category"] if gc else None
    await call.message.edit_text(
        "🎁 <b>Гифт-карты</b>\n\nЛот удалён.",
        reply_markup=admin_gc_lots_kb(category) if category else admin_giftcards_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "adm_orders")
async def cb_adm_orders(call: CallbackQuery):
    orders = load_orders()
    last = orders[-15:][::-1]
    if not last:
        text = "🧾 <b>Заказы</b>\n\nЗаказов пока нет."
    else:
        lines = [f"🧾 <b>Заказы</b> (последние {len(last)} из {len(orders)})\n"]
        for o in last:
            lines.append(
                f"#{o['local_id']} · {o['service_name']} × {o['quantity']} · "
                f"{o['status']} · {o['price']} ₽ · @{o.get('username') or o['user_id']}"
            )
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_kb("adm_back", "⬅️ В админ-панель"), parse_mode="HTML")
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
                                        f"✅ Баланс пополнен на <b>{fmt_price(amount, user_id)}</b> (оплата через CryptoBot получена).",
                                        parse_mode="HTML",
                                    )
                                except Exception as ex:
                                    logger.warning(f"Не удалось уведомить пользователя {user_id}: {ex}")
        except Exception as ex:
            logger.error(f"topup_checker error: {ex}")
        await asyncio.sleep(TOPUP_CHECK_INTERVAL)


async def rates_updater():
    """Фоновое обновление курса валют раз в час (RATES_UPDATE_INTERVAL)."""
    while True:
        try:
            ok = fetch_rates()
            if ok:
                logger.info("Курс валют обновлён")
            else:
                logger.warning("Не удалось обновить курс валют, оставляю прежний")
        except Exception as ex:
            logger.error(f"rates_updater error: {ex}")
        await asyncio.sleep(RATES_UPDATE_INTERVAL)


async def backup_scheduler():
    """Фоновый автобэкап всех json-файлов раз в сутки (BACKUP_INTERVAL)."""
    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        try:
            dest = backup_data()
            if dest:
                logger.info(f"Автобэкап создан: {dest}")
        except Exception as ex:
            logger.error(f"backup_scheduler error: {ex}")


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
# ─────────────────────────────────────────────
#  ФОНОВЫЙ ЗАПУСК (systemd)
#  Чтобы бот не зависел от открытой консоли/SSH-сессии и переживал
#  перезагрузку сервера, предлагаем установить его как systemd-сервис.
# ─────────────────────────────────────────────
SERVICE_NAME = "dzhant-shop-bot"


def systemd_available() -> bool:
    return (
        sys.platform.startswith("linux")
        and shutil.which("systemctl") is not None
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    )


def install_systemd_service() -> bool:
    service_path = f"/etc/systemd/system/{SERVICE_NAME}.service"
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    run_user = os.environ.get("SUDO_USER") or getpass.getuser()

    unit = (
        "[Unit]\n"
        "Description=Dzhant Shop Telegram Bot\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={run_user}\n"
        f"WorkingDirectory={BASE_DIR}\n"
        f"ExecStart={python_path} {script_path}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        f"StandardOutput=append:{LOG_PATH}\n"
        f"StandardError=append:{LOG_PATH}\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )

    try:
        with open(service_path, "w", encoding="utf-8") as f:
            f.write(unit)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        return True
    except Exception as ex:
        print(f"Не удалось установить systemd-сервис: {ex}", flush=True)
        return False


def print_manual_background_instructions() -> None:
    script_path = os.path.abspath(__file__)
    print("\nЧтобы бот работал в фоне без systemd, запустите его одним из способов:", flush=True)
    print(f"  nohup {sys.executable} {script_path} > /dev/null 2>&1 &", flush=True)
    print("  — или через screen: screen -S dzhant_shop -dm " f"{sys.executable} {script_path}", flush=True)
    print("  — или через tmux:   tmux new -d -s dzhant_shop "
          f"'{sys.executable} {script_path}'", flush=True)
    print(f"\nЛоги бота пишутся в файл: {LOG_PATH}\n", flush=True)


def offer_background_install() -> None:
    """Предлагает установить бота как фоновый systemd-сервис сразу после
    первичной настройки, чтобы консоль можно было закрыть."""
    print(
        "\nЧтобы бот работал постоянно и не зависел от открытой консоли/SSH,\n"
        "его можно запустить как фоновый systemd-сервис — он переживёт\n"
        "закрытие консоли и перезапуск сервера.\n",
        flush=True,
    )
    answer = input("Установить как фоновый сервис прямо сейчас? (y/n): ").strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        print_manual_background_instructions()
        return

    if not systemd_available():
        print(
            "\n⚠️ Автоустановка сервиса недоступна: нужен Linux-сервер и запуск "
            "от root (sudo python3 dzhant_shop_bot.py).",
            flush=True,
        )
        print_manual_background_instructions()
        return

    if install_systemd_service():
        print(f"\n✅ Сервис «{SERVICE_NAME}» установлен и запущен в фоне.", flush=True)
        print("Полезные команды:", flush=True)
        print(f"  systemctl status {SERVICE_NAME}    — статус", flush=True)
        print(f"  systemctl restart {SERVICE_NAME}   — перезапуск", flush=True)
        print(f"  systemctl stop {SERVICE_NAME}      — остановка", flush=True)
        print(f"  journalctl -u {SERVICE_NAME} -f    — логи systemd в реальном времени", flush=True)
        print(f"  tail -f {LOG_PATH}                 — файл логов бота\n", flush=True)
        print("Эту консоль теперь можно закрыть — бот продолжит работать в фоне.\n", flush=True)
        sys.exit(0)
    else:
        print_manual_background_instructions()


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

    offer_background_install()

    print("Запускаю бота в этой консоли...\n", flush=True)
    return cfg


async def main():
    cfg = load_config()
    if not cfg.get("token") or not cfg.get("admin_password_hash"):
        cfg = first_run_setup()

    bot = Bot(token=cfg["token"])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    fetch_rates()  # подтягиваем курс валют сразу при старте, дальше — раз в час
    asyncio.create_task(order_status_checker(bot))
    asyncio.create_task(topup_checker(bot))
    asyncio.create_task(rates_updater())
    asyncio.create_task(backup_scheduler())

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
