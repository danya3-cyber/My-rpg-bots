import random
import json
import os
import telebot
from telebot import types
from flask import Flask
from threading import Thread

# ================= НАСТРОЙКА БОТА =================
# ТОКЕН, полученный от @BotFather
TOKEN = os.environ.get("8988649368:AAFwxt6EAH0y_1awKWWAUOrPUB0yF93FZ9A")
bot = telebot.TeleBot(TOKEN)

# Имя файла для сохранения базы данных игроков
DATA_FILE = "players_data.json"

# ================= ВЕБ-СЕРВЕР ДЛЯ ХОСТИНГА (24/7) =================
app = Flask('')

@app.route('/')
def home():
    return "Бот запущен и успешно работает в облаке 24/7!"

def run_web_server():
    # Render автоматически передает нужный порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    """Запуск веб-сервера в отдельном потоке"""
    t = Thread(target=run_web_server)
    t.start()

# ================= РАБОТА С ФАЙЛОМ СОХРАНЕНИЯ =================
def load_players():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            return {}
    return {}


def save_players():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(players, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения данных: {e}")


# Загружаем базу данных игроков при старте
players = load_players()

# ================= НАСТРОЙКА БАТЛ ПАССА (10 УРОВНЕЙ) =================
BP_TIERS = {
    1: {"req": 20, "reward_text": "📦 Стартовый паёк (50💰 и 20 XP)", "gold": 50, "xp": 20},
    2: {"req": 50, "reward_text": "🎒 Сундук новобранца (100💰 и 50 XP)", "gold": 100, "xp": 50},
    3: {"req": 90, "reward_text": "🛡️ Кожаный жилет (+15 к макс. HP ❤️)", "gold": 0, "xp": 0, "hp_boost": 15},
    4: {"req": 140, "reward_text": "🗡️ Медный нож (+5 к урону ⚔️)", "gold": 0, "xp": 0, "dmg_boost": 5},
    5: {"req": 200, "reward_text": "💰 Мешок искателя (250💰 и 100 XP)", "gold": 250, "xp": 100},
    6: {"req": 270, "reward_text": "🧪 Эликсир Силы (+8 к урону ⚔️)", "gold": 0, "xp": 0, "dmg_boost": 8},
    7: {"req": 350, "reward_text": "🛡️ Стальной нагрудник (+35 к макс. HP ❤️)", "gold": 0, "xp": 0, "hp_boost": 35},
    8: {"req": 440, "reward_text": "👑 Королевская казна (500💰 и 200 XP)", "gold": 500, "xp": 200},
    9: {"req": 540, "reward_text": "🧪 Зелье Титана (+50 к макс. HP ❤️)", "gold": 0, "xp": 0, "hp_boost": 50},
    10: {"req": 650, "reward_text": "🔥 Меч Дракона (+20 к урону ⚔️) и 1000💰!", "gold": 1000, "xp": 0, "dmg_boost": 20}
}


def get_player(user_id, username):
    """Инициализация или обновление полей игрока"""
    if user_id not in players:
        players[user_id] = {
            "name": username or "Герой",
            "hp": 100,
            "max_hp": 100,
            "gold": 50,
            "level": 1,
            "xp": 0,
            "kills": 0,
            "bp_xp": 0,
            "bp_claimed": [],
            "dmg_bonus": 0  # Бонус к атаке от снаряжения
        }
        save_players()
    
    # Авто-добавление новых полей для старых сохранений
    modified = False
    if "bp_xp" not in players[user_id]:
        players[user_id]["bp_xp"] = 0
        modified = True
    if "bp_claimed" not in players[user_id]:
        players[user_id]["bp_claimed"] = []
        modified = True
    if "dmg_bonus" not in players[user_id]:
        players[user_id]["dmg_bonus"] = 0
        modified = True
        
    if modified:
        save_players()
        
    return players[user_id]


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
        "Сражайся с монстрами, копи золото и открывай уровни в **Батл Пассе**! 🎫\n"
        "Тебя ждут **10 уровней наград** — забирай мощное снаряжение!\n\n"
        "Используй кнопки внизу."
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
            f"💰 *Золото:* {player['gold']}\n"
            f"🌟 *Очки БП:* {player['bp_xp']}\n"
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
            save_players()
            bot.send_message(
                message.chat.id,
                "Вы отдохнули у костра. Здоровье восстановлено! (-10💰)",
                reply_markup=main_keyboard(),
            )

    # --- КНОПКА: БАТЛ ПАСС ---
    elif message.text == "🎫 Батл Пасс":
        text = "🎫 *БОЕВОЙ ПРОПУСК (БАТЛ ПАСС)* 🎫\n\n"
        text += f"Ваш прогресс: *{player['bp_xp']}* 🌟\n\n"
        text += "🎁 *Сетка наград (10 Уровней):*\n"
        
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
            {"name": "Слизень", "hp": 20, "dmg": 5, "gold": 8, "xp": 15},
            {"name": "Гоблин", "hp": 40, "dmg": 12, "gold": 15, "xp": 25},
            {"name": "Орк", "hp": 70, "dmg": 20, "gold": 35, "xp": 50},
            {"name": "Дракон", "hp": 120, "dmg": 35, "gold": 80, "xp": 100}
        ]
        
        available_monsters = monsters[:2] if player["level"] < 3 else monsters
        monster = random.choice(available_monsters)

        bot.send_message(
            message.chat.id,
            f"⚔️ Вы встретили врага: *{monster['name']}* (HP: {monster['hp']}, DMG: {monster['dmg']})!",
            parse_mode="Markdown",
        )

        player_damage = random.randint(15, 25) + (player["level"] * 3) + player["dmg_bonus"]
        monster_damage = random.randint(5, monster["dmg"])

        player["hp"] -= monster_damage
        if player["hp"] < 0:
            player["hp"] = 0

        if player["hp"] > 0:
            bp_xp_gain = 15 if monster["name"] in ["Орк", "Дракон"] else 10
            
            player["gold"] += monster["gold"]
            player["xp"] += monster["xp"]
            player["kills"] += 1
            player["bp_xp"] += bp_xp_gain

            battle_log = (
                f"Вы нанесли {player_damage} урона и одолели *{monster['name']}*!\n"
                f"Получено урона: {monster_damage} ❤️\n"
                f"Награда: +{monster['gold']}💰, +{monster['xp']} XP и **+{bp_xp_gain} очков БП 🌟**!\n"
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

        save_players()
        
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
    player["gold"] += data.get("gold", 0)
    player["xp"] += data.get("xp", 0)
    
    reward_msg = f"🎉 *Поздравляем!*\nВы получили награду за {tier}-й Уровень БП:\n"
    
    if data.get("gold", 0) > 0:
        reward_msg += f"+{data['gold']}💰 Золота\n"
    if data.get("xp", 0) > 0:
        reward_msg += f"+{data['xp']} XP Опыта\n"
        
    if "hp_boost" in data:
        player["max_hp"] += data["hp_boost"]
        player["hp"] = player["max_hp"]
        reward_msg += f"🛡️ Надето новое снаряжение! Максимальное здоровье увеличено на +{data['hp_boost']} ❤️\n"
        
    if "dmg_boost" in data:
        player["dmg_bonus"] += data["dmg_boost"]
        reward_msg += f"⚔️ Получено новое оружие! Постоянный урон увеличен на +{data['dmg_boost']} ⚔️\n"
        
    xp_needed = player["level"] * 50
    if player["xp"] >= xp_needed:
        player["level"] += 1
        player["xp"] -= xp_needed
        player["max_hp"] += 20
        player["hp"] = player["max_hp"]
        reward_msg += f"\n🎉 **УРОВЕНЬ ПОВЫШЕН!** Вы достигли {player['level']} уровня!"

    save_players()

    bot.answer_callback_query(call.id, "Награда получена!")
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=reward_msg,
        parse_mode="Markdown"
    )


# ================= ЗАПУСК ПРИЛОЖЕНИЯ =================
if __name__ == "__main__":
    # 1. Сначала запускаем веб-сервер Flask в фоне
    print("Запуск веб-сервера для круглосуточного хостинга...")
    keep_alive()
    
    # 2. Затем запускаем самого бота
    print("RPG Бот с 10 уровнями БП и сохранением успешно запущен!")
    bot.polling(none_stop=True)