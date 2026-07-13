import random
import json
import os
import sqlite3
import telebot
import time # Для работы с таймером кулдауна
from telebot import types
from flask import Flask
from threading import Thread

# Попытка импортировать psycopg2 для PostgreSQL (нужно на хостинге)
try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# ================= НАСТРОЙКА БОТА =================
TOKEN = os.environ.get("BOT_TOKEN")
# Если запускаете локально в Pydroid, можете временно вписать токен сюда
if not TOKEN:
    TOKEN = "ВАШ_ТОКЕН_БОТА" 

bot = telebot.TeleBot(TOKEN)

# ================= НАСТРОЙКА АДМИНКИ =================
ADMIN_IDS = [6597219983] # <--- ЗАМЕНИТЕ НА СВОЙ ID!

def is_admin(message):
    return message.from_user.id in ADMIN_IDS

def parse_admin_args(message_text, num_args=2):
    parts = message_text.split()
    if len(parts) < 1 + num_args: 
        return None, None, None

    try:
        target_user_id = int(parts[1])
        if num_args == 1:
            return target_user_id, None, parts[0]
        
        if num_args == 2:
            value = parts[2]
            return target_user_id, value, parts[0]
            
    except ValueError:
        return None, None, None
    return None, None, None


# ================= НАСТРОЙКА БАЗЫ ДАННЫХ =================
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = DATABASE_URL is not None and HAS_PSYCOPG2

def get_db_connection():
    if IS_POSTGRES:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return sqlite3.connect("players.db")


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            hp INTEGER,
            max_hp INTEGER,
            gold INTEGER,
            level INTEGER,
            xp INTEGER,
            kills INTEGER,
            bp_xp INTEGER,
            bp_claimed TEXT,
            dmg_bonus INTEGER,
            crit_chance INTEGER DEFAULT 5,
            defense INTEGER DEFAULT 0,
            gold_boost_percent INTEGER DEFAULT 0,
            xp_boost_percent INTEGER DEFAULT 0,
            inventory TEXT DEFAULT '[]',
            last_boss_fight_timestamp INTEGER DEFAULT 0 -- Новый столбец для кулдауна босса
        );
    """)
    conn.commit()

    columns_to_add = {
        "crit_chance": "INTEGER DEFAULT 5",
        "defense": "INTEGER DEFAULT 0",
        "gold_boost_percent": "INTEGER DEFAULT 0",
        "xp_boost_percent": "INTEGER DEFAULT 0",
        "inventory": "TEXT DEFAULT '[]'",
        "last_boss_fight_timestamp": "INTEGER DEFAULT 0" # Добавляем новое поле
    }

    if IS_POSTGRES:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='players' AND table_schema='public';")
    else:
        cur.execute("PRAGMA table_info(players);")
    
    existing_columns = [col[1] for col in cur.fetchall()]

    for col_name, col_type in columns_to_add.items():
        if col_name not in existing_columns:
            try:
                cur.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type};")
                conn.commit()
                print(f"Добавлена колонка: {col_name}")
            except (sqlite3.OperationalError, psycopg2.ProgrammingError) as e:
                print(f"Ошибка при добавлении колонки {col_name}: {e}")
                conn.rollback() 

    cur.close()
    conn.close()
    print("База данных успешно инициализирована/обновлена!")


def get_player(user_id, username):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cols = "user_id, name, hp, max_hp, gold, level, xp, kills, bp_xp, bp_claimed, dmg_bonus, crit_chance, defense, gold_boost_percent, xp_boost_percent, inventory, last_boss_fight_timestamp"
    if IS_POSTGRES:
        cur.execute(f"SELECT {cols} FROM players WHERE user_id = %s", (user_id,))
    else:
        cur.execute(f"SELECT {cols} FROM players WHERE user_id = ?", (user_id,))
        
    row = cur.fetchone()
    
    if row is None:
        player = {
            "user_id": user_id,
            "name": username or "Герой",
            "hp": 100,
            "max_hp": 100,
            "gold": 50,
            "level": 1,
            "xp": 0,
            "kills": 0,
            "bp_xp": 0,
            "bp_claimed": [],
            "dmg_bonus": 0,
            "crit_chance": 5,
            "defense": 0,
            "gold_boost_percent": 0,
            "xp_boost_percent": 0,
            "inventory": [],
            "last_boss_fight_timestamp": 0 # Дефолтное значение
        }
        
        bp_claimed_str = json.dumps(player["bp_claimed"])
        inventory_str = json.dumps(player["inventory"])
        
        if IS_POSTGRES:
            cur.execute(f"""
                INSERT INTO players ({cols})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, player["name"], player["hp"], player["max_hp"], player["gold"], 
                  player["level"], player["xp"], player["kills"], player["bp_xp"], 
                  bp_claimed_str, player["dmg_bonus"], player["crit_chance"], 
                  player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
                  inventory_str, player["last_boss_fight_timestamp"]))
        else:
            cur.execute(f"""
                INSERT INTO players ({cols})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, player["name"], player["hp"], player["max_hp"], player["gold"], 
                  player["level"], player["xp"], player["kills"], player["bp_xp"], 
                  bp_claimed_str, player["dmg_bonus"], player["crit_chance"], 
                  player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
                  inventory_str, player["last_boss_fight_timestamp"]))
        conn.commit()
    else:
        player = {
            "user_id": row[0],
            "name": row[1],
            "hp": row[2],
            "max_hp": row[3],
            "gold": row[4],
            "level": row[5],
            "xp": row[6],
            "kills": row[7],
            "bp_xp": row[8],
            "bp_claimed": json.loads(row[9]) if row[9] else [],
            "dmg_bonus": row[10],
            "crit_chance": row[11],
            "defense": row[12],
            "gold_boost_percent": row[13],
            "xp_boost_percent": row[14],
            "inventory": json.loads(row[15]) if row[15] else [],
            "last_boss_fight_timestamp": row[16] # Загрузка кулдауна
        }
        
    cur.close()
    conn.close()
    return player


def save_player(player):
    conn = get_db_connection()
    cur = conn.cursor()
    bp_claimed_str = json.dumps(player["bp_claimed"])
    inventory_str = json.dumps(player["inventory"])
    
    if IS_POSTGRES:
        cur.execute("""
            UPDATE players SET
                name = %s, hp = %s, max_hp = %s, gold = %s, level = %s, 
                xp = %s, kills = %s, bp_xp = %s, bp_claimed = %s, dmg_bonus = %s,
                crit_chance = %s, defense = %s, gold_boost_percent = %s, xp_boost_percent = %s,
                inventory = %s, last_boss_fight_timestamp = %s
            WHERE user_id = %s
        """, (
            player["name"], player["hp"], player["max_hp"], player["gold"], player["level"],
            player["xp"], player["kills"], player["bp_xp"], bp_claimed_str, player["dmg_bonus"],
            player["crit_chance"], player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
            inventory_str, player["last_boss_fight_timestamp"], player["user_id"]
        ))
    else:
        cur.execute("""
            UPDATE players SET
                name = ?, hp = ?, max_hp = ?, gold = ?, level = ?, 
                xp = ?, kills = ?, bp_xp = ?, bp_claimed = ?, dmg_bonus = ?,
                crit_chance = ?, defense = ?, gold_boost_percent = ?, xp_boost_percent = ?,
                inventory = ?, last_boss_fight_timestamp = ?
            WHERE user_id = ?
        """, (
            player["name"], player["hp"], player["max_hp"], player["gold"], player["level"],
            player["xp"], player["kills"], player["bp_xp"], bp_claimed_str, player["dmg_bonus"],
            player["crit_chance"], player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
            inventory_str, player["last_boss_fight_timestamp"], player["user_id"]
        ))
    conn.commit()
    cur.close()
    conn.close()


def get_all_player_ids():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM players;")
    user_ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return user_ids


# ================= ВЕБ-СЕРВЕР ДЛЯ ХОСТИНГА (24/7) =================
app = Flask('')

@app.route('/')
def home():
    engine = "PostgreSQL" if IS_POSTGRES else "SQLite"
    return f"Бот запущен и работает в облаке 24/7! (База данных: {engine})"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()


# ================= НАСТРОЙКА ИГРЫ И БП (60 УРОВНЕЙ) =================
BP_TIERS = {
    1: {"req": 20, "reward_text": "📦 Стартовый паёк (50💰 и 20 XP)", "gold": 50, "xp": 20},
    2: {"req": 40, "reward_text": "🎒 Сундук новобранца (100💰 и 50 XP)", "gold": 100, "xp": 50},
    3: {"req": 70, "reward_text": "🛡️ Кожаный жилет (+15 к макс. HP ❤️)", "hp_boost": 15},
    4: {"req": 110, "reward_text": "🗡️ Медный нож (+5 к урону ⚔️)", "dmg_boost": 5},
    5: {"req": 160, "reward_text": "💰 Мешок искателя (250💰 и 100 XP)", "gold": 250, "xp": 100},
    6: {"req": 220, "reward_text": "✨ Свиток Ученика (+5% к XP)", "xp_boost_percent": 5},
    7: {"req": 290, "reward_text": "🛡️ Стальной нагрудник (+25 к макс. HP ❤️)", "hp_boost": 25},
    8: {"req": 370, "reward_text": "⚔️ Топор Воина (+7 к урону ⚔️)", "dmg_boost": 7},
    9: {"req": 460, "reward_text": "💥 Амулет Везения (+3% к шансу крита 💥)", "crit_chance_boost": 3},
    10: {"req": 560, "reward_text": "💰 Амулет Торговца (+5% к золоту)", "gold_boost_percent": 5},
    11: {"req": 670, "reward_text": "👑 Золотой ларец (350💰 и 150 XP)", "gold": 350, "xp": 150},
    12: {"req": 790, "reward_text": "🛡️ Щит Защитника (+10 к Защите 🛡️)", "defense_boost": 10},
    13: {"req": 920, "reward_text": "✨ Фолиант Мудрости (+10% к XP)", "xp_boost_percent": 10},
    14: {"req": 1060, "reward_text": "💥 Кольцо Крита (+5% к шансу крита 💥)", "crit_chance_boost": 5},
    15: {"req": 1210, "reward_text": "⚔️ Двуручный меч (+12 к урону ⚔️)", "dmg_boost": 12},
    16: {"req": 1370, "reward_text": "💰 Алмазный слиток (+10% к золоту)", "gold_boost_percent": 10},
    17: {"req": 1540, "reward_text": "🛡️ Латы Героя (+50 к макс. HP ❤️)", "hp_boost": 50},
    18: {"req": 1720, "reward_text": "💥 Легендарный амулет (+7% к шансу крита 💥)", "crit_chance_boost": 7},
    19: {"req": 1910, "reward_text": "⚔️ Клинок Разрушителя (+20 к урону ⚔️)", "dmg_boost": 20},
    20: {"req": 2110, "reward_text": "🏆 Мастер БП! (1500💰, 500 XP и +25 к Защите 🛡️!)", 
        "gold": 1500, "xp": 500, "defense_boost": 25},
    
    21: {"req": 2320, "reward_text": "📦 Серебряный ларец (300💰, 120 XP)", "gold": 300, "xp": 120},
    22: {"req": 2540, "reward_text": "🛡️ Щит Отваги (+20 к макс. HP ❤️)", "hp_boost": 20},
    23: {"req": 2770, "reward_text": "⚔️ Острый кинжал (+6 к урону ⚔️)", "dmg_boost": 6},
    24: {"req": 3010, "reward_text": "✨ Древний свиток (+7% к XP)", "xp_boost_percent": 7},
    25: {"req": 3260, "reward_text": "💰 Кошелек удачи (+7% к золоту)", "gold_boost_percent": 7},
    26: {"req": 3520, "reward_text": "💥 Обсидиановый амулет (+4% к шансу крита 💥)", "crit_chance_boost": 4},
    27: {"req": 3790, "reward_text": "🛡️ Наручи Силы (+15 к Защите 🛡️)", "defense_boost": 15},
    28: {"req": 4070, "reward_text": "⚔️ Громовой топор (+10 к урону ⚔️)", "dmg_boost": 10},
    29: {"req": 4360, "reward_text": "📦 Золотой сундук (500💰, 200 XP)", "gold": 500, "xp": 200},
    30: {"req": 4660, "reward_text": "🛡️ Шлем Героя (+30 к макс. HP ❤️)", "hp_boost": 30},
    31: {"req": 4970, "reward_text": "✨ Великий фолиант (+12% к XP)", "xp_boost_percent": 12},
    32: {"req": 5290, "reward_text": "💥 Талисман Ярости (+6% к шансу крита 💥)", "crit_chance_boost": 6},
    33: {"req": 5620, "reward_text": "💰 Сумка богача (+12% к золоту)", "gold_boost_percent": 12},
    34: {"req": 5960, "reward_text": "⚔️ Меч Ассасина (+15 к урону ⚔️)", "dmg_boost": 15},
    35: {"req": 6310, "reward_text": "🛡️ Тяжелые латы (+20 к Защите 🛡️)", "defense_boost": 20},
    36: {"req": 6670, "reward_text": "📦 Алмазный ларец (750💰, 300 XP)", "gold": 750, "xp": 300},
    37: {"req": 7040, "reward_text": "✨ Эликсир Знаний (+15% к XP)", "xp_boost_percent": 15},
    38: {"req": 7420, "reward_text": "💥 Рунический камень (+8% к шансу крита 💥)", "crit_chance_boost": 8},
    39: {"req": 7810, "reward_text": "💰 Корона Изобилия (+15% к золоту)", "gold_boost_percent": 15},
    40: {"req": 8210, "reward_text": "⚔️ Коса Смерти (+25 к урону ⚔️)", "dmg_boost": 25},
    41: {"req": 8620, "reward_text": "🛡️ Доспехи Титана (+75 к макс. HP ❤️)", "hp_boost": 75},
    42: {"req": 9040, "reward_text": "💥 Глаз Дракона (+10% к шансу крита 💥)", "crit_chance_boost": 10},
    43: {"req": 9470, "reward_text": "✨ Сердце Феникса (+20% к XP)", "xp_boost_percent": 20},
    44: {"req": 9910, "reward_text": "💰 Рог Единорога (+20% к золоту)", "gold_boost_percent": 20},
    45: {"req": 10360, "reward_text": "⚔️ Легендарный меч (+30 к урону ⚔️)", "dmg_boost": 30},
    46: {"req": 10820, "reward_text": "🛡️ Плащ Неуязвимости (+30 к Защите 🛡️)", "defense_boost": 30},
    47: {"req": 11290, "reward_text": "📦 Сундук Пандоры (1000💰, 400 XP)", "gold": 1000, "xp": 400},
    48: {"req": 11770, "reward_text": "✨ Драконья кровь (+25% к XP)", "xp_boost_percent": 25},
    49: {"req": 12260, "reward_text": "💥 Искра Вечности (+12% к шансу крита 💥)", "crit_chance_boost": 12},
    50: {"req": 12760, "reward_text": "💰 Золотое Руно (+25% к золоту)", "gold_boost_percent": 25},
    51: {"req": 13270, "reward_text": "⚔️ Разрушитель Миров (+40 к урону ⚔️)", "dmg_boost": 40},
    52: {"req": 13790, "reward_text": "🛡️ Аспект Бессмертия (+100 к макс. HP ❤️)", "hp_boost": 100},
    53: {"req": 14320, "reward_text": "✨ Эссенция Богов (+30% к XP)", "xp_boost_percent": 30},
    54: {"req": 14860, "reward_text": "💥 Сердце Хаоса (+15% к шансу крита 💥)", "crit_chance_boost": 15},
    55: {"req": 15410, "reward_text": "💰 Сокровище Веков (+30% к золоту)", "gold_boost_percent": 30},
    56: {"req": 15970, "reward_text": "⚔️ Меч Правосудия (+50 к урону ⚔️)", "dmg_boost": 50},
    57: {"req": 16540, "reward_text": "🛡️ Доспех Сверхновой (+40 к Защите 🛡️)", "defense_boost": 40},
    58: {"req": 17120, "reward_text": "📦 Божественный Сундук (2000💰, 1000 XP)", "gold": 2000, "xp": 1000},
    59: {"req": 17710, "reward_text": "✨ Звездная Пыль (+50% к XP)", "xp_boost_percent": 50},
    60: {"req": 18310, "reward_text": "👑 Абсолютный Мастер БП! (5000💰, 2000 XP, +75 к макс. HP ❤️, +50 к урону ⚔️, +20 к Защите 🛡️!)", 
        "gold": 5000, "xp": 2000, "hp_boost": 75, "dmg_boost": 50, "defense_boost": 20}
}

# ================= НАСТРОЙКА МАГАЗИНА =================
SHOP_ITEMS = {
    "minor_hp_potion": {
        "name": "Малое зелье здоровья", "description": "+25 HP", 
        "price": 20, "sell_price": 10, "type": "consumable", "effect": {"hp_restore": 25}
    },
    "wooden_sword": {
        "name": "Деревянный меч", "description": "+5 урона", 
        "price": 50, "sell_price": 25, "type": "weapon", "effect": {"dmg_bonus": 5}
    },
    "leather_armor": {
        "name": "Кожаная броня", "description": "+20 макс. HP, +3 защита", 
        "price": 80, "sell_price": 40, "type": "armor", "effect": {"hp_boost": 20, "defense_boost": 3}
    },
    "sharp_knife": {
        "name": "Острый нож", "description": "+2% шанс крита",
        "price": 120, "sell_price": 60, "type": "misc", "effect": {"crit_chance_boost": 2}
    },
    "gold_amulet": {
        "name": "Золотой амулет", "description": "+5% к золоту",
        "price": 150, "sell_price": 75, "type": "misc", "effect": {"gold_boost_percent": 5}
    },
    "iron_sword": {
        "name": "Железный меч", "description": "+10 урона",
        "price": 180, "sell_price": 90, "type": "weapon", "effect": {"dmg_bonus": 10}
    },
    "plate_armor": {
        "name": "Латы", "description": "+40 макс. HP, +7 защита",
        "price": 250, "sell_price": 125, "type": "armor", "effect": {"hp_boost": 40, "defense_boost": 7}
    }
}

# ================= НАСТРОЙКА БОССОВ =================
BOSSES = {
    "giant_spider": {
        "name": "Гигантский Паук", "hp": 300, "dmg": 40, "defense": 10, 
        "gold": 200, "xp": 150, "bp_xp": 50, 
        "item_drop_chance": 30, # 30% шанс на выпадение предмета
        "item_pool": ["spider_fang_amulet"], # Пул предметов, которые может выбить босс
        "level_req": 5 # Минимальный уровень для встречи
    },
    "minotaur": {
        "name": "Минотавр", "hp": 600, "dmg": 70, "defense": 25, 
        "gold": 500, "xp": 300, "bp_xp": 100,
        "item_drop_chance": 40,
        "item_pool": ["minotaur_axe", "minotaur_horn_helmet"],
        "level_req": 10
    },
    "skeleton_king": {
        "name": "Король Скелетов", "hp": 1200, "dmg": 100, "defense": 40, 
        "gold": 1000, "xp": 600, "bp_xp": 200,
        "item_drop_chance": 50,
        "item_pool": ["skeleton_king_sword", "lich_amulet"],
        "level_req": 15
    }
}

BOSS_COOLDOWN_SECONDS = 3600 # 1 час = 3600 секунд
BOSS_FIGHT_COST = 50 # Золото за попытку боя с боссом

# Новые уникальные предметы для Боссов (добавляем их к SHOP_ITEMS, но они не будут продаваться в магазине)
SHOP_ITEMS["spider_fang_amulet"] = {
    "name": "Амулет Клыка Паука", "description": "+5% шанс крита", 
    "price": -1, "sell_price": 150, "type": "misc", "effect": {"crit_chance_boost": 5}
}
SHOP_ITEMS["minotaur_axe"] = {
    "name": "Топор Минотавра", "description": "+15 урона", 
    "price": -1, "sell_price": 400, "type": "weapon", "effect": {"dmg_bonus": 15}
}
SHOP_ITEMS["minotaur_horn_helmet"] = {
    "name": "Шлем с Рогами Минотавра", "description": "+50 макс. HP, +10 защита", 
    "price": -1, "sell_price": 300, "type": "armor", "effect": {"hp_boost": 50, "defense_boost": 10}
}
SHOP_ITEMS["skeleton_king_sword"] = {
    "name": "Меч Короля Скелетов", "description": "+25 урона, +7% шанс крита", 
    "price": -1, "sell_price": 1000, "type": "weapon", "effect": {"dmg_bonus": 25, "crit_chance_boost": 7}
}
SHOP_ITEMS["lich_amulet"] = {
    "name": "Амулет Лича", "description": "+15% к XP и золоту", 
    "price": -1, "sell_price": 750, "type": "misc", "effect": {"xp_boost_percent": 15, "gold_boost_percent": 15}
}


def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_fight = types.KeyboardButton("⚔️ В бой!")
    btn_heal = types.KeyboardButton("🏕️ Отдохнуть (10💰)")
    btn_stats = types.KeyboardButton("📊 Мой профиль")
    btn_bp = types.KeyboardButton("🎫 Батл Пасс")
    btn_shop = types.KeyboardButton("🛒 Магазин")
    btn_boss = types.KeyboardButton("💀 Босс!") # Новая кнопка для босса
    
    markup.add(btn_fight, btn_heal)
    markup.add(btn_stats, btn_bp)
    markup.add(btn_shop, btn_boss) # Добавили кнопку босса
    return markup

def shop_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Купить предметы", callback_data="shop_buy_menu"),
        types.InlineKeyboardButton("Продать предметы", callback_data="shop_sell_menu")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_main")
    )
    return markup

@bot.message_handler(commands=["start"])
def start_game(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    get_player(user_id, username)

    welcome_text = (
        f"Приветствуем тебя в мире приключений, {username}!\n\n"
        "Сражайся с монстрами, копи золото и открывай **60 уровней Батл Пасса**! 🎫\n"
        "Изучай **Магазин** 🛒 для покупки снаряжения и зелий!\n"
        "Готов к великим испытаниям? Попробуй бросить вызов **Боссам**! 💀\n\n"
        "Все твои сохранения теперь надежно записаны в базу данных!"
    )
    bot.send_message(
        message.chat.id, welcome_text, reply_markup=main_keyboard(), parse_mode="Markdown"
    )

# ================= ОСНОВНОЙ ЦИКЛ ИГРЫ =================
@bot.message_handler(content_types=["text"])
def game_loop(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    player = get_player(user_id, username)

    # --- КНОПКА: СТАТИСТИКА ---
    if message.text == "📊 Мой профиль":
        min_dmg = 15 + (player["level"] * 3) + player["dmg_bonus"]
        max_dmg = 25 + (player["level"] * 3) + player["dmg_bonus"]

        stats_text = (
            f"👤 *Герой:* {player['name']}\n"
            f"🏅 *Уровень:* {player['level']} ({player['xp']}/{(player['level']*50)} XP)\n"
            f"❤️ *Здоровье:* {player['hp']}/{player['max_hp']}\n"
            f"⚔️ *Сила атаки:* {min_dmg}-{max_dmg} " + (f"(+{player['dmg_bonus']} ⚔️)" if player['dmg_bonus'] > 0 else "") + "\n"
            f"🛡️ *Защита:* +{player['defense']} " + (f"(урон снижен на {player['defense']})" if player['defense'] > 0 else "") + "\n"
            f"💥 *Шанс крита:* {player['crit_chance']}% \n"
            f"💰 *Золото:* {player['gold']} " + (f"(+{player['gold_boost_percent']}%)" if player['gold_boost_percent'] > 0 else "") + "\n"
            f"🌟 *Очки БП:* {player['bp_xp']} " + (f"(+{player['xp_boost_percent']}% к XP)" if player['xp_boost_percent'] > 0 else "") + "\n"
            f"💀 *Побеждено монстров:* {player['kills']}\n\n"
            f"🎒 *Инвентарь:* " + (", ".join([SHOP_ITEMS[item]["name"] for item in player["inventory"]]) if player["inventory"] else "Пусто")
        )
        bot.send_message(
            message.chat.id,
            stats_text,
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )

    # --- КНОПКА: ОТДЫХ ---
    elif message.text == "🏕️ Отдохнуть (10💰)":
        if player["hp"] >= player["max_hp"]:
            bot.send_message(
                message.chat.id, "Вы полностью здоровы!", reply_markup=main_keyboard()
            )
        elif player["gold"] < 10:
            bot.send_message(
                message.chat.id,
                "У вас недостаточно золота! Нужно 10💰.",
                reply_markup=main_keyboard(),
            )
        else:
            player["gold"] -= 10
            player["hp"] = player["max_hp"]
            save_player(player)
            bot.send_message(
                message.chat.id,
                "Вы отдохнули у костра. Здоровье восстановлено! (-10💰)",
                reply_markup=main_keyboard(),
            )

    # --- КНОПКА: БАТЛ ПАСС ---
    elif message.text == "🎫 Батл Пасс":
        text = "🎫 *БОЕВОЙ ПРОПУСК (БАТЛ ПАСС)* 🎫\n\n"
        text += f"Ваш прогресс: *{player['bp_xp']}* 🌟\n\n"
        text += "🎁 *Сетка наград (60 Уровней):*\n"
        
        inline_markup = types.InlineKeyboardMarkup()
        
        for tier, data in BP_TIERS.items():
            if tier in player["bp_claimed"]:
                status = "✅ Забрано"
            elif player["bp_xp"] >= data["req"]:
                status = "🎁 Доступно!"
                btn = types.InlineKeyboardButton(
                    text=f"Получить Уровень {tier}", 
                    callback_data=f"claim_bp_{tier}"
                )
                inline_markup.add(btn)
            else:
                status = f"🔒 Закрыто (нужно {data['req']} 🌟)"
                
            text += f"• *Ур. {tier}*: {data['reward_text']} — {status}\n"
            
        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=inline_markup
        )

    # --- КНОПКА: МАГАЗИН ---
    elif message.text == "🛒 Магазин":
        bot.send_message(
            message.chat.id,
            "Добро пожаловать в лавку! Что вы желаете приобрести или продать?",
            reply_markup=shop_keyboard()
        )

    # --- КНОПКА: В БОЙ! (с обычными монстрами) ---
    elif message.text == "⚔️ В бой!":
        if player["hp"] <= 0:
            bot.send_message(
                message.chat.id,
                "Вы мертвы! Восстановите силы у костра 🏕️.",
                reply_markup=main_keyboard(),
            )
            return

        monsters = [
            {"name": "Слизень", "hp": 20, "dmg": 5, "defense": 0, "gold": 8, "xp": 15, "bp_xp": 10},
            {"name": "Гоблин", "hp": 40, "dmg": 12, "defense": 0, "gold": 15, "xp": 25, "bp_xp": 10},
            {"name": "Орк", "hp": 70, "dmg": 20, "defense": 5, "gold": 35, "xp": 50, "bp_xp": 15},
            {"name": "Дракон", "hp": 120, "dmg": 35, "defense": 10, "gold": 80, "xp": 100, "bp_xp": 20},
            {"name": "Лич", "hp": 180, "dmg": 50, "defense": 15, "gold": 120, "xp": 180, "bp_xp": 30},
            {"name": "Титан", "hp": 250, "dmg": 70, "defense": 20, "gold": 200, "xp": 250, "bp_xp": 40}
        ]
        
        available_monsters = []
        if player["level"] < 3:
            available_monsters = monsters[:2] 
        elif player["level"] < 6:
            available_monsters = monsters[:3] 
        elif player["level"] < 10:
            available_monsters = monsters[:4] 
        elif player["level"] < 15:
            available_monsters = monsters[:5] 
        else:
            available_monsters = monsters    
            
        monster = random.choice(available_monsters)

        bot.send_message(
            message.chat.id,
            f"⚔️ Вы встретили врага: *{monster['name']}* (HP: {monster['hp']}, DMG: {monster['dmg']})!",
            parse_mode="Markdown",
        )

        base_player_damage = random.randint(15, 25) + (player["level"] * 3) + player["dmg_bonus"]
        
        is_crit = False
        if random.randint(1, 100) <= player["crit_chance"]:
            base_player_damage *= 2
            is_crit = True

        monster_damage = random.randint(5, monster["dmg"])
        actual_monster_damage = max(1, monster_damage - player["defense"]) # Защита игрока снижает урон
        
        actual_monster_hp = monster["hp"]
        actual_player_damage_to_monster = max(1, base_player_damage - monster["defense"]) # Защита монстра снижает урон игрока

        # --- Симуляция быстрого боя (несколько раундов до победы/поражения) ---
        battle_log_rounds = []
        while player["hp"] > 0 and actual_monster_hp > 0:
            # Игрок атакует
            actual_monster_hp -= actual_player_damage_to_monster
            # Монстр атакует
            player["hp"] -= actual_monster_damage
        
        if player["hp"] < 0:
            player["hp"] = 0
        if actual_monster_hp < 0:
            actual_monster_hp = 0

        if player["hp"] > 0: # Игрок победил
            gold_gain = int(monster["gold"] * (1 + player["gold_boost_percent"] / 100))
            xp_gain = int(monster["xp"] * (1 + player["xp_boost_percent"] / 100))
            bp_xp_gain = monster["bp_xp"]
            
            player["gold"] += gold_gain
            player["xp"] += xp_gain
            player["kills"] += 1
            player["bp_xp"] += bp_xp_gain

            battle_log = (
                f"Вы нанесли {int(base_player_damage)} урона " + ("💥*КРИТ!* " if is_crit else "") + f"и одолели *{monster['name']}*!\n"
                f"Получено урона: {actual_monster_damage} ❤️ " + (f"(снижено вашей защитой на {monster_damage - actual_monster_damage})" if monster_damage > actual_monster_damage else "") + "\n"
                f"Награда: +{gold_gain}💰, +{xp_gain} XP и **+{bp_xp_gain} очков БП 🌟**!\n"
                f"Ваше здоровье: {player['hp']}/{player['max_hp']}"
            )

            xp_needed = player["level"] * 50
            if player["xp"] >= xp_needed:
                player["level"] += 1
                player["xp"] -= xp_needed
                player["max_hp"] += 20
                player["hp"] = player["max_hp"]
                battle_log += f"\n\n🎉 **УРОВЕНЬ ПОВЫШЕН!** Вы достигли {player['level']} уровня! Макс. HP увеличено!"

        else: # Игрок проиграл
            player["gold"] = max(0, player["gold"] - 15)
            battle_log = (
                f"💀 *{monster['name']}* оказался сильнее и одолел вас!\n"
                f"Вы потеряли 15💰. Отдохните, чтобы восстановиться."
            )

        save_player(player)
        
        bot.send_message(
            message.chat.id,
            battle_log,
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )

    # --- КНОПКА: БОСС! ---
    elif message.text == "💀 Босс!":
        if player["hp"] <= 0:
            bot.send_message(message.chat.id, "Вы слишком слабы! Восстановите силы у костра 🏕️.", reply_markup=main_keyboard())
            return
        
        if player["gold"] < BOSS_FIGHT_COST:
            bot.send_message(message.chat.id, f"У вас недостаточно золота для боя с боссом! Нужно {BOSS_FIGHT_COST}💰.", reply_markup=main_keyboard())
            return

        time_since_last_boss_fight = time.time() - player["last_boss_fight_timestamp"]
        if time_since_last_boss_fight < BOSS_COOLDOWN_SECONDS:
            remaining_time = int(BOSS_COOLDOWN_SECONDS - time_since_last_boss_fight)
            minutes = remaining_time // 60
            seconds = remaining_time % 60
            bot.send_message(message.chat.id, f"Босс еще не восстановился! Попробуйте через {minutes} мин. {seconds} сек.", reply_markup=main_keyboard())
            return

        # Выбираем босса в зависимости от уровня игрока
        available_bosses = [b for k, b in BOSSES.items() if player["level"] >= b["level_req"]]
        if not available_bosses:
            bot.send_message(message.chat.id, "Вы пока слишком слабы, чтобы сражаться с боссами. Поднимите свой уровень!", reply_markup=main_keyboard())
            return

        boss = random.choice(available_bosses)
        player["gold"] -= BOSS_FIGHT_COST # Отнимаем золото за попытку
        player["last_boss_fight_timestamp"] = int(time.time()) # Обновляем время последнего боя

        bot.send_message(
            message.chat.id,
            f"💀 Вы вступили в битву с *{boss['name']}* (HP: {boss['hp']}, DMG: {boss['dmg']}, DEF: {boss['defense']})! (-{BOSS_FIGHT_COST}💰)",
            parse_mode="Markdown",
        )

        # --- Симуляция боя с боссом ---
        boss_hp = boss["hp"]
        
        boss_battle_log = []
        while player["hp"] > 0 and boss_hp > 0:
            # Игрок атакует
            player_hit_damage = random.randint(15, 25) + (player["level"] * 3) + player["dmg_bonus"]
            if random.randint(1, 100) <= player["crit_chance"]:
                player_hit_damage *= 2
                boss_battle_log.append(f"Вы нанесли {int(player_hit_damage)} урона (💥КРИТ!) *{boss['name']}*.")
            else:
                boss_battle_log.append(f"Вы нанесли {int(player_hit_damage)} урона *{boss['name']}*.")
            boss_hp -= max(1, player_hit_damage - boss["defense"])

            if boss_hp <= 0: break # Босс побежден

            # Босс атакует
            boss_hit_damage = random.randint(10, boss["dmg"])
            actual_boss_damage = max(1, boss_hit_damage - player["defense"])
            player["hp"] -= actual_boss_damage
            boss_battle_log.append(f"*{boss['name']}* нанес вам {actual_boss_damage} урона.")
            
        if player["hp"] < 0: player["hp"] = 0

        final_message = "\n".join(boss_battle_log[-5:]) # Последние 5 событий боя
        
        if player["hp"] > 0: # Игрок победил босса
            gold_gain = int(boss["gold"] * (1 + player["gold_boost_percent"] / 100))
            xp_gain = int(boss["xp"] * (1 + player["xp_boost_percent"] / 100))
            bp_xp_gain = boss["bp_xp"]

            player["gold"] += gold_gain
            player["xp"] += xp_gain
            player["kills"] += 1
            player["bp_xp"] += bp_xp_gain

            final_message += (
                f"\n\n🎉 Вы победили *{boss['name']}*!\n"
                f"Награда: +{gold_gain}💰, +{xp_gain} XP и **+{bp_xp_gain} очков БП 🌟**!\n"
                f"Ваше здоровье: {player['hp']}/{player['max_hp']}"
            )
            
            # Шанс выпадения уникального предмета
            if random.randint(1, 100) <= boss["item_drop_chance"] and boss["item_pool"]:
                dropped_item_key = random.choice(boss["item_pool"])
                player["inventory"].append(dropped_item_key)
                apply_item_effects(player, dropped_item_key) # Применяем эффекты сразу
                final_message += f"\n🔥 Вы получили уникальный предмет: *{SHOP_ITEMS[dropped_item_key]['name']}*! Его эффекты применены."

            # Левелап
            xp_needed = player["level"] * 50
            if player["xp"] >= xp_needed:
                player["level"] += 1
                player["xp"] -= xp_needed
                player["max_hp"] += 20
                player["hp"] = player["max_hp"]
                final_message += f"\n\n🎉 **УРОВЕНЬ ПОВЫШЕН!** Вы достигли {player['level']} уровня! Макс. HP увеличено!"

        else: # Игрок проиграл боссу
            player["gold"] = max(0, player["gold"] - 50) # Штраф за поражение от босса
            final_message += (
                f"\n\n💀 *{boss['name']}* оказался слишком силен и одолел вас!\n"
                f"Вы потеряли 50💰. Отдохните, чтобы восстановиться."
            )
            
        save_player(player)

        bot.send_message(
            message.chat.id,
            final_message,
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )


# ================= АДМИН-КОМАНДЫ =================
@bot.message_handler(commands=['admin'], func=is_admin)
def admin_panel(message):
    admin_commands = (
        "🤖 *Панель Администратора*\n\n"
        "Доступные команды:\n"
        "/getstats `<user_id>` - Просмотр профиля игрока\n"
        "/setgold `<user_id>` `<amount>` - Установить золото\n"
        "/setxp `<user_id>` `<amount>` - Установить опыт\n"
        "/setlevel `<user_id>` `<amount>` - Установить уровень\n"
        "/sethp `<user_id>` `<amount>` - Установить текущее здоровье\n"
        "/setmaxhp `<user_id>` `<amount>` - Установить максимальное здоровье\n"
        "/setbp_xp `<user_id>` `<amount>` - Установить очки БП\n"
        "/setdmg_bonus `<user_id>` `<amount>` - Установить бонус к урону\n"
        "/setcrit_chance `<user_id>` `<amount>` - Установить шанс крита\n"
        "/setdefense `<user_id>` `<amount>` - Установить защиту\n"
        "/setgold_boost `<user_id>` `<amount>` - Установить бонус к золоту (%%)\n"
        "/setxp_boost `<user_id>` `<amount>` - Установить бонус к опыту (%%)\n"
        "/additem `<user_id>` `<item_key>` - Добавить предмет в инвентарь\n"
        "/removeitem `<user_id>` `<item_key>` - Удалить предмет из инвентаря\n"
        "/resetplayer `<user_id>` - Полностью сбросить игрока\n"
        "/resetboss_cooldown `<user_id>` - Сбросить кулдаун босса (для тестов)\n" # Новая админ-команда
        "/broadcast `<сообщение>` - Отправить сообщение всем игрокам"
    )
    bot.send_message(message.chat.id, admin_commands, parse_mode="Markdown")

@bot.message_handler(commands=['getstats'], func=is_admin)
def admin_get_stats(message):
    target_user_id, _, command = parse_admin_args(message.text, num_args=1)
    if not target_user_id:
        bot.reply_to(message, "Неверный формат команды. Используйте: /getstats <user_id>")
        return

    target_player = get_player(target_user_id, "Админ_цель")
    if not target_player:
        bot.reply_to(message, f"Игрок с ID {target_user_id} не найден.")
        return

    min_dmg = 15 + (target_player["level"] * 3) + target_player["dmg_bonus"]
    max_dmg = 25 + (target_player["level"] * 3) + target_player["dmg_bonus"]

    stats = (
        f"👤 *Игрок:* {target_player['name']} (ID: {target_player['user_id']})\n"
        f"🏅 *Уровень:* {target_player['level']} ({target_player['xp']}/{(target_player['level']*50)} XP)\n"
        f"❤️ *Здоровье:* {target_player['hp']}/{target_player['max_hp']}\n"
        f"⚔️ *Сила атаки:* {min_dmg}-{max_dmg} (+{target_player['dmg_bonus']} ⚔️)\n"
        f"🛡️ *Защита:* +{target_player['defense']} \n"
        f"💥 *Шанс крита:* {target_player['crit_chance']}% \n"
        f"💰 *Золото:* {target_player['gold']} (+{target_player['gold_boost_percent']}%) \n"
        f"🌟 *Очки БП:* {target_player['bp_xp']} (+{target_player['xp_boost_percent']}% к XP)\n"
        f"💀 *Побеждено монстров:* {target_player['kills']}\n"
        f"🎫 *БП Забрано:* {target_player['bp_claimed']}\n"
        f"🎒 *Инвентарь:* " + (", ".join([SHOP_ITEMS[item]["name"] for item in target_player["inventory"]]) if target_player["inventory"] else "Пусто") + "\n"
        f"⏳ *Босс кулдаун:* {time.time() - target_player['last_boss_fight_timestamp']:.0f} / {BOSS_COOLDOWN_SECONDS} сек."
    )
    bot.send_message(message.chat.id, stats, parse_mode="Markdown")

@bot.message_handler(func=lambda message: is_admin(message) and message.text.startswith((
    '/setgold', '/setxp', '/setlevel', '/sethp', '/setmaxhp', '/setbp_xp', 
    '/setdmg_bonus', '/setcrit_chance', '/setdefense', '/setgold_boost', '/setxp_boost'
)))
def admin_set_stat(message):
    target_user_id, value_str, command = parse_admin_args(message.text, num_args=2)
    
    if not target_user_id or value_str is None:
        bot.reply_to(message, "Неверный формат команды. Используйте: /команда <user_id> <значение>")
        return

    try:
        value = int(value_str)
    except ValueError:
        bot.reply_to(message, "Значение должно быть числом.")
        return

    target_player = get_player(target_user_id, "Админ_цель")
    if not target_player:
        bot.reply_to(message, f"Игрок с ID {target_user_id} не найден.")
        return

    stat_map = {
        '/setgold': 'gold',
        '/setxp': 'xp',
        '/setlevel': 'level',
        '/sethp': 'hp',
        '/setmaxhp': 'max_hp',
        '/setbp_xp': 'bp_xp',
        '/setdmg_bonus': 'dmg_bonus',
        '/setcrit_chance': 'crit_chance',
        '/setdefense': 'defense',
        '/setgold_boost': 'gold_boost_percent',
        '/setxp_boost': 'xp_boost_percent'
    }
    stat_name = stat_map.get(command)

    if stat_name:
        if stat_name == 'level':
            target_player['level'] = max(1, value)
            target_player['max_hp'] = 100 + (target_player['level'] - 1) * 20
            target_player['hp'] = target_player['max_hp']
        elif stat_name == 'hp':
            target_player['hp'] = min(value, target_player['max_hp'])
            target_player['hp'] = max(0, target_player['hp'])
        elif stat_name == 'max_hp':
            target_player['max_hp'] = max(1, value)
            if target_player['hp'] > target_player['max_hp']:
                target_player['hp'] = target_player['max_hp']
        elif stat_name in ['crit_chance', 'defense', 'gold_boost_percent', 'xp_boost_percent']:
            target_player[stat_name] = max(0, value)
        else:
            target_player[stat_name] = value

        save_player(target_player)
        bot.reply_to(message, f"Значение '{stat_name}' для игрока {target_player['name']} (ID: {target_user_id}) установлено на {value}.")
        try:
            bot.send_message(target_user_id, f"⚡️ Администратор изменил ваш *{stat_name}* на *{value}*!", parse_mode="Markdown")
        except Exception as e:
            print(f"Не удалось уведомить игрока {target_user_id}: {e}")
    else:
        bot.reply_to(message, "Неизвестная команда или некорректная характеристика.")

@bot.message_handler(commands=['additem'], func=is_admin)
def admin_add_item(message):
    target_user_id, item_key, command = parse_admin_args(message.text, num_args=2)
    if not target_user_id or not item_key:
        bot.reply_to(message, "Неверный формат команды. Используйте: /additem <user_id> <item_key>")
        return
    
    if item_key not in SHOP_ITEMS:
        bot.reply_to(message, f"Предмет с ключом '{item_key}' не найден в магазине.")
        return

    target_player = get_player(target_user_id, "Админ_цель")
    if not target_player:
        bot.reply_to(message, f"Игрок с ID {target_user_id} не найден.")
        return

    target_player["inventory"].append(item_key)
    # Применяем эффекты предмета, если это не расходник
    if SHOP_ITEMS[item_key].get("type") != "consumable":
        apply_item_effects(target_player, item_key)
    
    save_player(target_player)
    bot.reply_to(message, f"Предмет '{SHOP_ITEMS[item_key]['name']}' добавлен в инвентарь игрока {target_user_id}.")
    try:
        bot.send_message(target_user_id, f"⚡️ Администратор добавил вам в инвентарь: *{SHOP_ITEMS[item_key]['name']}*!", parse_mode="Markdown")
    except Exception as e:
        print(f"Не удалось уведомить игрока {target_user_id}: {e}")

@bot.message_handler(commands=['removeitem'], func=is_admin)
def admin_remove_item(message):
    target_user_id, item_key, command = parse_admin_args(message.text, num_args=2)
    if not target_user_id or not item_key:
        bot.reply_to(message, "Неверный формат команды. Используйте: /removeitem <user_id> <item_key>")
        return
    
    target_player = get_player(target_user_id, "Админ_цель")
    if not target_player:
        bot.reply_to(message, f"Игрок с ID {target_user_id} не найден.")
        return

    if item_key in target_player["inventory"]:
        target_player["inventory"].remove(item_key)
        # Снимаем эффекты предмета при продаже
        remove_item_effects(target_player, item_key)
        
        save_player(target_player)
        bot.reply_to(message, f"Предмет '{SHOP_ITEMS.get(item_key, {'name':item_key})['name']}' удален из инвентаря игрока {target_user_id}.")
        try:
            bot.send_message(target_user_id, f"⚡️ Администратор удалил у вас из инвентаря: *{SHOP_ITEMS.get(item_key, {'name':item_key})['name']}*!", parse_mode="Markdown")
        except Exception as e:
            print(f"Не удалось уведомить игрока {target_user_id}: {e}")
    else:
        bot.reply_to(message, f"Предмет '{item_key}' не найден в инвентаре игрока {target_user_id}.")

@bot.message_handler(commands=['resetplayer'], func=is_admin)
def admin_reset_player(message):
    target_user_id, _, command = parse_admin_args(message.text, num_args=1)
    if not target_user_id:
        bot.reply_to(message, "Неверный формат команды. Используйте: /resetplayer <user_id>")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    if IS_POSTGRES:
        cur.execute("DELETE FROM players WHERE user_id = %s", (target_user_id,))
    else:
        cur.execute("DELETE FROM players WHERE user_id = ?", (target_user_id,))
    conn.commit()
    cur.close()
    conn.close()

    bot.reply_to(message, f"Прогресс игрока с ID {target_user_id} был сброшен.")
    try:
        bot.send_message(target_user_id, "💀 Ваш прогресс был сброшен администратором. Начните игру с /start.")
    except Exception as e:
        print(f"Не удалось уведомить игрока {target_user_id}: {e}")

@bot.message_handler(commands=['resetboss_cooldown'], func=is_admin)
def admin_reset_boss_cooldown(message):
    target_user_id, _, command = parse_admin_args(message.text, num_args=1)
    if not target_user_id:
        bot.reply_to(message, "Неверный формат команды. Используйте: /resetboss_cooldown <user_id>")
        return

    target_player = get_player(target_user_id, "Админ_цель")
    if not target_player:
        bot.reply_to(message, f"Игрок с ID {target_user_id} не найден.")
        return

    target_player["last_boss_fight_timestamp"] = 0 # Сбрасываем таймер
    save_player(target_player)
    bot.reply_to(message, f"Кулдаун босса для игрока {target_user_id} сброшен.")
    try:
        bot.send_message(target_user_id, "⚡️ Администратор сбросил кулдаун на бой с боссом!")
    except Exception as e:
        print(f"Не удалось уведомить игрока {target_user_id}: {e}")


@bot.message_handler(commands=['broadcast'], func=is_admin)
def admin_broadcast(message):
    broadcast_message = message.text.replace("/broadcast ", "", 1)
    if not broadcast_message:
        bot.reply_to(message, "Вы не указали сообщение для рассылки.")
        return

    all_user_ids = get_all_player_ids()
    sent_count = 0
    for user_id in all_user_ids:
        try:
            bot.send_message(user_id, f"📢 *Сообщение от Администратора:*\n{broadcast_message}", parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
    
    bot.reply_to(message, f"Сообщение отправлено {sent_count} игрокам.")


# ================= МАГАЗИН: Функции для покупки/продажи =================
def apply_item_effects(player, item_key):
    item_data = SHOP_ITEMS.get(item_key)
    if not item_data: return

    effects = item_data.get("effect", {})
    if "hp_boost" in effects: player["max_hp"] += effects["hp_boost"]; player["hp"] = player["max_hp"]
    if "dmg_bonus" in effects: player["dmg_bonus"] += effects["dmg_bonus"]
    if "crit_chance_boost" in effects: player["crit_chance"] += effects["crit_chance_boost"]
    if "defense_boost" in effects: player["defense"] += effects["defense_boost"]
    if "gold_boost_percent" in effects: player["gold_boost_percent"] += effects["gold_boost_percent"]
    if "xp_boost_percent" in effects: player["xp_boost_percent"] += effects["xp_boost_percent"]
    if "hp_restore" in effects: player["hp"] = min(player["max_hp"], player["hp"] + effects["hp_restore"])

def remove_item_effects(player, item_key):
    item_data = SHOP_ITEMS.get(item_key)
    if not item_data or item_data.get("type") == "consumable": return

    effects = item_data.get("effect", {})
    if "hp_boost" in effects: player["max_hp"] = max(1, player["max_hp"] - effects["hp_boost"]); 
    if player["hp"] > player["max_hp"]: player["hp"] = player["max_hp"]
    if "dmg_bonus" in effects: player["dmg_bonus"] = max(0, player["dmg_bonus"] - effects["dmg_bonus"])
    if "crit_chance_boost" in effects: player["crit_chance"] = max(0, player["crit_chance"] - effects["crit_chance_boost"])
    if "defense_boost" in effects: player["defense"] = max(0, player["defense"] - effects["defense_boost"])
    if "gold_boost_percent" in effects: player["gold_boost_percent"] = max(0, player["gold_boost_percent"] - effects["gold_boost_percent"])
    if "xp_boost_percent" in effects: player["xp_boost_percent"] = max(0, player["xp_boost_percent"] - effects["xp_boost_percent"])


@bot.callback_query_handler(func=lambda call: call.data.startswith("shop_"))
def shop_callback_handler(call):
    user_id = call.from_user.id
    username = call.from_user.first_name
    player = get_player(user_id, username)
    
    action = call.data.split("_")[1]

    if action == "buy_menu":
        text = "🛒 *Магазин: Покупка предметов*\n\n"
        text += f"Ваше золото: {player['gold']}💰\n\n"
        text += "Доступные товары:\n"
        
        buy_markup = types.InlineKeyboardMarkup(row_width=1)
        for item_key, item_data in SHOP_ITEMS.items():
            # Не показываем предметы, которые даются только с боссов (price = -1)
            if item_data.get("price") == -1: continue 
            
            # Если это не расходник и уже есть в инвентаре, не показываем для покупки
            if item_data.get("type") != "consumable" and item_key in player["inventory"]:
                continue 
            
            text += f"• *{item_data['name']}* ({item_data['description']}) - {item_data['price']}💰\n"
            buy_markup.add(types.InlineKeyboardButton(
                f"Купить {item_data['name']} ({item_data['price']}💰)",
                callback_data=f"shop_buy_item_{item_key}"
            ))
        buy_markup.add(types.InlineKeyboardButton("🔙 В магазин", callback_data="shop_main_menu"))
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=buy_markup
        )
        bot.answer_callback_query(call.id)

    elif action == "sell_menu":
        text = "🛒 *Магазин: Продажа предметов*\n\n"
        text += f"Ваше золото: {player['gold']}💰\n\n"
        
        sell_markup = types.InlineKeyboardMarkup(row_width=1)
        if not player["inventory"]:
            text += "Ваш инвентарь пуст."
        else:
            text += "Предметы в инвентаре:\n"
            item_counts = {}
            for item_key in player["inventory"]:
                item_counts[item_key] = item_counts.get(item_key, 0) + 1
            
            for item_key, count in item_counts.items():
                item_data = SHOP_ITEMS.get(item_key)
                if not item_data: continue
                
                sell_price = item_data["sell_price"]
                text += f"• *{item_data['name']}* (x{count}) - {sell_price}💰/шт\n"
                sell_markup.add(types.InlineKeyboardButton(
                    f"Продать {item_data['name']} (x{count}) ({sell_price * count}💰)",
                    callback_data=f"shop_sell_item_{item_key}"
                ))
        
        sell_markup.add(types.InlineKeyboardButton("🔙 В магазин", callback_data="shop_main_menu"))
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=sell_markup
        )
        bot.answer_callback_query(call.id)

    elif action == "buy_item":
        item_key = call.data.split("_")[3]
        item_data = SHOP_ITEMS.get(item_key)
        
        if not item_data:
            bot.answer_callback_query(call.id, "Предмет не найден.", show_alert=True)
            return

        if player["gold"] < item_data["price"]:
            bot.answer_callback_query(call.id, "Недостаточно золота!", show_alert=True)
            return

        player["gold"] -= item_data["price"]
        
        # Если это расходник, то сразу используем и не добавляем в инвентарь
        if item_data.get("type") == "consumable":
            apply_item_effects(player, item_key)
            save_player(player) # Сохраняем после использования
            bot.answer_callback_query(call.id, f"Вы использовали {item_data['name']}!", show_alert=True)
        else:
            player["inventory"].append(item_key)
            apply_item_effects(player, item_key)
            save_player(player) # Сохраняем после добавления
            bot.answer_callback_query(call.id, f"Вы купили {item_data['name']}!", show_alert=True)
        
        # Обновляем сообщение магазина
        shop_callback_handler(types.CallbackQuery(id=call.id, from_user=call.from_user, message=call.message, data="shop_buy_menu"))

    elif action == "sell_item":
        item_key = call.data.split("_")[3]
        item_data = SHOP_ITEMS.get(item_key)
        
        if not item_data:
            bot.answer_callback_query(call.id, "Предмет не найден.", show_alert=True)
            return

        if item_key not in player["inventory"]:
            bot.answer_callback_query(call.id, "Этого предмета нет в вашем инвентаре.", show_alert=True)
            return

        player["gold"] += item_data["sell_price"]
        player["inventory"].remove(item_key)
        
        # Снимаем эффекты предмета при продаже
        remove_item_effects(player, item_key)
        
        save_player(player)
        bot.answer_callback_query(call.id, f"Вы продали {item_data['name']}!", show_alert=True)

        # Обновляем сообщение магазина
        shop_callback_handler(types.CallbackQuery(id=call.id, from_user=call.from_user, message=call.message, data="shop_sell_menu"))

    elif action == "main_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Добро пожаловать в лавку! Что вы желаете приобрести или продать?",
            reply_markup=shop_keyboard()
        )
        bot.answer_callback_query(call.id)
    
    elif call.data == "back_to_main":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Вы вернулись в главное меню игры.",
            reply_markup=main_keyboard()
        )
        bot.answer_callback_query(call.id)


# --- ОБРАБОТКА НАЖАТИЯ КНОПОК БАТЛ ПАССА ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("claim_bp_"))
def claim_bp_reward(call):
    user_id = call.from_user.id
    username = call.from_user.first_name
    player = get_player(user_id, username)
    
    tier = int(call.data.split("_")[2])
    
    if tier not in BP_TIERS:
        bot.answer_callback_query(call.id, "Ошибка: уровень не найден.")
        return
        
    data = BP_TIERS[tier]
    
    if player["bp_xp"] < data["req"]:
        bot.answer_callback_query(call.id, "У вас недостаточно очков БП!", show_alert=True)
        return
        
    if tier in player["bp_claimed"]:
        bot.answer_callback_query(call.id, "Вы уже получили эту награду!", show_alert=True)
        return
        
    player["bp_claimed"].append(tier)
    
    reward_msg = f"🎉 *Поздравляем!*\nВы получили награду за {tier}-й Уровень БП:\n"
    
    if data.get("gold", 0) > 0:
        player["gold"] += data["gold"]
        reward_msg += f"+{data['gold']}💰 Золота\n"
    if data.get("xp", 0) > 0:
        player["xp"] += data["xp"]
        reward_msg += f"+{data['xp']} XP Опыта\n"
        
    if "hp_boost" in data:
        player["max_hp"] += data["hp_boost"]
        player["hp"] = player["max_hp"]
        reward_msg += f"🛡️ Надето новое снаряжение! Максимальное здоровье увеличено на +{data['hp_boost']} ❤️\n"
        
    if "dmg_boost" in data:
        player["dmg_bonus"] += data["dmg_boost"]
        reward_msg += f"⚔️ Получено новое оружие! Постоянный урон увеличен на +{data['dmg_bonus']} ⚔️\n"

    if "crit_chance_boost" in data:
        player["crit_chance"] += data["crit_chance_boost"]
        reward_msg += f"💥 Получен Амулет! Шанс критического удара увеличен на +{data['crit_chance_boost']}% 💥\n"
        
    if "defense_boost" in data:
        player["defense"] += data["defense_boost"]
        reward_msg += f"🛡️ Усилена защита! Получение урона снижено на +{data['defense_boost']} 🛡️\n"

    if "gold_boost_percent" in data:
        player["gold_boost_percent"] += data["gold_boost_percent"]
        reward_msg += f"💰 Получен Эликсир! Бонус к золоту увеличен на +{data['gold_boost_percent']}% 💰\n"
        
    if "xp_boost_percent" in data:
        player["xp_boost_percent"] += data["xp_boost_percent"]
        reward_msg += f"✨ Получен Свиток! Бонус к опыту увеличен на +{data['xp_boost_percent']}% XP ✨\n"
        
    xp_needed = player["level"] * 50
    if player["xp"] >= xp_needed:
        player["level"] += 1
        player["xp"] -= xp_needed
        player["max_hp"] += 20
        player["hp"] = player["max_hp"]
        reward_msg += f"\n🎉 **УРОВЕНЬ ПОВЫШЕН!** Вы достигли {player['level']} уровня!"

    save_player(player)

    bot.answer_callback_query(call.id, "Награда получена!")
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=reward_msg,
        parse_mode="Markdown"
    )


# ================= ЗАПУСК ПРИЛОЖЕНИЯ =================
if __name__ == "__main__":
    init_db()
    
    print("Запуск веб-сервера для круглосуточного хостинга...")
    keep_alive()
    
    print(f"RPG Бот с админкой, 60 уровнями БП, магазином, БОССАМИ и {('PostgreSQL' if IS_POSTGRES else 'SQLite')} базой данных успешно запущен!")
    bot.polling(none_stop=True)