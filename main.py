import os
import sys
import asyncio
import secrets
import string
import random
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Optional
from typing import cast
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    LabeledPrice, PreCheckoutQuery,
    BufferedInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Text, create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import desc, func
from sqlalchemy import cast, Date

from openai import AsyncOpenAI
import aiohttp
from loguru import logger
from dotenv import load_dotenv

# ==================== ЗАГРУЗКА ПЕРЕМЕННЫХ ====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("\n" + "=" * 60)
    print("❌ ОШИБКА: BOT_TOKEN НЕ НАЙДЕН!")
    print("=" * 60)
    print("\n📌 ДЛЯ RAILWAY:")
    print("  1. Зайдите в railway.app")
    print("  2. Откройте ваш проект")
    print("  3. Нажмите вкладку 'Variables'")
    print("  4. Нажмите '+ Add Variable'")
    print("  5. Добавьте:")
    print("     Key:   BOT_TOKEN")
    print("     Value: ваш_токен_от_BotFather")
    print("  6. Нажмите 'Save'")
    print("  7. Нажмите 'Deploy' → 'Redeploy'")
    print("\n📌 ДЛЯ ЛОКАЛЬНОЙ РАЗРАБОТКИ:")
    print("  Создайте файл .env с содержимым:")
    print("  BOT_TOKEN=ваш_токен_от_BotFather")
    print("\n" + "=" * 60)
    sys.exit(1)

# OdiRouter API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.odirouter.ai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "free-gpt-5.5")

# HuggingFace для аватарок
HF_TOKEN = os.getenv("HF_TOKEN") or os.environ.get("HF_TOKEN")

ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x]
DEBUG = (os.getenv("DEBUG") or "False").lower() == "true"

logger.success(f"✅ BOT_TOKEN загружен успешно!")
logger.info(f"🔧 Режим DEBUG: {DEBUG}")
logger.info(f"👤 Администраторы: {ADMIN_IDS}")
logger.info(f"🤖 AI модель: {OPENAI_MODEL}")
logger.info(f"🌐 AI URL: {OPENAI_BASE_URL}")
logger.info(f"🖼️ HF_TOKEN: {'✅ Найден' if HF_TOKEN else '❌ Не найден'}")


# ==================== МУЛЬТИЯЗЫЧНОСТЬ ====================
class I18n:
    """Класс для работы с мультиязычностью"""

    def __init__(self, locales_dir="locales"):
        self.locales_dir = Path(locales_dir)
        self.default_lang = "ru"
        self._cache = {}
        self._load_all()

    def _load_all(self):
        """Загружает все языковые файлы"""
        if not self.locales_dir.exists():
            self.locales_dir.mkdir()
            self._create_default_locales()
            return

        for file in self.locales_dir.glob("*.json"):
            lang = file.stem
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    self._cache[lang] = json.load(f)
                logger.info(f"✅ Загружен язык: {lang}")
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {file}: {e}")

    def _create_default_locales(self):
        """Создает файлы локалей по умолчанию"""
        ru = {
            "welcome": "👋 Привет, {name}!\n\n🤖 **CyberNick AI** — твой генератор уникальных ников и паролей!\n\n🎯 **Что я умею:**\n• 🎮 Генерировать ники в 4 стилях\n• 🧠 Придумывать через нейросети (ChatGPT)\n• 🎨 Создавать аватарки (Stable Diffusion)\n• 🔐 Генерировать надежные пароли\n• 📜 Хранить историю генераций\n\n⭐ **3 бесплатных генераций в день!**\n💰 10 Stars = 3 дополнительные генерации\n\nВыбери действие ниже 👇",
            "main_menu": "🏠 Главное меню",
            "back": "🔙 Назад",
            "help": "ℹ️ Помощь",
            "settings": "⚙️ Настройки",
            "language": "🌐 Язык",
            "buttons": {
                "cool_nick": "🎮 Крутой ник",
                "anime_nick": "🌸 Аниме ник",
                "fantasy_nick": "🧙 Фэнтези ник",
                "ai_generation": "🤖 AI генерация",
                "password": "🔐 Пароль",
                "buy_generations": "⭐ Купить генерации",
                "history": "📜 История"
            },
            "ai_styles": {
                "cyber": "💻 Киберпанк",
                "anime": "🌸 Аниме",
                "fantasy": "🧙 Фэнтези",
                "random": "🎲 Рандом"
            },
            "generating": "🔄 **Генерирую уникальный ник через AI...**\n⏳ Подожди 3-5 секунд",
            "nick_result": "🎯 **Твой AI-ник:**\n\n`{nick}`\n\n🔐 **Пароль:** `{password}`\n\n📝 Стиль: {style}\n🧠 Сгенерировано нейросетью\n💾 Сохранен в историю",
            "password_result": "🔐 **Ваш надежный пароль:**\n\n`{password}`\n\n⚠️ Длина: 16 символов\n💡 Содержит: буквы, цифры, спецсимволы\n💾 Сохранен в историю",
            "history_title": "📜 **Ваша история (последние 10):**",
            "no_history": "📭 У вас пока нет сохраненных генераций",
            "limit_exceeded": "❌ Бесплатные генерации на сегодня использованы! (3/3)\nКупи дополнительные за ⭐ Stars",
            "buy_title": "⭐ Пополнение генераций",
            "buy_description": "Купи 3 дополнительных генерации за 10 Stars",
            "payment_success": "✅ **Оплата прошла успешно!**\n\nВам начислено **3 генерации**.\nСпасибо за поддержку! 🚀\n\nМожешь продолжать генерировать ники!"
        }
        en = {
            "welcome": "👋 Hello, {name}!\n\n🤖 **CyberNick AI** is your generator of unique nicknames and passwords!\n\n🎯 **What I can do:**\n• 🎮 Generate nicknames in 4 styles\n• 🧠 Create via neural networks (ChatGPT)\n• 🎨 Generate avatars (Stable Diffusion)\n• 🔐 Generate strong passwords\n• 📜 Store generation history\n\n⭐ **3 free generations per day!**\n💰 10 Stars = 3 additional generations\n\nChoose an action below 👇",
            "main_menu": "🏠 Main Menu",
            "back": "🔙 Back",
            "help": "ℹ️ Help",
            "settings": "⚙️ Settings",
            "language": "🌐 Language",
            "buttons": {
                "cool_nick": "🎮 Cool Nick",
                "anime_nick": "🌸 Anime Nick",
                "fantasy_nick": "🧙 Fantasy Nick",
                "ai_generation": "🤖 AI Generation",
                "password": "🔐 Password",
                "buy_generations": "⭐ Buy Generations",
                "history": "📜 History"
            },
            "ai_styles": {
                "cyber": "💻 Cyberpunk",
                "anime": "🌸 Anime",
                "fantasy": "🧙 Fantasy",
                "random": "🎲 Random"
            },
            "generating": "🔄 **Generating unique nickname via AI...**\n⏳ Wait 3-5 seconds",
            "nick_result": "🎯 **Your AI nickname:**\n\n`{nick}`\n\n🔐 **Password:** `{password}`\n\n📝 Style: {style}\n🧠 Generated by neural network\n💾 Saved to history",
            "password_result": "🔐 **Your strong password:**\n\n`{password}`\n\n⚠️ Length: 16 characters\n💡 Contains: letters, digits, special characters\n💾 Saved to history",
            "history_title": "📜 **Your history (last 10):**",
            "no_history": "📭 You have no saved generations yet",
            "limit_exceeded": "❌ Free generations for today are used! (3/3)\nBuy additional for ⭐ Stars",
            "buy_title": "⭐ Buy Generations",
            "buy_description": "Buy 3 additional generations for 10 Stars",
            "payment_success": "✅ **Payment successful!**\n\nYou have received **3 generations**.\nThank you for your support! 🚀\n\nYou can continue generating nicknames!"
        }

        with open(self.locales_dir / "ru.json", 'w', encoding='utf-8') as f:
            json.dump(ru, f, ensure_ascii=False, indent=2)
        with open(self.locales_dir / "en.json", 'w', encoding='utf-8') as f:
            json.dump(en, f, ensure_ascii=False, indent=2)
        self._cache = {"ru": ru, "en": en}
        logger.info("✅ Созданы файлы локалей по умолчанию")

    def get(self, key: str, lang: str = None, **kwargs) -> str:
        """Получает текст по ключу и языку"""
        if not lang or lang not in self._cache:
            lang = self.default_lang

        parts = key.split('.')
        value = self._cache.get(lang, {})

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part, key)
            else:
                return key

        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError:
                return value
        return value


# Создаем глобальный объект
i18n = I18n()

# ==================== БАЗА ДАННЫХ ====================
Base = declarative_base()
engine = create_engine("sqlite:///./cyber_nick.db", echo=DEBUG)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    language = Column(String(5), default="ru")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    purchased_generations = Column(Integer, default=0)


class GeneratedNick(Base):
    __tablename__ = "generated_nicks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    nick = Column(String(255), nullable=False)
    password = Column(String(255), nullable=True)
    style = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    charge_id = Column(String(255), nullable=False)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# Обновляем таблицу users если нужно
try:
    Base.metadata.create_all(engine)
    logger.info("✅ База данных инициализирована")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации БД: {e}")


# ==================== ФУНКЦИИ БАЗЫ ДАННЫХ ====================
async def get_user(telegram_id: int):
    with SessionLocal() as db:
        return db.query(User).filter(User.telegram_id == telegram_id).first()


async def get_user_language(telegram_id: int) -> str:
    """Получает язык пользователя"""
    user = await get_user(telegram_id)
    if user and hasattr(user, 'language'):
        return user.language or "ru"
    return "ru"


async def set_user_language(telegram_id: int, lang: str):
    """Устанавливает язык пользователя"""
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            user.language = lang
            db.commit()
            return True
    return False


async def create_user(telegram_id: int, username: str = None, first_name: str = None):
    with SessionLocal() as db:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language="ru"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


async def save_generated_nick(user_id: int, nick: str, password: str = None, style: str = None,
                              description: str = None):
    with SessionLocal() as db:
        record = GeneratedNick(
            user_id=user_id,
            nick=nick,
            password=password,
            style=style,
            description=description
        )
        db.add(record)
        db.commit()
        return True


async def get_user_history(telegram_id: int, limit: int = 10):
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return []
        return db.query(GeneratedNick).filter(
            GeneratedNick.user_id == user.id
        ).order_by(desc(GeneratedNick.created_at)).limit(limit).all()


async def get_daily_count(telegram_id: int) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return 0
        today = datetime.now(timezone.utc).date()
        return db.query(GeneratedNick).filter(
            GeneratedNick.user_id == user.id,
            cast(GeneratedNick.created_at, Date) == today
        ).count()


async def add_generations_to_user(user_id: int, count: int):
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if user:
            user.purchased_generations += count
            db.commit()
            return True
    return False


async def use_generation(user_id: int) -> bool:
    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            return False

        if user.purchased_generations > 0:
            user.purchased_generations -= 1
            db.commit()
            return True

        today = datetime.now(timezone.utc).date()
        daily_count = db.query(GeneratedNick).filter(
            GeneratedNick.user_id == user.id,
            func.date(GeneratedNick.created_at) == today
        ).count()

        if daily_count < 3:
            return True

        return False


# ==================== ГЕНЕРАТОРЫ ====================
def generate_secure_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_nick_from_template(style: str = "classic") -> str:
    adjectives = [
        "Cyber", "Neon", "Ghost", "Shadow", "Dark", "Light", "Storm", "Ice",
        "Crimson", "Silver", "Wild", "Savage", "Phantom", "Venom", "Fury", "Titan"
    ]
    nouns = [
        "Pulse", "Core", "Blade", "Phoenix", "Wolf", "Hawk", "Dragon",
        "Knight", "Fury", "Storm", "Titan", "Raven", "Viper", "Eagle", "Lynx"
    ]

    if style == "anime":
        return f"{random.choice(nouns)}_Kun{random.randint(10, 99)}"
    elif style == "cyber" or style == "cool":
        return f"xX_{random.choice(adjectives)}_{random.randint(100, 999)}_Xx"
    elif style == "fantasy":
        return f"{random.choice(adjectives)}{random.choice(nouns)}"
    else:
        return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(10, 99)}"


# ==================== AI ГЕНЕРАЦИЯ ====================
client = None
if OPENAI_API_KEY:
    try:
        client = AsyncOpenAI(
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
            timeout=120.0
        )
        logger.success(f"✅ OdiRouter клиент настроен (модель: {OPENAI_MODEL})")
    except Exception as e:
        logger.error(f"❌ Ошибка настройки OpenAI клиента: {e}")
else:
    logger.warning("⚠️ OPENAI_API_KEY не найден, будет использоваться резервная генерация")

ai_cache = {}


async def generate_nick_with_ai(style: str = "classic", count: int = 1) -> str:
    """Генерирует ник через AI с указанным стилем"""

    style_map = {
        "cool": "крутой, дерзкий, киберпанк, неон",
        "anime": "аниме, японский, кавайный или тёмный",
        "fantasy": "фэнтези, магия, драконы, эльфы",
        "classic": "уникальный, запоминающийся"
    }

    if not client:
        return generate_nick_from_template(style)

    prompt = f"""Придумай 1 уникальный ник в стиле {style_map.get(style, 'классический')}.

Требования:
- Длина: 5-20 символов
- Используй буквы, цифры, символы _ - .
- Ник должен быть запоминающимся и креативным
- Не используй оскорбительные слова

ОТВЕТЬ ТОЛЬКО НИКОМ, БЕЗ ОБЪЯСНЕНИЙ!"""

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Ты — креативный генератор никнеймов. Отвечаешь только одним ником."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            max_tokens=50
        )

        nick = response.choices[0].message.content.strip()
        if not nick or len(nick) > 30:
            return generate_nick_from_template(style)
        return nick

    except Exception as e:
        logger.error(f"Ошибка AI-генерации: {e}")
        return generate_nick_from_template(style)


async def generate_nicks_ai(description: str, style: str = "random", count: int = 3) -> List[str]:
    if not client:
        return [generate_nick_from_template(style) for _ in range(count)]

    cache_key = hashlib.md5(f"{description}_{style}_{count}".encode()).hexdigest()
    if cache_key in ai_cache:
        return ai_cache[cache_key]

    style_map = {
        "cyber": "киберпанк, неон, технологии, футуризм",
        "anime": "аниме, японский стиль, кавайный или тёмный",
        "fantasy": "фэнтези, магия, драконы, эльфы",
        "random": "любой стиль"
    }

    prompt = f"""Придумай {count} уникальных ников.
Описание: {description}
Стиль: {style_map.get(style, 'любой')}

Требования:
- Длина: 5-20 символов
- Используй буквы, цифры, символы _ - .
- Ники должны быть запоминающимися
- ОТВЕТЬ ТОЛЬКО СПИСКОМ НИКОВ, КАЖДЫЙ С НОВОЙ СТРОКИ!"""

    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Ты — генератор никнеймов. Отвечаешь только списком ников."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            max_tokens=200
        )
        nicks = [n.strip() for n in response.choices[0].message.content.strip().split('\n') if n.strip()]
        ai_cache[cache_key] = nicks
        return nicks[:count]
    except Exception as e:
        logger.error(f"Ошибка ChatGPT: {e}")
        return [generate_nick_from_template(style) for _ in range(count)]


# ==================== ГЕНЕРАЦИЯ АВАТАРОК ====================
async def generate_avatar(nick: str, style: str = "cyberpunk") -> Optional[bytes]:
    """Генерирует аватарку через HuggingFace API"""

    prompt = f"Avatar for gamer named {nick}, {style} style, digital art, vibrant colors, high quality, 512x512"

    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5",
                    json={
                        "inputs": prompt,
                        "parameters": {
                            "negative_prompt": "ugly, deformed, blurry, low quality, realistic photo",
                            "guidance_scale": 7.5
                        }
                    },
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    image_bytes = await response.read()
                    logger.success(f"✅ Аватарка сгенерирована для {nick}")
                    return image_bytes
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Ошибка HuggingFace: {response.status} - {error_text[:200]}")
                    return None
    except asyncio.TimeoutError:
        logger.error("⏰ Таймаут генерации аватарки")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка аватарки: {e}")
        return None


async def generate_avatar_free(nick: str, style: str = "cyberpunk") -> Optional[bytes]:
    """Генерирует аватарку через Pollinations.ai (бесплатно, без токена)"""

    prompt = f"Avatar for gamer named {nick}, {style} style, digital art, vibrant colors, high quality"
    url = f"https://image.pollinations.ai/prompt/{prompt}?width=512&height=512&nologo=true"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    image_bytes = await response.read()
                    logger.success(f"✅ Аватарка сгенерирована для {nick} (Pollinations)")
                    return image_bytes
                else:
                    logger.error(f"❌ Ошибка Pollinations: {response.status}")
                    return None
    except asyncio.TimeoutError:
        logger.error("⏰ Таймаут Pollinations")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка Pollinations: {e}")
        return None


# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Главная клавиатура с поддержкой языка"""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=i18n.get("buttons.cool_nick", lang),
        callback_data="gen_cool"
    )
    builder.button(
        text=i18n.get("buttons.anime_nick", lang),
        callback_data="gen_anime"
    )
    builder.button(
        text=i18n.get("buttons.fantasy_nick", lang),
        callback_data="gen_fantasy"
    )
    builder.button(
        text=i18n.get("buttons.ai_generation", lang),
        callback_data="gen_ai"
    )
    builder.button(
        text=i18n.get("buttons.password", lang),
        callback_data="gen_password"
    )
    builder.button(
        text=i18n.get("buttons.buy_generations", lang),
        callback_data="buy_generations"
    )
    builder.button(
        text=i18n.get("buttons.history", lang),
        callback_data="history"
    )
    builder.button(
        text=i18n.get("settings", lang),
        callback_data="settings"
    )
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


def get_ai_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура выбора стиля AI"""
    builder = InlineKeyboardBuilder()
    styles = [
        ("cyber", i18n.get("ai_styles.cyber", lang)),
        ("anime", i18n.get("ai_styles.anime", lang)),
        ("fantasy", i18n.get("ai_styles.fantasy", lang)),
        ("random", i18n.get("ai_styles.random", lang))
    ]
    for value, text in styles:
        builder.button(text=text, callback_data=f"ai_{value}")
    builder.button(text=i18n.get("back", lang), callback_data="back_to_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_payment_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Клавиатура оплаты"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Оплатить 10 Stars", pay=True)
    builder.button(text=i18n.get("back", lang), callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇬🇧 English", callback_data="lang_en")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


# ==================== СОСТОЯНИЯ ====================
class GenerateStates(StatesGroup):
    waiting_for_description = State()


# ==================== БОТ ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()


# ==================== КОМАНДЫ ====================
@router.message(Command("start"))
async def start_command(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        user = await create_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name
        )
        logger.info(f"👤 Новый пользователь: {user.telegram_id}")

    lang = await get_user_language(message.from_user.id)

    await message.answer(
        i18n.get("welcome", lang, name=message.from_user.first_name),
        reply_markup=get_main_keyboard(lang),
        parse_mode="Markdown"
    )


@router.message(Command("buy"))
async def buy_command(message: Message):
    lang = await get_user_language(message.from_user.id)
    prices = [LabeledPrice(label="⭐ 3 генерации", amount=1000)]
    await message.answer_invoice(
        title=i18n.get("buy_title", lang),
        description=i18n.get("buy_description", lang),
        prices=prices,
        provider_token="",
        payload="buy_3_generations",
        currency="XTR",
        reply_markup=get_payment_keyboard(lang)
    )


@router.message(Command("history"))
async def history_command(message: Message):
    lang = await get_user_language(message.from_user.id)
    history = await get_user_history(message.from_user.id, limit=10)

    if not history:
        await message.answer(
            i18n.get("no_history", lang),
            reply_markup=get_main_keyboard(lang)
        )
        return

    text = i18n.get("history_title", lang) + "\n\n"
    for i, record in enumerate(history, 1):
        text += f"{i}. `{record.nick}`"
        if record.password:
            text += f" | Пароль: `{record.password}`"
        text += f"\n   🕐 {record.created_at.strftime('%d.%m.%Y %H:%M')}\n"

    await message.answer(text, reply_markup=get_main_keyboard(lang))


@router.message(Command("help"))
async def help_command(message: Message):
    lang = await get_user_language(message.from_user.id)
    await message.answer(
        f"ℹ️ **{i18n.get('help', lang)}**\n\n"
        "📌 **Команды / Commands:**\n"
        "/start - Главное меню / Main Menu\n"
        "/buy - Купить генерации / Buy Generations\n"
        "/history - История / History\n"
        "/help - Помощь / Help\n\n"
        "📌 **Как использовать / How to use:**\n"
        "1. Нажми на кнопку / Press a button\n"
        "2. Получи уникальный ник / Get unique nickname\n"
        "3. Для AI-генерации напиши описание / For AI generation write description\n\n"
        "❓ Вопросы / Questions: @ваш_username",
        reply_markup=get_main_keyboard(lang)
    )


# ==================== КНОПКИ ====================
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    try:
        await callback.message.edit_text(
            i18n.get("main_menu", lang),
            reply_markup=get_main_keyboard(lang)
        )
    except Exception:
        await callback.message.answer(
            i18n.get("main_menu", lang),
            reply_markup=get_main_keyboard(lang)
        )
    await callback.answer()


@router.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ **Настройки / Settings**\n\n"
        "🌐 Выберите язык / Choose language:",
        reply_markup=get_language_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lang_"))
async def change_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]

    await set_user_language(callback.from_user.id, lang)

    text = "✅ Язык изменен на Русский!" if lang == "ru" else "✅ Language changed to English!"

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(lang)
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_main_keyboard(lang)
        )
    await callback.answer()


@router.callback_query(F.data == "history")
async def history_callback(callback: CallbackQuery):
    await history_command(callback.message)
    await callback.answer()


@router.callback_query(F.data == "gen_password")
async def generate_password_callback(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    password = generate_secure_password(16)
    user = await get_user(callback.from_user.id)
    if user:
        await save_generated_nick(user.id, "🔐 Пароль", password)

    try:
        await callback.message.edit_text(
            i18n.get("password_result", lang, password=password),
            reply_markup=get_main_keyboard(lang)
        )
    except Exception:
        await callback.message.answer(
            i18n.get("password_result", lang, password=password),
            reply_markup=get_main_keyboard(lang)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("gen_"))
async def generate_nick_ai(callback: CallbackQuery):
    """Генерация ника через AI"""
    lang = await get_user_language(callback.from_user.id)
    style = callback.data.split("_")[1]

    if not await use_generation(callback.from_user.id):
        await callback.answer(
            i18n.get("limit_exceeded", lang),
            show_alert=True
        )
        return

    try:
        await callback.message.edit_text(
            i18n.get("generating", lang),
            reply_markup=None
        )
    except Exception:
        await callback.message.answer(
            i18n.get("generating", lang)
        )

    try:
        nick = await generate_nick_with_ai(style, count=1)
        password = generate_secure_password(12)

        user = await get_user(callback.from_user.id)
        if user:
            await save_generated_nick(
                user_id=int(user.id),
                nick=nick,
                password=password,
                style=style
            )
            logger.info(f"💾 Сохранен ник: {nick} для пользователя {user.id}")
        else:
            logger.error(f"❌ Пользователь не найден: {callback.from_user.id}")

        style_names = {
            "cool": "🎮 Крутой / Cool",
            "anime": "🌸 Аниме / Anime",
            "fantasy": "🧙 Фэнтези / Fantasy"
        }

        result_text = i18n.get(
            "nick_result", lang,
            nick=nick,
            password=password,
            style=style_names.get(style, style)
        )

        try:
            await callback.message.edit_text(
                result_text,
                reply_markup=get_main_keyboard(lang)
            )
        except Exception:
            await callback.message.answer(
                result_text,
                reply_markup=get_main_keyboard(lang)
            )

    except Exception as e:
        logger.error(f"❌ Ошибка AI-генерации: {e}")
        try:
            await callback.message.edit_text(
                "❌ Ошибка генерации. Попробуй еще раз.",
                reply_markup=get_main_keyboard(lang)
            )
        except Exception:
            await callback.message.answer(
                "❌ Ошибка генерации. Попробуй еще раз.",
                reply_markup=get_main_keyboard(lang)
            )

    await callback.answer()


@router.callback_query(F.data == "gen_ai")
async def ai_generation_start(callback: CallbackQuery, state: FSMContext):
    """Начало AI-генерации с описанием"""

    lang = await get_user_language(callback.from_user.id)

    if not await use_generation(callback.from_user.id):
        await callback.answer(
            i18n.get("limit_exceeded", lang),
            show_alert=True
        )
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🤖 **AI-генерация ников**\n\n"
        "Выбери стиль / Choose style:",
        reply_markup=get_ai_keyboard(lang)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ai_"))
async def ai_style_selected(callback: CallbackQuery, state: FSMContext):
    """Выбор стиля для AI-генерации"""

    lang = await get_user_language(callback.from_user.id)
    style = callback.data.split("_")[1]
    await state.update_data(style=style)

    style_names = {
        "cyber": "💻 Киберпанк / Cyberpunk",
        "anime": "🌸 Аниме / Anime",
        "fantasy": "🧙 Фэнтези / Fantasy",
        "random": "🎲 Рандом / Random"
    }

    await callback.message.edit_text(
        f"✅ Выбран стиль / Selected style: **{style_names.get(style, style)}**\n\n"
        "📝 **Напиши описание** желаемого ника.\n"
        "**Write a description** of the desired nickname.\n\n"
        "Примеры / Examples:\n"
        "• 'для стримера, люблю космос' / 'for streamer, I love space'\n"
        "• 'для игр, агрессивный' / 'for games, aggressive'\n"
        "• 'для соцсетей, милый' / 'for social networks, cute'\n\n"
        "Или нажми /skip для случайного / Or press /skip for random",
        parse_mode="Markdown",
        reply_markup=None
    )
    await state.set_state(GenerateStates.waiting_for_description)
    await callback.answer()


@router.message(GenerateStates.waiting_for_description)
async def process_ai_description(message: Message, state: FSMContext):
    """Обработка описания и генерация ников"""

    lang = await get_user_language(message.from_user.id)

    if message.text == "/skip":
        description = "случайный уникальный ник / random unique nickname"
    else:
        description = message.text

    data = await state.get_data()
    style = data.get("style", "random")

    loading_msg = await message.answer(
        "🔄 **Генерирую уникальные ники...**\n"
        "⏳ Подожди 5-10 секунд / Wait 5-10 seconds"
    )

    try:
        nicks = await generate_nicks_ai(description, style, count=3)
        password = generate_secure_password(14)

        user = await get_user(message.from_user.id)
        if user:
            for nick in nicks:
                await save_generated_nick(
                    user_id=user.id,
                    nick=nick,
                    password=password,
                    style=style,
                    description=description
                )
                logger.info(f"💾 Сохранен ник: {nick} для пользователя {user.id}")
        else:
            logger.error(f"❌ Пользователь не найден: {message.from_user.id}")

        response = "🧠 **AI сгенерировал ники / AI generated nicknames:**\n\n"
        for i, nick in enumerate(nicks, 1):
            response += f"{i}. `{nick}`\n"
        response += f"\n🔐 **Пароль / Password:** `{password}`"

        await loading_msg.delete()

        # ГЕНЕРАЦИЯ АВАТАРКИ
        await message.answer(
            "🎨 **Генерирую аватарку...**\n"
            "⏳ Это может занять до 30 секунд / This may take up to 30 seconds"
        )

        # Пробуем через HuggingFace
        avatar = await generate_avatar(nicks[0], style)

        # Если HuggingFace не работает, пробуем Pollinations
        if not avatar:
            logger.info("🔄 Пробуем альтернативный сервис Pollinations")
            avatar = await generate_avatar_free(nicks[0], style)

        if avatar:
            await message.answer_photo(
                photo=BufferedInputFile(avatar, filename="avatar.png"),
                caption=response,
                reply_markup=get_main_keyboard(lang)
            )
        else:
            await message.answer(
                response + "\n\n❌ Аватарку не удалось сгенерировать, но ники готовы!\n"
                           "❌ Avatar generation failed, but nicknames are ready!",
                reply_markup=get_main_keyboard(lang)
            )

        await state.clear()

    except Exception as e:
        logger.error(f"❌ Ошибка AI генерации: {e}")
        await loading_msg.delete()
        await message.answer(
            "❌ Произошла ошибка. Попробуй позже.\n"
            "❌ An error occurred. Try again later.",
            reply_markup=get_main_keyboard(lang)
        )
        await state.clear()


# ==================== ПЛАТЕЖИ ====================
@router.callback_query(F.data == "buy_generations")
async def process_buy_generations(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    prices = [LabeledPrice(label="⭐ 3 генерации", amount=1000)]
    await callback.message.delete()
    await callback.message.answer_invoice(
        title=i18n.get("buy_title", lang),
        description=i18n.get("buy_description", lang),
        prices=prices,
        provider_token="",
        payload="buy_3_generations",
        currency="XTR",
        reply_markup=get_payment_keyboard(lang)
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)
    logger.info(f"✅ Pre-checkout: {pre_checkout_query.from_user.id}")


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payment = message.successful_payment
    user_id = message.from_user.id
    amount = payment.total_amount // 100

    await add_generations_to_user(user_id, 3)

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if user:
            db.add(Payment(
                user_id=user.id,
                charge_id=payment.telegram_payment_charge_id,
                amount=amount
            ))
            db.commit()

    logger.success(f"💰 Оплата {amount} Stars от {user_id}")

    lang = await get_user_language(user_id)
    await message.answer(
        i18n.get("payment_success", lang),
        reply_markup=get_main_keyboard(lang)
    )


# ==================== АДМИН-КОМАНДЫ ====================
@router.message(Command("stats"))
async def stats_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещен")
        return

    with SessionLocal() as db:
        total_users = db.query(User).count()
        total_generations = db.query(GeneratedNick).count()
        total_payments = db.query(Payment).count()
        total_stars = db.query(func.sum(Payment.amount)).scalar() or 0

        await message.answer(
            f"📊 **Статистика CyberNick AI**\n\n"
            f"👥 Пользователей: {total_users}\n"
            f"📝 Генераций: {total_generations}\n"
            f"💳 Платежей: {total_payments}\n"
            f"⭐ Заработано Stars: {total_stars}\n"
            f"💰 Заработано ($): ~${total_stars * 0.01:.2f}\n\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC"
        )


# ==================== ЗАПУСК ====================
async def main():
    dp.include_router(router)

    # Сбрасываем webhook при запуске
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook удален")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось удалить webhook: {e}")

    logger.info("🚀 CyberNick AI Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())