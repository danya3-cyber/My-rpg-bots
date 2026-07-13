import random
import json
import os
import sqlite3
import telebot
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

# ================= НАСТРОЙКА БАЗЫ ДАННЫХ =================
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = DATABASE_URL is not None and HAS_PSYCOPG2

def get_db_connection():
    """Подключение к Postgres в облаке или к SQLite локально"""
    if IS_POSTGRES:
        #print("Подключение к PostgreSQL...")
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        #print("Подключение к SQLite...")
        return sqlite3.connect("players.db")


def init_db():
    """Создание таблицы игроков и добавление новых колонок, если их нет"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Создаем таблицу, если она не существует
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
            xp_boost_percent INTEGER DEFAULT 0
        );
    """)
    conn.commit()

    # 2. Добавляем новые колонки, если они отсутствуют (для совместимости со старыми базами)
    columns_to_add = {
        "crit_chance": "INTEGER DEFAULT 5",
        "defense": "INTEGER DEFAULT 0",
        "gold_boost_percent": "INTEGER DEFAULT 0",
        "xp_boost_percent": "INTEGER DEFAULT 0"
    }

    if IS_POSTGRES:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='players' AND table_schema='public';")
    else:
        cur.execute("PRAGMA table_info(players);")
    
    existing_columns = [col[0] for col in cur.fetchall()]

    for col_name, col_type in columns_to_add.items():
        if col_name not in existing_columns:
            try:
                # В SQLite не поддерживается ADD COLUMN IF NOT EXISTS, поэтому используем TRY-EXCEPT
                cur.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type};")
                conn.commit()
                print(f"Добавлена колонка: {col_name}")
            except sqlite3.OperationalError as e:
                # Если колонка уже добавлена другим способом или ошибка
                print(f"Ошибка при добавлении колонки {col_name} в SQLite: {e}")
            except psycopg2.ProgrammingError as e:
                # Для Postgres
                if "column already exists" in str(e):
                    print(f"Колонка {col_name} уже существует в PostgreSQL.")
                    conn.rollback() # Откатываем транзакцию, если ошибка
                else:
                    print(f"Ошибка при добавлении колонки {col_name} в PostgreSQL: {e}")
                    conn.rollback()


    cur.close()
    conn.close()
    print("База данных успешно инициализирована/обновлена!")


def get_player(user_id, username):
    """Получение данных игрока или создание нового"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cols = "user_id, name, hp, max_hp, gold, level, xp, kills, bp_xp, bp_claimed, dmg_bonus, crit_chance, defense, gold_boost_percent, xp_boost_percent"
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
            "crit_chance": 5, # Дефолтный шанс крита 5%
            "defense": 0,     # Дефолтная защита
            "gold_boost_percent": 0, # Дефолтный бонус к золоту
            "xp_boost_percent": 0    # Дефолтный бонус к опыту
        }
        
        bp_claimed_str = json.dumps(player["bp_claimed"]) # [] -> "[]"
        
        if IS_POSTGRES:
            cur.execute(f"""
                INSERT INTO players ({cols})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, player["name"], player["hp"], player["max_hp"], player["gold"], 
                  player["level"], player["xp"], player["kills"], player["bp_xp"], 
                  bp_claimed_str, player["dmg_bonus"], player["crit_chance"], 
                  player["defense"], player["gold_boost_percent"], player["xp_boost_percent"]))
        else:
            cur.execute(f"""
                INSERT INTO players ({cols})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, player["name"], player["hp"], player["max_hp"], player["gold"], 
                  player["level"], player["xp"], player["kills"], player["bp_xp"], 
                  bp_claimed_str, player["dmg_bonus"], player["crit_chance"], 
                  player["defense"], player["gold_boost_percent"], player["xp_boost_percent"]))
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
            "xp_boost_percent": row[14]
        }
        
    cur.close()
    conn.close()
    return player


def save_player(player):
    """Сохранение данных конкретного игрока в базу"""
    conn = get_db_connection()
    cur = conn.cursor()
    bp_claimed_str = json.dumps(player["bp_claimed"])
    
    if IS_POSTGRES:
        cur.execute("""
            UPDATE players SET
                name = %s, hp = %s, max_hp = %s, gold = %s, level = %s, 
                xp = %s, kills = %s, bp_xp = %s, bp_claimed = %s, dmg_bonus = %s,
                crit_chance = %s, defense = %s, gold_boost_percent = %s, xp_boost_percent = %s
            WHERE user_id = %s
        """, (
            player["name"], player["hp"], player["max_hp"], player["gold"], player["level"],
            player["xp"], player["kills"], player["bp_xp"], bp_claimed_str, player["dmg_bonus"],
            player["crit_chance"], player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
            player["user_id"]
        ))
    else:
        cur.execute("""
            UPDATE players SET
                name = ?, hp = ?, max_hp = ?, gold = ?, level = ?, 
                xp = ?, kills = ?, bp_xp = ?, bp_claimed = ?, dmg_bonus = ?,
                crit_chance = ?, defense = ?, gold_boost_percent = ?, xp_boost_percent = ?
            WHERE user_id = ?
        """, (
            player["name"], player["hp"], player["max_hp"], player["gold"], player["level"],
            player["xp"], player["kills"], player["bp_xp"], bp_claimed_str, player["dmg_bonus"],
            player["crit_chance"], player["defense"], player["gold_boost_percent"], player["xp_boost_percent"],
            player["user_id"]
        ))
    conn.commit()
    cur.close()
    conn.close()


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


# ================= НАСТРОЙКА ИГРЫ И БП (20 УРОВНЕЙ) =================
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
    20: {"req": 2110, "reward_text": "🏆 Мастер БП! (1500💰, 500 XP и +25 к Защите 🛡️!)", "gold": 1500, "xp": 500, "defense_boost": 25}
}


def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_fight = types.KeyboardButton("⚔️ В бой!")
    btn_heal = types.KeyboardButton("🏕️ Отдохнуть (10💰)")
    btn_stats = types.KeyboardButton("📊 Мой профиль")
    btn_bp = types.KeyboardButton("🎫 Батл Пасс")
    
    markup.add(btn_fight, btn_heal)
    markup.add(btn_stats, btn_bp)
    return markup


@bot.message_handler(commands=["start"])
def start_game(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    get_player(user_id, username)

    welcome_text = (
        f"Приветствуем тебя в мире приключений, {username}!\n\n"
        "Сражайся с монстрами, копи золото и открывай **20 уровней Батл Пасса**! 🎫\n"
        "Тебя ждут новые бонусы к **критическому урону 💥** и **защите 🛡️**.\n\n"
        "Все твои сохранения теперь надежно записаны в базу данных!"
    )
    bot.send_message(
        message.chat.id, welcome_text, reply_markup=main_keyboard(), parse_mode="Markdown"
    )


@bot.message_handler(content_types=["text"])
def game_loop(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    player = get_player(user_id, username)

    # --- КНОПКА: СТАТИСТИКА ---
    if message.text == "📊 Мой профиль":
        min_dmg = 15 + (player["level"] * 3) + player["dmg_bonus"]
        max_dmg = 25 + (player["level"] * 3) + player["dmg_bonus"]

        stats = (
            f"👤 *Герой:* {player['name']}\n"
            f"🏅 *Уровень:* {player['level']} ({player['xp']}/{(player['level']*50)} XP)\n"
            f"❤️ *Здоровье:* {player['hp']}/{player['max_hp']}\n"
            f"⚔️ *Сила атаки:* {min_dmg}-{max_dmg} " + (f"(+{player['dmg_bonus']} ⚔️)" if player['dmg_bonus'] > 0 else "") + "\n"
            f"🛡️ *Защита:* +{player['defense']} " + (f"(урон снижен на {player['defense']})" if player['defense'] > 0 else "") + "\n"
            f"💥 *Шанс крита:* {player['crit_chance']}% \n"
            f"💰 *Золото:* {player['gold']} " + (f"(+{player['gold_boost_percent']}%)" if player['gold_boost_percent'] > 0 else "") + "\n"
            f"🌟 *Очки БП:* {player['bp_xp']} " + (f"(+{player['xp_boost_percent']}% к XP)" if player['xp_boost_percent'] > 0 else "") + "\n"
            f"💀 *Побеждено монстров:* {player['kills']}"
        )
        bot.send_message(
            message.chat.id,
            stats,
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
        text += "🎁 *Сетка наград (20 Уровней):*\n"
        
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

    # --- КНОПКА: В БОЙ! ---
    elif message.text == "⚔️ В бой!":
        if player["hp"] <= 0:
            bot.send_message(
                message.chat.id,
                "Вы мертвы! Восстановите силы у костра 🏕️.",
                reply_markup=main_keyboard(),
            )
            return

        monsters = [
            {"name": "Слизень", "hp": 20, "dmg": 5, "gold": 8, "xp": 15, "bp_xp": 10},
            {"name": "Гоблин", "hp": 40, "dmg": 12, "gold": 15, "xp": 25, "bp_xp": 10},
            {"name": "Орк", "hp": 70, "dmg": 20, "gold": 35, "xp": 50, "bp_xp": 15},
            {"name": "Дракон", "hp": 120, "dmg": 35, "gold": 80, "xp": 100, "bp_xp": 20}
        ]
        
        # Подбираем монстра по уровню
        available_monsters = []
        if player["level"] < 3:
            available_monsters = monsters[:2] # Слизень, Гоблин
        elif player["level"] < 6:
            available_monsters = monsters[:3] # Слизень, Гоблин, Орк
        else:
            available_monsters = monsters    # Все монстры
            
        monster = random.choice(available_monsters)

        bot.send_message(
            message.chat.id,
            f"⚔️ Вы встретили врага: *{monster['name']}* (HP: {monster['hp']}, DMG: {monster['dmg']})!",
            parse_mode="Markdown",
        )

        # Расчет урона игрока
        base_player_damage = random.randint(15, 25) + (player["level"] * 3) + player["dmg_bonus"]
        
        is_crit = False
        if random.randint(1, 100) <= player["crit_chance"]:
            base_player_damage *= 2 # Удвоенный урон при крите
            is_crit = True

        # Расчет урона монстра с учетом защиты игрока
        monster_damage = random.randint(5, monster["dmg"])
        actual_monster_damage = max(1, monster_damage - player["defense"]) # Защита снижает урон, минимум 1

        player["hp"] -= actual_monster_damage
        if player["hp"] < 0:
            player["hp"] = 0

        if player["hp"] > 0:
            # Награды с учетом бустов
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

            # Левелап
            xp_needed = player["level"] * 50
            if player["xp"] >= xp_needed:
                player["level"] += 1
                player["xp"] -= xp_needed
                player["max_hp"] += 20
                player["hp"] = player["max_hp"]
                battle_log += f"\n\n🎉 **УРОВЕНЬ ПОВЫШЕН!** Вы достигли {player['level']} уровня! Макс. HP увеличено!"

        else:
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
    
    # Выдаем награды
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
        reward_msg += f"⚔️ Получено новое оружие! Постоянный урон увеличен на +{data['dmg_boost']} ⚔️\n"

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
        
    # Проверка уровня после добавления XP
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
    init_db() # Инициализация базы данных
    
    print("Запуск веб-сервера для круглосуточного хостинга...")
    keep_alive() # Запуск Flask в отдельном потоке
    
    print(f"RPG Бот с 20 уровнями БП и {('PostgreSQL' if IS_POSTGRES else 'SQLite')} базой данных успешно запущен!")
    bot.polling(none_stop=True)