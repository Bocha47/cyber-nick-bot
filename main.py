import os
import sys
import asyncio
import secrets
import string
import random
import json
import re
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    BufferedInputFile, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime,
    BigInteger, Text, desc, func
)
from sqlalchemy.orm import declarative_base, sessionmaker

from openai import AsyncOpenAI
from loguru import logger
from dotenv import load_dotenv

# ==================== ЗАГРУЗКА ПЕРЕМЕННЫХ ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN не найден!")
    sys.exit(1)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.odirouter.ai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "free-gpt-5.5")
ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x]
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

logger.info(f"🚀 Запуск CyberNick AI")
logger.info(f"🤖 Модель: {OPENAI_MODEL}")


# ==================== МУЛЬТИЯЗЫЧНОСТЬ ====================
class I18n:
    def __init__(self):
        self.default = "ru"
        self.data = {}
        self._load()

    def _load(self):
        locales_dir = Path("locales")
        if not locales_dir.exists():
            locales_dir.mkdir()
            self._create_default()
            return
        for f in locales_dir.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    self.data[f.stem] = json.load(file)
            except Exception:
                pass

    def _create_default(self):
        ru = {
            "welcome": "👋 Привет, {name}!\n\n🤖 **CyberNick AI** — генератор ников и аватарок!\n\n⭐ **3 бесплатные генерации в день**\n💰 10 Stars = +3 генерации",
            "main_menu": "🏠 Главное меню",
            "back": "🔙 Назад",
            "settings": "⚙️ Настройки",
            "buttons": {
                "ai_generation": "🤖 AI генерация",
                "password": "🔐 Пароль",
                "history": "📜 История",
                "buy": "⭐ Купить генерации"
            },
            "limit_exceeded": "❌ Лимит исчерпан! Купите генерации за Stars",
            "no_history": "📭 Нет сохраненных генераций",
            "generating": "🔄 Генерирую... ⏳ 5-10 сек",
            "avatar_generating": "🎨 Генерирую аватарку... ⏳ до 30 сек",
            "password_result": "🔐 Пароль: `{password}`",
            "history_title": "📜 История (последние 10):",
            "choose_gender": "👤 Выбери пол / Choose gender:",
            "choose_style": "🎨 Выбери стиль:"
        }
        en = {
            "welcome": "👋 Hello, {name}!\n\n🤖 **CyberNick AI** — nickname & avatar generator!\n\n⭐ **3 free generations per day**\n💰 10 Stars = +3 generations",
            "main_menu": "🏠 Main Menu",
            "back": "🔙 Back",
            "settings": "⚙️ Settings",
            "buttons": {
                "ai_generation": "🤖 AI Generation",
                "password": "🔐 Password",
                "history": "📜 History",
                "buy": "⭐ Buy Generations"
            },
            "limit_exceeded": "❌ Limit exceeded! Buy generations for Stars",
            "no_history": "📭 No saved generations",
            "generating": "🔄 Generating... ⏳ 5-10 sec",
            "avatar_generating": "🎨 Generating avatar... ⏳ up to 30 sec",
            "password_result": "🔐 Password: `{password}`",
            "history_title": "📜 History (last 10):",
            "choose_gender": "👤 Choose gender:",
            "choose_style": "🎨 Choose style:"
        }
        with open("locales/ru.json", 'w', encoding='utf-8') as f:
            json.dump(ru, f, ensure_ascii=False, indent=2)
        with open("locales/en.json", 'w', encoding='utf-8') as f:
            json.dump(en, f, ensure_ascii=False, indent=2)
        self.data = {"ru": ru, "en": en}

    def get(self, key: str, lang: str = None, **kwargs) -> str:
        if not lang or lang not in self.data:
            lang = self.default
        parts = key.split('.')
        value = self.data.get(lang, {})
        for p in parts:
            if isinstance(value, dict):
                value = value.get(p, key)
            else:
                return key
        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError:
                return value
        return value


i18n = I18n()

# ==================== БАЗА ДАННЫХ ====================
Base = declarative_base()
engine = create_engine("sqlite:///./cyber_nick.db", echo=DEBUG)
Session = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255))
    first_name = Column(String(255))
    language = Column(String(5), default="ru")
    purchased = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Nick(Base):
    __tablename__ = "nicks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    nick = Column(String(255), nullable=False)
    password = Column(String(255))
    style = Column(String(50))
    gender = Column(String(10))
    description = Column(Text)  # Добавляем поле для описания
    created_at = Column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    charge_id = Column(String(255), nullable=False)
    amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)
logger.info("✅ База данных создана")


# ==================== ФУНКЦИИ БАЗЫ ====================

def get_user_db(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает словарь с данными пользователя"""
    with Session() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return None
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "language": user.language,
            "purchased": user.purchased
        }


def create_user_db(telegram_id: int, username: str = None, first_name: str = None) -> int:
    with Session() as db:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        db.add(user)
        db.commit()
        return user.id


def save_nick_db(user_id: int, nick: str, password: str = None, style: str = None, gender: str = None,
                 description: str = None):
    with Session() as db:
        record = Nick(
            user_id=user_id,
            nick=nick,
            password=password,
            style=style,
            gender=gender,
            description=description
        )
        db.add(record)
        db.commit()
        return True


def get_history_db(user_id: int, limit: int = 10):
    with Session() as db:
        return db.query(Nick).filter(Nick.user_id == user_id).order_by(desc(Nick.created_at)).limit(limit).all()


def get_daily_count_db(user_id: int) -> int:
    with Session() as db:
        today = datetime.utcnow().date()
        return db.query(Nick).filter(
            Nick.user_id == user_id,
            func.date(Nick.created_at) == today
        ).count()


def add_purchased_db(telegram_id: int, count: int):
    with Session() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            user.purchased += count
            db.commit()
            return True
    return False


def use_generation_db(telegram_id: int) -> bool:
    with Session() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return False
        if user.purchased > 0:
            user.purchased -= 1
            db.commit()
            return True
        today = datetime.utcnow().date()
        count = db.query(Nick).filter(
            Nick.user_id == user.id,
            func.date(Nick.created_at) == today
        ).count()
        return count < 3


def get_user_language(telegram_id: int) -> str:
    """Безопасно получает язык пользователя"""
    user_data = get_user_db(telegram_id)
    if user_data:
        return user_data["language"]
    return "ru"


def get_user_id(telegram_id: int) -> Optional[int]:
    """Безопасно получает внутренний ID пользователя"""
    user_data = get_user_db(telegram_id)
    if user_data:
        return user_data["id"]
    return None


# ==================== ГЕНЕРАТОРЫ ====================
def gen_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(secrets.choice(chars) for _ in range(length))


async def gen_nick_ai(style: str = "cool") -> str:
    """Генерирует ник ТОЛЬКО на латинице"""
    if not OPENAI_API_KEY:
        return f"{random.choice(['Cyber', 'Neon', 'Shadow'])}{random.randint(10, 99)}"

    styles = {
        "cool": "cool, cyberpunk, english, latin letters only, no cyrillic",
        "anime": "anime, japanese style, english, latin letters only, no cyrillic",
        "fantasy": "fantasy, magic, english, latin letters only, no cyrillic"
    }
    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=30)
    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system",
                 "content": "You are a nickname generator. Reply with ONLY ONE nickname. Use ONLY latin letters (a-z, A-Z), numbers and symbols _ - . No cyrillic letters!"},
                {"role": "user",
                 "content": f"Generate 1 unique nickname in style {styles.get(style, 'cool')}. Length 5-20 characters. Use only latin letters, numbers and symbols. Reply with ONLY the nickname."}
            ],
            temperature=0.9,
            max_tokens=30
        )
        nick = resp.choices[0].message.content.strip()
        nick = re.sub(r'[^a-zA-Z0-9_\-.]', '', nick)
        if len(nick) > 30 or len(nick) < 3:
            return f"{random.choice(['Cyber', 'Neon', 'Shadow', 'Phoenix', 'Nova'])}{random.randint(10, 99)}"
        return nick
    except Exception as e:
        logger.error(f"AI error: {e}")
        return f"{random.choice(['Cyber', 'Neon', 'Shadow', 'Phoenix', 'Nova'])}{random.randint(10, 99)}"


async def gen_avatar_female(nick: str, description: str = "") -> Optional[bytes]:
    """Генерирует женскую аватарку с учетом описания"""

    # Базовый промпт
    base_prompt = f"Beautiful female avatar, girl, woman, gamer, named {nick}"

    # Добавляем описание, если оно есть
    if description and description != "случайный":
        keywords = description.lower()
        if "стример" in keywords or "streamer" in keywords:
            base_prompt += ", streamer, gaming setup, microphone, headset"
        if "космос" in keywords or "space" in keywords:
            base_prompt += ", space background, stars, galaxy, cosmic"
        if "милый" in keywords or "cute" in keywords:
            base_prompt += ", cute, kawaii, pastel colors"
        if "агрессивный" in keywords or "aggressive" in keywords:
            base_prompt += ", aggressive, dark, red accents, fierce"
        if "киберпанк" in keywords or "cyberpunk" in keywords:
            base_prompt += ", cyberpunk, neon lights, futuristic"
        if "аниме" in keywords or "anime" in keywords:
            base_prompt += ", anime style, big eyes, colorful hair"
        if "фэнтези" in keywords or "fantasy" in keywords:
            base_prompt += ", fantasy, elf ears, magical, glowing"
        if "игры" in keywords or "games" in keywords or "gaming" in keywords:
            base_prompt += ", gaming, controller, gamer girl"
        if "природа" in keywords or "nature" in keywords:
            base_prompt += ", nature background, forest, flowers"
        if "темный" in keywords or "dark" in keywords:
            base_prompt += ", dark theme, gothic, mysterious"
        # Добавляем само описание
        base_prompt += f", {description}"

    # Добавляем общие параметры качества
    base_prompt += ", digital art, vibrant, high quality, detailed, portrait, 4k, masterpiece, trending on artstation"

    url = f"https://image.pollinations.ai/prompt/{base_prompt}?width=512&height=512&nologo=true"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Женская аватарка сгенерирована для {nick}")
                    return await resp.read()
                else:
                    logger.warning(f"❌ Ошибка Pollinations: {resp.status}")
    except Exception as e:
        logger.error(f"Avatar error: {e}")
    return None


async def gen_avatar_male(nick: str, description: str = "") -> Optional[bytes]:
    """Генерирует мужскую аватарку с учетом описания"""

    # Базовый промпт
    base_prompt = f"Cool male avatar, boy, man, gamer, named {nick}"

    # Добавляем описание, если оно есть
    if description and description != "случайный":
        keywords = description.lower()
        if "стример" in keywords or "streamer" in keywords:
            base_prompt += ", streamer, gaming, headset, setup"
        if "космос" in keywords or "space" in keywords:
            base_prompt += ", space background, stars, futuristic"
        if "милый" in keywords or "cute" in keywords:
            base_prompt += ", cute, soft features, gentle"
        if "агрессивный" in keywords or "aggressive" in keywords:
            base_prompt += ", aggressive, dark, red, warrior"
        if "киберпанк" in keywords or "cyberpunk" in keywords:
            base_prompt += ", cyberpunk, neon, tech"
        if "аниме" in keywords or "anime" in keywords:
            base_prompt += ", anime style, spiky hair"
        if "фэнтези" in keywords or "fantasy" in keywords:
            base_prompt += ", fantasy, knight, magic, sword"
        if "игры" in keywords or "games" in keywords or "gaming" in keywords:
            base_prompt += ", gaming, controller, gamer"
        if "природа" in keywords or "nature" in keywords:
            base_prompt += ", nature, forest, mountain"
        if "темный" in keywords or "dark" in keywords:
            base_prompt += ", dark theme, gothic, mysterious"
        base_prompt += f", {description}"

    base_prompt += ", digital art, vibrant, high quality, detailed, portrait, 4k, masterpiece, trending on artstation"

    url = f"https://image.pollinations.ai/prompt/{base_prompt}?width=512&height=512&nologo=true"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Мужская аватарка сгенерирована для {nick}")
                    return await resp.read()
    except Exception as e:
        logger.error(f"Avatar error: {e}")
    return None


# ==================== УНИВЕРСАЛЬНАЯ ФУНКЦИЯ ====================
async def edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None):
    """Безопасно редактирует или отправляет новое сообщение"""
    try:
        if callback.message and callback.message.text is not None:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        else:
            await callback.message.answer(text, reply_markup=reply_markup)
            if callback.message:
                await callback.message.delete()
    except Exception as e:
        logger.warning(f"Edit fallback: {e}")
        await callback.message.answer(text, reply_markup=reply_markup)


# ==================== КЛАВИАТУРЫ ====================
def main_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=i18n.get("buttons.ai_generation", lang), callback_data="gen_ai")
    b.button(text=i18n.get("buttons.password", lang), callback_data="gen_pass")
    b.button(text=i18n.get("buttons.history", lang), callback_data="history")
    b.button(text=i18n.get("buttons.buy", lang), callback_data="buy")
    b.button(text=i18n.get("settings", lang), callback_data="settings")
    b.adjust(2, 2, 1)
    return b.as_markup()


def style_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💻 Киберпанк", callback_data="style_cool")
    b.button(text="🌸 Аниме", callback_data="style_anime")
    b.button(text="🧙 Фэнтези", callback_data="style_fantasy")
    b.button(text=i18n.get("back", lang), callback_data="back")
    b.adjust(2, 1)
    return b.as_markup()


def gender_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👩 Девушка / Girl", callback_data="gender_female")
    b.button(text="👨 Парень / Boy", callback_data="gender_male")
    b.button(text="🔙 Назад", callback_data="back")
    b.adjust(2, 1)
    return b.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский", callback_data="lang_ru")
    b.button(text="🇬🇧 English", callback_data="lang_en")
    b.button(text="🔙 Назад", callback_data="back")
    b.adjust(2, 1)
    return b.as_markup()


# ==================== СОСТОЯНИЯ ====================
class Form(StatesGroup):
    waiting_gender = State()
    waiting_style = State()
    waiting_description = State()


# ==================== БОТ ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()


# ==================== ОБРАБОТЧИКИ ====================
@router.message(Command("start"))
async def start(msg: Message):
    user_data = get_user_db(msg.from_user.id)
    if not user_data:
        create_user_db(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
        lang = "ru"
    else:
        lang = user_data["language"]

    await msg.answer(
        i18n.get("welcome", lang, name=msg.from_user.first_name),
        reply_markup=main_kb(lang)
    )


@router.callback_query(F.data == "back")
async def back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_user_language(cb.from_user.id)
    await edit_or_answer(cb, i18n.get("main_menu", lang), main_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "settings")
async def settings(cb: CallbackQuery):
    await edit_or_answer(cb, "🌐 Выберите язык:", lang_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("lang_"))
async def set_lang(cb: CallbackQuery):
    lang = cb.data.split("_")[1]
    with Session() as db:
        user = db.query(User).filter(User.telegram_id == cb.from_user.id).first()
        if user:
            user.language = lang
            db.commit()
    text = "✅ Язык изменен!" if lang == "ru" else "✅ Language changed!"
    await edit_or_answer(cb, text, main_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "gen_ai")
async def gen_ai_start(cb: CallbackQuery, state: FSMContext):
    lang = get_user_language(cb.from_user.id)
    if not use_generation_db(cb.from_user.id):
        await cb.answer(i18n.get("limit_exceeded", lang), show_alert=True)
        return
    await state.set_state(Form.waiting_gender)
    await edit_or_answer(cb, i18n.get("choose_gender", lang), gender_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("gender_"))
async def choose_gender(cb: CallbackQuery, state: FSMContext):
    gender = cb.data.split("_")[1]
    await state.update_data(gender=gender)
    await state.set_state(Form.waiting_style)
    lang = get_user_language(cb.from_user.id)
    await edit_or_answer(cb, i18n.get("choose_style", lang), style_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("style_"))
async def choose_style(cb: CallbackQuery, state: FSMContext):
    style = cb.data.split("_")[1]
    await state.update_data(style=style)
    await state.set_state(Form.waiting_description)
    lang = get_user_language(cb.from_user.id)
    await edit_or_answer(
        cb,
        "📝 Напиши описание (или /skip):\nПример: 'для стримера, люблю космос'",
        None
    )
    await cb.answer()


@router.message(Form.waiting_description)
async def process_desc(msg: Message, state: FSMContext):
    user_id = get_user_id(msg.from_user.id)
    if not user_id:
        await msg.answer("❌ Ошибка: пользователь не найден")
        return

    lang = get_user_language(msg.from_user.id)

    data = await state.get_data()
    style = data.get("style", "cool")
    gender = data.get("gender", "female")

    # Сохраняем описание
    if msg.text == "/skip":
        description = ""
    else:
        description = msg.text

    loading = await msg.answer(i18n.get("generating", lang))

    try:
        # Генерируем ник
        nick = await gen_nick_ai(style)
        password = gen_password(12)

        # Сохраняем с описанием
        save_nick_db(user_id, nick, password, style, gender, description)

        await loading.delete()

        gender_text = "👩 Женская" if gender == "female" else "👨 Мужская"
        await msg.answer(
            f"🎨 **Генерирую {gender_text.lower()} аватарку...**\n⏳ до 30 сек\n📝 Описание: {description if description else 'без описания'}")

        # Генерируем аватарку С УЧЕТОМ ОПИСАНИЯ
        if gender == "female":
            avatar = await gen_avatar_female(nick, description)
        else:
            avatar = await gen_avatar_male(nick, description)

        # Формируем текст результата
        text = f"🎯 **{nick}**\n🔐 Пароль: `{password}`\n{gender_text} аватарка"
        if description:
            text += f"\n📝 Описание: {description[:50]}..."
        text += "\n💾 Сохранено в историю"

        if avatar:
            await msg.answer_photo(
                photo=BufferedInputFile(avatar, filename="avatar.png"),
                caption=text,
                reply_markup=main_kb(lang)
            )
        else:
            await msg.answer(
                text + "\n\n❌ Аватарка не сгенерировалась, но ник готов!",
                reply_markup=main_kb(lang)
            )

        await state.clear()

    except Exception as e:
        logger.error(f"Generation error: {e}")
        await loading.delete()
        await msg.answer("❌ Ошибка. Попробуйте позже.", reply_markup=main_kb(lang))
        await state.clear()


@router.callback_query(F.data == "gen_pass")
async def gen_pass(cb: CallbackQuery):
    lang = get_user_language(cb.from_user.id)
    password = gen_password(16)
    await edit_or_answer(
        cb,
        i18n.get("password_result", lang, password=password),
        main_kb(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "history")
async def history(cb: CallbackQuery):
    user_id = get_user_id(cb.from_user.id)
    lang = get_user_language(cb.from_user.id)

    if not user_id:
        await edit_or_answer(cb, i18n.get("no_history", lang), main_kb(lang))
        await cb.answer()
        return

    history = get_history_db(user_id, 10)
    if not history:
        await edit_or_answer(cb, i18n.get("no_history", lang), main_kb(lang))
        await cb.answer()
        return

    text = i18n.get("history_title", lang) + "\n\n"
    for i, n in enumerate(history, 1):
        text += f"{i}. `{n.nick}`"
        if n.password:
            text += f" | Пароль: `{n.password}`"
        if n.gender:
            gender_icon = "👩" if n.gender == "female" else "👨"
            text += f" | {gender_icon}"
        if n.description:
            text += f"\n   📝 {n.description[:30]}..."
        text += f"\n   🕐 {n.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    await edit_or_answer(cb, text, main_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery):
    lang = get_user_language(cb.from_user.id)
    prices = [LabeledPrice(label="⭐ 3 генерации", amount=1000)]
    await cb.message.answer_invoice(
        title="⭐ Пополнение",
        description="3 дополнительные генерации",
        prices=prices,
        provider_token="",
        payload="buy_3",
        currency="XTR"
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def payment_success(msg: Message):
    add_purchased_db(msg.from_user.id, 3)
    lang = get_user_language(msg.from_user.id)
    await msg.answer("✅ Оплата успешна! +3 генерации", reply_markup=main_kb(lang))


@router.message(Command("stats"))
async def stats(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("⛔ Доступ запрещен")
        return
    with Session() as db:
        users = db.query(User).count()
        nicks = db.query(Nick).count()
        await msg.answer(f"📊 Статистика:\n👥 Пользователей: {users}\n📝 Ников: {nicks}")


# ==================== ЗАПУСК ====================
async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 CyberNick AI Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())