import os
import sys
import asyncio
import secrets
import string
import random
import json
import aiohttp
from datetime import datetime
from typing import Optional, List
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
        ru = {"welcome": "Привет!", "main_menu": "Главное меню"}
        en = {"welcome": "Hello!", "main_menu": "Main Menu"}
        with open("locales/ru.json", 'w', encoding='utf-8') as f:
            json.dump(ru, f, ensure_ascii=False)
        with open("locales/en.json", 'w', encoding='utf-8') as f:
            json.dump(en, f, ensure_ascii=False)
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
def get_user_db(telegram_id: int):
    with Session() as db:
        return db.query(User).filter(User.telegram_id == telegram_id).first()


def create_user_db(telegram_id: int, username: str = None, first_name: str = None):
    with Session() as db:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        db.add(user)
        db.commit()
        return user


def save_nick_db(user_id: int, nick: str, password: str = None, style: str = None):
    with Session() as db:
        record = Nick(user_id=user_id, nick=nick, password=password, style=style)
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


# ==================== ГЕНЕРАТОРЫ ====================
def gen_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(secrets.choice(chars) for _ in range(length))


async def gen_nick_ai(style: str = "cool") -> str:
    if not OPENAI_API_KEY:
        return f"{random.choice(['Cyber', 'Neon'])}{random.randint(10, 99)}"

    styles = {
        "cool": "крутой, киберпанк",
        "anime": "аниме, японский",
        "fantasy": "фэнтези, магия"
    }
    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=30)
    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Ты генератор ников. Отвечай только одним ником."},
                {"role": "user",
                 "content": f"Придумай 1 ник в стиле {styles.get(style, 'крутой')}. Длина 5-20 символов."}
            ],
            temperature=0.9,
            max_tokens=30
        )
        nick = resp.choices[0].message.content.strip()
        if len(nick) > 30 or not nick:
            return f"{random.choice(['Cyber', 'Neon'])}{random.randint(10, 99)}"
        return nick
    except Exception as e:
        logger.error(f"AI error: {e}")
        return f"{random.choice(['Cyber', 'Neon'])}{random.randint(10, 99)}"


async def gen_avatar(nick: str) -> Optional[bytes]:
    """Генерация аватарки через Pollinations.ai (бесплатно, без токена)"""
    prompt = f"Avatar for {nick}, digital art, vibrant"
    url = f"https://image.pollinations.ai/prompt/{prompt}?width=512&height=512"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.error(f"Avatar error: {e}")
    return None


# ==================== КЛАВИАТУРЫ ====================
def main_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🤖 AI генерация", callback_data="gen_ai")
    b.button(text="🔐 Пароль", callback_data="gen_pass")
    b.button(text="📜 История", callback_data="history")
    b.button(text="⭐ Купить", callback_data="buy")
    b.button(text="⚙️ Настройки", callback_data="settings")
    b.adjust(2, 2, 1)
    return b.as_markup()


def style_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💻 Киберпанк", callback_data="style_cool")
    b.button(text="🌸 Аниме", callback_data="style_anime")
    b.button(text="🧙 Фэнтези", callback_data="style_fantasy")
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
    waiting_style = State()
    waiting_description = State()


# ==================== БОТ ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()


# ==================== ОБРАБОТЧИКИ ====================
@router.message(Command("start"))
async def start(msg: Message):
    user = get_user_db(msg.from_user.id)
    if not user:
        user = create_user_db(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    lang = user.language if user else "ru"
    await msg.answer(
        i18n.get("welcome", lang, name=msg.from_user.first_name),
        reply_markup=main_kb(lang)
    )


@router.callback_query(F.data == "back")
async def back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = "ru"
    user = get_user_db(cb.from_user.id)
    if user:
        lang = user.language
    await cb.message.edit_text(i18n.get("main_menu", lang), reply_markup=main_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "settings")
async def settings(cb: CallbackQuery):
    await cb.message.edit_text("🌐 Выберите язык:", reply_markup=lang_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("lang_"))
async def set_lang(cb: CallbackQuery):
    lang = cb.data.split("_")[1]
    with Session() as db:
        user = db.query(User).filter(User.telegram_id == cb.from_user.id).first()
        if user:
            user.language = lang
            db.commit()
    await cb.message.edit_text(
        "✅ Язык изменен!" if lang == "ru" else "✅ Language changed!",
        reply_markup=main_kb(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "gen_ai")
async def gen_ai_start(cb: CallbackQuery, state: FSMContext):
    user = get_user_db(cb.from_user.id)
    lang = user.language if user else "ru"
    if not use_generation_db(cb.from_user.id):
        await cb.answer(i18n.get("limit_exceeded", lang), show_alert=True)
        return
    await state.set_state(Form.waiting_style)
    await cb.message.edit_text("🎨 Выбери стиль:", reply_markup=style_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("style_"))
async def choose_style(cb: CallbackQuery, state: FSMContext):
    style = cb.data.split("_")[1]
    await state.update_data(style=style)
    await state.set_state(Form.waiting_description)
    user = get_user_db(cb.from_user.id)
    lang = user.language if user else "ru"
    await cb.message.edit_text(
        "📝 Напиши описание (или /skip):\nПример: 'для стримера, люблю космос'",
        reply_markup=None
    )
    await cb.answer()


@router.message(Form.waiting_description)
async def process_desc(msg: Message, state: FSMContext):
    user = get_user_db(msg.from_user.id)
    lang = user.language if user else "ru"

    data = await state.get_data()
    style = data.get("style", "cool")

    if msg.text == "/skip":
        desc = "случайный"
    else:
        desc = msg.text

    await msg.answer(i18n.get("generating", lang))

    try:
        nick = await gen_nick_ai(style)
        password = gen_password(12)

        save_nick_db(user.id, nick, password, style)

        # Аватарка
        await msg.answer(i18n.get("avatar_generating", lang))
        avatar = await gen_avatar(nick)

        text = f"🎯 **{nick}**\n🔐 Пароль: `{password}`"

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
        logger.error(f"Error: {e}")
        await msg.answer("❌ Ошибка. Попробуйте позже.", reply_markup=main_kb(lang))
        await state.clear()


@router.callback_query(F.data == "gen_pass")
async def gen_pass(cb: CallbackQuery):
    user = get_user_db(cb.from_user.id)
    lang = user.language if user else "ru"
    password = gen_password(16)
    await cb.message.edit_text(
        i18n.get("password_result", lang, password=password),
        reply_markup=main_kb(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "history")
async def history(cb: CallbackQuery):
    user = get_user_db(cb.from_user.id)
    lang = user.language if user else "ru"
    history = get_history_db(user.id, 10)
    if not history:
        await cb.message.edit_text(i18n.get("no_history", lang), reply_markup=main_kb(lang))
        await cb.answer()
        return
    text = i18n.get("history_title", lang) + "\n\n"
    for i, n in enumerate(history, 1):
        text += f"{i}. `{n.nick}`"
        if n.password:
            text += f" | Пароль: `{n.password}`"
        text += f"\n   🕐 {n.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    await cb.message.edit_text(text, reply_markup=main_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery):
    user = get_user_db(cb.from_user.id)
    lang = user.language if user else "ru"
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
    user = get_user_db(msg.from_user.id)
    lang = user.language if user else "ru"
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
    logger.info("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())