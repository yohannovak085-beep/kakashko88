import asyncio
import html
import logging
import os
import random
import re
import time

import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
)

load_dotenv()

# Токен хранится только в .env:
# BOT_TOKEN=ваш_токен
TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "rabobot.db")

# ===== Игра =====
WORK_CD_MIN = 25 * 60          # мин. КД работенки (сек)
WORK_CD_MAX = 60 * 60          # макс. КД работенки (сек)
WORK_MIN = 15                  # мин. заработок за работенку
WORK_MAX = 75                  # макс. заработок за работенку
GOLDEN_CHANCE = 0.02           # шанс золотой работенки
GOLDEN_MULT = 3                # множитель золотой смены
JACKPOT_CHANCE = 0.01          # шанс джекпота на .работать
JACKPOT_MIN = 90               # мин. джекпот XC
JACKPOT_MAX = 150              # макс. джекпот XC
MASTER_CUT = 0.25               # доля заработка раба, уходящая хозяину
PRICE_BASE = 300                # базовая цена порабощения
PRICE_PER_SLAVE = 100           # +к цене за каждого раба хозяина
ESCAPE_IMMUNITY = 5 * 60        # иммунитет после побега
FIND_COOLDOWN = 4 * 60 * 60     # КД команды .найти
ESCAPE_COOLDOWN = 4 * 60 * 60   # КД команды .побег
FORCE_COOLDOWN = 4 * 60 * 60    # КД команды .работать
FORCE_REWARD_PER_SLAVE = 15     # XC за одного раба по .работать
FIND_CHANCE = 0.12              # шанс .найти
ESCAPE_CHANCE = 0.03            # шанс .побег
BUYOUT_MULT = 1.5               # выкуп стоит в 1.5 раза дороже цены
SLAVE_ACTION_COST = 5           # цена действия над рабом (XC)
ADMIN_IDS = {8201074902}        # скрытые админ-команды (!выдать и т.п.)
INVENTORY_MAX = 6               # макс. предметов в инвентаре
ITEM_CHECK_COOLDOWN = 60 * 60   # КД .проверить_рабов
ANARCHY_DURATION = 60 * 60      # длительность эффекта .анархия
ANARCHY_COOLDOWN = 12 * 60 * 60 # КД между активациями .анархия

# Каталог предметов: id -> данные
# rarity: Обычный / Редкий / Эпический
ITEMS = {
    "lopata": {
        "name": "Лопата", "emoji": "⛏️", "rarity": "Обычный",
        "price": 100, "desc": "+10% к заработку на работенке",
    },
    "botinki": {
        "name": "Кроссовки", "emoji": "👟", "rarity": "Обычный",
        "price": 150, "desc": "−10% ко времени перезарядки работенки",
    },
    "chasy": {
        "name": "Часы", "emoji": "⌚", "rarity": "Обычный",
        "price": 80, "desc": "+5 XC к каждой работенке",
    },
    "perchatki": {
        "name": "Рабочие перчатки", "emoji": "🧤", "rarity": "Редкий",
        "price": 300, "desc": "Действия над рабами стоят 4 XC вместо 5",
    },
    "maska": {
        "name": "Маска", "emoji": "🎭", "rarity": "Редкий",
        "price": 400, "desc": "Выкуп из рабства на 20% дешевле",
    },
    "nadzorshchik": {
        "name": "Надсмотрщик", "emoji": "📖", "rarity": "Редкий",
        "price": 500, "desc": ".проверить_рабов: +3 XC за раба",
    },
    "fortuna": {
        "name": "Талисман Фортуны", "emoji": "🍀", "rarity": "Эпический",
        "price": 800, "desc": "+15% к заработку на работенке",
    },
    "anarhiya": {
        "name": "Дыхание Анархии", "emoji": "🌪️", "rarity": "Эпический",
        "price": 1000, "desc": ".анархия: .работать даст ×2 XC",
    },
}
ITEM_LIST = list(ITEMS.keys())

# Шансы дропа с работенки
DROP_CHANCE_EPIC = 0.005    # 0.5%
DROP_CHANCE_RARE = 0.04     # 4%
DROP_CHANCE_COMMON = 0.10   # 10%

# Пакеты доната: (название, Telegram Stars, XC)
DONATE_PACKAGES = [
    ("100 XC", 6, 100),
    ("300 XC", 10, 300),
    ("600 XC", 18, 600),
    ("1 000 XC", 25, 1000),
    ("2 500 XC", 50, 2500),
    ("5 000 XC", 90, 5000),
    ("10 000 XC", 160, 10000),
]

# Титулы за XC: уровни прокачки «Империи»
# pct — % ко всем доходам, slots — доп. слоты инвентаря
TITLES = [
    {"name": "Свободный",    "cost": 0,     "pct": 0,  "slots": 0},
    {"name": "Босяк",        "cost": 500,   "pct": 5,  "slots": 0},
    {"name": "Надсмотрщик",  "cost": 1000,  "pct": 10, "slots": 1},
    {"name": "Барон",        "cost": 3000,  "pct": 15, "slots": 1},
    {"name": "Магнат",       "cost": 10000, "pct": 20, "slots": 2},
    {"name": "Император",    "cost": 25000, "pct": 25, "slots": 2},
]

# Ачивки: code -> (название, проверка по total_earned)
ACHIEVEMENTS = {
    "earn_100": ("🌱 Первый заработок", 100),
    "earn_1000": ("💼 Труженик Подполья", 1000),
    "earn_5000": ("🏭 Фабрика XC", 5000),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("rabobot")

if not TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Создайте файл .env рядом со скриптом "
        "и добавьте строку BOT_TOKEN=ваш_токен"
    )

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

db: aiosqlite.Connection | None = None
db_lock = asyncio.Lock()


class LastChatMiddleware(BaseMiddleware):
    """Запоминает последний групповой чат пользователя —
    нужно для .найти и будущих чатовых механик."""

    async def __call__(self, handler, event: Message, data):
        user = event.from_user
        if user and not user.is_bot and event.chat.type != "private":
            try:
                async with db_lock:
                    assert db is not None
                    await db.execute(
                        """
                        INSERT INTO users
                            (user_id, username, first_name, last_chat_id)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            username = excluded.username,
                            first_name = excluded.first_name,
                            last_chat_id = excluded.last_chat_id
                        """,
                        (user.id, user.username, user.first_name,
                         event.chat.id),
                    )
                    await db.commit()
            except Exception:
                pass
        return await handler(event, data)


dp.message.middleware(LastChatMiddleware())


class PrivateGuardMiddleware(BaseMiddleware):
    """В личке работает только /start — остальное игнорируем
    и просим добавить бота в группу."""

    async def __call__(self, handler, event: Message, data):
        if event.chat.type != "private":
            return await handler(event, data)

        # Подтверждение оплаты Stars — пропускаем всегда
        if getattr(event, "successful_payment", None):
            return await handler(event, data)

        text = (event.text or "").strip()
        if re.match(r"(?i)^[/\\.]?start(\s|$)", text):
            return await handler(event, data)
        # Донат разрешён в личке
        if re.match(r"(?i)^[\W_]*донат[\W_]*$", text):
            return await handler(event, data)

        await event.answer(
            "🤖 | Для использования бота добавьте меня в группу."
        )
        return None


dp.message.middleware(PrivateGuardMiddleware())


# =========================
# DATABASE
# =========================

async def init_db() -> None:
    global db

    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")

    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            bb INTEGER NOT NULL DEFAULT 0,
            total_earned INTEGER NOT NULL DEFAULT 0,
            slaves_count INTEGER NOT NULL DEFAULT 0,
            slave_of INTEGER,
            enslaved_at INTEGER,
            escape_immune_until INTEGER NOT NULL DEFAULT 0,
            last_work_at INTEGER NOT NULL DEFAULT 0,
            work_ready_at INTEGER NOT NULL DEFAULT 0,
            force_ready_at INTEGER NOT NULL DEFAULT 0,
            find_ready_at INTEGER NOT NULL DEFAULT 0,
            escape_ready_at INTEGER NOT NULL DEFAULT 0,
            item_ready_at INTEGER NOT NULL DEFAULT 0,
            anarchy_until INTEGER NOT NULL DEFAULT 0,
            anarchy_ready_at INTEGER NOT NULL DEFAULT 0,
            last_chat_id INTEGER NOT NULL DEFAULT 0,
            title_level INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_items (
            user_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            acquired_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS slaves (
            owner_id INTEGER NOT NULL,
            slave_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL DEFAULT 0,
            enslaved_at INTEGER NOT NULL,
            PRIMARY KEY (owner_id, slave_id)
        );

        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, code)
        );

        CREATE TABLE IF NOT EXISTS pending_invoices (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )
    await db.commit()

    # Миграции для старых БД.
    for ddl in (
        "ALTER TABLE slaves ADD COLUMN chat_id "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN item_ready_at "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN anarchy_until "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN work_ready_at "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN anarchy_ready_at "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_chat_id "
        "INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN title_level "
        "INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            await db.execute(ddl)
            await db.commit()
        except aiosqlite.Error:
            pass


async def ensure_user(user) -> None:
    assert db is not None
    await db.execute(
        """
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
        """,
        (user.id, user.username, user.first_name),
    )


async def get_user(user_id: int):
    assert db is not None
    cursor = await db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )
    return await cursor.fetchone()


async def get_user_by_id(user_id: int):
    """Возвращает строку пользователя или None (без создания)."""
    assert db is not None
    cursor = await db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )
    return await cursor.fetchone()


async def add_bb(user_id: int, amount: int) -> None:
    assert db is not None
    await db.execute(
        "UPDATE users SET bb = bb + ? WHERE user_id = ?",
        (amount, user_id),
    )


# =========================
# ITEMS / ACHIEVEMENTS
# =========================

async def get_inventory(user_id: int) -> list:
    """Список item_id в инвентаре (в порядке получения)."""
    assert db is not None
    cursor = await db.execute(
        "SELECT item_id FROM user_items WHERE user_id = ? "
        "ORDER BY acquired_at ASC",
        (user_id,),
    )
    return [row["item_id"] for row in await cursor.fetchall()]


async def has_item(user_id: int, item_id: str) -> bool:
    assert db is not None
    cursor = await db.execute(
        "SELECT 1 FROM user_items WHERE user_id = ? AND item_id = ?",
        (user_id, item_id),
    )
    return await cursor.fetchone() is not None


async def add_item(user_id: int, item_id: str, now: int) -> str | None:
    """Добавляет предмет. Возвращает вытесненный item_id или None."""
    assert db is not None
    inventory = await get_inventory(user_id)
    limit = await inventory_max(user_id)
    burned = None
    while len(inventory) >= limit:
        burned = inventory.pop(0)
        await db.execute(
            "DELETE FROM user_items WHERE user_id = ? AND item_id = ?",
            (user_id, burned),
        )
    await db.execute(
        "INSERT OR REPLACE INTO user_items (user_id, item_id, acquired_at) "
        "VALUES (?, ?, ?)",
        (user_id, item_id, now),
    )
    return burned


async def work_bonus_percent(user_id: int) -> int:
    """Суммарный % бонус к работенке от предметов."""
    total = 0
    if await has_item(user_id, "lopata"):
        total += 10
    if await has_item(user_id, "fortuna"):
        total += 15
    return total


async def slave_action_cost(user_id: int) -> int:
    return 4 if await has_item(user_id, "perchatki") else SLAVE_ACTION_COST


async def title_level(user_id: int) -> int:
    assert db is not None
    cursor = await db.execute(
        "SELECT title_level FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    return row["title_level"] if row else 0


async def income_multiplier(user_id: int) -> float:
    """Множитель ко всем доходам от титула."""
    level = await title_level(user_id)
    if level >= len(TITLES):
        level = len(TITLES) - 1
    return 1 + TITLES[level]["pct"] / 100


async def inventory_max(user_id: int) -> int:
    level = await title_level(user_id)
    if level >= len(TITLES):
        level = len(TITLES) - 1
    return INVENTORY_MAX + TITLES[level]["slots"]


async def check_achievements(user_id: int, total_earned: int) -> list[str]:
    """Выдаёт ачивки по наработке, возвращает названия новых."""
    assert db is not None
    unlocked = []
    for code, (name, threshold) in ACHIEVEMENTS.items():
        if total_earned < threshold:
            continue
        cursor = await db.execute(
            "INSERT OR IGNORE INTO achievements (user_id, code, created_at) "
            "VALUES (?, ?, ?)",
            (user_id, code, int(time.time())),
        )
        if cursor.rowcount:
            unlocked.append(name)
    return unlocked


async def get_achievements(user_id: int) -> list[str]:
    assert db is not None
    cursor = await db.execute(
        "SELECT code FROM achievements WHERE user_id = ?",
        (user_id,),
    )
    codes = {row["code"] for row in await cursor.fetchall()}
    return [name for code, (name, _) in ACHIEVEMENTS.items() if code in codes]


# =========================
# HELPERS
# =========================

def display_name(user) -> str:
    if user.username:
        return "@" + html.escape(user.username)
    name = html.escape(user.first_name or "Игрок")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def row_name(row) -> str:
    """Имя для строки из БД (username/first_name)."""
    if row["username"]:
        return "@" + html.escape(row["username"])
    safe = html.escape(row["first_name"] or "Игрок")
    return (
        f'<a href="tg://user?id={row["user_id"]}">{safe}</a>'
    )


def slave_price(slaves_count: int) -> int:
    return PRICE_BASE + slaves_count * PRICE_PER_SLAVE


def cooldown_text(ready_at: int, now: int, what: str = "работенки") -> str | None:
    remaining = ready_at - now
    if remaining <= 0:
        return None
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    return (
        f"⏳ Перезарядка {what}!\n\n"
        f"Следующий раз через <b>{hours} ч. {minutes} мин.</b>"
    )


WORK_PHRASES = [
    "А это не ты недавно уже подходил к кассе?",
    "Ба! Никак за зарплатой? Неужто появились собственные нужды и желания?",
    "Глядь! Вы поймали удачу!",
    "Вот если бы ты купил биткоины в нужное время, ты сейчас этим не занимался.",
    "А ты знаешь, что после смерти на глаза кладут 2 монеты?",
    "Смена окончена. Босс доволен, ты — почти.",
    "Работа не волк. Работа — это XC.",
    "Ещё чуть-чуть — и можно на покой.",
]


# =========================
# START / RULES / HELP
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.]?start(?:@\w+)?(?:\s|$)"))
async def start_command(message: Message) -> None:
    if message.from_user:
        async with db_lock:
            await ensure_user(message.from_user)
            assert db is not None
            await db.commit()

    await message.answer(
        "<blockquote>"
        "» Приветствую, я - <b>Дофаминовый Уолтер</b>.\n\n"
        "Готов стать главным рабовладельцем чата? Со мной вы сможете "
        "фармить <b>XC</b>, захватывать друзей и строить экономическую "
        "империю прямо в группе.\n\n"
        "<tg-emoji emoji-id=\"5447644880824181073\">💎</tg-emoji> "
        "<b>Важно:</b> добавь меня в группу и дай права админа, "
        "чтобы я мог навести там свои порядки.\n\n"
        "Что я умею: <code>/помощь</code>\n"
        "💎 Докупить XC — <code>/донат</code>"
        "</blockquote>"
    )


@dp.message(F.text.regexp(r"(?i)^[/\\.](правила|rules)$"))
async def rules_command(message: Message) -> None:
    await message.reply(
        "📜 <b>ПРАВИЛА ИГРЫ</b>\n\n"
        "🎯 Цель — стать самым богатым работорговцем чата: "
        "фармить <b>XC</b>, порабощать игроков и заставлять их работать на тебя.\n\n"
        "⚔️ Основы:\n"
        "• <code>/работенка</code> — фарм XC (перезарядка 25–60 мин)\n"
        "• <code>/поработить</code> ответом — сделать игрока рабом\n"
        "• <code>/сбежать</code> — выкупиться из рабства\n"
        "• <code>/освободить</code> — отпустить всех рабов\n\n"
        "🚫 Нельзя: поработить себя, чужого раба или того, "
        "кто недавно сбежал.\n\n"
        "💡 Полный список команд — <code>/помощь</code>\n"
        "💎 Докупить XC — <code>/донат</code>"
    )


@dp.message(F.text.regexp(r"(?i)^[/\\.](помощь|help|команды)$"))
async def help_command(message: Message) -> None:
    await message.reply(
        "<blockquote>"
        "📖 <b>КОМАНДЫ ДОФАМИНОВОГО УОЛТЕРА</b>\n\n"
        "💰 <b>Фарм и валюта</b>\n"
        "• <code>/работенка</code> — подзаработать XC "
        "(перезарядка 25–60 мин)\n\n"
        "⛓ <b>Рабство и управление</b>\n"
        "• Ответом + <code>/поработить</code> — захватить игрока в рабство\n"
        "• <code>/работать</code> — заставить рабов приносить доход "
        "(перезарядка 4 часа)\n"
        "• <code>/найти</code> — попытать удачу и найти свободную жертву\n"
        "• <code>/сбежать</code> — выкупиться из рабства за деньги\n"
        "• <code>/побег</code> — рискнуть и сбежать бесплатно\n"
        "• <code>/освободить</code> — отпустить всех своих рабов\n"
        "• Ответом + <code>/свободен</code> — отпустить конкретного раба\n"
        "• Ответом + <code>/перекупить</code> — выкупить чужого раба\n"
        "• Ответом + <code>/передать [сумма]</code> — передать XC\n\n"
        "😈 <b>Действия над рабами</b> (ответом на раба, стоит 5 XC)\n"
        "• <code>/выпороть</code> — наказать за лень\n"
        "• <code>/унизить</code> — показать, кто здесь главный\n"
        "• <code>/похвалить</code> — проявить милость\n"
        "• <code>/заткнуть</code> — лишить права голоса\n\n"
        "🎒 <b>Магазин и предметы</b>\n"
        "• <code>/лавка</code> — открыть ассортимент магазина\n"
        "• <code>/купить [номер]</code> — приобрести товар\n"
        "• <code>/проверить_рабов</code> — использовать предмет проверки\n"
        "• <code>/анархия</code> — активировать предмет анархии\n\n"
        "📊 <b>Информация и топы</b>\n"
        "• <code>/кошель</code> — твой баланс и инвентарь\n"
        "• <code>/хозяин</code> — узнать, кому ты принадлежишь\n"
        "• <code>/рабы</code> — список твоих рабов\n"
        "• Ответом + <code>/цена</code> — узнать стоимость игрока\n"
        "• <code>/топ</code> — рейтинг лучших в этом чате\n"
        "• <code>/глотоп</code> — мировой рейтинг игроков\n"
        "• <code>/пергамент</code> — посмотреть все статусы\n"
        "• <code>/скрижаль</code> — общая статистика чата\n"
        "• <code>/титул</code> — титулы империи · <code>/улучшить</code> — прокачка\n"
        "• <code>/донат</code> — докупить XC за крипту\n\n"
        "💡 <b>Подсказка:</b> все команды можно вводить как через "
        "<code>/</code>, так и через <code>.</code>"
        "</blockquote>"
    )


# =========================
# WORK (фарм XC)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](работенка|работа|фарм)$"))
async def work_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())
    base_amount = random.randint(WORK_MIN, WORK_MAX)

    async with db_lock:
        await ensure_user(user)
        data = await get_user(user.id)

        # Кулдаун теперь хранится в work_ready_at —
        # после каждой смены выставляется случайный 25–60 мин.
        remaining = data["work_ready_at"] - now
        if remaining > 0:
            hours, rem = divmod(remaining, 3600)
            minutes = rem // 60
            await message.reply(
                "🏭 <b>РАБОТЕНКА</b>\n\n"
                "Где вы ходите, когда так нужны? "
                "Сейчас не нужны.\n\n"
                f"⏳ Понадобишься через <b>{hours} ч. {minutes} мин.</b>"
            )
            return

        # Бонусы от предметов: % + фикс
        amount = base_amount
        pct = await work_bonus_percent(user.id)
        if pct:
            amount += int(base_amount * pct / 100)
        if await has_item(user.id, "chasy"):
            amount += 5

        # Золотая смена: ×3 XC
        golden = random.random() < GOLDEN_CHANCE
        if golden:
            amount *= GOLDEN_MULT

        # Бонус титула ко всем доходам
        mult = await income_multiplier(user.id)
        amount = int(amount * mult)

        next_cd = random.randint(WORK_CD_MIN, WORK_CD_MAX)
        if await has_item(user.id, "botinki"):
            next_cd = int(next_cd * 0.9)

        assert db is not None
        await db.execute(
            "UPDATE users SET last_work_at = ?, work_ready_at = ?, "
            "bb = bb + ?, total_earned = total_earned + ? "
            "WHERE user_id = ?",
            (now, now + next_cd, amount, amount, user.id),
        )
        await db.commit()

        updated = await get_user(user.id)
        achievements = await check_achievements(
            user.id, updated["total_earned"]
        )

        # Доля заработка уходит хозяину, если игрок — раб.
        master_cut = 0
        master_row = None
        if data["slave_of"]:
            master_cut = int(amount * MASTER_CUT)
            if master_cut > 0:
                master_row = await get_user_by_id(data["slave_of"])
                await db.execute(
                    "UPDATE users SET bb = bb + ? WHERE user_id = ?",
                    (master_cut, data["slave_of"]),
                )
                await db.commit()

        # Дроп предмета
        dropped = None
        burned = None
        roll = random.random()
        if roll < DROP_CHANCE_EPIC:
            pool = [i for i in ITEM_LIST
                    if ITEMS[i]["rarity"] == "Эпический"]
        elif roll < DROP_CHANCE_EPIC + DROP_CHANCE_RARE:
            pool = [i for i in ITEM_LIST
                    if ITEMS[i]["rarity"] == "Редкий"]
        elif roll < (DROP_CHANCE_EPIC + DROP_CHANCE_RARE
                     + DROP_CHANCE_COMMON):
            pool = [i for i in ITEM_LIST
                    if ITEMS[i]["rarity"] == "Обычный"]
        else:
            pool = []
        if pool:
            item_id = random.choice(pool)
            burned = await add_item(user.id, item_id, now)
            await db.commit()
            item = ITEMS[item_id]
            dropped = (
                f"🎁 Дроп: {item['emoji']} <b>{item['name']}</b> "
                f"({item['rarity']})!"
            )
            if burned:
                old = ITEMS[burned]
                dropped += (
                    f"\n🔥 Инвентарь полон — {old['emoji']} "
                    f"<b>{old['name']}</b> сгорел."
                )

    phrase = random.choice(WORK_PHRASES)
    if golden:
        phrase = "🌟 ЗОЛОТАЯ РАБОТЕНКА! " + phrase
    lines = [
        f"🏭 <b>РАБОТЕНКА</b>\n\n{phrase}\n\n💰 <b>+{amount} XC</b>",
    ]
    if master_cut and master_row:
        lines.append(
            f"🏛️ {master_cut} XC отправлено хозяину "
            f"{row_name(master_row)}"
        )
    if dropped:
        lines.append(dropped)
    for name in achievements:
        lines.append(f"🏆 Достижение: <b>{name}</b>")

    await message.reply("\n".join(lines))


# =========================
# WALLET
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](кошель|wallet|баланс)$"))
async def wallet_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

    slave_line = ""
    if data["slave_of"]:
        master = await get_user_by_id(data["slave_of"])
        if master:
            slave_line = f"⛓️ Хозяин: {row_name(master)}\n"

    inventory = await get_inventory(user.id)
    inv_limit = await inventory_max(user.id)
    if inventory:
        items_text = "\n".join(
            f"  {ITEMS[i]['emoji']} {ITEMS[i]['name']}" for i in inventory
        )
        inv_text = (
            f"🎒 Инвентарь ({len(inventory)}/{inv_limit}):\n{items_text}"
        )
    else:
        inv_text = "🎒 Инвентарь пуст — загляни в <code>.лавка</code>"

    await message.reply(
        "👛 <b>КОШЕЛЬ</b>\n\n"
        f"💰 Баланс: <b>{data['bb']} XC</b>\n"
        f"🧷 Рабов: <b>{data['slaves_count']}</b>\n"
        f"📈 Твоя цена: <b>{slave_price(data['slaves_count'])} XC</b>\n"
        f"{slave_line}\n"
        f"{inv_text}"
    )


# =========================
# SLAVERY HELPERS
# =========================

async def free_slave(owner_id: int, slave_id: int) -> bool:
    """Освобождает раба. True если раб был у этого хозяина."""
    assert db is not None
    cursor = await db.execute(
        "DELETE FROM slaves WHERE owner_id = ? AND slave_id = ?",
        (owner_id, slave_id),
    )
    if cursor.rowcount == 0:
        return False
    await db.execute(
        "UPDATE users SET slaves_count = MAX(slaves_count - 1, 0) "
        "WHERE user_id = ?",
        (owner_id,),
    )
    await db.execute(
        "UPDATE users SET slave_of = NULL, enslaved_at = NULL "
        "WHERE user_id = ?",
        (slave_id,),
    )
    return True


# =========================
# ENSLAVE
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](поработить|раб)$"), F.reply_to_message)
async def enslave_command(message: Message) -> None:
    actor = message.from_user
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not actor or actor.is_bot:
        return
    if not target or target.is_bot:
        await message.reply("❌ Нельзя поработить бота.")
        return
    if target.id == actor.id:
        await message.reply("😅 Нельзя поработить самого себя!")
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(actor)
        await ensure_user(target)
        assert db is not None
        await db.commit()

        actor_data = await get_user(actor.id)
        target_data = await get_user(target.id)

        if actor_data["slave_of"]:
            await message.reply("⛓️ Ты сам в рабстве — порабощать нельзя!")
            return
        if target_data["slave_of"]:
            await message.reply("⛓️ Этот игрок уже чей-то раб.")
            return
        if target_data["escape_immune_until"] > now:
            await message.reply(
                "🛡️ Этот игрок недавно сбежал — "
                "у него иммунитет к порабощению."
            )
            return

        price = slave_price(target_data["slaves_count"])
        if actor_data["bb"] < price:
            await message.reply(
                f"❌ Недостаточно XC. Нужно <b>{price}</b>."
            )
            return

        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (price, actor.id),
        )
        # Деньги за порабощение сгорают в экономику бота —
        # жертве ничего не начисляется.
        await db.execute(
            "UPDATE users SET slave_of = ?, enslaved_at = ? "
            "WHERE user_id = ?",
            (actor.id, now, target.id),
        )
        await db.execute(
            "INSERT INTO slaves (owner_id, slave_id, chat_id, enslaved_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_id, slave_id) DO NOTHING",
            (actor.id, target.id, message.chat.id, now),
        )
        await db.execute(
            "UPDATE users SET slaves_count = slaves_count + 1 "
            "WHERE user_id = ?",
            (actor.id,),
        )
        await db.commit()

        actor_updated = await get_user(actor.id)

    await message.reply(
        f"⛓️ | {display_name(actor)} поработил "
        f"{display_name(target)}.\n"
        f"💸 Уплачено: <b>{price} XC</b>\n"
        f"🧷 Рабов у {display_name(actor)}: "
        f"<b>{actor_updated['slaves_count']}</b>"
    )


# =========================
# ESCAPE (платный)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](сбежать|выкуп)$"))
async def escape_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        if not data["slave_of"]:
            await message.reply("🕊️ Вы свободны. Пока что...")
            return

        # Выкуп дороже цены порабощения
        price = int(slave_price(data["slaves_count"]) * BUYOUT_MULT)
        if await has_item(user.id, "maska"):
            price = int(price * 0.8)
        if data["bb"] < price:
            await message.reply(
                f"❌ Не хватает XC на выкуп. Нужно <b>{price}</b>."
            )
            return

        owner_id = data["slave_of"]
        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (price, user.id),
        )
        await db.execute(
            "UPDATE users SET bb = bb + ? WHERE user_id = ?",
            (price, owner_id),
        )
        await free_slave(owner_id, user.id)
        await db.execute(
            "UPDATE users SET escape_immune_until = ? WHERE user_id = ?",
            (now + ESCAPE_IMMUNITY, user.id),
        )
        await db.commit()

        owner = await get_user_by_id(owner_id)

    await message.reply(
        "🔓 <b>ПОБЕГ УДАЛСЯ!</b>\n\n"
        f"Свобода куплена за <b>{price} XC</b>.\n"
        "Хозяин будет недоволен...\n\n"
        "🛡️ Иммунитет к порабощению: 5 минут."
    )

    if owner:
        try:
            await bot.send_message(
                owner_id,
                f"💢 Раб {display_name(user)} сбежал! "
                "Выкуп ушёл тебе.",
            )
        except Exception:
            pass


# =========================
# LUCKY ESCAPE (.побег, 2%)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](побег)$"))
async def lucky_escape_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        if not data["slave_of"]:
            await message.reply("🕊️ Ты свободен — бежать не от кого.")
            return

        remaining = data["escape_ready_at"] - now
        if remaining > 0:
            await cooldown_text_reply(message, remaining, "побега")
            return

        await db.execute(
            "UPDATE users SET escape_ready_at = ? WHERE user_id = ?",
            (now + ESCAPE_COOLDOWN, user.id),
        )
        await db.commit()

        if random.random() >= ESCAPE_CHANCE:
            await message.reply("👮‍♂️ Поймали при попытке к бегству!")
            return

        owner_id = data["slave_of"]
        await free_slave(owner_id, user.id)
        await db.execute(
            "UPDATE users SET escape_immune_until = ? WHERE user_id = ?",
            (now + ESCAPE_IMMUNITY, user.id),
        )
        await db.commit()
        owner = await get_user_by_id(owner_id)

    await message.reply(
        "🏃‍♂️ <b>БЕГСТВО УДАЛОСЬ!</b>\n\n"
        "Ты вырвался из рабства бесплатно!\n"
        "Хозяин в ярости..."
    )

    if owner:
        try:
            await bot.send_message(
                owner_id,
                f"😡 Твой раб {display_name(user)} сбежал бесплатно!",
            )
        except Exception:
            pass


async def cooldown_text_reply(message: Message, remaining: int, what: str) -> None:
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    await message.reply(
        f"⏳ Перезарядка {what}!\n\n"
        f"Следующий раз через <b>{hours} ч. {minutes} мин.</b>"
    )


# =========================
# FREE SLAVES
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](освободить|фри_все|freeall)$"))
async def free_all_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    async with db_lock:
        assert db is not None
        await db.commit()
        cursor = await db.execute(
            "SELECT slave_id FROM slaves WHERE owner_id = ?",
            (user.id,),
        )
        slave_ids = [row["slave_id"] for row in await cursor.fetchall()]

        for slave_id in slave_ids:
            await free_slave(user.id, slave_id)
        await db.commit()

    if not slave_ids:
        await message.reply("🕊️ У тебя нет рабов, которых можно освободить.")
    else:
        await message.reply(
            f"🕊️ Освобождено рабов: <b>{len(slave_ids)}</b>. "
            "Все свободны!"
        )


@dp.message(F.text.regexp(r"(?i)^[/\\.](свободен|фри)$"), F.reply_to_message)
async def free_one_command(message: Message) -> None:
    user = message.from_user
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not user or user.is_bot:
        return
    if not target:
        await message.reply("❌ Ответь на сообщение раба.")
        return

    async with db_lock:
        assert db is not None
        await db.commit()
        freed = await free_slave(user.id, target.id)
        await db.commit()

    if freed:
        await message.reply(
            f"🕊️ | {display_name(user)} освободил "
            f"{display_name(target)}."
        )
    else:
        await message.reply("❌ Этот игрок не твой раб.")


# =========================
# INFO: хозяин / рабы / цена
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](хозяин|господин)$"))
async def master_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    async with db_lock:
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

    if not data or not data["slave_of"]:
        await message.reply("🕊️ Вы свободны. Пока что...")
        return

    owner = await get_user_by_id(data["slave_of"])
    if owner:
        since = time.strftime("%d.%m.%Y", time.localtime(data["enslaved_at"] or 0))
        await message.reply(
            f"⛓️ Твой хозяин: {row_name(owner)}\n"
            f"📅 В рабстве с: {since}"
        )
    else:
        await message.reply("🕊️ Вы свободны. Пока что...")


@dp.message(F.text.regexp(r"(?i)^[/\\.](рабы|мои_рабы)$"))
async def slaves_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    async with db_lock:
        assert db is not None
        await db.commit()
        cursor = await db.execute(
            """
            SELECT s.slave_id, s.enslaved_at, u.username, u.first_name
            FROM slaves AS s
            LEFT JOIN users AS u ON u.user_id = s.slave_id
            WHERE s.owner_id = ?
            ORDER BY s.enslaved_at ASC
            """,
            (user.id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.reply("🕊️ У тебя пока нет рабов. Иди поработай!")
        return

    lines = [f"⛓️ <b>ТВОИ РАБЫ ({len(rows)}):</b>\n"]
    for row in rows:
        if row["username"]:
            name = "@" + html.escape(row["username"])
        else:
            name = html.escape(row["first_name"] or "Игрок")
            name = f'<a href="tg://user?id={row["slave_id"]}">{name}</a>'
        since = time.strftime("%d.%m.%Y", time.localtime(row["enslaved_at"]))
        lines.append(f"• {name} — с {since}")

    await message.reply("\n".join(lines))


@dp.message(F.text.regexp(r"(?i)^[/\\.](цена|price)$"), F.reply_to_message)
async def price_command(message: Message) -> None:
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply("❌ Ответь на сообщение игрока.")
        return

    async with db_lock:
        assert db is not None
        await db.commit()
        data = await get_user(target.id)

    if not data:
        await message.reply("❌ Этот человек не найден в базе.")
        return

    price = slave_price(data["slaves_count"])
    await message.reply(
        f"💵 Цена {display_name(target)}: <b>{price} XC</b>"
    )


# =========================
# TOP
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](топ|top)$"))
async def top_command(message: Message) -> None:
    async with db_lock:
        assert db is not None
        await db.commit()
        cursor = await db.execute(
            """
            SELECT owner_id, COUNT(*) AS cnt
            FROM slaves
            WHERE chat_id = ?
            GROUP BY owner_id
            ORDER BY cnt DESC, owner_id ASC
            LIMIT 10
            """,
            (message.chat.id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.reply("🏆 Рабов пока ни у кого нет. Будь первым!")
        return

    owners = []
    for row in rows:
        owner = await get_user_by_id(row["owner_id"])
        owners.append((row["cnt"], owner))

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>ТОП РАБОВЛАДЕЛЬЦЕВ ЧАТА</b>\n"]
    for i, (cnt, owner) in enumerate(owners):
        if not owner:
            continue
        medal = medals[i] if i < 3 else f"{i + 1}."
        lvl = min(owner["title_level"], len(TITLES) - 1)
        title_tag = (
            f" · {TITLES[lvl]['name']}" if lvl > 0 else ""
        )
        lines.append(
            f"{medal} {row_name(owner)}{title_tag} — "
            f"<b>{cnt} рабов</b>"
        )

    await message.reply("\n".join(lines))


@dp.message(F.text.regexp(r"(?i)^[/\\.](глотоп|globaltop)$"))
async def global_top_command(message: Message) -> None:
    async with db_lock:
        assert db is not None
        await db.commit()
        cursor = await db.execute(
            """
            SELECT owner_id, COUNT(*) AS cnt
            FROM slaves
            GROUP BY owner_id
            ORDER BY cnt DESC, owner_id ASC
            LIMIT 10
            """
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.reply("🌍 Рабов в мире пока нет. Будь первым!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🌍 <b>ГЛОБАЛЬНЫЙ ТОП РАБОВЛАДЕЛЬЦЕВ</b>\n"]
    i = 0
    for row in rows:
        owner = await get_user_by_id(row["owner_id"])
        if not owner:
            continue
        medal = medals[i] if i < 3 else f"{i + 1}."
        lvl = min(owner["title_level"], len(TITLES) - 1)
        title_tag = (
            f" · {TITLES[lvl]['name']}" if lvl > 0 else ""
        )
        lines.append(
            f"{medal} {row_name(owner)}{title_tag} — "
            f"<b>{row['cnt']} рабов</b>"
        )
        i += 1

    await message.reply("\n".join(lines))


# =========================
# FORCE WORK (.работать)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](работать|принудить)$"))
async def force_work_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        remaining = data["force_ready_at"] - now
        if remaining > 0:
            hours, rem = divmod(remaining, 3600)
            minutes = rem // 60
            await message.reply(
                "🏭 <b>ПРИНУЖДЕНИЕ</b>\n\n"
                f"⏳ Следующая смена через <b>{hours} ч. {minutes} мин.</b>"
            )
            return

        if data["slaves_count"] <= 0:
            await message.reply(
                "🕊️ У тебя нет рабов — заставлять некого."
            )
            return

        earned = data["slaves_count"] * FORCE_REWARD_PER_SLAVE
        anarchy = data["anarchy_until"] > now
        jackpot = False
        if random.random() < JACKPOT_CHANCE:
            earned = random.randint(JACKPOT_MIN, JACKPOT_MAX)
            jackpot = True
        elif anarchy:
            earned *= 2
        earned = int(earned * await income_multiplier(user.id))
        await db.execute(
            "UPDATE users SET bb = bb + ?, force_ready_at = ?, "
            "anarchy_until = 0 WHERE user_id = ?",
            (earned, now + FORCE_COOLDOWN, user.id),
        )
        await db.commit()
        updated = await get_user(user.id)

    notes = []
    if anarchy:
        notes.append("🌪️ Анархия: ×2 XC!")
    if jackpot:
        notes.append("🎰 ДЖЕКПОТ!")
    anarchy_note = ("\n" + "\n".join(notes)) if notes else ""
    await message.reply(
        "💪 <b>ПРИНУЖДЕНИЕ К ТРУДУ!</b>\n\n"
        f"{data['slaves_count']} рабов отработали смену.\n"
        f"💰 Получено: <b>{earned} XC</b>{anarchy_note}\n"
        f"💳 Баланс: <b>{updated['bb']} XC</b>\n"
        "⏰ Следующее принуждение через 4 часа"
    )


# =========================
# FIND / LUCKY ENSLAVE (.найти)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](найти|поиск)$"))
async def find_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        remaining = data["find_ready_at"] - now
        if remaining > 0:
            hours, rem = divmod(remaining, 3600)
            minutes = rem // 60
            await message.reply(
                "🔍 <b>ПОИСК ЖЕРТВЫ</b>\n\n"
                f"⏳ Следующая попытка через <b>{hours} ч. {minutes} мин.</b>"
            )
            return

        await db.execute(
            "UPDATE users SET find_ready_at = ? WHERE user_id = ?",
            (now + FIND_COOLDOWN, user.id),
        )
        await db.commit()

        if data["slave_of"]:
            await message.reply("⛓️ Ты сам в рабстве — искать жертв нельзя.")
            return

        if random.random() >= FIND_CHANCE:
            fail = random.choice([
                "🔍 Поиски не увенчались успехом...",
                "🌫️ Туман мешает найти жертву",
                "🔍 Никого подходящего рядом не оказалось.",
            ])
            await message.reply(fail)
            return

        # Ищем случайную свободную жертву — сначала среди
        # участников этого чата, потом глобально.
        victim = None
        for extra in ("AND last_chat_id = ?", ""):
            params = [user.id, now]
            if extra:
                params.append(message.chat.id)
            cursor = await db.execute(
                f"""
                SELECT * FROM users
                WHERE user_id != ?
                  AND slave_of IS NULL
                  AND escape_immune_until <= ?
                  {extra}
                ORDER BY RANDOM()
                LIMIT 1
                """,
                params,
            )
            victim = await cursor.fetchone()
            if victim:
                break
        if not victim:
            await message.reply("🔍 Подходящих жертв в базе нет.")
            return

        await db.execute(
            "UPDATE users SET slave_of = ?, enslaved_at = ? "
            "WHERE user_id = ?",
            (user.id, now, victim["user_id"]),
        )
        await db.execute(
            "INSERT INTO slaves (owner_id, slave_id, chat_id, enslaved_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_id, slave_id) DO NOTHING",
            (user.id, victim["user_id"], message.chat.id, now),
        )
        await db.execute(
            "UPDATE users SET slaves_count = slaves_count + 1 "
            "WHERE user_id = ?",
            (user.id,),
        )
        await db.commit()
        actor_updated = await get_user(user.id)

    victim_name = row_name(victim)
    await message.reply(
        f"🎯 <b>ЖЕРТВА НАЙДЕНА!</b>\n\n"
        f"{victim_name} теперь твой раб — бесплатно!\n"
        f"🧷 Всего рабов: <b>{actor_updated['slaves_count']}</b>"
    )


# =========================
# TRANSFER (.передать)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](передать|transfer)(?:\s+(\d+))?$"),
            F.reply_to_message)
async def transfer_command(message: Message) -> None:
    actor = message.from_user
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not actor or actor.is_bot:
        return
    if not target or target.is_bot:
        await message.reply("❌ Нельзя передать XC боту.")
        return
    if target.id == actor.id:
        await message.reply("😅 Себе переводить не надо!")
        return

    amount = None
    parts = (message.text or "").split()
    if len(parts) > 1:
        try:
            amount = int(parts[-1])
        except ValueError:
            await message.reply(
                "❌ Укажи сумму числом: <code>.передать 100</code>"
            )
            return
        if amount <= 0:
            await message.reply("❌ Сумма должна быть больше нуля.")
            return

    if amount is None:
        await message.reply(
            "❌ Укажи сумму: <code>.передать 100</code>"
        )
        return

    async with db_lock:
        await ensure_user(actor)
        await ensure_user(target)
        assert db is not None
        await db.commit()
        actor_data = await get_user(actor.id)

        if actor_data["bb"] < amount:
            await message.reply(
                f"❌ Не хватает XC. У тебя <b>{actor_data['bb']}</b>."
            )
            return

        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (amount, actor.id),
        )
        await db.execute(
            "UPDATE users SET bb = bb + ? WHERE user_id = ?",
            (amount, target.id),
        )
        await db.commit()
        actor_updated = await get_user(actor.id)

    await message.reply(
        f"💸 | {display_name(actor)} передал "
        f"<b>{amount} XC</b> {display_name(target)}.\n"
        f"💰 Твой баланс: <b>{actor_updated['bb']} XC</b>"
    )


# =========================
# BUYOUT SLAVE (.перекупить)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](перекупить|перекуп|buyout)$"),
            F.reply_to_message)
async def buyout_command(message: Message) -> None:
    actor = message.from_user
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not actor or actor.is_bot:
        return
    if not target or target.is_bot:
        await message.reply("❌ Нельзя перекупить бота.")
        return
    if target.id == actor.id:
        await message.reply("😅 Это твой раб — перекупать не надо!")
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(actor)
        await ensure_user(target)
        assert db is not None
        await db.commit()

        actor_data = await get_user(actor.id)
        target_data = await get_user(target.id)

        if actor_data["slave_of"]:
            await message.reply("⛓️ Ты сам в рабстве — перекупать нельзя!")
            return
        if not target_data["slave_of"]:
            await message.reply("🕊️ Этот игрок не чей-то раб — "
                                "просто используй .поработить")
            return
        if target_data["slave_of"] == actor.id:
            await message.reply("😅 Это уже твой раб!")
            return

        owner_id = target_data["slave_of"]
        # Цена перекупа = цена раба × 2
        cost = slave_price(target_data["slaves_count"]) * 2
        if actor_data["bb"] < cost:
            await message.reply(
                f"❌ Не хватает XC на перекуп. Нужно <b>{cost}</b>."
            )
            return

        # Деньги уходят старому хозяину
        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (cost, actor.id),
        )
        await db.execute(
            "UPDATE users SET bb = bb + ? WHERE user_id = ?",
            (cost, owner_id),
        )
        # Снимаем старое рабство
        await db.execute(
            "DELETE FROM slaves WHERE owner_id = ? AND slave_id = ?",
            (owner_id, target.id),
        )
        await db.execute(
            "UPDATE users SET slaves_count = MAX(slaves_count - 1, 0) "
            "WHERE user_id = ?",
            (owner_id,),
        )
        # Назначаем нового хозяина
        await db.execute(
            "UPDATE users SET slave_of = ?, enslaved_at = ? "
            "WHERE user_id = ?",
            (actor.id, now, target.id),
        )
        await db.execute(
            "INSERT INTO slaves (owner_id, slave_id, chat_id, enslaved_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(owner_id, slave_id) DO NOTHING",
            (actor.id, target.id, message.chat.id, now),
        )
        await db.execute(
            "UPDATE users SET slaves_count = slaves_count + 1 "
            "WHERE user_id = ?",
            (actor.id,),
        )
        await db.commit()

        actor_updated = await get_user(actor.id)
        owner = await get_user_by_id(owner_id)

    owner_text = row_name(owner) if owner else "хозяин"
    await message.reply(
        f"💰 | {display_name(actor)} перекупил "
        f"{display_name(target)} у {owner_text}.\n"
        f"💸 Уплачено: <b>{cost} XC</b>\n"
        f"🧷 Рабов у {display_name(actor)}: "
        f"<b>{actor_updated['slaves_count']}</b>"
    )

    if owner:
        try:
            await bot.send_message(
                owner_id,
                f"💸 Твой раб {display_name(target)} перекуплен "
                f"игроком {display_name(actor)} за {cost} XC.",
            )
        except Exception:
            pass


# =========================
# SLAVE ACTIONS (.выпороть и др.)
# =========================

# emoji, глагол — стиль: "🥰 | @a погладил @b."
SLAVE_ACTIONS = {
    "выпороть": ("💥", "выпорол"),
    "унизить": ("😡", "унизил"),
    "похвалить": ("🌟", "похвалил"),
}

for cmd, (emoji, verb) in SLAVE_ACTIONS.items():
    @dp.message(F.text.regexp(rf"(?i)^[/\\.]({cmd})$"), F.reply_to_message)
    async def slave_action(message: Message, _emoji=emoji, _verb=verb) -> None:
        actor = message.from_user
        target = message.reply_to_message.from_user if message.reply_to_message else None

        if not actor or actor.is_bot or not target:
            return

        async with db_lock:
            assert db is not None
            await ensure_user(actor)
            await db.commit()
            data = await get_user(actor.id)
            cost = await slave_action_cost(actor.id)

            if not data or data["bb"] < cost:
                await message.reply(
                    f"❌ Недостаточно XC для этого действия "
                    f"(нужно {cost})."
                )
                return

            cursor = await db.execute(
                "SELECT 1 FROM slaves WHERE owner_id = ? AND slave_id = ?",
                (actor.id, target.id),
            )
            if not await cursor.fetchone():
                await message.reply("❌ Этот игрок не твой раб.")
                return

            await db.execute(
                "UPDATE users SET bb = bb - ? WHERE user_id = ?",
                (cost, actor.id),
            )
            await db.commit()

        await message.reply(
            f"{_emoji} | {display_name(actor)} {_verb} "
            f"{display_name(target)}.\n−{cost} XC"
        )


@dp.message(F.text.regexp(r"(?i)^[/\\.](заткнуть|mute)$"), F.reply_to_message)
async def mute_slave_command(message: Message) -> None:
    actor = message.from_user
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not actor or actor.is_bot or not target:
        await message.reply("❌ Ответь на сообщение раба.")
        return

    async with db_lock:
        assert db is not None
        await ensure_user(actor)
        await db.commit()
        data = await get_user(actor.id)
        cost = await slave_action_cost(actor.id)

        if not data or data["bb"] < cost:
            await message.reply(
                f"❌ Недостаточно XC для этого действия "
                f"(нужно {cost})."
            )
            return

        cursor = await db.execute(
            "SELECT 1 FROM slaves WHERE owner_id = ? AND slave_id = ?",
            (actor.id, target.id),
        )
        if not await cursor.fetchone():
            await message.reply("❌ Этот игрок не твой раб.")
            return

        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (cost, actor.id),
        )
        await db.commit()

    try:
        await bot.restrictChatMember(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False,
            ),
            until_date=int(time.time()) + 60,
        )
        await message.reply(
            f"🤐 | {display_name(actor)} заткнул "
            f"{display_name(target)}.\n−{cost} XC"
        )
    except Exception:
        await message.reply(
            "❌ Не удалось заткнуть: у бота нет прав "
            "ограничивать участников (нужна админка)."
        )


# =========================
# TITLES (/титул, /улучшить)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](титул|title|статус_игрока)$"))
async def title_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

    level = data["title_level"]
    if level >= len(TITLES):
        level = len(TITLES) - 1
    current = TITLES[level]

    lines = [
        "👑 <b>ТИТУЛЫ ИМПЕРИИ</b>\n",
        f"Твой титул: <b>{current['name']}</b>\n",
        "<b>Шкала прокачки:</b>",
    ]
    for i, t in enumerate(TITLES):
        mark = "✅" if i < level else ("👉" if i == level else "▫️")
        cost = "—" if t["cost"] == 0 else f"{t['cost']} XC"
        bonus = f"+{t['pct']}% доход" if t["pct"] else "старт"
        if t["slots"]:
            bonus += f", +{t['slots']} слот(а)"
        lines.append(f"{mark} {t['name']} — {cost} ({bonus})")

    if data["title_level"] < len(TITLES) - 1:
        nxt = TITLES[data["title_level"] + 1]
        lines.append(
            f"\nСледующий титул: <b>{nxt['name']}</b> — "
            f"<b>{nxt['cost']} XC</b>\n"
            "Прокачаться: <code>/улучшить</code>"
        )
    else:
        lines.append("\n👑 Ты достиг вершины империи!")

    await message.reply("\n".join(lines))


@dp.message(F.text.regexp(r"(?i)^[/\\.](улучшить|upgrade|прокачать)$"))
async def upgrade_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        level = data["title_level"]
        if level >= len(TITLES) - 1:
            await message.reply(
                "👑 Ты уже на максимальном титуле — "
                "выше только империя!"
            )
            return

        nxt = TITLES[level + 1]
        if data["bb"] < nxt["cost"]:
            await message.reply(
                f"❌ Не хватает XC на титул <b>{nxt['name']}</b>.\n"
                f"Нужно: <b>{nxt['cost']} XC</b>, "
                f"у тебя: <b>{data['bb']} XC</b>."
            )
            return

        await db.execute(
            "UPDATE users SET bb = bb - ?, title_level = ? "
            "WHERE user_id = ?",
            (nxt["cost"], level + 1, user.id),
        )
        await db.commit()
        updated = await get_user(user.id)

    bonus_parts = [f"+{nxt['pct']}% ко всем доходам"]
    if nxt["slots"]:
        bonus_parts.append(f"+{nxt['slots']} слот(а) инвентаря")

    await message.reply(
        f"👑 <b>НОВЫЙ ТИТУЛ: {nxt['name']}!</b>\n\n"
        f"−{nxt['cost']} XC · Баланс: <b>{updated['bb']} XC</b>\n"
        f"Бонусы: {', '.join(bonus_parts)}"
    )


# =========================
# SHOP (.лавка / .купить)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](лавка|shop|магазин)$"))
async def shop_command(message: Message) -> None:
    lines = ["🏪 <b>ЛАВКА</b>\n", "Предметы покупаются за XC:\n"]
    for i, item_id in enumerate(ITEM_LIST, 1):
        item = ITEMS[item_id]
        lines.append(
            f"{i}. {item['emoji']} <b>{item['name']}</b> "
            f"— {item['price']} XC ({item['rarity']})\n"
            f"   <i>{item['desc']}</i>"
        )
    lines.append(
        "\nКупить: <code>.купить 1</code>\n"
        f"Инвентарь вмещает до {INVENTORY_MAX} предметов."
    )
    await message.reply("\n".join(lines))


@dp.message(F.text.regexp(r"(?i)^[/\\.](купить|buy)\s+(\d+)$"))
async def buy_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    match = message.text or ""
    try:
        index = int(match.split()[-1]) - 1
        item_id = ITEM_LIST[index]
    except (ValueError, IndexError):
        await message.reply("❌ Укажи номер предмета: <code>.купить 1</code>")
        return

    item = ITEMS[item_id]
    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        if data["bb"] < item["price"]:
            await message.reply(
                f"❌ Не хватает XC. Нужно <b>{item['price']}</b>."
            )
            return

        await db.execute(
            "UPDATE users SET bb = bb - ? WHERE user_id = ?",
            (item["price"], user.id),
        )
        burned = await add_item(user.id, item_id, now)
        await db.commit()
        updated = await get_user(user.id)

    text = (
        f"🛒 Куплено: {item['emoji']} <b>{item['name']}</b>\n"
        f"−{item['price']} XC · Баланс: <b>{updated['bb']} XC</b>"
    )
    if burned:
        old = ITEMS[burned]
        text += (
            f"\n🔥 Инвентарь был полон — {old['emoji']} "
            f"<b>{old['name']}</b> сгорел."
        )
    await message.reply(text)


# =========================
# PERGAMENT (.пергамент)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](пергамент|статус)$"))
async def pergament_command(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)
        achievements = await get_achievements(user.id)
        inventory = await get_inventory(user.id)

    def fmt_cd(ready_at: int) -> str:
        rem = ready_at - now
        if rem <= 0:
            return "готово"
        h, r = divmod(rem, 3600)
        return f"{h} ч. {r // 60} мин."

    status = "⛓️ Раб" if data["slave_of"] else "🕊️ Свободен"
    force_cd = fmt_cd(data["force_ready_at"])
    anarchy_left = max(0, data["anarchy_until"] - now)

    lines = [
        f"📜 <b>ПЕРГАМЕНТ</b> — {display_name(user)}\n",
        f"💰 XC: <b>{data['bb']}</b>",
        f"👥 Рабов: <b>{data['slaves_count']}</b>",
        f"📈 Цена: <b>{slave_price(data['slaves_count'])} XC</b>",
        f"🕊️ Статус: {status}",
        f"👑 Титул: <b>{TITLES[min(data['title_level'], len(TITLES) - 1)]['name']}</b>",
        f"⚒️ Принуждение: {force_cd}",
    ]
    if anarchy_left:
        lines.append(f"🌪️ Анархия активна: {anarchy_left // 60} мин.")

    if inventory:
        items_text = ", ".join(
            f"{ITEMS[i]['emoji']} {ITEMS[i]['name']}" for i in inventory
        )
        max_slots = await inventory_max(user.id)
        lines.append(
            f"🎒 Предметы ({len(inventory)}/{max_slots}): {items_text}"
        )

    if achievements:
        lines.append("\n🏆 <b>Достижения:</b>")
        lines.extend(f"• {name}" for name in achievements)

    await message.reply("\n".join(lines))


# =========================
# SKRIZHAL (.скрижаль)
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](скрижаль|stats)$"))
async def skrizhal_command(message: Message) -> None:
    async with db_lock:
        assert db is not None
        await db.commit()
        cursor = await db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM slaves WHERE chat_id = ?) AS active,
                (SELECT COUNT(DISTINCT uid) FROM (
                    SELECT owner_id AS uid FROM slaves WHERE chat_id = ?
                    UNION
                    SELECT slave_id AS uid FROM slaves WHERE chat_id = ?
                )) AS players
            """,
            (message.chat.id, message.chat.id, message.chat.id),
        )
        row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT owner_id, COUNT(*) AS cnt
            FROM slaves
            WHERE chat_id = ?
            GROUP BY owner_id
            ORDER BY cnt DESC
            LIMIT 3
            """,
            (message.chat.id,),
        )
        top = await cursor.fetchall()

    lines = [
        "📊 <b>СКРИЖАЛЬ ЧАТА</b>\n",
        f"👥 Игроков в рабстве/у рабов: <b>{row['players']}</b>",
        f"⛓️ Активных рабств: <b>{row['active']}</b>\n",
        "👑 Топ рабовладельцев:",
    ]
    for i, r in enumerate(top, 1):
        owner = await get_user_by_id(r["owner_id"])
        if owner:
            lines.append(f"{i}. {row_name(owner)} — {r['cnt']} рабов")

    await message.reply("\n".join(lines))


# =========================
# ITEM ACTIVE COMMANDS
# =========================

@dp.message(F.text.regexp(r"(?i)^[/\\.](проверить_рабов|check)$"))
async def check_slaves_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        if not await has_item(user.id, "nadzorshchik"):
            await message.reply(
                "❌ У вас нет предмета 'Надсмотрщик 📖' "
                "для использования этой команды."
            )
            return

        remaining = data["item_ready_at"] - now
        if remaining > 0:
            await cooldown_text_reply(message, remaining, "проверки")
            return

        if data["slaves_count"] <= 0:
            await message.reply("🕊️ Рабов нет — проверять некого.")
            return

        earned = int(
            data["slaves_count"] * 3 * await income_multiplier(user.id)
        )
        await db.execute(
            "UPDATE users SET bb = bb + ?, item_ready_at = ? "
            "WHERE user_id = ?",
            (earned, now + ITEM_CHECK_COOLDOWN, user.id),
        )
        await db.commit()
        updated = await get_user(user.id)

    await message.reply(
        "📖 <b>ПРОВЕРКА РАБОВ</b>\n\n"
        f"Надсмотрщик заглянул в казармы.\n"
        f"💰 Получено: <b>+{earned} XC</b>\n"
        f"💳 Баланс: <b>{updated['bb']} XC</b>\n"
        "⏰ Следующая проверка через час"
    )


@dp.message(F.text.regexp(r"(?i)^[/\\.](анархия|anarchy)$"))
async def anarchy_command(message: Message) -> None:
    user = message.from_user
    if not user or user.is_bot:
        return

    now = int(time.time())

    async with db_lock:
        await ensure_user(user)
        assert db is not None
        await db.commit()
        data = await get_user(user.id)

        if not await has_item(user.id, "anarhiya"):
            await message.reply(
                "❌ У вас нет предмета 'Дыхание Анархии 🌪️' "
                "для использования этой команды."
            )
            return

        remaining = data["anarchy_ready_at"] - now
        if remaining > 0:
            await cooldown_text_reply(message, remaining, "анархии")
            return

        await db.execute(
            "UPDATE users SET anarchy_until = ?, anarchy_ready_at = ? "
            "WHERE user_id = ?",
            (now + ANARCHY_DURATION, now + ANARCHY_COOLDOWN, user.id),
        )
        await db.commit()

    await message.reply(
        "🌪️ <b>ДЫХАНИЕ АНАРХИИ</b>\n\n"
        "Рабочие в ярости! Следующий <code>.работать</code> "
        "принесёт <b>×2 XC</b>.\n"
        "Действует 1 час."
    )


# =========================
# DONATE (Telegram Stars)
# =========================

@dp.message(F.text.regexp(r"(?i)^[\W_]*донат[\W_]*$"))
async def donate_command(message: Message) -> None:
    if not message.from_user or message.from_user.is_bot:
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=DONATE_PACKAGES[i + j][0],
                callback_data=f"donate_{i + j}",
            )
            for j in range(2)
            if i + j < len(DONATE_PACKAGES)
        ]
        for i in range(0, len(DONATE_PACKAGES), 2)
    ]
    await message.reply(
        "💎 <b>ДОНАТ</b>\n\n"
        "Выбери пакет — оплата Telegram Stars. "
        "XC придут на баланс после оплаты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("donate_"))
async def donate_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.is_bot:
        return
    if not callback.message:
        await callback.answer()
        return
    try:
        index = int((callback.data or "").split("_")[1])
        name, stars, xc = DONATE_PACKAGES[index]
    except (IndexError, ValueError):
        await callback.answer("❌ Пакет не найден", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer_invoice(
        title=f"Донат {name}",
        description=f"{xc} XC для Дофаминового Уолтера — цена {stars}⭐",
        payload=f"donate_{index}_{xc}",
        currency="XTR",
        prices=[LabeledPrice(label=name, amount=stars)],
    )


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query) -> None:
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message) -> None:
    payment = message.successful_payment
    if not payment or not message.from_user:
        return

    parts = (payment.invoice_payload or "").split("_")
    if len(parts) != 3 or parts[0] != "donate":
        return
    try:
        xc = int(parts[2])
    except ValueError:
        return

    user_id = message.from_user.id
    async with db_lock:
        assert db is not None
        await ensure_user(message.from_user)
        await db.execute(
            "UPDATE users SET bb = bb + ? WHERE user_id = ?",
            (xc, user_id),
        )
        await db.commit()
        updated = await get_user(user_id)

    await message.answer(
        "💎 Оплата получена!\n\n"
        f"💰 Начислено: <b>+{xc} XC</b>\n"
        f"💳 Баланс: <b>{updated['bb']} XC</b>"
    )
    logger.info("Stars-донат: user=%s +%s XC", user_id, xc)


# Фолбэк: reply-команды без ответа — подсказываем, а не молчим
@dp.message(F.text.regexp(
    r"(?i)^[/\\.](поработить|раб|свободен|фри|цена|price|"
    r"перекупить|перекуп|buyout|передать|transfer|"
    r"выпороть|унизить|похвалить|заткнуть|mute)\b"
))
async def reply_required_hint(message: Message) -> None:
    await message.reply(
        "❌ Ответь этой командой на сообщение нужного игрока."
    )


# =========================
# ADMIN (скрытые команды)
# =========================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@dp.message(
    F.text.regexp(r"(?i)^!выдать\s+\d+$"),
    F.reply_to_message,
)
async def admin_give_command(message: Message) -> None:
    actor = message.from_user
    if not actor or not is_admin(actor.id):
        return

    target = (
        message.reply_to_message.from_user
        if message.reply_to_message else None
    )
    if not target:
        return

    match = re.search(r"(\d+)", message.text or "")
    amount = int(match.group(1)) if match else 0
    if amount <= 0:
        await message.reply("❌ Укажи сумму: <code>!выдать 100</code>")
        return

    async with db_lock:
        assert db is not None
        await ensure_user(target)
        await db.execute(
            "UPDATE users SET bb = bb + ? WHERE user_id = ?",
            (amount, target.id),
        )
        await db.commit()
        updated = await get_user(target.id)

    await message.reply(
        f"💰 | {display_name(actor)} выдал "
        f"<b>{amount} XC</b> {display_name(target)}.\n"
        f"💳 Баланс: <b>{updated['bb']} XC</b>"
    )


# =========================
# STARTUP
# =========================

async def main() -> None:
    await init_db()
    logger.info("Бот запускается")
    try:
        await dp.start_polling(bot)
    finally:
        if db is not None:
            await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Работа завершена")
